from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXEC = (ROOT / "plugins.v3/shukguangyadisk/organizer_execution_v360.py").read_text(encoding="utf-8")


def test_v372_durable_retry_and_admission_probe_stay_installed():
    assert "install_durable_retry_v3611" in EXEC
    assert "install_admission_conflict_probe_v3621" in EXEC
