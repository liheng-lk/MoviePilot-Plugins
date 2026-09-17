from __future__ import annotations

import ast
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INIT = ROOT / "plugins.v3/shukguangyadisk/__init__.py"
PACKAGE = ROOT / "package.v3.json"
PLUGIN_JSON = ROOT / "plugins.v3/shukguangyadisk/plugin.json"
README = ROOT / "plugins.v3/shukguangyadisk/README.md"
TEST = ROOT / "tests/v3/shukguangyadisk/test_orphan_inflight_reconcile_v3916.py"


def load_bundle(text: str):
    pattern = re.compile(
        r'(_BUNDLED_SOURCES:\s*_BundleDict\[str, str\]\s*=\s*_bundle_json\.loads\()'
        r'("(?:\\.|[^"\\])*")'
        r'(\))',
        re.S,
    )
    match = pattern.search(text)
    if not match:
        raise SystemExit("cannot locate _BUNDLED_SOURCES json literal")
    return match, json.loads(ast.literal_eval(match.group(2)))


def dump_bundle(text: str, match: re.Match[str], sources: dict[str, str]) -> str:
    payload = json.dumps(sources, ensure_ascii=True, separators=(",", ":"))
    literal = json.dumps(payload, ensure_ascii=True)
    return text[: match.start(2)] + literal + text[match.end(2) :]


