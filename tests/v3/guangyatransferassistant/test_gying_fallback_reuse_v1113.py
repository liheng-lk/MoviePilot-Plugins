from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
FALLBACK = PLUGIN / "gying_fallback_reuse_v1113.py"
UI = PLUGIN / "gying_ui_v1109.py"
BROWSER = PLUGIN / "gying_browser_v1112.py"

fallback_text = FALLBACK.read_text(encoding="utf-8")
ui_text = UI.read_text(encoding="utf-8")
browser_text = BROWSER.read_text(encoding="utf-8")


def test_fallback_layer_parses_and_is_wired_before_browser_profile():
    ast.parse(fallback_text, filename=str(FALLBACK))
    ast.parse(ui_text, filename=str(UI))
    assert "from .gying_fallback_reuse_v1113 import GuangYaGyingFallbackReuseV1113Mixin" in ui_text
    assert "class GuangYaGyingUiV1109Mixin(GuangYaGyingFallbackReuseV1113Mixin):" in ui_text
    assert "class GuangYaGyingFallbackReuseV1113Mixin(GuangYaGyingBrowserProfileV1112Mixin):" in fallback_text


def test_fallback_reuses_only_current_node_saved_verification_cookie_after_real_browser_failure():
    method = fallback_text.split("    def _gying_new_session(", 1)[1].split("\n\n\n__all__", 1)[0]
    assert 'getattr(self, "_gying_browser_fallback_logged_v1112", False)' in method
    assert "_restore_fallback_node_cookies_v1113(session, saved_cookie)" in method
    assert "_gying_shared_cookie_v1108" not in fallback_text
    for name in ("browser_pow", "browser_verified", "vrg_sc", "vrg_go"):
        assert f'"{name}"' in fallback_text


def test_cross_mirror_cookie_filter_remains_strict_in_browser_layer():
    sync = browser_text.split("    def _gying_sync_cookie_v1108(", 1)[1].split(
        "    def _gying_browser_key_v1112(", 1
    )[0]
    assert "_cookie_header_without_browser_state_v1112(session)" in sync
    assert "self._gying_shared_cookie_v1108 = header" in sync


def test_normal_cloakbrowser_mode_still_strips_restored_browser_bound_cookies():
    method = browser_text.split("    def _gying_new_session(", 1)[1].split(
        "    def _gying_sync_cookie_v1108(", 1
    )[0]
    assert "_BROWSER_BOUND_COOKIES_V1112" in method
    assert "session.cookies.clear(" in method
