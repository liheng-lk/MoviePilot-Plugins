from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXEC = (ROOT / "plugins.v3/shukguangyadisk/organizer_execution_v360.py").read_text(encoding="utf-8")


def test_v371_unrecognized_present_source_still_parks_without_retry():
    assert "FileDisposition.LEAVE_UNRECOGNIZED" in EXEC
    assert "mark_non_actionable" in EXEC
    assert "未识别保留" in EXEC
