from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
AUTH = PLUGIN / "gying_auth_v1107.py"
AUTH_VERIFIED = PLUGIN / "gying_auth_verified_v1107.py"
STABILITY = PLUGIN / "stability_v1106.py"
ENTRY = PLUGIN / "__init__.py"


auth_text = AUTH.read_text(encoding="utf-8")
verified_text = AUTH_VERIFIED.read_text(encoding="utf-8")
stability_text = STABILITY.read_text(encoding="utf-8")
entry_text = ENTRY.read_text(encoding="utf-8")


def test_v1107_files_parse_and_release_metadata_are_aligned():
    for path, text in (
        (AUTH, auth_text),
        (AUTH_VERIFIED, verified_text),
        (STABILITY, stability_text),
        (ENTRY, entry_text),
    ):
        ast.parse(text, filename=str(path))
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    assert package["version"] == local["version"] == "1.10.8"
    assert 'plugin_version = "1.10.8"' in entry_text
    assert 'build_id = "20260902-r19"' in entry_text
    assert "v1.10.8" in package.get("history", {})
    assert "v1.10.7" in package.get("history", {})


def test_v1107_auth_layer_is_outermost_through_stability_gate():
    assert "from .gying_auth_verified_v1107 import GuangYaGyingAuthVerifiedV1107Mixin" in stability_text
    assert "class GuangYaStabilityV1106Mixin(GuangYaGyingAuthVerifiedV1107Mixin):" in stability_text
    assert "class GuangYaGyingAuthVerifiedV1107Mixin(GuangYaGyingAuthV1107Mixin):" in verified_text
    start = entry_text.index("class GuangYaTransferAssistant")
    assert entry_text.index("GuangYaStabilityV1106Mixin,", start) < entry_text.index("GuangYaGyingProtocolV1106Mixin,", start)
    assert entry_text.index("GuangYaGyingProtocolV1106Mixin,", start) < entry_text.index("GuangYaGyingRuntimeMixin,", start)


def test_real_click_captcha_protocol_is_encoded_without_ocr():
    for token in (
        '"/res/captcha/2"',
        'data={"webp": "1"}',
        'data={"do": "check", "info": info}',
        'payload.get("code") in (200, "200")',
        '"code": str(info or "")',
        'payload.get("type")',
        'payload.get("img")',
        'payload.get("text")',
        "_CAPTCHA_WIDTH = 315",
        "_CAPTCHA_HEIGHT = 180",
        "_CAPTCHA_GRID = 15",
    ):
        assert token in auth_text, token
    lowered = auth_text.lower()
    for forbidden in ("pytesseract", "easyocr", "paddleocr", "captcha_solver"):
        assert forbidden not in lowered
    assert "插件不会自动识别验证码" in auth_text


def test_captcha_info_uses_click_order_and_canvas_size():
    tree = ast.parse(auth_text)
    func = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_captcha_info")
    source = ast.get_source_segment(auth_text, func) or ""
    assert "'-'.join" in source
    assert "f'{x},{y}'" in source
    assert ";{int(width)};{int(height)}" in source


def test_same_session_flows_through_captcha_check_login_and_probe():
    for token in (
        '"session": session',
        'session = row.get("session")',
        "self._gying_verify_captcha(row)",
        "self._gying_finish_manual_login(row",
        "self._gying_authenticated_probe(session, node)",
        'login_mode="manual_captcha"',
        "authenticated=True",
    ):
        assert token in auth_text, token
    assert "requests.Session()" not in auth_text.split("def _gying_verify_captcha", 1)[1].split("def _gying_finish_manual_login", 1)[0]


def test_cookie_is_never_trusted_only_because_it_exists():
    assert "has_cookie and self._gying_authenticated_probe(session, node)" in verified_text
    assert "观影 Cookie 已通过受限搜索验真并复用" in verified_text
    assert 'row["authenticated"] = False' in verified_text
    assert "return self._gying_login_password(session, node)" in verified_text
    assert '"mode": "configured_cookie"' not in verified_text


def test_pow_retries_three_times_and_only_then_logs_verified():
    assert "max_pow = 3 if retry_challenge else 0" in auth_text
    assert "PoW计算提交完成" in auth_text
    assert "等待原请求确认" in auth_text
    assert "浏览器计算验证确认通过" in auth_text
    request_body = auth_text.split("    def _gying_request(\n", 1)[1].split("    # ------------------------------------------------------------------\n    # 登录状态", 1)[0]
    assert request_body.index("if not challenge:") < request_body.index("浏览器计算验证确认通过")


def test_auth_probe_rejects_anonymous_restricted_search_marker():
    assert "/search?q=" in auth_text
    assert "&type=&mode=1" in auth_text
    assert "未登录，访问受限" in auth_text
    assert "_BT.PC.HTML('nologin')" in auth_text
    assert "return False" in auth_text.split("def _gying_authenticated_probe", 1)[1].split("def _gying_login_password", 1)[0]


def test_manual_auth_api_and_moviepilot_click_grid_are_exposed():
    for path in (
        "/viewing/auth/start",
        "/viewing/auth/status",
        "/viewing/auth/click",
        "/viewing/auth/undo",
        "/viewing/auth/refresh",
        "/viewing/auth/cancel",
    ):
        assert path in auth_text
    assert "观影人工认证" in auth_text
    assert "请依次点击" in auth_text
    assert "position:absolute" in auth_text
    assert '"params": {"auth_id": auth_id, "x": x, "y": y}' in auth_text
    assert "每次点击会回传对应位置" in auth_text


def test_public_auth_state_never_returns_cookie_password_or_raw_points():
    public = auth_text.split("    def _gying_auth_public(", 1)[1].split("    # ------------------------------------------------------------------\n    # 节点发现", 1)[0]
    assert '"captcha"' in public
    assert '"image"' in public
    assert '"text"' in public
    assert '"clicked"' in public
    assert '"cookie"' not in public.lower()
    assert '"password"' not in public.lower()
    assert '"points":' not in public.lower()


def test_current_frontend_content_nodes_and_urlop_are_candidates_not_single_hardcoded_entry():
    for value in ("肖申克的救赎.com", "阿甘正传.com", "盗梦空间.com", "星际穿越.com"):
        assert value in auth_text
    assert 'registry.rstrip("/") + "/urlop/"' in auth_text
    assert "_CURRENT_FRONTEND_SEEDS_V1107" in auth_text


def test_fixed_transfer_priority_is_untouched():
    assert "观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K" in entry_text
    assert "Magnet/ED2K 继续使用光鸭原生 cloudcollection" in entry_text
