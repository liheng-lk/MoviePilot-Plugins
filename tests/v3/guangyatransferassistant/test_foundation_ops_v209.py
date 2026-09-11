"""2.0.9 内部迭代：native audit / library preflight / extractor inbox（不改 version）。"""
from __future__ import annotations

import ast
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Set, Tuple
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")


def test_foundation_mro_and_version_frozen():
    assert 'plugin_version = "2.0.10"' in ENTRY
    assert 'build_id = "20260911-r94"' in ENTRY
    head = ENTRY.split("class GuangYaTransferAssistant(", 1)[1].split("):", 1)[0]
    lines = [ln.strip().rstrip(",") for ln in head.strip().splitlines() if ln.strip()]
    assert lines[0] == "GuangYaFoundationOpsV209Mixin"
    assert lines[1] == "GuangYaEpisodeTargetV210Mixin"
    assert lines[2] == "GuangYaCalendarDrivenV209Mixin"
    assert "【原生审计】【RSS】" in ENTRY
    assert "channel_resource_cache_v1115" not in (PLUGIN / "foundation_ops_v209.py").read_text(encoding="utf-8")


def _load_module(path: Path, name: str):
    import sys
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    pkg_name = "plugins.v3.guangyatransferassistant"
    if "resource_inbox" in name or path.name.startswith("resource_inbox") or path.name.startswith("channel_message") or path.name.startswith("transfer_diag"):
        pkg = sys.modules.get(pkg_name) or types.ModuleType(pkg_name)
        pkg.__path__ = [str(PLUGIN)]
        sys.modules[pkg_name] = pkg
        st_name = f"{pkg_name}.source_types_v180"
        if st_name not in sys.modules:
            st = types.ModuleType(st_name)

            def normalize_source_uri(uri: str):
                text = str(uri or "")
                if text.lower().startswith("magnet:"):
                    return {"uri": text, "identity": text[7:60]}
                if text.lower().startswith("ed2k:"):
                    return {"uri": text, "identity": text[:80]}
                return {"uri": text, "identity": text}

            st.normalize_source_uri = normalize_source_uri
            sys.modules[st_name] = st
        mod.__package__ = pkg_name
        sys.modules[f"{pkg_name}.{path.stem}"] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_foundation_mixin():
    # Load resource_inbox first, then foundation via AST isolation for the class only
    inbox = _load_module(PLUGIN / "resource_inbox_v209.py", "gy_resource_inbox_v209")
    scan_name = "plugins.v3.guangyatransferassistant.channel_message_scan_v209"
    if scan_name not in sys.modules:
        scan = _load_module(PLUGIN / "channel_message_scan_v209.py", "gy_channel_message_scan_v209")
    else:
        scan = sys.modules[scan_name]
    diag_path = PLUGIN / "transfer_diag_v209.py"
    diag = _load_module(diag_path, "gy_transfer_diag_v209") if diag_path.exists() else None
    tree = ast.parse((PLUGIN / "foundation_ops_v209.py").read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "GuangYaFoundationOpsV209Mixin")
    mod_ast = ast.Module(body=[cls], type_ignores=[])
    ast.fix_missing_locations(mod_ast)
    ns: Dict[str, Any] = {
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "Optional": Optional,
        "Set": Set,
        "Tuple": Tuple,
        "Iterable": List,
        "threading": __import__("threading"),
        "time": __import__("time"),
        "hashlib": __import__("hashlib"),
        "urlparse": __import__("urllib.parse", fromlist=["urlparse"]).urlparse,
        "_INBOX_KEY": inbox._INBOX_KEY,
        "build_inbox_row_from_entry": inbox.build_inbox_row_from_entry,
        "build_inbox_row_from_message_block": inbox.build_inbox_row_from_message_block,
        "convert_inbox_row_to_entry": inbox.convert_inbox_row_to_entry,
        "extract_message_resource_candidates_v209": inbox.extract_message_resource_candidates_v209,
        "shadow_match_inbox_for_subscribe": inbox.shadow_match_inbox_for_subscribe,
        "summarize_page_extract_stats_v209": inbox.summarize_page_extract_stats_v209,
        "union_legacy_and_inbox_entries": inbox.union_legacy_and_inbox_entries,
        "upsert_inbox_rows": inbox.upsert_inbox_rows,
        "extract_channel_message_blocks_v209": scan.extract_channel_message_blocks_v209,
        "page_has_resource_features_v209": scan.page_has_resource_features_v209,
        "classify_transfer_message_v209": diag.classify_transfer_message_v209,
        "format_diag_log": diag.format_diag_log,
        "make_diag": diag.make_diag,
        "stable_trace_id": diag.stable_trace_id,
        "aggregate_subscription_diag": diag.aggregate_subscription_diag,
        "enrich_diag": diag.enrich_diag,
        "make_subscription_run_id": diag.make_subscription_run_id,
        "dedup_candidate_diags": diag.dedup_candidate_diags,
        "finalize_subscription_diag": diag.finalize_subscription_diag,
    }
    exec(compile(mod_ast, str(PLUGIN / "foundation_ops_v209.py"), "exec"), ns)
    return ns["GuangYaFoundationOpsV209Mixin"], inbox


