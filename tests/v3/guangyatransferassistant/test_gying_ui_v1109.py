from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
UI = PLUGIN / "gying_ui_v1109.py"
AUTO = PLUGIN / "gying_autologin_v1109.py"

ui_text = UI.read_text(encoding="utf-8")
auto_text = AUTO.read_text(encoding="utf-8")


def test_v1109_ui_layer_parses_and_is_wired_into_auto_login():
    ast.parse(ui_text, filename=str(UI))
    ast.parse(auto_text, filename=str(AUTO))
    assert "from .gying_ui_v1109 import GuangYaGyingUiV1109Mixin" in auto_text
    assert "class GuangYaGyingAutoLoginV1109Mixin(GuangYaGyingUiV1109Mixin):" in auto_text


def test_panel_no_longer_presents_manual_verification_as_default():
    assert '"观影人工认证": "观影登录"' in ui_text
    assert '"开始人工认证": "建立观影会话"' in ui_text
    assert "插件会优先自动完成浏览器计算验证和账号密码登录" in ui_text
    assert "只有站点明确要求点击验证时" in ui_text
    assert "账号密码自动登录" in ui_text


def test_ui_rewrite_does_not_change_api_paths_or_captcha_behavior():
    lowered = ui_text.lower()
    for forbidden in ("/viewing/auth/click", "pytesseract", "easyocr", "paddleocr", "requests."):
        assert forbidden not in lowered
    assert "只改展示文字，不改变 API 或会话协议" in ui_text
