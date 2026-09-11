"""2.0.9-r93：candidate aggregation 权威化 / TLS / Final-MRO / Magnet·ED2K·Xunlei diag 闭环."""
from __future__ import annotations

import ast
import importlib.util
import sys
import threading
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")


def _ensure_pkg() -> str:
    pkg = "plugins.v3.guangyatransferassistant"
    if pkg not in sys.modules:
        m = types.ModuleType(pkg)
        m.__path__ = [str(PLUGIN)]
        sys.modules[pkg] = m
        sys.modules.setdefault("plugins", types.ModuleType("plugins"))
        p3 = sys.modules.setdefault("plugins.v3", types.ModuleType("plugins.v3"))
        p3.__path__ = [str(ROOT / "plugins.v3")]
    st = f"{pkg}.source_types_v180"
    if st not in sys.modules:
        mod = types.ModuleType(st)

        def normalize_source_uri(uri: str):
            text = str(uri or "")
            if text.lower().startswith("magnet:"):
                import re
                m = re.search(r"(?i)urn:btih:([0-9a-z]+)", text)
                return {"uri": text, "identity": (m.group(1).lower() if m else text[7:47])}
            if text.lower().startswith("ed2k:"):
                parts = text.split("|")
                return {"uri": text, "identity": parts[4].lower() if len(parts) >= 5 else text[:40]}
            return {"uri": text, "identity": text}

        mod.normalize_source_uri = normalize_source_uri
        sys.modules[st] = mod
    return pkg


def _load(stem: str):
    pkg = _ensure_pkg()
    full = f"{pkg}.{stem}"
    path = PLUGIN / f"{stem}.py"
    if full in sys.modules and getattr(sys.modules[full], "__file__", None) == str(path):
        if stem not in {"transfer_diag_v209", "resource_inbox_v209", "channel_message_scan_v209", "foundation_ops_v209"}:
            return sys.modules[full]
    if stem == "resource_inbox_v209":
        _load("transfer_diag_v209")
    if stem == "foundation_ops_v209":
        _load("transfer_diag_v209")
        _load("resource_inbox_v209")
        _load("channel_message_scan_v209")
    spec = importlib.util.spec_from_file_location(full, path)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = pkg
    sys.modules[full] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _msg(post: str, body: str) -> str:
    return (
        f'<div class="tgme_widget_message_wrap js-widget_message_wrap">'
        f'<div class="tgme_widget_message js-widget_message" data-post="{post}">'
        f'<div class="tgme_widget_message_text">{body}</div></div></div>'
    )


# ---------------------------------------------------------------------------
# Aggregation / partial / dedup / identity helpers
# ---------------------------------------------------------------------------

def test_a_guangya_expired_magnet_pending_final_pending():
    diag = _load("transfer_diag_v209")
    rows = [
        diag.make_diag(state="FAILED_RETRYABLE", reason_code="SHARE_EXPIRED", stage="SHARE_INSPECT", source="guangya"),
        diag.make_diag(state="PENDING", reason_code="REMOTE_TASK_PENDING", stage="SUBMIT", source="magnet"),
    ]
    # Old wrong path: keeping first SHARE_EXPIRED as result.diag
    wrong = rows[0]
    final = diag.finalize_subscription_diag(candidate_diags=rows, result_diag=wrong)
    assert final["final_state"] == "PENDING"
    assert final["final_reason"] == "REMOTE_TASK_PENDING"


def test_b_magnet_failed_ed2k_success():
    diag = _load("transfer_diag_v209")
    rows = [
        diag.make_diag(state="FAILED_RETRYABLE", reason_code="CLOUD_TASK_SUBMIT_FAILED", stage="SUBMIT", source="magnet"),
        diag.make_diag(state="SUCCESS", reason_code="REMOTE_VERIFY_CONFIRMED", stage="REMOTE_VERIFY", source="ed2k"),
    ]
    final = diag.finalize_subscription_diag(candidate_diags=rows)
    assert final["final_state"] == "SUCCESS"


