from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_v372_release_branch_has_architecture_record():
    assert (ROOT / "plugins.v3/shukguangyadisk/PHASE2_V372.md").exists()
