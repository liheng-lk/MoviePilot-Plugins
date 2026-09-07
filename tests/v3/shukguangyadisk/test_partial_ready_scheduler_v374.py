from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MONITOR = ROOT / "plugins.v3" / "shukguangyadisk" / "organizer_monitor_v366.py"


def _schedule_body() -> str:
    source = MONITOR.read_text(encoding="utf-8")
    start = source.index("    def _v360_schedule_resource")
    end = source.index("\n        envelope = self._v360_make_envelope", start)
    return source[start:end]


def test_partial_ready_members_are_not_blocked_by_sibling_wait_state():
    body = _schedule_body()
    assert '"reason": "resource_wait" if hard_wait else "no_ready"' in body
    assert "if hard_wait:" not in body
    assert "if not rows:" in body
    assert "selected = rows" in body


def test_partial_ready_directory_batch_stays_disabled_until_all_members_ready():
    body = _schedule_body()
    assert "all_primary_ready = (" in body
    assert "len(selected) == len(primary)" in body
    assert 'int(phases.get("ready") or 0) == len(primary)' in body
    assert "not manual_safe_mode" in body
    assert "and all_primary_ready" in body
    assert "_can_use_native_directory_batch(" in body
