from __future__ import annotations

import importlib.util
import threading
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "plugins.v3" / "shukguangyadisk" / "organizer_state.py"
spec = importlib.util.spec_from_file_location("shukguangyadisk_organizer_state", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)
OrganizerStateStore = module.OrganizerStateStore


class MemoryBackend:
    def __init__(self, initial=None):
        self.data = {"state": initial or {}}

    def read(self, key):
        return self.data.get(key)

    def write(self, key, value):
        self.data[key] = value


class OrganizerStateStoreTest(unittest.TestCase):
    def make_store(self, initial=None):
        backend = MemoryBackend(initial)
        store = OrganizerStateStore(
            read=backend.read,
            write=backend.write,
            key="state",
            lock=threading.RLock(),
        )
        return store, backend

    def test_legacy_seen_is_reconfirmed_not_trusted_as_completed(self):
        store, _ = self.make_store({
            "seen": {"/TV/demo.mkv": "fp1"},
            "pending": {"/TV/wait.mkv": {"fingerprint": "fp2", "first_seen": 10}},
        })
        stats = store.migrate_from_v322(monitor_path="/TV")
        self.assertEqual(stats["completed"], 0)
        self.assertEqual(stats["retry_wait"], 1)
        state = store.load()
        self.assertIn("/TV/demo.mkv", state["retry"])
        self.assertIn("/TV/wait.mkv", state["stabilizing"])

    def test_stability_then_inflight_then_complete(self):
        store, _ = self.make_store({"schema_version": 3})
        self.assertEqual(store.classify(path="/TV/a.mkv", fingerprint="fp", now=100, stability_seconds=30, inflight_lease_seconds=1800), "stabilizing")
        self.assertEqual(store.classify(path="/TV/a.mkv", fingerprint="fp", now=131, stability_seconds=30, inflight_lease_seconds=1800), "ready")
        self.assertEqual(store.mark_submitting(path="/TV/a.mkv", fingerprint="fp", now=131), 1)
        self.assertEqual(store.classify(path="/TV/a.mkv", fingerprint="fp", now=150, stability_seconds=30, inflight_lease_seconds=1800), "inflight")
        store.mark_completed(path="/TV/a.mkv", fingerprint="fp")
        self.assertEqual(store.classify(path="/TV/a.mkv", fingerprint="fp", now=151, stability_seconds=30, inflight_lease_seconds=1800), "completed")

    def test_failure_uses_backoff_and_never_becomes_completed(self):
        store, _ = self.make_store({"schema_version": 3})
        store.mark_submitting(path="/TV/a.mkv", fingerprint="fp", now=100)
        retry = store.mark_failed(path="/TV/a.mkv", fingerprint="fp", now=101, reason="network")
        self.assertEqual(retry["delay"], 60)
        self.assertEqual(store.classify(path="/TV/a.mkv", fingerprint="fp", now=120, stability_seconds=0, inflight_lease_seconds=1800), "retry_wait")
        self.assertEqual(store.classify(path="/TV/a.mkv", fingerprint="fp", now=162, stability_seconds=0, inflight_lease_seconds=1800), "ready")
        self.assertEqual(store.stats()["completed"], 0)

    def test_stale_inflight_recovers_after_lease(self):
        store, _ = self.make_store({"schema_version": 3})
        store.mark_submitting(path="/TV/a.mkv", fingerprint="fp", now=100)
        phase = store.classify(path="/TV/a.mkv", fingerprint="fp", now=2000, stability_seconds=0, inflight_lease_seconds=1800)
        self.assertEqual(phase, "ready")
        self.assertEqual(store.stats()["inflight"], 0)
        self.assertEqual(store.stats()["retry_wait"], 1)

    def test_blocked_item_is_revalidated_and_can_be_manually_unblocked(self):
        store, _ = self.make_store({"schema_version": 3})
        store.mark_blocked(path="/TV/a.mkv", fingerprint="fp", reason="retry exhausted", now=100)
        self.assertEqual(store.classify(path="/TV/a.mkv", fingerprint="fp", now=200, stability_seconds=0, inflight_lease_seconds=1800), "blocked")
        self.assertEqual(store.classify(path="/TV/a.mkv", fingerprint="fp", now=701, stability_seconds=0, inflight_lease_seconds=1800), "ready")
        store.mark_blocked(path="/TV/a.mkv", fingerprint="fp", reason="retry exhausted", now=800)
        self.assertEqual(store.clear_blocked(), 1)
        self.assertEqual(store.classify(path="/TV/a.mkv", fingerprint="fp", now=801, stability_seconds=0, inflight_lease_seconds=1800), "ready")

    def test_new_fingerprint_reopens_completed_path(self):
        store, _ = self.make_store({"schema_version": 3})
        store.mark_completed(path="/TV/a.mkv", fingerprint="old")
        phase = store.classify(path="/TV/a.mkv", fingerprint="new", now=100, stability_seconds=0, inflight_lease_seconds=1800)
        self.assertEqual(phase, "ready")
        self.assertNotIn("/TV/a.mkv", store.load()["completed"])

    def test_truncated_inventory_never_prunes_state(self):
        store, _ = self.make_store({"schema_version": 3})
        store.mark_completed(path="/TV/a.mkv", fingerprint="fp")
        store.reconcile_inventory([], truncated=True)
        self.assertEqual(store.stats()["completed"], 1)
        store.reconcile_inventory([], truncated=False)
        self.assertEqual(store.stats()["completed"], 0)


if __name__ == "__main__":
    unittest.main()
