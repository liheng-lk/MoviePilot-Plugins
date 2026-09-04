from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
PATCH_PATH = PLUGIN / "gying_pow_v1111.py"
PATCH = PATCH_PATH.read_text(encoding="utf-8")
UI = (PLUGIN / "gying_ui_v1109.py").read_text(encoding="utf-8")
FINAL = (PLUGIN / "xunlei_final_v1114.py").read_text(encoding="utf-8")
GOV = (PLUGIN / "governance_v1114.py").read_text(encoding="utf-8")
RUNTIME_FIX = (PLUGIN / "runtime_fix_v1113.py").read_text(encoding="utf-8")
FALLBACK = (PLUGIN / "gying_fallback_reuse_v1113.py").read_text(encoding="utf-8")


def test_v1111_release_and_layer_parse():
    for text in (PATCH, ENTRY, UI, FINAL, GOV, RUNTIME_FIX, FALLBACK):
        ast.parse(text)
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    assert package["version"] == local["version"] == "1.12.5"
    assert 'plugin_version = "1.12.5"' in ENTRY
    assert 'build_id = "20260904-r51"' in ENTRY
    assert "v1.12.5" in package.get("history", {})
    assert "v1.12.3" in package.get("history", {})
    assert "v1.10.16" in package.get("history", {})
    assert "v1.10.12" in package.get("history", {})
    assert "v1.10.11" in package.get("history", {})
    assert "class GuangYaGyingPowV1111Mixin(GuangYaGyingPanSouV1110Mixin)" in PATCH
    assert "class GuangYaGyingUiV1109Mixin(GuangYaConsoleControlCursorV1116Mixin)" in UI
    assert "class GuangYaXunleiFinalV1114Mixin(GuangYaGovernanceV1114Mixin)" in FINAL
    assert "class GuangYaGovernanceV1114Mixin(GuangYaRuntimeFixV1113Mixin)" in GOV
    assert "class GuangYaRuntimeFixV1113Mixin(GuangYaGyingFallbackReuseV1113Mixin)" in RUNTIME_FIX
    assert "class GuangYaGyingFallbackReuseV1113Mixin(GuangYaGyingBrowserProfileV1112Mixin)" in FALLBACK


def test_remote_pow_timer_starts_after_challenge_fetch():
    method = PATCH.split("    def _gying_solve_challenge_v1110(", 1)[1].split("    def _gying_request(", 1)[0]
    get_pos = method.index("challenge = session.get(")
    parse_pos = method.index("data = _json_v1110(challenge)")
    timer_pos = method.index("solve_started = time.monotonic()")
    solve_pos = method.index("_solve_pow_hex(", timer_pos)
    assert get_pos < parse_pos < timer_pos < solve_pos
    assert "_MIN_REMOTE_POW_SECONDS_V1111 = 3.15" in PATCH
    assert "time.sleep(_MIN_REMOTE_POW_SECONDS_V1111 - solve_elapsed)" in method


def test_http_200_without_ack_is_verified_by_original_retry_not_premature_failure():
    solve = PATCH.split("    def _gying_solve_challenge_v1110(", 1)[1].split("    def _gying_request(", 1)[0]
    assert "if status >= 400:" in solve
    assert '_truthy_success_v1110(success_value)' in solve
    assert "code_ok" in solve
    assert '_has_cookie_v1111(session, "browser_verified")' in solve
    assert "继续以原请求验真" in solve
    assert '"success": True' in solve
    assert "or not _truthy_success_v1110" not in solve


def test_business_failover_excludes_registry_landing_domains():
    discovery = PATCH.split("    def _discover_gying_nodes(", 1)[1].split("    def _gying_solve_challenge_v1110(", 1)[0]
    candidate = PATCH.split("def _is_content_candidate_v1111", 1)[1].split("\n\n\nclass", 1)[0]
    assert 'host.startswith("xn--") or ".xn--" in host' in candidate
    assert "if force:" in discovery
    assert "super()._discover_gying_nodes(force=True)" in discovery
    assert "_GYING_MIRRORS_V1108" in discovery
    assert "_MAX_CONTENT_NODES_V1111 = 10" in PATCH


def test_pow_does_not_require_or_recommend_proxy():
    request = PATCH.split("    def _gying_request(", 1)[1].split("\n\n\n__all__", 1)[0]
    assert "观影/外部搜索使用代理" not in PATCH
    assert "session.proxies" not in PATCH
    assert "getattr(session, \"proxies\"" not in PATCH
    assert "return super()._gying_request(" in request
    lowered = PATCH.lower()
    for forbidden in (
        "pytesseract",
        "easyocr",
        "paddleocr",
        "captcha_solver",
        "selenium",
        "playwright",
        "launch_browser_context",
    ):
        assert forbidden not in lowered


def test_fixed_transfer_priority_remains_unchanged():
    assert "观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K" in ENTRY
    assert "Magnet/ED2K 继续使用光鸭原生 cloudcollection" in ENTRY
