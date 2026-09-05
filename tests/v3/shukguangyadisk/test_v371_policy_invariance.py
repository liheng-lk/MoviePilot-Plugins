from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"


def test_v371_phase2_keeps_one_canonical_disposition_module():
    execution = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")
    policy = (PLUGIN / "organizer_policy.py").read_text(encoding="utf-8")
    assert "from .organizer_policy import" in execution
    assert "class FileDisposition" in policy
    assert "decide_existing_target" in policy
    assert "decide_failed_execution" in policy