def test_native_audit_blocks_managed_leak():
    Mixin, _ = _load_foundation_mixin()

    class Base:
        def _call_original_search(self, original, chain_self, *args, **kwargs):
            self.last_kwargs = dict(kwargs)
            return original(chain_self, **kwargs)

        def _plugin_log(self, *a, **k):
            self.logs = getattr(self, "logs", [])
            self.logs.append((a, k))

        def _is_managed_sid(self, sid):
            return int(sid) in set(self._selected_subscriptions)

        def _is_managed_subscription(self, sub):
            return int(getattr(sub, "id", 0) or 0) in set(self._selected_subscriptions)

        def _find_subscription(self, sid):
            return SimpleNamespace(id=int(sid), name=f"s{sid}")

    class Obj(Mixin, Base):
        pass

    obj = Obj()
    obj._selected_subscriptions = [101, 202]
    calls = []

    def original(chain_self, **kwargs):
        calls.append(dict(kwargs))
        return "ok"

    # managed only → None, never call original
    assert obj._call_original_search(original, object(), sid=101) is None
    assert calls == []

    # mixed sids → only unmanaged forwarded
    result = obj._call_original_search(original, object(), sids=(101, 303), manual=False)
    assert result == "ok"
    assert calls and set(calls[0].get("sids") or ()) == {303}
    assert any("【原生审计】" in str(x) for x in obj.logs)


def test_library_preflight_skips_when_missing_empty():
    Mixin, _ = _load_foundation_mixin()

    class Base:
        def _plugin_log(self, *a, **k):
            pass

        def _is_movie_subscription(self, subscribe):
            return False

        def _mp_authoritative_missing_episodes_v209(self, subscribe):
            return "used_complete", set()

        def _finish_subscription_if_complete(self, subscribe):
            return False

        def _resource_trace_v209(self, **kwargs):
            self.traces = getattr(self, "traces", [])
            self.traces.append(kwargs)

        def _try_transfer_subscription_inner(self, subscribe, force=False, refresh_channel=True):
            raise AssertionError("must not reach channel match when satisfied")

        def _begin_subscription_run_v209(self, subscribe):
            return "run-1"

        def _end_subscription_run_v209(self):
            pass

        def _trace_transfer_result_v209(self, subscribe, result):
            pass

    class Obj(Mixin, Base):
        pass

    obj = Obj()
    obj._library_snapshot_lock_v209 = __import__("threading").RLock()
    obj._library_snapshot_v209 = {}
    sub = SimpleNamespace(id=9, name="剧", media_id="1", season=1, tmdbid=1)
    result = Obj._try_transfer_subscription_inner(obj, sub, force=False, refresh_channel=False)
    assert result.get("completion_pending") or result.get("already")
    assert "满足" in str(result.get("message") or "") or "satisfied" in str(result.get("message") or "")


def test_library_preflight_used_empty_continues_match():
    Mixin, _ = _load_foundation_mixin()
    reached = []

    class Base:
        def _plugin_log(self, *a, **k):
            pass

        def _is_movie_subscription(self, subscribe):
            return False

        def _mp_authoritative_missing_episodes_v209(self, subscribe):
            return "used_empty", set()

        def _finish_subscription_if_complete(self, subscribe):
            raise AssertionError("must not finish on used_empty")

        def _resource_trace_v209(self, **kwargs):
            pass

        def _try_transfer_subscription_inner(self, subscribe, force=False, refresh_channel=True):
            reached.append(True)
            return {"success": True, "handled": True, "message": "continued"}

        def _begin_subscription_run_v209(self, subscribe):
            return "run-2"

        def _end_subscription_run_v209(self):
            pass

        def _trace_transfer_result_v209(self, subscribe, result):
            pass

        def _snapshot_candidate_diags_v209(self):
            return []

        def _shadow_inbox_compare_v209(self, subscribe, result):
            pass

        def _try_match_inbox_for_subscribe_v209(self, subscribe):
            return None

    class Obj(Mixin, Base):
        pass

    obj = Obj()
    obj._library_snapshot_lock_v209 = __import__("threading").RLock()
    obj._library_snapshot_v209 = {}
    snap = obj._library_preflight_v209(SimpleNamespace(id=10, name="冬城", media_id="290863", season=1, tmdbid=290863))
    assert snap["current_target_satisfied"] is False
    assert snap["preflight_state"] == "UNKNOWN"
    result = Obj._try_transfer_subscription_inner(
        obj, SimpleNamespace(id=10, name="冬城", media_id="290863", season=1, tmdbid=290863),
        force=False, refresh_channel=False,
    )
    assert reached == [True]
    assert result.get("message") == "continued"


