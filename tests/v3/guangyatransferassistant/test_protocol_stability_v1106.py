from __future__ import annotations

import ast
import html
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import parse_qs, quote, urlparse


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
PROTOCOL = (PLUGIN / "gying_protocol_v1106.py").read_text(encoding="utf-8")
STABILITY = (PLUGIN / "stability_v1106.py").read_text(encoding="utf-8")


def _helper_namespace(source: str, names: set[str], *, extra: Dict[str, Any] | None = None) -> Dict[str, Any]:
    tree = ast.parse(source)
    body = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.Assign))
        and (
            isinstance(node, ast.FunctionDef) and node.name in names
            or isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id in names for target in node.targets)
        )
    ]
    namespace: Dict[str, Any] = {
        "Any": Any,
        "Dict": Dict,
        "Iterable": Iterable,
        "List": List,
        "Optional": Optional,
        "html": html,
        "json": json,
        "re": re,
        "quote": quote,
        "parse_qs": parse_qs,
        "urlparse": urlparse,
        "_find_links": lambda *args, **kwargs: [],
    }
    namespace.update(extra or {})
    exec(compile(ast.Module(body=body, type_ignores=[]), "<helpers>", "exec"), namespace)
    return namespace


def test_v1106_layers_parse_and_mro_is_intentional():
    ast.parse(PROTOCOL)
    ast.parse(STABILITY)
    ast.parse(ENTRY)
    assert "from .gying_protocol_v1106 import GuangYaGyingProtocolV1106Mixin" in ENTRY
    assert "from .stability_v1106 import GuangYaStabilityV1106Mixin" in ENTRY
    start = ENTRY.index("class GuangYaTransferAssistant")
    assert ENTRY.index("GuangYaStabilityV1106Mixin,", start) < ENTRY.index("GuangYaContentResilienceV1105Mixin,", start)
    assert ENTRY.index("GuangYaGyingObservabilityV1104Mixin,", start) < ENTRY.index("GuangYaGyingHardeningMixin,", start)
    assert ENTRY.index("GuangYaGyingHardeningMixin,", start) < ENTRY.index("GuangYaGyingFailoverMixin,", start)
    assert ENTRY.index("GuangYaGyingFailoverMixin,", start) < ENTRY.index("GuangYaGyingProtocolV1106Mixin,", start)
    assert ENTRY.index("GuangYaGyingProtocolV1106Mixin,", start) < ENTRY.index("GuangYaGyingRuntimeMixin,", start)


def test_har_downurl_shape_yields_pan_passcode_and_direct_magnet():
    names = {
        "_BTIH_RE",
        "_safe_int",
        "_as_list",
        "_recursive_dict",
        "extract_panlist_v1106",
        "extract_downlist_v1106",
        "_parallel_value",
        "_build_magnet",
        "extract_resource_rows_v1106",
    }
    ns = _helper_namespace(PROTOCOL, names)
    payload = {
        "code": 200,
        "downlist": {
            "list": {
                "t": ["Captured.Movie.2026.2160p", "Folder Resource"],
                "m": ["0123456789abcdef0123456789abcdef01234567", ""],
                "k": [0, 2],
                "u": ["btDetailA", "btDetailB"],
                "s": ["12.5G", "20G"],
                "e": [31, 0],
                "p": ["tracker", "folder"],
                "n": ["today", "today"],
            }
        },
        "panlist": {
            "url": [
                "https://pan.xunlei.com/s/XL123",
                "https://pan.quark.cn/s/QK123",
            ],
            "name": ["迅雷资源", "夸克资源"],
            "type": [1, 2],
            "p": ["a1b2", ""],
            "id": [101, 102],
        },
    }
    item = {"title": "Captured Movie", "year": 2026, "type": "mv", "id": "akpW8"}
    rows = ns["extract_resource_rows_v1106"](payload, item)
    assert len(rows) == 3
    xunlei = next(row for row in rows if "pan.xunlei.com" in row["url"])
    assert xunlei["passcode"] == "a1b2"
    assert xunlei["resource_kind"] == "pan"
    magnet = next(row for row in rows if row["url"].startswith("magnet:?"))
    assert "0123456789abcdef0123456789abcdef01234567" in magnet["url"]
    assert "Captured.Movie.2026.2160p" in magnet["url"]
    assert magnet["bt_detail_id"] == "btDetailA"
    assert all(row.get("bt_detail_id") != "btDetailB" for row in rows)


def test_protocol_uses_real_browser_search_and_downurl_without_fake_clicks():
    assert '"browser", f"{node}/search?q={query}&type=&mode=1"' in PROTOCOL
    assert '"legacy", f"{node}/search?q={query}&type=0&mode=2"' in PROTOCOL
    assert "/res/downurl/" in PROTOCOL
    assert "extract_downlist_v1106" in PROTOCOL
    assert "downlist.list.k == 0" in PROTOCOL
    assert "magnet:?xt=urn:btih:" in PROTOCOL
    assert "bt_detail_id" in PROTOCOL
    assert "window.open" not in PROTOCOL
    assert "selenium" not in PROTOCOL.lower()


def test_protocol_handles_json_login_flag_refresh_and_cookie_reuse():
    for token in (
        'payload.get("login")',
        'payload.get("refresh")',
        "configured_cookie",
        "cookie_reuse",
        "captcha_required",
        "网页图形验证码",
        '"Origin": node.rstrip("/")',
        '"Referer": login_url',
    ):
        assert token in PROTOCOL
    assert '"passcode": str(_parallel_value(pan, "p", index, "")' in PROTOCOL


def test_dirty_selected_ids_and_source_rows_are_normalized():
    names = {
        "_INT_CONFIGS",
        "safe_int_v1106",
        "safe_float_v1106",
        "selected_ids_v1106",
        "selected_indexes_v1106",
        "sanitize_source_row_v1106",
    }
    ns = _helper_namespace(STABILITY, names)
    assert ns["selected_ids_v1106"]("1, 2，undefined;2; 0;abc;9") == [1, 2, 9]
    row = ns["sanitize_source_row_v1106"]({
        "subscribe_id": "undefined",
        "attempts": "bad",
        "progress": "999",
        "next_retry_at": "NaN?",
        "selected_indexes": "0,2,undefined,2",
    })
    assert row["subscribe_id"] == 0
    assert row["attempts"] == 0
    assert row["progress"] == 100
    assert row["next_retry_at"] == 0.0
    assert row["selected_indexes"] == [0, 2]


def test_stability_guards_known_crash_boundaries():
    for token in (
        "_heal_selected_subscriptions_v1106",
        "api_provider_test",
        "api_provider_search_selected",
        "sanitize_source_row_v1106(source)",
        "provider_test_last",
        "if isinstance(row, dict)",
        "_source_store",
        "_sources_for_subscription",
        "_upsert_source",
    ):
        assert token in STABILITY


def test_v1106_layers_do_not_enable_moviepilot_native_downloader():
    combined = (PROTOCOL + "\n" + STABILITY).lower()
    for forbidden in (
        "downloadchain(",
        "from app.chain.download",
        "qbittorrent",
        "transmission",
        "aria2",
        "add_download",
    ):
        assert forbidden not in combined
