from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
AUTO = (ROOT / "plugins.v3" / "guangyatransferassistant" / "gying_autologin_v1109.py").read_text(encoding="utf-8")


def test_public_login_contract_keeps_empty_code_and_warmup():
    assert '"code": ""' in AUTO
    assert '"/user/login"' in AUTO
    assert '"/mv/wkMn"' in AUTO
