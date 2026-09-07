from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
QUEUE = (ROOT / "plugins.v3/shukguangyadisk/organizer_queue_recovery.py").read_text(encoding="utf-8")
PENDING = (ROOT / "plugins.v3/shukguangyadisk/organizer_pending_revisit_v361.py").read_text(encoding="utf-8")
EXECUTION = (ROOT / "plugins.v3/shukguangyadisk/organizer_execution_v360.py").read_text(encoding="utf-8")


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


def test_sync_success_evidence_pending_rechecks_source_without_faking_completion():
    assert "_EVIDENCE_RECHECK_SECONDS = 30.0" in EXECUTION
    assert "def _v360_prepare_member(self, member: Any):" in EXECUTION
    assert 'if phase != "inflight":' in EXECUTION
    assert 'if not evidence.get("v360_sync_success"):' in EXECUTION
    assert "now - pending_since < _EVIDENCE_RECHECK_SECONDS" in EXECUTION
    assert "presence = probe_source_presence_v3618(self, member)" in EXECUTION
    assert "if presence == SourcePresence.MISSING:" in EXECUTION
    assert "retire_missing_source_v3618(self, member)" in EXECUTION
    assert 'return "retired", None' in EXECUTION
    assert "store.mark_completed" not in EXECUTION[
        EXECUTION.index("def _v360_prepare_member(self, member: Any):"):
        EXECUTION.index("def _execute_isolated_transfer", EXECUTION.index("def _v360_prepare_member(self, member: Any):"))
    ]


def test_evidence_unknown_or_present_stays_inflight_and_is_observable():
    start = EXECUTION.index("def _v360_prepare_member(self, member: Any):")
    end = EXECUTION.index("def _execute_isolated_transfer", start)
    body = EXECUTION[start:end]
    assert 'row["v360_evidence_last_recheck_at"] = now' in body
    assert 'row["v360_evidence_source_presence"]' in body
    assert 'row["v360_evidence_recheck_count"]' in body
    assert "return phase, ready_row" in body
