from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXEC = (ROOT / "plugins.v3/shukguangyadisk/organizer_execution_v360.py").read_text(encoding="utf-8")


def test_v371_terminal_history_chain_runs_before_duplicate_cleanup():
    block = EXEC[EXEC.index("def _record_terminal_transfer"):EXEC.index("def _fallback_terminal_state")]
    assert block.index("super()._record_terminal_transfer(event, success)") < block.index(
        "handle_duplicate_terminal_event(self, event, success)"
    )
