from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RULES = (ROOT / "plugins.v3/shukguangyadisk/ORGANIZER_RULES.md").read_text(encoding="utf-8")


def test_v372_refactor_still_forbids_new_behavior_patch_modules():
    assert "不得继续新增同类行为补丁" in RULES
