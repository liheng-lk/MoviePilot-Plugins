from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
PATCH = (PLUGIN / "organizer_legacy_queue_cleanup_v343.py").read_text(encoding="utf-8")
FILTER = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")


def test_v343_rechecks_legacy_queue_instead_of_one_shot_marker():
    assert "每次初始化都会重新检查" in PATCH
    assert "legacy_before = self._legacy_global_queue_snapshot()" in PATCH
    assert "_cleanup_legacy_global_tasks(self)" in PATCH


def test_waiting_legacy_tasks_are_removed_with_public_moviepilot_api():
    assert 'remove = state == "waiting"' in PATCH
    assert "chain.remove_from_queue(fileitem)" in PATCH
    assert "pending_oper.discard(storage=storage, src_path=path)" in PATCH
    assert "global_vars.stop_transfer(path)" in PATCH


def test_running_task_is_only_removed_after_history_confirms_success():
    assert "_history_confirms_completed" in PATCH
    assert '== "completed"' in PATCH
    assert "stale_completed = _history_confirms_completed" in PATCH
    assert "retained_running.append(path)" in PATCH


def test_cleanup_is_scoped_to_guangya_storage_and_monitor_path():
    assert "storage not in storage_names" in PATCH
    assert "not self._queue_guard_path_matches(path)" in PATCH
    assert "其它存储未处理" in PATCH


def test_v343_patch_is_installed():
    assert "install_legacy_queue_cleanup_v343" in FILTER
    assert "install_legacy_queue_cleanup_v343()" in FILTER
