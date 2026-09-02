from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
AUTO = (PLUGIN / "gying_autologin_v1109.py").read_text(encoding="utf-8")
UI = (PLUGIN / "gying_ui_v1109.py").read_text(encoding="utf-8")


def test_auto_login_ui_smoke():
    assert '"code": ""' in AUTO
    assert '"mode": "captcha_required"' in AUTO
    assert '"开始人工认证": "建立观影会话"' in UI
