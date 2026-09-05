from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"


def test_refactor_progress_forbids_new_versioned_behavior_patch_modules():
    progress = (PLUGIN / "REFACTOR_PROGRESS.md").read_text(encoding="utf-8")
    rules = (PLUGIN / "ORGANIZER_RULES.md").read_text(encoding="utf-8")
    assert "do not add new versioned behavior patch modules" in progress
    assert "不得再修改" in rules
