from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXEC = (ROOT / "plugins.v3/shukguangyadisk/organizer_execution_v360.py").read_text(encoding="utf-8")


def test_v372_ordinary_folder_failure_still_falls_through_existing_terminal_chain():
    assert "return super()._fallback_terminal_state(item, success=success, message=message)" in EXEC
