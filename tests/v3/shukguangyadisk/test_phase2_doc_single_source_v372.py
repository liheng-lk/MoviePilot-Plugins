from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"


def test_v372_has_one_phase2_architecture_record():
    assert (PLUGIN / "PHASE2_V372.md").exists()
    assert not (PLUGIN / "README_PHASE2_CURRENT.md").exists()