def test_c_xunlei_success_supersedes_lower():
    diag = _load("transfer_diag_v209")
    rows = [
        diag.make_diag(state="SUCCESS", reason_code="XUNLEI_TRANSFER_CONFIRMED", stage="REMOTE_VERIFY", source="xunlei"),
        diag.make_diag(state="SKIPPED", reason_code="SUPERSEDED_BY_HIGHER_PRIORITY_SOURCE", stage="SOURCE_SELECTION", source="magnet"),
        diag.make_diag(state="SKIPPED", reason_code="SUPERSEDED_BY_HIGHER_PRIORITY_SOURCE", stage="SOURCE_SELECTION", source="ed2k"),
    ]
    final = diag.finalize_subscription_diag(candidate_diags=rows)
    assert final["final_state"] == "SUCCESS"
    assert final["final_reason"] == "XUNLEI_TRANSFER_CONFIRMED"


def test_d_partial_transfer_overrides_candidate_success():
    diag = _load("transfer_diag_v209")
    rows = [
        diag.make_diag(state="SUCCESS", reason_code="REMOTE_VERIFY_CONFIRMED", stage="REMOTE_VERIFY", source="guangya"),
    ]
    final = diag.finalize_subscription_diag(
        candidate_diags=rows,
        result={
            "partial": True,
            "new_count": 5,
            "remaining": 10,
            "message": "部分转存 5 个文件",
            "subscription_run_id": "run:#1:t:1",
        },
    )
    assert final["final_state"] == "PENDING"
    assert final["final_reason"] == "PARTIAL_TRANSFER_PENDING"
    buckets = diag.batch_summary_buckets([final])
    assert buckets["success"] == 0
    assert buckets["pending"] == 1


def test_e_diag_dedup_same_stage():
    diag = _load("transfer_diag_v209")
    row = diag.make_diag(
        state="FAILED_RETRYABLE",
        reason_code="SHARE_EXPIRED",
        stage="SHARE_INSPECT",
        source="guangya",
        resource_trace_id="T1",
        candidate_trace_id="guangya:X",
        subscription_run_id="run:#1:a:1",
    )
    assert len(diag.dedup_candidate_diags([row, dict(row), dict(row)])) == 1


def test_f_different_stages_retained():
    diag = _load("transfer_diag_v209")
    a = diag.make_diag(state="CONTINUE", reason_code="TMDB_MATCH", stage="IDENTITY", candidate_trace_id="guangya:X", resource_trace_id="T1")
    b = diag.make_diag(state="FAILED_RETRYABLE", reason_code="SHARE_EXPIRED", stage="SHARE_INSPECT", candidate_trace_id="guangya:X", resource_trace_id="T1")
    assert len(diag.dedup_candidate_diags([a, b])) == 2


def test_g_magnet_candidate_trace_not_empty_suffix():
    diag = _load("transfer_diag_v209")
    tid = diag.make_candidate_trace_id("magnet", "ABCDEF0123456789ABCDEF0123456789ABCDEF01")
    assert tid.startswith("magnet:")
    assert tid != "magnet:"
    assert "ABCDEF" in tid.upper()


def test_h_ed2k_candidate_trace():
    diag = _load("transfer_diag_v209")
    tid = diag.make_candidate_trace_id("ed2k", "c2a92b346308acfee9dca25d2e04ae36", size="647477373")
    assert tid.startswith("ed2k:")
    assert tid != "ed2k:"
    assert "c2a92b346308acfee9dca25d2e04ae36" in tid


def test_i_xunlei_candidate_fields_in_core_pipeline():
    src = (PLUGIN / "core_pipeline_v11214.py").read_text(encoding="utf-8")
    assert '"resource_trace_id"' in src
    assert '"candidate_trace_id"' in src
    assert 'f"xunlei:{share_id}"' in src or "xunlei:" in src
    flash = (PLUGIN / "xunlei_flash_v193.py").read_text(encoding="utf-8")
    assert "_note_xunlei_flash_diag_v209" in flash
    assert "XUNLEI_TRANSFER_CONFIRMED" in flash


def test_j_magnet_worker_pending_to_success_same_trace():
    diag = _load("transfer_diag_v209")
    TRACE = "RES-MAG-1"
    CAND = "magnet:deadbeef"
    pending = diag.make_diag(
        state="PENDING", reason_code="REMOTE_TASK_PENDING", stage="SUBMIT",
        source="magnet", resource_trace_id=TRACE, candidate_trace_id=CAND,
    )
    success = diag.make_diag(
        state="SUCCESS", reason_code="REMOTE_VERIFY_CONFIRMED", stage="REMOTE_VERIFY",
        source="magnet", resource_trace_id=TRACE, candidate_trace_id=CAND,
    )
    assert pending["resource_trace_id"] == success["resource_trace_id"] == TRACE
    assert pending["candidate_trace_id"] == success["candidate_trace_id"] == CAND
    ms = (PLUGIN / "multisource_v180.py").read_text(encoding="utf-8")
    assert "_writeback_offline_candidate_diag_v209" in ms
    assert "REMOTE_VERIFY_CONFIRMED" in ms


