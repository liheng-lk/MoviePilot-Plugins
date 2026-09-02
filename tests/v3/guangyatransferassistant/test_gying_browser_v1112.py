from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
BROWSER = PLUGIN / "gying_browser_v1112.py"
VERIFIED = PLUGIN / "gying_browser_verified_v1112.py"
PROFILE = PLUGIN / "gying_browser_profile_v1112.py"
FALLBACK = PLUGIN / "gying_fallback_reuse_v1113.py"
RUNTIME_FIX = PLUGIN / "runtime_fix_v1113.py"
GOV = PLUGIN / "governance_v1114.py"
FINAL = PLUGIN / "xunlei_final_v1114.py"
UI = PLUGIN / "gying_ui_v1109.py"


browser_text = BROWSER.read_text(encoding="utf-8")
verified_text = VERIFIED.read_text(encoding="utf-8")
profile_text = PROFILE.read_text(encoding="utf-8")
fallback_text = FALLBACK.read_text(encoding="utf-8")
runtime_fix_text = RUNTIME_FIX.read_text(encoding="utf-8")
gov_text = GOV.read_text(encoding="utf-8")
final_text = FINAL.read_text(encoding="utf-8")
ui_text = UI.read_text(encoding="utf-8")


def test_v1112_browser_files_parse():
    for path, text in (
        (BROWSER, browser_text),
        (VERIFIED, verified_text),
        (PROFILE, profile_text),
        (FALLBACK, fallback_text),
        (RUNTIME_FIX, runtime_fix_text),
        (GOV, gov_text),
        (FINAL, final_text),
        (UI, ui_text),
    ):
        ast.parse(text, filename=str(path))


def test_v1112_uses_moviepilot_public_browser_sdk_and_fixed_single_thread_context():
    assert "from app.sdk.browser import launch_browser_context" in browser_text
    assert "from app.sdk.browser import launch_browser_context" in profile_text
    assert "ThreadPoolExecutor(" in browser_text
    assert "max_workers=1" in browser_text
    assert 'thread_name_prefix="gying-cloakbrowser"' in browser_text


def test_v1112_profile_matches_moviepilot_browser_defaults_without_internal_helper_dependency():
    assert '_DEFAULT_VIEWPORT_V1112 = {"width": 1280, "height": 720}' in profile_text
    assert 'get_runtime_setting("CLOAKBROWSER_HUMANIZE")' in profile_text
    assert 'get_runtime_setting("CLOAKBROWSER_HUMAN_PRESET")' in profile_text
    assert 'context_kwargs["humanize"] = humanize' in profile_text
    assert 'context_kwargs["human_preset"] = human_preset' in profile_text
    tree = ast.parse(profile_text, filename=str(PROFILE))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module != "app.adapters.network.browser"
            assert all(alias.name != "BrowserSessionHelper" for alias in node.names)
        elif isinstance(node, ast.Import):
            assert all(alias.name != "app.adapters.network.browser" for alias in node.names)
    assert "from app.sdk.browser import launch_browser_context" in profile_text


def test_v1112_keeps_business_requests_inside_browser_context():
    assert "credentials: 'include'" in browser_text
    assert "page.evaluate(" in browser_text
    assert "const response = await fetch(payload.url, options);" in browser_text
    assert "_gying_browser_fetch_v1112" in browser_text
    assert "_gying_browser_request_in_thread_v1112" in browser_text


def test_v1112_remote_pow_get_and_post_share_browser_fetch():
    solver = browser_text.split("    def _gying_browser_solve_v1112(", 1)[1].split(
        "    def _gying_browser_bootstrap_v1112(", 1
    )[0]
    assert 'pow_url = node.rstrip("/") + "/res/pow"' in solver
    assert '"GET",\n                pow_url' in solver
    assert '"POST",\n                pow_url' in solver
    assert "_solve_pow_hex(" in solver
    assert "_MIN_POW_SECONDS_V1112" in solver
    assert "session.get(" not in solver
    assert "session.post(" not in solver


def test_v1112_browser_bound_antibot_cookies_are_not_shared_or_restored_into_new_browser_context():
    for name in ("browser_pow", "browser_verified", "vrg_sc", "vrg_go"):
        assert f'"{name}"' in browser_text
    assert "_cookie_seed_v1112" in browser_text
    assert "_cookie_header_without_browser_state_v1112" in browser_text
    assert "self._gying_shared_cookie_v1108 = header" in browser_text
    assert "_restore_fallback_node_cookies_v1113(session, saved_cookie)" in fallback_text
    assert 'getattr(self, "_gying_browser_fallback_logged_v1112", False)' in fallback_text


def test_v1112_only_sdk_or_launch_unavailability_falls_back_to_requests_chain():
    request_method = browser_text.split("    def _gying_request(", 1)[1].split(
        "    def api_viewing_auth_start(", 1
    )[0]
    assert "except _GyingBrowserUnavailableV1112 as err:" in request_method
    assert "except Exception" not in request_method
    assert "return super()._gying_request(" in request_method


def test_v1112_browser_verified_wins_over_stale_challenge_dom():
    assert 'self._gying_browser_has_cookie_v1112(row, "browser_verified")' in verified_text
    assert "旧 DOM" in verified_text
    assert "_response_v1112(" in verified_text


def test_ui_chain_wires_final_governance_runtime_fallback_profile_verified_browser_layers():
    assert "class GuangYaGyingUiV1109Mixin(GuangYaXunleiFinalV1114Mixin):" in ui_text
    assert "class GuangYaXunleiFinalV1114Mixin(GuangYaGovernanceV1114Mixin):" in final_text
    assert "class GuangYaGovernanceV1114Mixin(GuangYaRuntimeFixV1113Mixin):" in gov_text
    assert "class GuangYaRuntimeFixV1113Mixin(GuangYaGyingFallbackReuseV1113Mixin):" in runtime_fix_text
    assert "class GuangYaGyingFallbackReuseV1113Mixin(GuangYaGyingBrowserProfileV1112Mixin):" in fallback_text
    assert "class GuangYaGyingBrowserProfileV1112Mixin(GuangYaGyingBrowserVerifiedV1112Mixin):" in profile_text
