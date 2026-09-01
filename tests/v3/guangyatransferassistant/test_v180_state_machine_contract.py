import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TYPES = ROOT / "plugins.v3" / "guangyatransferassistant" / "source_types_v180.py"


def test_source_state_sets_are_disjoint_and_cover_recovery_states():
    ns = runpy.run_path(str(TYPES))
    pending = ns["SOURCE_PENDING_STATES"]
    inflight = ns["SOURCE_INFLIGHT_STATES"]
    terminal = ns["SOURCE_TERMINAL_STATES"]
    assert pending.isdisjoint(inflight)
    assert pending.isdisjoint(terminal)
    assert inflight.isdisjoint(terminal)
    assert {"new", "retry"} <= pending
    assert {"dispatching", "submitted", "queued", "waiting"} <= inflight
    assert {"completed", "failed"} <= terminal