def patch_recovery(module: str) -> str:
    attrs_old = (
        '    _stale_pending_cleanup_lease_seconds = 120\n'
        '    _isolated_queue_capacity = 256\n'
    )
    attrs_new = (
        '    _stale_pending_cleanup_lease_seconds = 120\n'
        '    # v3.9.16: inflight 只有在没有任何私有 Worker 运行/排队事实时才允许回收。\n'
        '    _orphan_inflight_grace_seconds = 120.0\n'
        '    _orphan_inflight_diag_interval = 120.0\n'
        '    _orphan_inflight_last_diag_at = 0.0\n'
        '    _isolated_queue_capacity = 256\n'
    )
    if attrs_new not in module:
        if attrs_old not in module:
            raise SystemExit("cannot locate v3915 recovery attrs")
        module = module.replace(attrs_old, attrs_new, 1)

    marker = '    def init_organizer_monitor(self, force: bool = False) -> None:\n'
    if 'def _reconcile_orphan_inflight_v3916' not in module:
        if marker not in module:
            raise SystemExit("cannot locate init_organizer_monitor")
        method = '''    def _reconcile_orphan_inflight_v3916(self) -> Dict[str, Any]:
        """把没有任何私有 Worker 事实支撑的陈旧 inflight 交回历史预检。

        这里不能仅依赖时间 lease。目录/整季任务可能真实运行很久；只要当前插件私有
        worker 的 running path 或 pending key 仍覆盖该成员，就必须保留 inflight。
        """
        now = time.time()
        result: Dict[str, Any] = {
            "version": "3.9.16",
            "checked_at": now,
            "inflight": 0,
            "active": 0,
            "grace": 0,
            "unknown": 0,
            "reclaimed": 0,
            "worker_alive": False,
            "private_pending": 0,
            "private_queue": 0,
            "running_path": "",
            "sample": [],
            "skipped": "",
        }

        # 热更新交接期间旧 owner 仍可能真实执行同步任务，绝不能由新实例回收它的状态。
        if bool(getattr(self, "_isolated_owner_conflict", False)):
            result["skipped"] = "foreign_owner_alive"
            return result

        def norm(value: Any) -> str:
            text = str(value or "").strip().replace("\\\\", "/")
            if not text:
                return ""
            if not text.startswith("/"):
                text = "/" + text
            while "//" in text:
                text = text.replace("//", "/")
            return text.rstrip("/") or "/"

        try:
            lock = self._isolated_runtime_lock()
            with lock:
                worker = getattr(self, "_isolated_worker", None)
                worker_alive = bool(worker and worker.is_alive())
                running_path = norm(getattr(self, "_isolated_running_path", ""))
                pending_keys = set(getattr(self, "_isolated_pending_keys", None) or set())
                private_queue = getattr(self, "_isolated_queue", None)
                qsize = int(private_queue.qsize()) if private_queue is not None else 0
        except Exception as err:  # noqa: BLE001
            result["skipped"] = f"runtime_snapshot_failed:{err}"
            return result

        result["worker_alive"] = worker_alive
        result["private_pending"] = len(pending_keys)
        result["private_queue"] = qsize
        result["running_path"] = running_path

        # pending key 的第一个元素是插件自己的 item/group path。目录 envelope 的
        # inflight 存的是成员文件路径，因此祖先 group 也属于真实活动证据。
        active_groups: set[str] = set()
        active_exact: set[tuple[str, str]] = set()
        if worker_alive:
            if running_path:
                active_groups.add(running_path)
            for raw_key in pending_keys:
                try:
                    raw_path, raw_fp = raw_key
                except Exception:
                    continue
                key_path = norm(raw_path)
                key_fp = str(raw_fp or "")
                if key_path:
                    active_groups.add(key_path)
                    active_exact.add((key_path, key_fp))

        grace_seconds = max(float(self._orphan_inflight_grace_seconds), 0.0)
        reclaimed_paths: List[str] = []
        counters = {"inflight": 0, "active": 0, "grace": 0, "unknown": 0}

        def covered_by_active_group(path: str) -> bool:
            for group in active_groups:
                if path == group:
                    return True
                if group == "/":
                    return True
                if path.startswith(group + "/"):
                    return True
            return False

        def apply(state: Dict[str, Any]) -> int:
            inflight = dict(state.get("inflight") or {})
            stabilizing = dict(state.get("stabilizing") or {})
            counters["inflight"] = len(inflight)
            for raw_path, raw_row in list(inflight.items()):
                row = dict(raw_row or {}) if isinstance(raw_row, dict) else {}
                path = norm(raw_path)
                fingerprint = str(row.get("fingerprint") or "")
                if not path or not fingerprint:
                    counters["unknown"] += 1
                    continue

                if worker_alive and (
                    (path, fingerprint) in active_exact
                    or covered_by_active_group(path)
                ):
                    counters["active"] += 1
                    continue

                try:
                    submitted_at = float(row.get("submitted_at") or 0.0)
                except (TypeError, ValueError):
                    submitted_at = 0.0
                age = (now - submitted_at) if submitted_at > 0 else grace_seconds + 1.0
                if age < grace_seconds:
                    counters["grace"] += 1
                    continue

                stabilizing[raw_path] = {
                    "fingerprint": fingerprint,
                    "first_seen": 0,
                    "v3916_pending_reason": "inflight 无对应私有 Worker running/queue 事实，交回 MoviePilot 历史预检",
                    "v3916_reclaimed_at": now,
                    "v3916_previous_submitted_at": submitted_at,
                    "v3916_previous_attempts": int(row.get("attempts") or 0),
                }
                inflight.pop(raw_path, None)
                reclaimed_paths.append(str(raw_path))

            state["inflight"] = inflight
            state["stabilizing"] = stabilizing
            return len(reclaimed_paths)

        try:
            reclaimed = int(self._state().mutate(apply) or 0)
        except Exception as err:  # noqa: BLE001
            result["skipped"] = f"state_reconcile_failed:{err}"
            return result

        result.update(counters)
        result["reclaimed"] = reclaimed
        result["sample"] = reclaimed_paths[:10]

        if reclaimed_paths:
            repair = getattr(self, "_v361_repair_zero_first_seen", None)
            if callable(repair):
                try:
                    repair(reclaimed_paths)
                except Exception as err:  # noqa: BLE001
                    logger.warning("【光鸭云盘助手】【v3.9.16 inflight自愈】稳定期修复失败: %s", err)

        last_diag = float(getattr(self, "_orphan_inflight_last_diag_at", 0.0) or 0.0)
        if reclaimed or (counters["inflight"] and now - last_diag >= self._orphan_inflight_diag_interval):
            self._orphan_inflight_last_diag_at = now
            logger.warning(
                "【光鸭云盘助手】【v3.9.16 inflight核对】持久=%s 活动=%s 保护期=%s "
                "未知=%s 回收=%s worker=%s 私有pending=%s 私有queue=%s running=%s%s",
                counters["inflight"],
                counters["active"],
                counters["grace"],
                counters["unknown"],
                reclaimed,
                worker_alive,
                len(pending_keys),
                qsize,
                running_path or "-",
                f" sample={reclaimed_paths[:3]}" if reclaimed_paths else "",
            )

        try:
            self._save_monitor_status(orphan_inflight_v3916=dict(result))
        except Exception:
            pass
        return result

'''
        module = module.replace(marker, method + marker, 1)

    old_init = '''    def init_organizer_monitor(self, force: bool = False) -> None:\n        super().init_organizer_monitor(force=force)\n        self._apply_legacy_queue_migration_once()\n        blocked, legacy = self._legacy_queue_blocks_isolated_start()\n        if not blocked:\n            self._recover_isolated_inflight_once()\n            self._ensure_isolated_worker()\n        self._refresh_queue_guard_status(blocked, legacy)\n'''
    new_init = '''    def init_organizer_monitor(self, force: bool = False) -> None:\n        super().init_organizer_monitor(force=force)\n        self._apply_legacy_queue_migration_once()\n        blocked, legacy = self._legacy_queue_blocks_isolated_start()\n        if not blocked:\n            self._recover_isolated_inflight_once()\n            self._ensure_isolated_worker()\n            self._reconcile_orphan_inflight_v3916()\n        self._refresh_queue_guard_status(blocked, legacy)\n'''
    if new_init not in module:
        if old_init not in module:
            raise SystemExit("cannot locate queue recovery init body")
        module = module.replace(old_init, new_init, 1)

    return module


