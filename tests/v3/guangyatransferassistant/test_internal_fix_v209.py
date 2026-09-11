"""2.0.9 内部修正：guangyapan 域名 / ownership 不突变 / MP normalize import。"""
from __future__ import annotations

import ast
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Set
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"


def _load_inbox():
    name = "gy_resource_inbox_fix_v209"
    pkg = "plugins.v3.guangyatransferassistant"
    if pkg not in sys.modules:
        mod = types.ModuleType(pkg)
        mod.__path__ = [str(PLUGIN)]
        sys.modules[pkg] = mod
        sys.modules.setdefault("plugins", types.ModuleType("plugins"))
        sys.modules.setdefault("plugins.v3", types.ModuleType("plugins.v3"))
        sys.modules["plugins.v3"].__path__ = [str(ROOT / "plugins.v3")]
    st_name = f"{pkg}.source_types_v180"
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
    # stub legacy canonicalizer used by inbox
    leg_name = f"{pkg}.legacy"
    if leg_name not in sys.modules:
        leg = types.ModuleType(leg_name)

        def _canonical_share_url(raw_url: str, context: str = ""):
            text = str(raw_url or "")
            if "guangyapan.com" not in text.lower():
                return ""
            if "/s/" not in text and "/share/" not in text:
                return ""
            return text.split("#", 1)[0]

        leg._canonical_share_url = _canonical_share_url
        sys.modules[leg_name] = leg
    spec = importlib.util.spec_from_file_location(name, PLUGIN / "resource_inbox_v209.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    mod.__package__ = pkg
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _guangya_rows(rows):
    return [r for r in rows if r.get("type") == "guangya"]


def test_resource_inbox_real_guangyapan_domains():
    inbox = _load_inbox()
    visible = inbox.extract_message_resource_candidates_v209(
        "", "看这里 https://www.guangyapan.com/s/AAA"
    )
    assert any("guangyapan.com" in r["uri"] and r["identity"] == "AAA" for r in _guangya_rows(visible))
    bare = inbox.extract_message_resource_candidates_v209(
        "", "https://guangyapan.com/share/BBB"
    )
    assert any(r["identity"] == "BBB" for r in _guangya_rows(bare))
    # historical mirror still accepted
    legacy = inbox.extract_message_resource_candidates_v209(
        "", "https://www.guangyunav.com/s/LEGACY"
    )
    assert any(r["identity"] == "LEGACY" for r in _guangya_rows(legacy))


def test_resource_inbox_guangyapan_hidden_extractors():
    inbox = _load_inbox()
    encoded = quote("https://www.guangyapan.com/s/GGG", safe="")
    html = f'''
    <a href="https://www.guangyapan.com/s/BBB">href</a>
    <a data-url="https://www.guangyapan.com/share/CCC">data</a>
    <a data-clipboard-text="https://www.guangyapan.com/s/DDD">clip</a>
    <div onclick="window.open('https://www.guangyapan.com/s/EEE')">click</div>
    <script>{{"shareUrl":"https://www.guangyapan.com/s/FFF"}}</script>
    <a href="https://example.com/redirect?url={encoded}">wrap</a>
    '''
    rows = inbox.extract_message_resource_candidates_v209(html, "")
    by_id = {r["identity"]: r for r in _guangya_rows(rows)}
    for identity in ("BBB", "CCC", "DDD", "EEE", "FFF", "GGG"):
        assert identity in by_id, identity
        assert "guangyapan.com" in by_id[identity]["uri"]
    assert by_id["DDD"]["extractor"] == "clipboard"
    assert by_id["EEE"]["extractor"] in {"onclick", "javascript"}
    assert by_id["FFF"]["extractor"] == "json"
    assert by_id["GGG"]["extractor"] == "wrapped_redirect" or "guangyapan.com" in by_id["GGG"]["uri"]


def test_resource_inbox_guangyapan_bootstrap_write():
    inbox = _load_inbox()
    entry = {
        "source_url": "https://tgm.li668.asia/pan_guangya",
        "channel": "pan_guangya",
        "message_id": "12345",
        "title": "测试资源",
        "context_html": '<a data-clipboard-text="https://www.guangyapan.com/s/TEST123">x</a>',
        "text": "",
    }
    row = inbox.build_inbox_row_from_entry(entry)
    assert row["candidates"]
    assert any(
        c.get("type") == "guangya" and "guangyapan.com" in str(c.get("uri") or "")
        for c in row["candidates"]
    )
    store = inbox.upsert_inbox_rows({}, [row])
    assert store["count"] >= 1
    # bootstrap: no new event requirement — inbox still holds the row
    assert any(
        any(c.get("identity") == "TEST123" for c in (item.get("candidates") or []))
        for item in (store.get("items") or {}).values()
    )


def _load_foundation_mixin():
    inbox = _load_inbox()
    diag_spec = importlib.util.spec_from_file_location("gy_transfer_diag_fix", PLUGIN / "transfer_diag_v209.py")
    diag = importlib.util.module_from_spec(diag_spec)
    assert diag_spec.loader is not None
    diag_spec.loader.exec_module(diag)
    tree = ast.parse((PLUGIN / "foundation_ops_v209.py").read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "GuangYaFoundationOpsV209Mixin")
    wanted = {
        "_subscriptions_for_new_channel_entries_v1115",
        "_library_preflight_v209",
        "_library_snapshot_key_v209",
        "_resource_trace_v209",
        "_resource_trace_id_v209",
        "_managed_ids_now_v209",
        "_is_managed_sid",
    }
    methods = [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in wanted]
    stub = ast.ClassDef(name="GuangYaFoundationOpsV209Mixin", bases=[], keywords=[], body=methods or [ast.Pass()], decorator_list=[])
    mod = ast.Module(body=[stub], type_ignores=[])
    ast.fix_missing_locations(mod)
    ns: Dict[str, Any] = {
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "Optional": Optional,
        "Set": Set,
        "Iterable": List,
        "Tuple": tuple,
        "threading": __import__("threading"),
        "time": __import__("time"),
        "hashlib": __import__("hashlib"),
        "_INBOX_KEY": inbox._INBOX_KEY,
        "build_inbox_row_from_entry": inbox.build_inbox_row_from_entry,
        "extract_message_resource_candidates_v209": inbox.extract_message_resource_candidates_v209,
        "shadow_match_inbox_for_subscribe": inbox.shadow_match_inbox_for_subscribe,
        "upsert_inbox_rows": inbox.upsert_inbox_rows,
        "stable_trace_id": diag.stable_trace_id,
        "classify_transfer_message_v209": diag.classify_transfer_message_v209,
        "format_diag_log": diag.format_diag_log,
        "make_diag": diag.make_diag,
    }
    exec(compile(mod, str(PLUGIN / "foundation_ops_v209.py"), "exec"), ns)
    return ns["GuangYaFoundationOpsV209Mixin"]


def test_library_preflight_does_not_mutate_selected_subscriptions():
    Mixin = _load_foundation_mixin()
    observed: List[List[int]] = []

    class Parent:
        def _subscriptions_for_new_channel_entries_v1115(self):
            observed.append(list(self._selected_subscriptions))
            return [90, 135]

        def _plugin_log(self, *a, **k):
            pass

        def _resource_trace_v209(self, **kwargs):
            pass

        def _is_guangya_route(self, subscribe):
            return True

        def _list_subscriptions(self, state=None):
            return [
                SimpleNamespace(id=90, name="done", media_id="1", season=1, tmdbid=1),
                SimpleNamespace(id=135, name="miss", media_id="2", season=1, tmdbid=2),
            ]

        def _is_movie_subscription(self, subscribe):
            return False

        def _mp_authoritative_missing_episodes_v209(self, subscribe):
            sid = int(getattr(subscribe, "id", 0) or 0)
            if sid == 90:
                return "used_complete", set()
            return "used_missing", {10}

        def get_data(self, key):
            return {}

        def save_data(self, key, value):
            return None

        def _is_managed_sid(self, sid):
            return int(sid) in {int(v) for v in self._selected_subscriptions}

    class Obj(Mixin, Parent):
        pass

    obj = Obj()
    obj._resource_trace_max_v209 = 100
    obj._library_snapshot_lock_v209 = __import__("threading").RLock()
    obj._library_snapshot_v209 = {}
    obj._resource_trace_lock_v209 = __import__("threading").RLock()
    obj._selected_subscriptions = [90, 135]
    before = list(obj._selected_subscriptions)
    result = obj._subscriptions_for_new_channel_entries_v1115()
    after = list(obj._selected_subscriptions)
    assert before == [90, 135]
    assert after == [90, 135]
    assert observed == [[90, 135]]  # during super: ownership unchanged
    assert result == [135]


def test_library_preflight_managed_sid_remains_managed():
    Mixin = _load_foundation_mixin()

    class Parent:
        def _subscriptions_for_new_channel_entries_v1115(self):
            # concurrent observer: managed check during preflight path
            assert self._is_managed_sid(90) is True
            return [90]

        def _plugin_log(self, *a, **k):
            pass

        def _resource_trace_v209(self, **kwargs):
            pass

        def _is_guangya_route(self, subscribe):
            return True

        def _list_subscriptions(self, state=None):
            return [SimpleNamespace(id=90, name="done", media_id="1", season=1, tmdbid=1)]

        def _is_movie_subscription(self, subscribe):
            return False

        def _mp_authoritative_missing_episodes_v209(self, subscribe):
            return "used_complete", set()

        def get_data(self, key):
            return {}

        def save_data(self, key, value):
            return None

        def _is_managed_sid(self, sid):
            return int(sid) in {int(v) for v in self._selected_subscriptions}

    class Obj(Mixin, Parent):
        pass

    obj = Obj()
    obj._resource_trace_max_v209 = 100
    obj._library_snapshot_lock_v209 = __import__("threading").RLock()
    obj._library_snapshot_v209 = {}
    obj._resource_trace_lock_v209 = __import__("threading").RLock()
    obj._selected_subscriptions = [90]
    assert obj._is_managed_sid(90) is True
    result = obj._subscriptions_for_new_channel_entries_v1115()
    assert result == []  # skip_match filtered
    assert obj._is_managed_sid(90) is True
    assert obj._selected_subscriptions == [90]


def test_moviepilot_normalize_media_source_import():
    src = (PLUGIN / "media_source_v209.py").read_text(encoding="utf-8")
    assert "from app.schemas.media import normalize_media_source" in src
    media_idx = src.index("from app.schemas.media import normalize_media_source")
    types_idx = src.index("from app.schemas.types import normalize_media_source")
    assert media_idx < types_idx
    assert "except ImportError" in src
    assert "except Exception:\n        normalize_media_source" not in src

    ms = importlib.util.spec_from_file_location("media_source_check_v209", PLUGIN / "media_source_v209.py")
    mod = importlib.util.module_from_spec(ms)
    assert ms.loader is not None
    ms.loader.exec_module(mod)
    assert mod.is_tmdb_source("themoviedb") is True
    assert mod.is_tmdb_source("tmdb") is True
    assert mod.is_tmdb_source("TMDB") is True
    assert mod.is_tmdb_source("TheMovieDB") is True
    assert mod.is_tmdb_source("imdb") is False
    assert mod.is_tmdb_source(None) is False
    assert mod.is_tmdb_source("") is False
