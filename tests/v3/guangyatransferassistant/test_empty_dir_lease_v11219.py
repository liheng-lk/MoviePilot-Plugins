from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
SOURCE = PLUGIN / "empty_dir_lease_v11219.py"
GUARD = PLUGIN / "empty_dir_guard_v11218.py"
MOVIE = PLUGIN / "movie_identity_v1129.py"


class Item:
    def __init__(self, path, item_type="dir"):
        self.path = str(path)
        self.fileid = self.path
        self.type = item_type
        self.name = Path(self.path).name or "/"


class FakeApi:
    def __init__(self, existing=None):
        self.items = {"/": Item("/")}
        self.deleted = []
        for path in existing or []:
            self.ensure_dir(path)

    @staticmethod
    def norm(value):
        raw = str(value or "/").replace("\\", "/")
        parts = [p for p in raw.split("/") if p and p not in {".", ".."}]
        return "/" + "/".join(parts) if parts else "/"

    def ensure_dir(self, path):
        normalized = self.norm(path)
        current = ""
        for part in normalized.strip("/").split("/") if normalized != "/" else []:
            current += "/" + part
            self.items.setdefault(current, Item(current))
        return self.items.get(normalized)

    def add_file(self, path):
        normalized = self.norm(path)
        parent = normalized.rsplit("/", 1)[0] or "/"
        self.ensure_dir(parent)
        self.items[normalized] = Item(normalized, "file")

    def get_item(self, path):
        return self.items.get(self.norm(path))

    def get_folder(self, path):
        return self.ensure_dir(path)

    def list(self, folder):
        parent = self.norm(folder.path)
        prefix = parent.rstrip("/") + "/"
        result = []
        for path, item in list(self.items.items()):
            if path == parent or not path.startswith(prefix):
                continue
            tail = path[len(prefix):]
            if "/" not in tail:
                result.append(item)
        return result

    def delete(self, folder):
        path = self.norm(folder.path)
        if self.list(folder):
            return False
        self.deleted.append(path)
        self.items.pop(path, None)
        return True

    def _invalidate_path_cache(self, _path):
        return None


