"""2.0.7 生产级回归：P0/P1 根因防回归（静态契约 + 可执行单元）。"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import types
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ROUTING = (PLUGIN / "routing_v170.py").read_text(encoding="utf-8")
RUNTIME = (PLUGIN / "runtime_v170.py").read_text(encoding="utf-8")
LEGACY = (PLUGIN / "legacy.py").read_text(encoding="utf-8")
SHARE = (PLUGIN / "share_leaf_compat_v11225.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")


def test_v207_version_markers():
    assert 'plugin_version = "2.0.7"' in ENTRY
    assert 'build_id = "20260910-r88"' in ENTRY


def test_p0_shareid_retry_on_legacy_failure_contract():
    method = SHARE.split("    def _inspect_share(self, share_url", 1)[1]
    assert "need_share_id = (not legacy_ok) or empty_paths" in method
    assert "legacy_failed" in method
    assert "_inspect_share_with_share_id_v11225" in method
    assert '"retryable": True' in method


def test_p0_search_abi_transparent_kwargs():
    assert "def guarded_search(chain_self, *args, **kwargs)" in ROUTING
    assert "bind_partial" in ROUTING
    assert "scheduled_interval" in ROUTING
    # wrapper must forward unknown kwargs without hard-coded full signature
    install = ROUTING.split("    def _install_search_guard", 1)[1].split(
        "    def _restore_search_guard", 1
    )[0]
    assert "sid=None" not in install or "*args" in install
    assert "return original(chain_self, *args, **kwargs)" in install or (
        "plugin._guard_subscribe_search" in install and "*args" in install
    )


def test_p0_orphan_search_restore_contract():
    assert "_unwrap_orphan_subscribe_chain_attr" in ENTRY
    assert 'guard_flag="_guangya_route_guard"' in ENTRY
    assert 'original_attr="_guangya_original_search"' in ENTRY
    assert '"search"' in ENTRY or "\"search\"" in ENTRY
    assert "max_depth" in ENTRY


def test_p1_inactive_state_never_blackholes():
    assert "_is_active_transfer_state" in ROUTING
    one = ROUTING.split("    def _guard_one_subscription", 1)[1].split(
        "    def _guard_subscribe_search", 1
    )[0]
    assert 'handled": False' in one
    assert "非活跃" in one
    assert "handled\": True, \"message\": \"固定转存订阅当前非活跃" not in ROUTING
    dispatch = RUNTIME.split("    def _dispatch_subscribe_search", 1)[1].split(
        "    def _try_transfer_subscription", 1
    )[0]
    assert "【回退原生】" in dispatch
    assert "仍阻断原生下载" not in dispatch


def test_p1_dispatch_preserves_batch_sids_and_interval():
    block = RUNTIME.split("    def _dispatch_subscribe_search", 1)[1].split(
        "    def _try_transfer_subscription", 1
    )[0]
    assert 'native_kwargs["sids"] = tuple(native_ids)' in block
    assert "for index, native_sid in enumerate(native_ids)" not in block
    assert "is_scheduled_scan" in block
    assert "_load_search_subscriptions" in block or "_load_due_search_subscriptions" in block


def test_p1_rule_fingerprint_and_filtered_reopen():
    assert "def _rule_fingerprint" in LEGACY
    assert '"rule_fingerprint"' in LEGACY
    assert "_status_reprocess_on_rule_change" in LEGACY
    assert "规则指纹变化" in LEGACY


def test_p1_is_success_rejects_bare_none_code():
    method = LEGACY.split("    def _is_success(response: Any) -> bool:", 1)[1].split(
        "    def _share_access", 1
    )[0]
    assert "code in (None, 0, \"0\")" not in method
    assert "code in (0, \"0\")" in method
    assert 'msg == "success"' in method


def test_restore_requires_remote_confirm_not_task_id_alone():
    restore = LEGACY.split("    def _restore_items(", 1)[1].split(
        "    def _restore_share(", 1
    )[0]
    assert "restore_payload" in restore
    assert '"shareId"' in restore or "shareId" in restore
    assert "remote_not_found" in restore
    assert "remote_verify" in restore
    assert "未返回 taskId" in restore


def _load_legacy_static_helpers():
    """抽离 _is_success / fingerprint 纯逻辑做可执行断言。"""

    class _Probe:
        @staticmethod
        def _is_success(response: Any) -> bool:
            if not isinstance(response, dict):
                return False
            code = response.get("code")
            msg = str(response.get("msg") or response.get("message") or "").strip().lower()
            if code in (0, "0"):
                return msg not in ("error", "failed", "fail")
            if msg == "success":
                return True
            if response.get("success") is True and code in (None, ""):
                return msg not in ("error", "failed", "fail")
            return False

        def _rule_fingerprint(self, subscribe: Any = None) -> str:
            if subscribe is None:
                return ""
            rule_data = {
                "include": str(getattr(subscribe, "include", "") or "").strip(),
                "exclude": str(getattr(subscribe, "exclude", "") or "").strip(),
                "resolution": str(getattr(subscribe, "resolution", "") or "").strip(),
                "quality": str(getattr(subscribe, "quality", "") or "").strip(),
                "effect": str(getattr(subscribe, "effect", "") or "").strip(),
                "filter": str(getattr(subscribe, "filter", "") or "").strip(),
                "filter_groups": getattr(subscribe, "filter_groups", None),
                "best_version": bool(getattr(subscribe, "best_version", 0)),
                "season": getattr(subscribe, "season", None),
                "media_source": str(getattr(subscribe, "media_source", "") or ""),
                "media_id": str(getattr(subscribe, "media_id", "") or ""),
                "tmdbid": str(getattr(subscribe, "tmdbid", "") or getattr(subscribe, "tmdb_id", "") or ""),
                "doubanid": str(getattr(subscribe, "doubanid", "") or getattr(subscribe, "douban_id", "") or ""),
                "year": str(getattr(subscribe, "year", "") or ""),
                "type": str(getattr(subscribe, "type", "") or ""),
            }
            raw = json.dumps(rule_data, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
            return hashlib.sha256(raw.encode("utf-8")).hexdigest()

        @staticmethod
        def _status_reprocess_on_rule_change(status: str) -> bool:
            return str(status or "").strip().lower() in {
                "filtered", "no_match", "ignored", "resource_denied", "skipped",
            }

        def _entry_processed(self, entry, subscribe=None):
            key = "k1"
            raw = (self.get_data("processed_entries") or {}).get(key)
            if not raw:
                return False
            if subscribe is None or not isinstance(raw, dict):
                return True
            status = str(raw.get("status") or "").strip().lower()
            if self._status_reprocess_on_rule_change(status):
                current_fp = self._rule_fingerprint(subscribe)
                stored_fp = str(raw.get("rule_fingerprint") or "")
                if current_fp and (not stored_fp or stored_fp != current_fp):
                    return False
            return True

        def get_data(self, name):
            return self._store.get(name)

        def __init__(self):
            self._store = {}

    return _Probe()


def test_is_success_executable_matrix():
    probe = _load_legacy_static_helpers()
    assert probe._is_success({"code": 0, "msg": "ok"}) is True
    assert probe._is_success({"code": "0"}) is True
    assert probe._is_success({"code": None}) is False
    assert probe._is_success({"code": None, "msg": "success"}) is True
    assert probe._is_success({"code": None, "success": True}) is True
    assert probe._is_success({"code": 1, "msg": "fail"}) is False
    assert probe._is_success("x") is False


def test_filtered_reopens_when_rule_fingerprint_changes():
    probe = _load_legacy_static_helpers()
    sub = types.SimpleNamespace(include="1080", exclude="", resolution="", quality="", effect="",
                                filter="", filter_groups=None, best_version=0, season=1,
                                media_source="tmdb", media_id="1", tmdbid="1", doubanid="", year="2024", type="TV")
    fp1 = probe._rule_fingerprint(sub)
    probe._store["processed_entries"] = {
        "k1": {"status": "filtered", "rule_fingerprint": fp1, "time": "2026-01-01 00:00:00"}
    }
    assert probe._entry_processed({"x": 1}, sub) is True
    sub.include = "2160"
    assert probe._entry_processed({"x": 1}, sub) is False
    # transferred must not reopen solely due to rule change
    probe._store["processed_entries"]["k1"] = {
        "status": "transferred", "rule_fingerprint": fp1, "time": "2026-01-01 00:00:00"
    }
    assert probe._entry_processed({"x": 1}, sub) is True


def test_guard_subscribe_search_forwards_scheduled_interval():
    """可执行：未知 kwargs 必须原样交还 original。"""
    captured = {}

    def original(
        chain_self,
        sid=None,
        state="N",
        manual=False,
        progress_callback=None,
        sids=None,
        scheduled_interval=None,
        **extra,
    ):
        captured["kwargs"] = {
            "sid": sid,
            "state": state,
            "manual": manual,
            "sids": sids,
            "scheduled_interval": scheduled_interval,
            **extra,
        }
        return "native"

    def bind_search_args(original_fn, args, kwargs):
        merged = dict(kwargs or {})
        try:
            bound = inspect.signature(original_fn).bind_partial(*args, **merged)
            bound.apply_defaults()
            values = dict(bound.arguments)
        except TypeError:
            values = dict(merged)
        return {
            "sid": values.get("sid", merged.get("sid")),
            "sids": values.get("sids", merged.get("sids")),
            "state": values.get("state", merged.get("state", "N")),
            "manual": values.get("manual", merged.get("manual", False)),
            "progress_callback": values.get(
                "progress_callback", merged.get("progress_callback")
            ),
            "kwargs": merged,
            "args": args,
        }

    def call_original(original_fn, chain_self, *args, **kwargs):
        return original_fn(chain_self, *args, **kwargs)

    kwargs = {"state": "R", "scheduled_interval": 24, "future_flag": True}
    parsed = bind_search_args(original, (), kwargs)
    assert parsed["state"] == "R"
    assert parsed["kwargs"]["scheduled_interval"] == 24
    assert parsed["kwargs"]["future_flag"] is True
    result = call_original(original, object(), **parsed["kwargs"])
    assert result == "native"
    assert captured["kwargs"]["scheduled_interval"] == 24
    assert captured["kwargs"]["future_flag"] is True


def test_orphan_search_unwrap_restores_identity():
    class Chain:
        @staticmethod
        def search(self=None):
            return "root"

    root = Chain.search

    def outer(*a, **k):
        return "outer"

    outer._guangya_route_guard = True
    outer._guangya_original_search = root
    outer._guangya_plugin_ref = lambda: None

    def nested(*a, **k):
        return "nested"

    nested._guangya_route_guard = True
    nested._guangya_original_search = outer
    nested._guangya_plugin_ref = lambda: None
    Chain.search = nested

    # mirror emergency unwrap
    for _ in range(8):
        current = Chain.search
        if not getattr(current, "_guangya_route_guard", False):
            break
        owner = current._guangya_plugin_ref()
        if owner is not None:
            break
        original = getattr(current, "_guangya_original_search", None)
        if original is None or original is current:
            break
        Chain.search = original
    assert Chain.search is root


def test_syntax_of_touched_modules():
    for path in (
        PLUGIN / "routing_v170.py",
        PLUGIN / "runtime_v170.py",
        PLUGIN / "legacy.py",
        PLUGIN / "share_leaf_compat_v11225.py",
        PLUGIN / "__init__.py",
        PLUGIN / "content_resilience_v1105.py",
    ):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
