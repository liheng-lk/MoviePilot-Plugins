from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"


def test_v371_folder_batch_policy_is_called_from_execution_not_candidate_import_side_effect():
    execution = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")
    candidate = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")
    assert "result = _execute_conflict_aware(self, item)" in execution
    assert "return rescue_partial_preview_if_needed(self, item, result)" in execution
    assert "install_conflict_resolution_v353" not in candidate
    assert "install_preview_partial_v355" not in candidate