class _GuardBase:
    """只模拟 v1.12.18 已冻结的目录事务语义，v1.12.19 逻辑必须真实执行。"""

    shared_data = {}

    def __init__(self, *, api=None, data=None):
        self.api = api or FakeApi(existing=["/library"])
        self.data = data if data is not None else {}
        self._save_path = "/library"
        self._enabled = True
        self.logs = []
        self.subscription = SimpleNamespace(id=1, name="Demo")
        self.source = {
            "id": "src1",
            "subscribe_id": 1,
            "type": "magnet",
            "state": "new",
            "task_id": "",
            "enabled": True,
        }
        self.offline_result = {"success": True, "data": {"task_id": "cloud-1", "state": "submitted"}}
        self.restore_result = {
            "success": False,
            "pending_verification": True,
            "task_ids": ["restore-1"],
            "completed_items": [],
        }
        self.xunlei_result = {"success": False, "task_id": "xu-1", "reason": "remote failed"}
        self.jobs = {}
        self.services = []

    def init_plugin(self, config=None):
        return None

    def get_data(self, key):
        if key == "transfer_jobs":
            return self.jobs
        return self.data.get(key)

    def save_data(self, key, value):
        if key == "transfer_jobs":
            self.jobs = value
        else:
            self.data[key] = value

    def _plugin_log(self, *args):
        self.logs.append(args)

    def _get_guangya_runtime(self):
        return object(), self.api

    def _target_path(self, _subscribe):
        return "/library/Demo (2026)"

    def _source_store(self):
        return {"items": {"src1": dict(self.source)}}

    def _cloud_path_v11218(self, value):
        return self.api.norm(value)

    def _dir_guard_local_v11218(self):
        local = getattr(self, "_test_local", None)
        if local is None:
            local = SimpleNamespace()
            self._test_local = local
        return local

    def _dir_guard_current_v11218(self):
        return getattr(self._dir_guard_local_v11218(), "txn", None)

    def _dir_guard_begin_v11218(self, kind):
        local = self._dir_guard_local_v11218()
        current = getattr(local, "txn", None)
        if isinstance(current, dict):
            current["depth"] = int(current.get("depth") or 1) + 1
            return current, False
        txn = {
            "kind": str(kind),
            "depth": 1,
            "protected_root": "/library",
            "created_candidates": set(),
            "checked": set(),
            "unsafe": False,
        }
        local.txn = txn
        return txn, True

    def _record_create_path_v11218(self, path):
        txn = self._dir_guard_current_v11218()
        if not isinstance(txn, dict):
            return
        path = self.api.norm(path)
        current = ""
        for part in path.strip("/").split("/"):
            current += "/" + part
            if current in {"/library"}:
                continue
            if self.api.get_item(Path(current)) is None:
                txn["created_candidates"].add(current)

    def _cleanup_empty_dirs_v11218(self, txn):
        removed = 0
        for path in sorted(txn.get("created_candidates") or [], key=lambda x: x.count("/"), reverse=True):
            folder = self.api.get_item(Path(path))
            if folder and folder.type == "dir" and not self.api.list(folder) and self.api.delete(folder):
                removed += 1
        return removed

    def _dir_guard_end_v11218(self, txn, owner, *, cleanup=False):
        if not owner:
            txn["depth"] = max(1, int(txn.get("depth") or 2) - 1)
            return
        try:
            if cleanup:
                self._cleanup_empty_dirs_v11218(txn)
        finally:
            self._dir_guard_local_v11218().txn = None

    def _offline_target_parent(self, subscribe):
        target = self._target_path(subscribe)
        self._record_create_path_v11218(target)
        folder = self.api.get_folder(Path(target))
        return target, folder.fileid

    def _submit_offline_source(self, _source_id):
        self._offline_target_parent(self.subscription)
        return dict(self.offline_result)

    def _restore_items(self, probe, save_path, items, job_key=""):
        for item in items:
            parent = str(item.get("target_parent") or "").strip("/")
            target = str(save_path).rstrip("/") + ("/" + parent if parent else "")
            self._record_create_path_v11218(target)
            self.api.get_folder(Path(target))
        return dict(self.restore_result)

    def _xunlei_target_parent(self, subscribe, relative_path):
        base = self._target_path(subscribe)
        parent = str(relative_path or "").replace("\\", "/").rsplit("/", 1)[0] if "/" in str(relative_path or "").replace("\\", "/") else ""
        target = base.rstrip("/") + ("/" + parent if parent else "")
        self._record_create_path_v11218(base)
        if parent:
            self._record_create_path_v11218(target)
        folder = self.api.get_folder(Path(target))
        return target, folder.fileid

    def _xunlei_import_json_file_v1117(self, subscribe, obj, source_row):
        path = str(((obj.get("files") or [{}])[0]).get("path") or source_row.get("path") or "S01E01.mkv")
        self._xunlei_target_parent(subscribe, path)
        return dict(self.xunlei_result)

    def _rapid_transfer_xunlei_file(self, subscribe, row):
        self._xunlei_target_parent(subscribe, row.get("path") or "S01E01.mkv")
        return dict(self.xunlei_result)

    def _set_job_state(self, job_key, status, **fields):
        row = dict(self.jobs.get(job_key) or {})
        row.update(fields)
        row["status"] = status
        self.jobs[job_key] = row
        return None

    def _poll_offline_source(self, source):
        return {"success": str(source.get("state") or "") == "completed", "data": dict(source)}

    def _offline_tick(self):
        return None

    def get_service(self):
        return list(self.services)


def _namespace():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    body = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level:
            continue
        body.append(node)
    module = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"GuangYaEmptyDirGuardV11218Mixin": _GuardBase}
    exec(compile(module, str(SOURCE), "exec"), namespace)
    return namespace


NS = _namespace()
Lease = NS["GuangYaEmptyDirLeaseV11219Mixin"]


class Probe(Lease):
    _empty_dir_lease_grace_v11219 = 0
    _empty_dir_share_grace_v11219 = 0