def history_v3915() -> str:
    return (
        "修复历史 MoviePilot durable pending 反复回放：旧兼容 discard 返回 0 不再误报删除成功；"
        "对已被状态机接管的旧任务使用宿主 admission repository 的 claim/abandon_unstarted，"
        "仅在光鸭远端确认源文件不存在且无执行证据时安全注销，网络异常与有效执行任务一律保留。"
    )


def history_v3916() -> str:
    return (
        "修复自动整理成员长期停在 inflight/member_wait：每次监控运行把持久 inflight 与插件私有 Worker "
        "running/pending 事实对账，真实运行或排队任务继续保护；无任何 Worker 事实且超过 120 秒的孤儿状态"
        "自动退回稳定/历史预检，不直接重做、不写失败、不越过热更新旧 owner。同步修正 plugin.json/README 版本漂移。"
    )


def patch_metadata() -> None:
    pkg = json.loads(PACKAGE.read_text(encoding="utf-8"))
    entry = pkg["ShukGuangYaDisk"]
    entry["version"] = "3.9.16"
    hist = dict(entry.get("history") or {})
    hist.setdefault("v3.9.15", history_v3915())
    entry["history"] = {"v3.9.16": history_v3916(), **{k: v for k, v in hist.items() if k != "v3.9.16"}}
    PACKAGE.write_text(json.dumps(pkg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    meta = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))
    meta["version"] = "3.9.16"
    mh = dict(meta.get("history") or {})
    mh.setdefault("v3.9.15", history_v3915())
    meta["history"] = {"v3.9.16": history_v3916(), **{k: v for k, v in mh.items() if k != "v3.9.16"}}
    PLUGIN_JSON.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    readme = README.read_text(encoding="utf-8")
    readme = readme.replace("# 光鸭云盘助手 3.9.14", "# 光鸭云盘助手 3.9.16", 1)
    if "## 3.9.16 inflight 孤儿状态自愈" not in readme:
        anchor = "## 3.9.14 多级目录监控同轮下钻修复\n"
        if anchor not in readme:
            raise SystemExit("README v3.9.14 anchor not found")
        section = f'''## 3.9.16 inflight 孤儿状态自愈\n\n- `{history_v3916()}`\n- `member_wait phases={{'inflight': 1}}` 现在不再仅依赖 7 天 lease；每次 heartbeat 会核对插件私有 Worker 的真实 running/pending。\n- 活跃目录 envelope 会按祖先 group path 保护其全部成员，避免长任务被误判成孤儿。\n- 只有超过 120 秒、且 Worker/队列中都找不到的 inflight 才回到 stabilizing → MoviePilot 历史预检。\n- 日志新增 `【v3.9.16 inflight核对】`，直接显示持久、活动、保护期、回收、worker、私有 queue 与 running path。\n\n## 3.9.15 durable pending 安全清理\n\n- {history_v3915()}\n\n'''
        readme = readme.replace(anchor, section + anchor, 1)
    README.write_text(readme, encoding="utf-8")


