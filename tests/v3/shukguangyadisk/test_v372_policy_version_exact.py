from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXEC = (ROOT / "plugins.v3/shukguangyadisk/organizer_execution_v360.py").read_text(encoding="utf-8")


def test_v372_policy_status_is_exact():
    assert '"organizer_policy_version": "v3.7.2"' in EXEC