def _lease_items(probe):
    return dict((probe.data.get("empty_dir_leases_v11219") or {}).get("items") or {})


def test_module_is_nested_on_v11218_and_keeps_old_guard_file_unchanged():
    text = SOURCE.read_text(encoding="utf-8")
    assert "class GuangYaEmptyDirLeaseV11219Mixin(GuangYaEmptyDirGuardV11218Mixin):" in text
    assert 'plugin_version = "1.12.19"' in text
    assert 'plugin_version = "1.12.18"' in GUARD.read_text(encoding="utf-8")


def test_cloud_task_persists_lease_and_survives_restart_then_failed_task_reclaims_empty_dir():
    shared = {}
    api = FakeApi(existing=["/library"])
    first = Probe(api=api, data=shared)
    result = first._submit_offline_source("src1")
    assert result["success"]
    assert "/library/Demo (2026)" in api.items
    leases = _lease_items(first)
    assert "offline:src1" in leases
    assert leases["offline:src1"]["task_ids"] == ["cloud-1"]

    # 模拟插件重启：新实例只依赖 save_data 中的 lease，不共享线程本地事务。
    second = Probe(api=api, data=shared)
    second.source.update({"state": "failed", "task_id": "cloud-1"})
    second._reconcile_empty_dir_leases_v11219()
    assert "/library/Demo (2026)" not in api.items
    assert "offline:src1" not in _lease_items(second)


def test_cloud_completed_but_zero_files_reclaims_after_terminal_confirmation():
    probe = Probe()
    probe._submit_offline_source("src1")
    probe.source.update({"state": "completed", "task_id": "cloud-1"})
    probe._reconcile_empty_dir_leases_v11219()
    assert "/library/Demo (2026)" not in probe.api.items


def test_cloud_completed_with_real_file_drops_lease_but_keeps_directory_and_file():
    probe = Probe()
    probe._submit_offline_source("src1")
    probe.api.add_file("/library/Demo (2026)/Demo.S01E01.mkv")
    probe.source.update({"state": "completed", "task_id": "cloud-1"})
    probe._reconcile_empty_dir_leases_v11219()
    assert "/library/Demo (2026)" in probe.api.items
    assert "/library/Demo (2026)/Demo.S01E01.mkv" in probe.api.items
    assert "offline:src1" not in _lease_items(probe)


def test_preexisting_target_never_becomes_a_lease():
    probe = Probe(api=FakeApi(existing=["/library", "/library/Demo (2026)"]))
    probe._submit_offline_source("src1")
    assert _lease_items(probe) == {}


def test_share_pending_verification_persists_and_verifying_job_reclaims_after_restart():
    shared = {}
    api = FakeApi(existing=["/library"])
    items = [{"target_parent": "Season 1", "effective_path": "Season 1/Demo.S01E01.mkv"}]
    first = Probe(api=api, data=shared)
    first._restore_items({}, "/library/Demo (2026)", items, job_key="job1")
    assert "share:job1" in _lease_items(first)
    assert "/library/Demo (2026)/Season 1" in api.items

    second = Probe(api=api, data=shared)
    second.jobs = {"job1": {"status": "verifying"}}
    second._reconcile_empty_dir_leases_v11219()
    assert "/library/Demo (2026)" not in api.items
    assert "share:job1" not in _lease_items(second)


def test_share_verified_or_cancelled_releases_lease_without_deleting():
    items = [{"target_parent": "Season 1", "effective_path": "Season 1/Demo.S01E01.mkv"}]
    for status in ("verified", "cancelled"):
        probe = Probe()
        probe._restore_items({}, "/library/Demo (2026)", items, job_key="job1")
        probe.jobs = {"job1": {"status": status}}
        probe._reconcile_empty_dir_leases_v11219()
        assert "/library/Demo (2026)" in probe.api.items
        assert "share:job1" not in _lease_items(probe)


