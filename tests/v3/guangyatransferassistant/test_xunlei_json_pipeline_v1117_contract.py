from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PIPELINE = ROOT / "plugins.v3" / "guangyatransferassistant" / "xunlei_json_pipeline_v1117.py"


def test_xunlei_json_pipeline_contract_exists():
    text = PIPELINE.read_text(encoding="utf-8")
    assert "scriptVersion" in text
    assert "sourceTag" in text
    assert "sourceXunlei" in text
    assert "passCodeToken" in text
    assert "shareId" in text