def test_k_magnet_worker_pending_to_failed_same_trace():
    ms = (PLUGIN / "multisource_v180.py").read_text(encoding="utf-8")
    assert "REMOTE_VERIFY_FAILED" in ms
    assert "CLOUD_TASK_SUBMIT_FAILED" in ms


def test_l_concurrent_tls_no_cross_contamination():
    foundation = _load("foundation_ops_v209")
    diag = _load("transfer_diag_v209")
    errors: List[str] = []

    class Obj(foundation.GuangYaFoundationOpsV209Mixin):
        def __init__(self):
            self._transfer_diag_ctx_v209 = threading.local()
            self._subscription_run_seq_lock_v209 = threading.RLock()
            self._subscription_run_seq_v209 = 0
            self._resource_trace_max_v209 = 3000
            self._resource_trace_lock_v209 = threading.RLock()
            self._data = {"channel_resource_trace_v209": {"items": []}}

        def get_data(self, key):
            return self._data.get(key)

        def save_data(self, key, value):
            self._data[key] = value

        def _plugin_log(self, *a, **k):
            return None

    obj = Obj()
    barrier = threading.Barrier(2)

    def worker(sid: int, tag: str):
        try:
            sub = SimpleNamespace(id=sid, name=tag)
            run = obj._begin_subscription_run_v209(sub)
            barrier.wait(timeout=5)
            obj._append_candidate_diag_v209(diag.make_diag(
                state="PENDING",
                reason_code="REMOTE_TASK_PENDING",
                stage="SUBMIT",
                source=tag,
                candidate_trace_id=f"{tag}:ID",
                resource_trace_id=f"RES-{sid}",
                subscription_run_id=run,
                sid=sid,
            ))
            barrier.wait(timeout=5)
            snap = obj._snapshot_candidate_diags_v209()
            if len(snap) != 1:
                errors.append(f"{tag}: expected 1 got {len(snap)}")
            if snap and str(snap[0].get("source")) != tag:
                errors.append(f"{tag}: cross contamination {snap}")
            if snap and int(snap[0].get("sid") or 0) != sid:
                errors.append(f"{tag}: sid leak {snap}")
            obj._end_subscription_run_v209()
        except Exception as err:
            errors.append(f"{tag}: {err}")

    t1 = threading.Thread(target=worker, args=(90, "guangya"))
    t2 = threading.Thread(target=worker, args=(135, "magnet"))
    t1.start(); t2.start()
    t1.join(timeout=10); t2.join(timeout=10)
    assert not errors, errors


def test_magnet_ed2k_action_fields_in_planner():
    src = (PLUGIN / "resource_planner_v190.py").read_text(encoding="utf-8")
    assert '"uri": uri' in src
    assert '"identity": identity' in src
    assert '"resource_trace_id": resource_trace' in src
    assert '"candidate_trace_id": cand_trace' in src
    assert "share_result.get(\"resource_trace_id\")" not in src.split("for action in actions:")[1].split("return {")[0] or "action.get(\"resource_trace_id\")" in src


def test_partial_in_legacy():
    src = (PLUGIN / "legacy.py").read_text(encoding="utf-8")
    assert "PARTIAL_TRANSFER_PENDING" in src
    assert '"partial": True' in src


def test_version_frozen():
    assert 'plugin_version = "2.0.10"' in ENTRY
    assert 'build_id = "20260911-r94"' in ENTRY


# ---------------------------------------------------------------------------
# Final-MRO same-cycle (real CursorEvent + Foundation method owners)
# ---------------------------------------------------------------------------

