from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
PATCH_PATH = PLUGIN / "gying_pansou_v1110.py"
PATCH = PATCH_PATH.read_text(encoding="utf-8")
UI = (PLUGIN / "gying_ui_v1109.py").read_text(encoding="utf-8")
FINAL = (PLUGIN / "xunlei_final_v1114.py").read_text(encoding="utf-8")
GOV = (PLUGIN / "governance_v1114.py").read_text(encoding="utf-8")
RUNTIME_FIX = (PLUGIN / "runtime_fix_v1113.py").read_text(encoding="utf-8")
FALLBACK = (PLUGIN / "gying_fallback_reuse_v1113.py").read_text(encoding="utf-8")
POW = (PLUGIN / "gying_pow_v1111.py").read_text(encoding="utf-8")


def _challenge_namespace():
    tree = ast.parse(PATCH, filename=str(PATCH_PATH))
    body = []
    wanted_assigns = {"_VERIFY_TEXT_V1110", "_REMOTE_SIG_V1110"}
    wanted_functions = {"_json_v1110", "_challenge_kind_v1110"}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if names.intersection(wanted_assigns):
                body.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in wanted_functions:
            node.returns = None
            for arg in node.args.args:
                arg.annotation = None
            body.append(node)
    module = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(module)

    import re
    runtime = (PLUGIN / "gying_runtime_v193.py").read_text(encoding="utf-8")
    match = re.search(r'_GYING_CHALLENGE_RE\s*=\s*re\.compile\(r"([^"]+)"\)', runtime)
    assert match
    ns: Dict[str, Any] = {
        "Any": Any,
        "Dict": Dict,
        "json": json,
        "_safe_int": lambda value, default=0: int(value or default),
        "_GYING_CHALLENGE_RE": re.compile(match.group(1)),
    }
    exec(compile(module, str(PATCH_PATH), "exec"), ns)
    return ns


class _Response(SimpleNamespace):
    def json(self):
        return json.loads(str(getattr(self, "text", "") or "{}"))


def test_v1110_release_and_layer_parse():
    for text in (PATCH, ENTRY, UI, FINAL, GOV, RUNTIME_FIX, FALLBACK, POW):
        ast.parse(text)
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    assert package["version"] == local["version"] == "1.10.15"
    assert 'plugin_version = "1.10.15"' in ENTRY
    assert 'build_id = "20260902-r30"' in ENTRY
    assert "v1.10.15" in package.get("history", {})
    assert "v1.10.12" in package.get("history", {})
    assert "v1.10.10" in package.get("history", {})
    assert "GuangYaGyingPanSouV1110Mixin" in POW
    assert "class GuangYaGyingPowV1111Mixin(GuangYaGyingPanSouV1110Mixin)" in POW
    assert "class GuangYaGyingUiV1109Mixin(GuangYaXunleiFinalV1114Mixin)" in UI
    assert "class GuangYaXunleiFinalV1114Mixin(GuangYaGovernanceV1114Mixin)" in FINAL
    assert "class GuangYaGovernanceV1114Mixin(GuangYaRuntimeFixV1113Mixin)" in GOV
    assert "class GuangYaRuntimeFixV1113Mixin(GuangYaGyingFallbackReuseV1113Mixin)" in RUNTIME_FIX
    assert "class GuangYaGyingFallbackReuseV1113Mixin(GuangYaGyingBrowserProfileV1112Mixin)" in FALLBACK


def test_challenge_detection_matches_pansou_and_does_not_confuse_refresh_with_remote_pow():
    kind = _challenge_namespace()["_challenge_kind_v1110"]

    normal = _Response(
        text="<script>_obj.search={};</script><script src='powSolve-demo.js'></script>浏览器安全验证",
        status_code=200,
    )
    assert kind(normal) == ""

    remote = _Response(
        text="<html>正在进行浏览器计算验证<script src='powSolve-demo.js'></script></html>",
        status_code=200,
    )
    assert kind(remote) == "remote_pow"

    embedded = _Response(
        text='浏览器安全验证<script>const json={"id":"abc","N":"ff","x":"02","t":3};const jss={};</script>',
        status_code=200,
    )
    assert kind(embedded) == "embedded_pow"

    refresh = _Response(
        text=json.dumps({"refresh": 1, "overlay": "https://static.example/pow-overlay.js", "msg": "验证"}),
        status_code=200,
    )
    assert kind(refresh) == "refresh_overlay"
    assert kind(refresh) != "remote_pow"


def test_remote_pow_follows_pansou_get_compute_post_success_retry_contract():
    solve = PATCH.split("    def _gying_solve_challenge_v1110(", 1)[1].split("    def _gying_refresh_bootstrap_v1110", 1)[0]
    request = PATCH.split("    def _gying_request(", 1)[1].split("\n\n\n__all__", 1)[0]
    refresh = PATCH.split("    def _gying_refresh_bootstrap_v1110(", 1)[1].split("    def _gying_request(", 1)[0]

    assert 'pow_url = node.rstrip("/") + "/res/pow"' in solve
    assert "challenge = session.get(" in solve
    assert "_solve_pow_hex" in solve
    assert "if elapsed < 3.0:" in solve
    assert 'data={"y": y}' in solve
    assert '_truthy_success_v1110(result.get("success"))' in solve
    assert "browser_verified" in solve
    assert "_drop_cookie_v1108" not in solve

    assert 'node.rstrip("/") + "/"' in refresh
    assert 'kind in {"embedded_pow", "legacy_hash", "remote_pow"}' in refresh
    assert 'attempts = 2 if retry_challenge else 1' in request
    assert 'if kind == "refresh_overlay":' in request
    assert "_gying_refresh_bootstrap_v1110" in request
    assert "PanSou PoW：原请求重试成功" in request


def test_v1110_does_not_add_browser_automation_ocr_or_secret_logging():
    lowered = PATCH.lower()
    for forbidden in (
        "pytesseract",
        "easyocr",
        "paddleocr",
        "playwright",
        "puppeteer",
        "selenium",
        "captcha_solver",
    ):
        assert forbidden not in lowered

    log_lines = [line for line in PATCH.splitlines() if "_gying_auth_log" in line or '"PanSou PoW：' in line]
    joined = "\n".join(log_lines).lower()
    for secret in ("password", "username", "cookie_header", "captcha", "points", " n=", " x=", " y="):
        assert secret not in joined


def test_fixed_transfer_priority_remains_unchanged():
    assert "观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K" in ENTRY
    assert "Magnet/ED2K 继续使用光鸭原生 cloudcollection" in ENTRY
