from __future__ import annotations

import importlib.util
import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "plugins.v3" / "shukguangyadisk" / "organizer_state.py"
SOURCE = MODULE_PATH.read_text(encoding="utf-8")
spec = importlib.util.spec_from_file_location("shukguangyadisk_state_v3614", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)
OrganizerStateStore = module.OrganizerStateStore


class _Backend:
    def __init__(self):
        self.data = {"state": {"schema_version": 3}}
        self.writes = 0

    def read(self, key):
        return self.data.get(key)

    def write(self, key, value):
        self.data[key] = value
        self.writes += 1


def _store():
    backend = _Backend()
    store = OrganizerStateStore(
        read=backend.read,
        write=backend.write,
        key="state",
        lock=threading.RLock(),
    )
    # Canonicalize the deliberately sparse fixture once, then observe steady-state writes only.
    store.mutate(lambda state: None)
    backend.writes = 0
    return store, backend


def test_v3614_mutate_compares_before_after_and_preserves_schema_canonicalization():
    assert "raw = copy.deepcopy(self._read(self._key))" in SOURCE
    assert "before = copy.deepcopy(state)" in SOURCE
    assert "canonical_dirty = raw != before" in SOURCE
    assert "after = self.normalize(state)" in SOURCE
    assert "if canonical_dirty or after != before:" in SOURCE
    assert "self._write(self._key, after)" in SOURCE


def test_v3614_completed_retry_blocked_classification_are_zero_write_when_unchanged():
    store, backend = _store()

    store.mark_completed(path="/TV/completed.mkv", fingerprint="fc")
    backend.writes = 0
    assert store.classify(
        path="/TV/completed.mkv",
        fingerprint="fc",
        now=100,
        stability_seconds=0,
        inflight_lease_seconds=1800,
    ) == "completed"
    assert backend.writes == 0

    store.mark_submitting(path="/TV/retry.mkv", fingerprint="fr", now=100)
    store.mark_failed(path="/TV/retry.mkv", fingerprint="fr", now=101, reason="temporary")
    backend.writes = 0
    assert store.classify(
        path="/TV/retry.mkv",
        fingerprint="fr",
        now=120,
        stability_seconds=0,
        inflight_lease_seconds=1800,
    ) == "retry_wait"
    assert backend.writes == 0

    store.mark_blocked(path="/TV/blocked.mkv", fingerprint="fb", reason="blocked", now=100)
    backend.writes = 0
    assert store.classify(
        path="/TV/blocked.mkv",
        fingerprint="fb",
        now=200,
        stability_seconds=0,
        inflight_lease_seconds=1800,
    ) == "blocked"
    assert backend.writes == 0


def test_v3614_real_transition_remains_atomic_and_persistent():
    store, backend = _store()
    store.mark_submitting(path="/TV/a.mkv", fingerprint="fp", now=100)
    backend.writes = 0
    phase = store.classify(
        path="/TV/a.mkv",
        fingerprint="fp",
        now=2000,
        stability_seconds=0,
        inflight_lease_seconds=1800,
    )
    assert phase == "ready"
    assert backend.writes == 1
    state = store.load()
    assert "/TV/a.mkv" not in state["inflight"]
    assert "/TV/a.mkv" in state["retry"]


def test_v3614_does_not_change_retry_or_business_policy():
    assert "def retry_delay" in SOURCE
    assert "min(60 * (2 ** min(attempts - 1, 6)), 3600)" in SOURCE
    for forbidden in (
        "MediaType.TV",
        "MediaType.MOVIE",
        "target_directory",
        "rename_format",
        "TransferExecutionCommand",
        "planning_input",
        "move_item",
        "delete_file",
    ):
        assert forbidden not in SOURCE, forbidden
