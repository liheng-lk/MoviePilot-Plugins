from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CANDIDATE = (ROOT / "plugins.v3/shukguangyadisk/organizer_candidate_filter.py").read_text(encoding="utf-8")


def test_v372_candidate_filter_no_longer_installs_loss_or_empty_guards():
    assert "install_loss_guard_v349" not in CANDIDATE
    assert "install_empty_folder_guard_v3410" not in CANDIDATE