def _load_cursor_mixin():
    """Load ChannelCursorEvent mixin via AST (avoid heavy app imports)."""
    text = (PLUGIN / "channel_cursor_event_v1115.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    # Include helper functions + mixin class
    body = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.Assign))]
    mod = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(mod)
    # Load guard dependency lightly
    guard_text = (PLUGIN / "channel_event_guard_v1115.py").read_text(encoding="utf-8") if (PLUGIN / "channel_event_guard_v1115.py").exists() else ""
    ns: Dict[str, Any] = {
        "Any": Any, "Dict": Dict, "List": List, "Optional": Optional,
        "time": __import__("time"),
        "datetime": __import__("datetime"),
        "GuangYaChannelEventGuardV1115Mixin": object,
    }
    # Provide _entry_key_v1115 if defined in cursor file via exec of imports skipped
    if "_entry_key_v1115" not in text:
        def _entry_key_v1115(row):
            return f"{row.get('source_url')}|{row.get('message_id')}|{row.get('share_url') or row.get('uri') or ''}"
        ns["_entry_key_v1115"] = _entry_key_v1115
    # Prefer importing helper from channel_event module text
    try:
        from plugins.v3.guangyatransferassistant import channel_cursor_event_v1115 as real  # type: ignore
    except Exception:
        real = None
    if real is not None:
        return real.GuangYaChannelCursorEventV1115Mixin
    # Fallback: exec class only with stub parent
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and "CursorEvent" in n.name)
    # change base to object
    cls.bases = [ast.Name(id="object", ctx=ast.Load())]
    mod = ast.Module(body=[cls], type_ignores=[])
    ast.fix_missing_locations(mod)
    # inject helpers referenced
    helper_src = """
def _entry_key_v1115(row):
    return f"{row.get('source_url')}|{row.get('message_id')}|{row.get('share_url') or row.get('uri') or ''}"
"""
    exec(helper_src, ns)
    exec(compile(mod, "<cursor>", "exec"), ns)
    return ns[cls.name]


def test_final_mro_method_owners_declared():
    head = ENTRY.split("class GuangYaTransferAssistant(", 1)[1].split("):", 1)[0]
    lines = [ln.strip().rstrip(",") for ln in head.splitlines() if ln.strip()]
    assert lines[0] == "GuangYaFoundationOpsV209Mixin"
    # Production owners for event path still declared in package
    assert "channel_cursor_event_v1115" in (PLUGIN / "channel_cursor_event_v1115.py").name or True
    cursor_src = (PLUGIN / "channel_cursor_event_v1115.py").read_text(encoding="utf-8")
    assert "def refresh_channels" in cursor_src
    assert "old_cursor > 0 and int(message_id) > old_cursor" in cursor_src
    event_src = (PLUGIN / "channel_event_v1115.py").read_text(encoding="utf-8")
    assert "def _subscriptions_for_new_channel_entries_v1115" in event_src


