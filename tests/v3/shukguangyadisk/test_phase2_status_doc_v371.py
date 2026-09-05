from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"


def test_phase2_release_status_keeps_main_ci_as_final_gate():
    text = (PLUGIN / "PHASE2_V371_STATUS.md").read_text(encoding="utf-8")
    assert "33967599149" in text
    assert "33967759283" in text
    assert "标准 PR CI" in text
    assert "main push CI" in text