def test_xunlei_failure_with_task_id_becomes_terminal_persistent_lease_and_reclaims():
    probe = Probe()
    obj = {"files": [{"path": "Season 1/Demo.S01E01.mkv"}]}
    result = probe._xunlei_import_json_file_v1117(probe.subscription, obj, {})
    assert not result["success"]
    assert "xunlei:xu-1" in _lease_items(probe)
    probe._reconcile_empty_dir_leases_v11219()
    assert "/library/Demo (2026)" not in probe.api.items
    assert "xunlei:xu-1" not in _lease_items(probe)


def test_recursive_empty_subtree_is_deleted_deepest_first():
    probe = Probe()
    txn, owner = probe._dir_guard_begin_v11218("offline")
    probe._record_create_path_v11218("/library/Demo (2026)")
    probe.api.ensure_dir("/library/Demo (2026)/Season 1/extras")
    key = probe._persist_lease_v11219(txn, kind="xunlei", owner="t1", task_ids=["t1"], terminal_hint=True)
    probe._dir_guard_end_v11218(txn, owner, cleanup=False)
    probe._reconcile_empty_dir_leases_v11219()
    assert key not in _lease_items(probe)
    assert "/library/Demo (2026)" not in probe.api.items
    assert probe.api.deleted[-1] == "/library/Demo (2026)"


def test_any_file_anywhere_in_new_subtree_blocks_deletion():
    probe = Probe()
    txn, owner = probe._dir_guard_begin_v11218("offline")
    probe._record_create_path_v11218("/library/Demo (2026)")
    probe.api.ensure_dir("/library/Demo (2026)/Season 1/extras")
    probe.api.add_file("/library/Demo (2026)/Season 1/extras/keep.nfo")
    key = probe._persist_lease_v11219(txn, kind="xunlei", owner="t1", task_ids=["t1"], terminal_hint=True)
    probe._dir_guard_end_v11218(txn, owner, cleanup=False)
    probe._reconcile_empty_dir_leases_v11219()
    assert "/library/Demo (2026)/Season 1/extras/keep.nfo" in probe.api.items
    assert "/library/Demo (2026)" in probe.api.items
    assert key not in _lease_items(probe)


def test_overlapping_active_lease_blocks_terminal_cleanup_until_other_owner_finishes():
    probe = Probe()
    txn1, owner1 = probe._dir_guard_begin_v11218("offline")
    probe._record_create_path_v11218("/library/Demo (2026)")
    probe.api.ensure_dir("/library/Demo (2026)")
    probe._persist_lease_v11219(txn1, kind="xunlei", owner="dead", task_ids=["dead"], terminal_hint=True)
    probe._dir_guard_end_v11218(txn1, owner1, cleanup=False)

    # 第二个活跃 owner 覆盖同一路径。
    txn2, owner2 = probe._dir_guard_begin_v11218("offline")
    txn2["created_candidates"].add("/library/Demo (2026)")
    probe._persist_lease_v11219(txn2, kind="offline", owner="live", task_ids=["live"])
    probe._dir_guard_end_v11218(txn2, owner2, cleanup=False)

    probe._reconcile_empty_dir_leases_v11219()
    assert "/library/Demo (2026)" in probe.api.items
    assert "xunlei:dead" in _lease_items(probe)


def test_service_registered_once_and_root_save_root_are_never_leased():
    probe = Probe()
    txn, owner = probe._dir_guard_begin_v11218("offline")
    txn["created_candidates"].update({"/", "/library"})
    assert probe._persist_lease_v11219(txn, kind="xunlei", owner="t1", terminal_hint=True) == ""
    probe._dir_guard_end_v11218(txn, owner, cleanup=False)
    services = probe.get_service()
    ids = [row.get("id") for row in services if isinstance(row, dict)]
    assert ids.count("GuangYaTransferAssistantEmptyDirLeaseV11219") == 1


def test_movie_runtime_bridge_will_keep_v11218_under_v11219():
    movie = MOVIE.read_text(encoding="utf-8")
    # wiring happens in the release candidate; this test intentionally accepts only the new chain.
    assert "GuangYaEmptyDirLeaseV11219Mixin" in movie
    assert "GuangYaEmptyDirGuardV11218Mixin" not in movie.split("class GuangYaMovieIdentityV1129Mixin(", 1)[1].split("):", 1)[0]
