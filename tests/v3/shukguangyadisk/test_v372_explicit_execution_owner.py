from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXEC = (ROOT / "plugins.v3/shukguangyadisk/organizer_execution_v360.py").read_text(encoding="utf-8")


def test_v372_execution_owns_folder_terminal_reconciliation():
    assert "_defer_unconfirmed_members(self, item, reason)" in EXEC
    assert "_guangya_empty_folder_skip_v3410" in EXEC
