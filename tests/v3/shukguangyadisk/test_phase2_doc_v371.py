from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"


def test_phase2_architecture_record_matches_runtime_boundary():
    doc = (PLUGIN / "PHASE2_V371.md").read_text(encoding="utf-8")
    execution = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")
    candidate = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")
    for token in (
        "install_conflict_resolution_v353()",
        "install_preview_partial_v355()",
        "install_preview_retry_wakeup_v356()",
    ):
        assert token in doc
        assert token not in candidate
    assert "handle_duplicate_terminal_event(self, event, success)" in execution
    assert "v3.6.20 storage/path outer scope" in doc
