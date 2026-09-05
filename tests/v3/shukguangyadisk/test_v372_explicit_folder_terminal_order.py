from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXEC = (ROOT / "plugins.v3/shukguangyadisk/organizer_execution_v360.py").read_text(encoding="utf-8")


def test_v372_empty_terminal_marker_precedes_unconfirmed_member_defer():
    start = EXEC.index("if isinstance(item, _FolderBatchEnvelope) and item.directory_mode:", EXEC.index("def _fallback_terminal_state"))
    end = EXEC.index("return super()._fallback_terminal_state", start)
    block = EXEC[start:end]
    assert block.index("_guangya_empty_folder_skip_v3410") < block.index("_defer_unconfirmed_members")
