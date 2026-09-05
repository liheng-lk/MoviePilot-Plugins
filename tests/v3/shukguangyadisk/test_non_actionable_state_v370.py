from __future__ import annotations

import importlib.util
import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "plugins.v3" / "shukguangyadisk" / "organizer_state.py"
spec = importlib.util.spec_from_file_location("shuk_v370_state_behavior", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
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
    return store, backend


def _classify(store, *, fingerprint: str, now: float = 100.0):
    return store.classify(
        path="/光鸭媒体库/剧集/无法识别/E01.mkv",
        fingerprint=fingerprint,
        now=now,
        stability_seconds=0,
        inflight_lease_seconds=1800,
    )


def test_unrecognized_member_leaves_only_ignored_and_cannot_remain_retry_or_inflight():
    store, _ = _store()
    path = "/光鸭媒体库/剧集/无法识别/E01.mkv"
    store.mark_submitting(path=path, fingerprint="fp1", now=10)
    store.mark_failed(path=path, fingerprint="fp1", now=11, reason="old failure")
    store.mark_blocked(path=path, fingerprint="fp1", reason="old block", now=12)

    changed = store.mark_non_actionable(path=path, fingerprint="fp1")
    assert changed is True
    state = store.load()
    assert state["ignored"] == {path: "fp1"}
    assert path not in state["stabilizing"]
    assert path not in state["inflight"]
    assert path not in state["retry"]
    assert path not in state["blocked"]
    assert path not in state["completed"]
    assert _classify(store, fingerprint="fp1", now=1000) == "ignored"


def test_same_unrecognized_fingerprint_is_idempotent_and_does_not_rewrite_state():
    store, backend = _store()
    path = "/光鸭媒体库/剧集/无法识别/E01.mkv"
    assert store.mark_non_actionable(path=path, fingerprint="fp1") is True
    backend.writes = 0
    assert store.mark_non_actionable(path=path, fingerprint="fp1") is False
    assert backend.writes == 0
    assert _classify(store, fingerprint="fp1") == "ignored"


def test_changed_file_fingerprint_reopens_previously_unrecognized_source():
    store, _ = _store()
    path = "/光鸭媒体库/剧集/无法识别/E01.mkv"
    store.mark_non_actionable(path=path, fingerprint="fp1")

    phase = _classify(store, fingerprint="fp2", now=100)
    assert phase == "ready"
    state = store.load()
    assert path not in state["ignored"]


def test_retire_path_removes_every_scheduler_tombstone_after_move_or_delete():
    store, _ = _store()
    path = "/光鸭媒体库/剧集/已处理/E01.mkv"
    store.mark_completed(path=path, fingerprint="fp")
    assert store.retire_path(path=path) is True
    state = store.load()
    for table in ("completed", "ignored", "blocked", "stabilizing", "inflight", "retry"):
        assert path not in state[table]
    assert store.retire_path(path=path) is False