def test_extractor_hidden_clipboard_and_wrapped_redirect():
    inbox = _load_module(PLUGIN / "resource_inbox_v209.py", "gy_resource_inbox_v209_extract")
    html = '''
    <a href="https://www.guangyapan.com/s/visible1">v</a>
    <a data-url="https://www.guangyapan.com/share/data1">d</a>
    <a data-clipboard-text="https://pan.xunlei.com/s/XLCLIP">copy</a>
    <div onclick="window.open('https://www.guangyapan.com/s/onclick1')">x</div>
    <script>location.href='https://www.guangyapan.com/s/js1'</script>
    <script>{"shareUrl":"https://www.guangyapan.com/s/json1"}</script>
    <a href="https://t.me/redirect?url=magnet%3A%3Fxt%3Durn%3Abtih%3ADEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEF">m</a>
    <a href="ed2k://|file|demo.mkv|1|ABCDEF|">e</a>
    <a href="https://go.example/r?target=https%3A%2F%2Fpan.xunlei.com%2Fs%2FXLWRAP">w</a>
    '''
    rows = inbox.extract_message_resource_candidates_v209(html, "可见文本 https://www.guangyapan.com/s/text1")
    by_type = {}
    for r in rows:
        by_type.setdefault(r["type"], []).append(r)
    assert "guangya" in by_type and "xunlei" in by_type and "magnet" in by_type and "ed2k" in by_type
    extractors = {r.get("extractor") for r in rows}
    assert "clipboard" in extractors
    assert "onclick" in extractors or "javascript" in extractors
    assert "json" in extractors
    assert any(r.get("extractor") == "wrapped_redirect" or "xunlei" == r.get("type") for r in rows)
    enriched = inbox.enrich_candidates_with_local_passcode(rows, "迅雷密码：abcd")
    assert any(r.get("type") == "xunlei" and r.get("passcode") == "abcd" for r in enriched)


def test_passcode_is_message_local():
    inbox = _load_module(PLUGIN / "resource_inbox_v209.py", "gy_resource_inbox_v209_pass")
    a = inbox.enrich_candidates_with_local_passcode(
        [{"type": "xunlei", "uri": "https://pan.xunlei.com/s/A", "identity": "A", "passcode": "", "extractor": "href"}],
        "只有链接没有密码",
    )
    b = inbox.enrich_candidates_with_local_passcode(
        [{"type": "xunlei", "uri": "https://pan.xunlei.com/s/B", "identity": "B", "passcode": "", "extractor": "href"}],
        "密码：ab12",
    )
    assert not a[0].get("passcode")
    assert b[0].get("passcode") == "ab12"


def test_inbox_bootstrap_dual_write_without_replacing_cache_key():
    inbox = _load_module(PLUGIN / "resource_inbox_v209.py", "gy_resource_inbox_v209_store")
    store = {}
    entry = {
        "source_url": "https://t.me/c/1",
        "message_id": "42",
        "title": "测试剧 S01E01",
        "share_url": "https://www.guangyapan.com/s/abc",
        "context_html": '<a data-url="magnet:?xt=urn:btih:ABCDEFABCDEFABCDEFABCDEFABCDEFABCDEF">x</a>',
    }
    row = inbox.build_inbox_row_from_entry(entry)
    assert row["candidates"]
    updated = inbox.upsert_inbox_rows(store, [row])
    assert updated["count"] >= 1
    assert inbox._INBOX_KEY == "channel_resource_inbox_v1"
    src = (PLUGIN / "resource_inbox_v209.py").read_text(encoding="utf-8")
    # production matcher cache key must not be written by inbox helpers
    assert "save_data" not in src
    assert "channel_resource_inbox_v1" in src
    assert "build_inbox_row_from_message_block" in src
    assert "union_legacy_and_inbox_entries" in src