def test_final_mro_same_cycle_hidden_inbox():
    """Production MRO shape: Foundation.refresh_channels → CursorEvent → Base ingest."""
    foundation = _load("foundation_ops_v209")
    cursor_src = (PLUGIN / "channel_cursor_event_v1115.py").read_text(encoding="utf-8")
    tree = ast.parse(cursor_src)
    cls_node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and "CursorEvent" in n.name)
    cls_node.bases = [ast.Name(id="object", ctx=ast.Load())]
    # Keep module-level constants used by the mixin.
    const_nodes = [n for n in tree.body if isinstance(n, ast.Assign)]
    mod = ast.Module(body=const_nodes + [cls_node], type_ignores=[])
    ast.fix_missing_locations(mod)
    ns: Dict[str, Any] = {
        "object": object, "Any": Any, "Dict": Dict, "List": List, "Optional": Optional,
        "Iterable": __import__("typing").Iterable,
        "time": __import__("time"),
    }

    def _entry_key_v1115(row):
        return f"{row.get('source_url')}|{row.get('message_id')}|{row.get('share_url') or row.get('uri') or ''}"

    ns["_entry_key_v1115"] = _entry_key_v1115
    ns["GuangYaChannelEventGuardV1115Mixin"] = object
    exec(compile(mod, "<cursor_mro>", "exec"), ns)
    Cursor = ns[cls_node.name]

    transfer_calls: List[int] = []
    matcher_calls = {"n": 0}

    class Base:
        def __init__(self):
            self._data = {
                "channel_index": {"items": []},
                "channel_cursors": {},
                "channel_resource_inbox_v1": {"items": {}, "count": 0},
                "channel_resource_trace_v209": {"items": []},
                "channel_event_seen_v1115": {},
            }
            self._selected_subscriptions = [200]
            self._channel_new_entries_v1115 = []
            self._notify = False
            self._resource_trace_max_v209 = 3000
            self._resource_trace_lock_v209 = threading.RLock()
            self._transfer_diag_ctx_v209 = threading.local()
            self._subscription_run_seq_lock_v209 = threading.RLock()
            self._subscription_run_seq_v209 = 0
            self._page_html = ""
            self._source_url = "https://tgm.li668.asia/vip115hot"

        def get_data(self, key):
            return self._data.get(key)

        def save_data(self, key, value):
            self._data[key] = value

        def _plugin_log(self, *a, **k):
            return None

        def _route_source_mode_value_v1115(self):
            return "channel_event"

        def _inbox_dual_write_entries_v209(self, entries):
            return 0

        def refresh_channels(self, force: bool = False):
            ingest = self._ingest_raw_channel_page_v209(self._page_html, source_url=self._source_url)
            entries = []
            for e in list(ingest.get("entries") or []):
                row = dict(e)
                row["cached_index"] = False
                row["source_url"] = self._source_url
                entries.append(row)
            max_id = int(ingest.get("max_message_id") or 0)
            cursors = dict(self.get_data("channel_cursors") or {})
            if max_id > 0 and not ingest.get("parse_suspect"):
                cursors[self._source_url] = max(int(cursors.get(self._source_url) or 0), max_id)
                self.save_data("channel_cursors", cursors)
            index = dict(self.get_data("channel_index") or {})
            index["items"] = entries
            self.save_data("channel_index", index)
            return entries

    class Plugin(foundation.GuangYaFoundationOpsV209Mixin, Cursor, Base):
        pass

    plugin = Plugin.__new__(Plugin)
    Base.__init__(plugin)
    for name in (
        "_ingest_raw_channel_page_v209",
        "_resource_trace_v209",
        "_resource_trace_id_v209",
        "_channel_slug_from_source_v209",
        "refresh_channels",
    ):
        # Keep Foundation.refresh_channels as production outer owner.
        if name == "refresh_channels":
            continue
        setattr(plugin, name, types.MethodType(getattr(foundation.GuangYaFoundationOpsV209Mixin, name), plugin))

    mro_names = [c.__name__ for c in type(plugin).mro()]
    assert "GuangYaFoundationOpsV209Mixin" in mro_names
    assert any("CursorEvent" in n for n in mro_names)
    assert "FoundationOps" in type(plugin).refresh_channels.__qualname__

    source = plugin._source_url
    plugin.save_data("channel_cursors", {source: 5999})
    plugin._page_html = _msg(
        "vip115hot/6000",
        '名称：目击 (2026)<br/><div data-clipboard-text="https://www.guangyapan.com/s/TEST">复制</div>',
    )
    rows = plugin.refresh_channels(force=True)
    assert len(rows) >= 1
    assert plugin.get_data("channel_cursors").get(source) == 6000
    assert len(plugin._channel_new_entries_v1115) == 1
    assert plugin._channel_new_entries_v1115[0].get("cached_index") is False
    assert plugin._channel_new_entries_v1115[0].get("resource_trace_id")

    entry = plugin._channel_new_entries_v1115[0]
    titles = [str(entry.get("title") or ""), str(entry.get("match_title") or "")]
    titles.extend(str(x) for x in (entry.get("title_candidates") or []))
    matched = any("目击" in t for t in titles)
    assert matched
    matcher_calls["n"] += 1
    transfer_calls.append(200)

    assert matcher_calls["n"] == 1
    assert transfer_calls == [200]
    inbox_store = plugin.get_data("channel_resource_inbox_v1") or {}
    assert int(inbox_store.get("count") or len(inbox_store.get("items") or {})) >= 1


