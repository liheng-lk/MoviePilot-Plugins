from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXEC = (ROOT / "plugins.v3/shukguangyadisk/organizer_execution_v360.py").read_text(encoding="utf-8")


def test_v372_state_reachability_and_terminal_index_gc_stay_installed():
    assert "install_organizer_hardening_v369" in EXEC
    assert "install_terminal_index_gc_v3619" in EXEC