def write_test() -> None:
    TEST.write_text('''from __future__ import annotations\n\nimport json\nfrom pathlib import Path\n\nfrom source_helper import single_init_plugin_path\n\n\nROOT = Path(__file__).resolve().parents[3]\nPLUGIN = single_init_plugin_path(ROOT / "plugins.v3" / "shukguangyadisk")\nRECOVERY = (PLUGIN / "organizer_queue_recovery.py").read_text(encoding="utf-8")\nINIT = (PLUGIN / "__init__.py").read_text(encoding="utf-8")\n\n\ndef test_v3916_reconciles_only_orphan_inflight_against_private_worker_facts():\n    for token in (\n        "def _reconcile_orphan_inflight_v3916",\n        "_isolated_pending_keys",\n        "_isolated_running_path",\n        "worker.is_alive()",\n        "active_groups",\n        "covered_by_active_group",\n        "submitted_at",\n        "_orphan_inflight_grace_seconds = 120.0",\n        'state["inflight"] = inflight',\n        'state["stabilizing"] = stabilizing',\n        "v3916_pending_reason",\n    ):\n        assert token in RECOVERY, token\n\n\ndef test_v3916_never_reclaims_live_foreign_owner_and_runs_after_worker_ensure():\n    reconcile = RECOVERY.split("def _reconcile_orphan_inflight_v3916", 1)[1].split("def init_organizer_monitor", 1)[0]\n    assert '_isolated_owner_conflict' in reconcile\n    assert 'foreign_owner_alive' in reconcile\n    init = RECOVERY.split("def init_organizer_monitor", 1)[1].split("def run_organize_monitor_scan", 1)[0]\n    assert init.index("_ensure_isolated_worker()") < init.index("_reconcile_orphan_inflight_v3916()")\n\n\ndef test_v3916_keeps_active_or_recent_inflight_instead_of_forcing_retry():\n    reconcile = RECOVERY.split("def _reconcile_orphan_inflight_v3916", 1)[1].split("def init_organizer_monitor", 1)[0]\n    assert "counters[\\\"active\\\"] += 1" in reconcile\n    assert "age < grace_seconds" in reconcile\n    assert "mark_failed" not in reconcile\n    assert "mark_blocked" not in reconcile\n    assert "global_vars.stop_transfer" not in reconcile\n\n\ndef test_v3916_versions_are_synchronized():\n    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))\n    plugin = json.loads((ROOT / "plugins.v3/shukguangyadisk/plugin.json").read_text(encoding="utf-8"))\n    assert package["ShukGuangYaDisk"]["version"] == "3.9.16"\n    assert plugin["version"] == "3.9.16"\n    assert 'ShukGuangYaDisk.plugin_version = "3.9.16"' in INIT\n    assert "光鸭云盘助手 v3.9.16 单文件运行时" in INIT\n''', encoding="utf-8")


def verify(text: str, sources: dict[str, str]) -> None:
    compile(text, str(INIT), "exec")
    for name, source in sources.items():
        compile(source, f"<single-init:{name}.py>", "exec")
    assert 'ShukGuangYaDisk.plugin_version = "3.9.16"' in text
    assert "_reconcile_orphan_inflight_v3916" in sources["organizer_queue_recovery"]
    assert json.loads(PACKAGE.read_text(encoding="utf-8"))["ShukGuangYaDisk"]["version"] == "3.9.16"
    assert json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))["version"] == "3.9.16"


def main() -> None:
    text = INIT.read_text(encoding="utf-8")
    match, sources = load_bundle(text)
    sources["organizer_queue_recovery"] = patch_recovery(sources["organizer_queue_recovery"])
    text = dump_bundle(text, match, sources)
    text = text.replace("光鸭云盘助手 v3.9.15 单文件运行时", "光鸭云盘助手 v3.9.16 单文件运行时", 1)
    text = text.replace("v3.9.15 MoviePilot V3 SDK 运行态保障", "v3.9.16 MoviePilot V3 SDK 运行态保障", 1)
    text = text.replace('ShukGuangYaDisk.plugin_version = "3.9.15"', 'ShukGuangYaDisk.plugin_version = "3.9.16"', 1)
    if 'ShukGuangYaDisk.plugin_version = "3.9.16"' not in text:
        raise SystemExit("physical plugin_version replacement failed")
    INIT.write_text(text, encoding="utf-8")

    patch_metadata()
    write_test()
    verify(text, sources)

    subprocess.run(["python", "tests/v3/shukguangyadisk/run_contract_tests.py"], cwd=ROOT, check=True)
    subprocess.run(["python", "-m", "unittest", "discover", "-s", "tests/v3/shukguangyadisk", "-p", "test_*.py"], cwd=ROOT, check=True)
    subprocess.run(["git", "diff", "--check"], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