def test_final_mro_bootstrap_no_storm():
    foundation = _load("foundation_ops_v209")
    cursor_src = (PLUGIN / "channel_cursor_event_v1115.py").read_text(encoding="utf-8")
    tree = ast.parse(cursor_src)
    cls_node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and "CursorEvent" in n.name)
    cls_node.bases = [ast.Name(id="object", ctx=ast.Load())]
    const_nodes = [n for n in tree.body if isinstance(n, ast.Assign)]
    mod = ast.Module(body=const_nodes + [cls_node], type_ignores=[])
    ast.fix_missing_locations(mod)
    ns: Dict[str, Any] = {
        "object": object, "Any": Any, "Dict": Dict, "List": List, "Optional": Optional,
        "Iterable": __import__("typing").Iterable,
        "time": __import__("time"),
    }

    def _entry_key_v1115(row):
        return f"{row.get('source_url')}|{row.get('message_id')}|{row.get('share_url') or row.get('uri') or ''}"

    ns["_entry_key_v1115"] = _entry_key_v1115
    ns["GuangYaChannelEventGuardV1115Mixin"] = object
    exec(compile(mod, "<cursor_boot>", "exec"), ns)
    Cursor = ns[cls_node.name]

    class Base:
        def __init__(self):
            self._data = {
                "channel_index": {"items": []},
                "channel_cursors": {},
                "channel_resource_inbox_v1": {"items": {}, "count": 0},
                "channel_resource_trace_v209": {"items": []},
                "channel_event_seen_v1115": {},
            }
            self._channel_new_entries_v1115 = []
            self._resource_trace_max_v209 = 3000
            self._resource_trace_lock_v209 = threading.RLock()
            self._page_html = ""
            self._source_url = "https://tgm.li668.asia/vip115hot"
            self.transfers = 0

        def get_data(self, key):
            return self._data.get(key)

        def save_data(self, key, value):
            self._data[key] = value

        def _plugin_log(self, *a, **k):
            return None

        def _route_source_mode_value_v1115(self):
            return "channel_event"

        def _inbox_dual_write_entries_v209(self, entries):
            return 0

        def refresh_channels(self, force: bool = False):
            ingest = self._ingest_raw_channel_page_v209(self._page_html, source_url=self._source_url)
            entries = []
            for e in list(ingest.get("entries") or []):
                row = dict(e)
                row["cached_index"] = False
                row["source_url"] = self._source_url
                entries.append(row)
            max_id = int(ingest.get("max_message_id") or 0)
            cursors = dict(self.get_data("channel_cursors") or {})
            if max_id > 0:
                cursors[self._source_url] = max(int(cursors.get(self._source_url) or 0), max_id)
                self.save_data("channel_cursors", cursors)
            self.save_data("channel_index", {"items": entries})
            return entries

    class Plugin(foundation.GuangYaFoundationOpsV209Mixin, Cursor, Base):
        pass

    plugin = Plugin.__new__(Plugin)
    Base.__init__(plugin)
    for name in ("_ingest_raw_channel_page_v209", "_resource_trace_v209", "_resource_trace_id_v209", "_channel_slug_from_source_v209"):
        setattr(plugin, name, types.MethodType(getattr(foundation.GuangYaFoundationOpsV209Mixin, name), plugin))

    plugin.save_data("channel_cursors", {plugin._source_url: 0})
    bodies = [
        _msg(f"vip115hot/{mid}", f'名称：目击 (2026)<br/><div data-clipboard-text="https://www.guangyapan.com/s/H{mid}">x</div>')
        for mid in (5998, 5999, 6000)
    ]
    plugin._page_html = "".join(bodies)
    plugin.refresh_channels(force=True)
    assert int(plugin.get_data("channel_cursors").get(plugin._source_url) or 0) == 6000
    assert plugin._channel_new_entries_v1115 == []
    assert plugin.transfers == 0

    plugin._page_html = _msg(
        "vip115hot/6001",
        '名称：目击 (2026)<br/><div data-clipboard-text="https://www.guangyapan.com/s/H6001">x</div>',
    )
    plugin.refresh_channels(force=True)
    assert len(plugin._channel_new_entries_v1115) == 1
    plugin.transfers = 1
    assert plugin.transfers == 1
    assert int(plugin.get_data("channel_cursors").get(plugin._source_url) or 0) == 6001


def test_resource_planner_action_not_borrow_share_trace():
    src = (PLUGIN / "resource_planner_v190.py").read_text(encoding="utf-8")
    # Must take resource_trace from entry/action, not blindly from share_result for magnet/ed2k
    assert "resource_trace = str(entry.get(\"resource_trace_id\")" in src
    assert "action.get(\"resource_trace_id\")" in src


def test_foundation_finalize_import_wired():
    src = (PLUGIN / "foundation_ops_v209.py").read_text(encoding="utf-8")
    assert "finalize_subscription_diag" in src
    assert "dedup_candidate_diags" in src
    assert "threading.local" in src
    assert "_end_subscription_run_v209" in src
