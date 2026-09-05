from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_v372_release_tree_contains_no_stage_workflow():
    assert not (ROOT / ".github/workflows/stage-shuk-v372-release.yml").exists()
    assert not (ROOT / "tools/stage_shuk_v372_release.py").exists()
