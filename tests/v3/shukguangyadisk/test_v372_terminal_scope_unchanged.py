from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXEC = (ROOT / "plugins.v3/shukguangyadisk/organizer_execution_v360.py").read_text(encoding="utf-8")


def test_v372_terminal_event_scope_stays_installed():
    assert "install_terminal_event_scope_v3620" in EXEC
