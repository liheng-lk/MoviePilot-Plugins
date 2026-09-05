from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXEC = (ROOT / "plugins.v3/shukguangyadisk/organizer_execution_v360.py").read_text(encoding="utf-8")


def test_v372_move_guard_installation_remains_unchanged():
    assert "install_move_confirmation_v360()" in EXEC
    assert "install_move_transaction_guard_v364()" in EXEC
