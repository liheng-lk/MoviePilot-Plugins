from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXEC = (ROOT / "plugins.v3/shukguangyadisk/organizer_execution_v360.py").read_text(encoding="utf-8")


def test_v372_empty_folder_skip_returns_before_defer():
    start = EXEC.index("def _fallback_terminal_state")
    block = EXEC[start:]
    assert block.index("_guangya_empty_folder_skip_v3410") < block.index("_defer_unconfirmed_members(self, item, reason)")
