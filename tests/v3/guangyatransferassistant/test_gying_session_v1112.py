from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
SESSION_PATH = PLUGIN / "gying_session_v1112.py"
SESSION = SESSION_PATH.read_text(encoding="utf-8")
PACKAGE = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
LOCAL = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))


def _method_source(name: str) -> str:
    tree = ast.parse(SESSION, filename=str(SESSION_PATH))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "GuangYaGyingSessionV1112Mixin")
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == name)
    return ast.get_source_segment(SESSION, method) or ""


def test_v1112_release_metadata_and_outermost_mro():
    ast.parse(SESSION, filename=str(SESSION_PATH))
    ast.parse(ENTRY)
    assert PACKAGE["version"] == LOCAL["version"] == "1.10.12"
    assert 'plugin_version = "1.10.12"' in ENTRY
    assert 'build_id = "20260902-r23"' in ENTRY
    assert "v1.10.12" in PACKAGE.get("history", {})
    assert "from .gying_session_v1112 import GuangYaGyingSessionV1112Mixin" in ENTRY
    start = ENTRY.index("class GuangYaTransferAssistant")
    assert ENTRY.index("GuangYaGyingSessionV1112Mixin,", start) < ENTRY.index("GuangYaGyingTransportV1108Mixin,", start)


def test_challenge_cookies_are_not_cross_mirror_shared_or_restored():
    sanitize = SESSION.split("def _sanitize_cookie_header_v1112", 1)[1].split("\n\n\ndef ", 1)[0]
    new_session = _method_source("_gying_new_session")
    sync = _method_source("_gying_sync_cookie_v1108")
    assert '"browser_pow", "browser_verified"' in SESSION
    assert "_CHALLENGE_COOKIE_NAMES_V1112" in sanitize
    assert "_sanitize_cookie_header_v1112(_cookie_header_v1108(session))" in sync
    assert "for name in _CHALLENGE_COOKIE_NAMES_V1112:" in new_session
    assert "_drop_cookie_v1108(session, name)" in new_session


def test_new_remote_challenge_invalidates_stale_verified_before_ack():
    solve = _method_source("_gying_solve_challenge_v1110")
    assert 'kind == "remote_pow"' in solve
    assert '_has_cookie_v1111(session, "browser_verified")' in solve
    assert '_drop_cookie_v1108(session, "browser_verified")' in solve
    assert solve.index('_drop_cookie_v1108(session, "browser_verified")') < solve.index("super()._gying_solve_challenge_v1110")


def test_final_solver_routes_recognized_challenges_away_from_v1108_remote_solver():
    solve = _method_source("_gying_solve_challenge")
    assert 'kind in {"remote_pow", "embedded_pow", "legacy_hash"}' in solve
    assert "self._gying_solve_challenge_v1110" in solve
    assert 'kind == "refresh_overlay"' in solve
    assert "_gying_refresh_bootstrap_v1110" in solve
    recognized = solve.split('if kind in {"remote_pow", "embedded_pow", "legacy_hash"}:', 1)[1].split('if kind == "refresh_overlay":', 1)[0]
    assert "super()._gying_solve_challenge" not in recognized


def test_business_node_order_filters_registry_and_landing_domains():
    order = _method_source("_gying_node_order")
    assert "_is_content_candidate_v1111(node)" in order
    assert "_MAX_CONTENT_NODES_V1112" in order
    assert "gying." not in order
    assert "gyg." not in order


def test_hot_reload_owner_fences_old_gying_workers():
    auth_current = _method_source("_gying_auth_is_current_v1108")
    viewing = _method_source("_viewing_session")
    raw = _method_source("_gying_raw_results")
    assert "_gying_runtime_current_v1112" in auth_current
    assert '"mode": "stale_instance"' in viewing
    assert '"mode": "stale_instance"' in raw
    assert "旧版观影" in viewing and "旧版观影" in raw


def test_cloakbrowser_fallback_uses_only_moviepilot_official_sdk_and_is_lazy():
    browser = _method_source("_gying_browser_fallback_v1112")
    request = _method_source("_gying_request")
    assert "from app.sdk.browser import launch_browser_context" in browser
    assert "launch_browser_context(headless=True)" in browser
    assert "page.goto(" in browser
    assert "context.cookies()" in browser
    assert "_import_browser_cookies_v1112" in browser
    assert "算法链已经失败后才启用真实浏览器" in request
    assert "_gying_browser_fallback_v1112" in request
    top_level = SESSION.split("class GuangYaGyingSessionV1112Mixin", 1)[0]
    assert "from app.sdk.browser" not in top_level
    assert "import cloakbrowser" not in SESSION.lower()


def test_no_proxy_or_automatic_visual_captcha_solver_is_added():
    lowered = SESSION.lower()
    for forbidden in (
        "pytesseract",
        "easyocr",
        "paddleocr",
        "captcha_solver",
        "selenium",
        "proxy=",
        "proxies=",
    ):
        assert forbidden not in lowered
    assert "人工汉字验证码" in SESSION


def test_fixed_transfer_priority_is_untouched():
    assert "观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K" in ENTRY
    assert "Magnet/ED2K 继续使用光鸭原生 cloudcollection" in ENTRY
