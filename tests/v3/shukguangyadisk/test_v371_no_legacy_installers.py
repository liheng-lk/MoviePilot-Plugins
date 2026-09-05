from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3/shukguangyadisk"


def test_v371_removed_behavior_installers_stay_absent():
    candidate = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")
    for name in (
        "install_conflict_resolution_v353",
        "install_preview_partial_v355",
        "install_preview_retry_wakeup_v356",
    ):
        assert name not in candidate
