from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXEC = (ROOT / "plugins.v3/shukguangyadisk/organizer_execution_v360.py").read_text(encoding="utf-8")


def test_v372_pending_truth_and_fairness_stay_installed():
    assert "install_pending_truth_v3612" in EXEC
    assert "install_pending_fairness_v3615" in EXEC
