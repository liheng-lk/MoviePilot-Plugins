from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SAFETY = (ROOT / "plugins.v3" / "guangyatransferassistant" / "offline_safety_v180.py").read_text(encoding="utf-8")
TYPES = (ROOT / "plugins.v3" / "guangyatransferassistant" / "source_types_v180.py").read_text(encoding="utf-8")


def test_queued_is_not_resubmitted_after_restart():
    assert 'SOURCE_PENDING_STATES = {"new", "retry"}' in TYPES
    assert '"queued"' in TYPES.split("SOURCE_INFLIGHT_STATES", 1)[1].split("\n", 1)[0]
    block = SAFETY.split("    def _submit_offline_source(", 1)[1].split("    def _poll_offline_source(", 1)[0]
    assert "if task_id:" in block
    assert "return self._poll_offline_source(source)" in block
