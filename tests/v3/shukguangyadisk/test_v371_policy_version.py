from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXEC = (ROOT / "plugins.v3/shukguangyadisk/organizer_execution_v360.py").read_text(encoding="utf-8")


def test_v371_policy_version_is_explicit():
    assert '"organizer_policy_version": "v3.7.1"' in EXEC
