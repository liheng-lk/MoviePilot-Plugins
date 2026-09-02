from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
BROWSER_PATH = PLUGIN / "gying_browser_v1111.py"
BROWSER = BROWSER_PATH.read_text(encoding="utf-8")
UI = (PLUGIN / "gying_ui_v1109.py").read_text(encoding="utf-8")


def test_v1111_release_and_sdk_layer_are_wired():
    ast.parse(BROWSER, filename=str(BROWSER_PATH))
    ast.parse(ENTRY)
    ast.parse(UI)
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    assert package["version"] == local["version"] == "1.10.11"
    assert 'plugin_version = "1.10.11"' in ENTRY
    assert 'build_id = "20260902-r22"' in ENTRY
    assert "v1.10.11" in package.get("history", {})
    assert "from app.sdk.browser import launch_browser_context" in BROWSER
    assert "class GuangYaGyingBrowserV1111Mixin(GuangYaGyingPanSouV1110Mixin)" in BROWSER
    assert "class GuangYaGyingUiV1109Mixin(GuangYaGyingBrowserV1111Mixin)" in UI


def test_browser_pow_is_node_local_and_old_cross_mirror_seed_is_disabled():
    assert '_EPHEMERAL_COOKIE_NAMES_V1111 = frozenset({"browser_pow"})' in BROWSER
    assert "def _clear_ephemeral_cookies_v1111" in BROWSER
    assert "_clear_ephemeral_cookies_v1111(session)" in BROWSER
    group = BROWSER.split("    def _gying_group_cookie_seed_v1108", 1)[1].split("    def _gying_sync_cookie_v1108", 1)[0]
    assert 'return ""' in group
    sync = BROWSER.split("    def _gying_sync_cookie_v1108", 1)[1].split("    def _gying_new_session", 1)[0]
    assert "return None" in sync
    assert "_REGISTRY_ONLY_HOSTS_V1111" in BROWSER
    assert "self._gying_registry_only_v1111(node)" in BROWSER


def test_challenge_switches_to_same_cloakbrowser_context_for_business_requests():
    assert "launch_browser_context(headless=True, **kwargs)" in BROWSER
    assert 'kwargs["proxy"] = proxy' in BROWSER
    assert "_gying_browser_page_v1111" in BROWSER
    request = BROWSER.split("    def _gying_request(", 1)[1].split("    def _gying_solve_challenge(", 1)[0]
    assert "current_page is not None and current_node == canonical" in request
    assert "_gying_browser_fetch_v1111" in request
    assert "切换 MoviePilot 官方 CloakBrowser 请求链" in request


def test_refresh_overlay_uses_site_script_and_retries_in_browser():
    fetch = BROWSER.split("    def _gying_browser_fetch_v1111(", 1)[1].split("    def _gying_request(", 1)[0]
    assert "payload.refresh" in fetch
    assert "payload.overlay" in fetch
    assert "window.PowOverlay" in fetch
    assert "window.PowOverlay.run(payload)" in fetch
    assert "result = await requestOnce()" in fetch
    assert "force=True" in fetch


def test_old_solver_entry_is_intercepted_and_no_captcha_automation_added():
    solver = BROWSER.split("    def _gying_solve_challenge(", 1)[1].split("\n\n\n__all__", 1)[0]
    assert "_gying_browser_bootstrap_v1111" in solver
    assert "_gying_solve_challenge_v1110" in solver
    lowered = BROWSER.lower()
    for forbidden in (
        "pytesseract",
        "easyocr",
        "paddleocr",
        "captcha_solver",
        "selenium",
        "from playwright",
    ):
        assert forbidden not in lowered


def test_fixed_transfer_route_is_unchanged():
    assert "观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K" in ENTRY
    assert "Magnet/ED2K 继续使用光鸭原生 cloudcollection" in ENTRY
