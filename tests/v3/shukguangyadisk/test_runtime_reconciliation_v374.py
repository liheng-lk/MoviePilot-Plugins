from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
QUEUE = (ROOT / "plugins.v3/shukguangyadisk/organizer_queue_recovery.py").read_text(encoding="utf-8")
PENDING = (ROOT / "plugins.v3/shukguangyadisk/organizer_pending_revisit_v361.py").read_text(encoding="utf-8")


def test_worker_orphan_ownership_has_grace_period_and_self_heal():
    assert "_isolated_orphan_owned_grace = 120.0" in QUEUE
    assert "pending > 0 and qsize == 0 and not self._isolated_running_path" in QUEUE
    assert "now - self._isolated_orphan_owned_since >= self._isolated_orphan_owned_grace" in QUEUE
    assert "self._isolated_pending_keys.clear()" in QUEUE
    assert "【独立worker】【自愈】" in QUEUE


def test_remote_empty_pending_retires_file_level_scheduler_state():
    assert "def _v361_retire_missing_group_state" in PENDING
    assert '("stabilizing", "inflight", "retry", "completed", "blocked", "ignored")' in PENDING
    assert "store.retire_path(path=path)" in PENDING
    empty_pos = PENDING.index("if not self._v360_primary_files(direct_files):")
    retire_pos = PENDING.index("self._v361_retire_missing_group_state(group_path)", empty_pos)
    pending_pos = PENDING.index("self._v361_remove_pending(group_path)", empty_pos)
    known_pos = PENDING.index("self._v361_forget_known_resource(group_path)", empty_pos)
    assert empty_pos < retire_pos < pending_pos < known_pos
