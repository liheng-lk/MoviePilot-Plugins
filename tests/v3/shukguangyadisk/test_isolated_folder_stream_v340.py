from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
INIT = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
STREAM = (PLUGIN / "organizer_folder_stream.py").read_text(encoding="utf-8")
HISTORY = (PLUGIN / "organizer_folder_history.py").read_text(encoding="utf-8")
RECOVERY = (PLUGIN / "organizer_queue_recovery.py").read_text(encoding="utf-8")
GUARD = (PLUGIN / "organizer_worker_guard.py").read_text(encoding="utf-8")
FILTER = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")


def test_v340_mro_routes_scan_to_private_worker_before_organizer_dispatch():
    for import_line in (
        "from .organizer_folder_history import GuangYaFolderHistoryMixin",
        "from .organizer_worker_guard import GuangYaWorkerGuardMixin",
        "from .organizer_queue_recovery import GuangYaQueueRecoveryMixin",
        "from .organizer_candidate_filter import GuangYaCandidateFilterMixin",
        "from .organizer_folder_stream import GuangYaFolderStreamMixin",
    ):
        assert import_line in INIT, import_line

    mro = INIT.split("class ShukGuangYaDisk(", 1)[1].split("):", 1)[0]
    expected = (
        "GuangYaFolderHistoryMixin",
        "GuangYaWorkerGuardMixin",
        "GuangYaQueueRecoveryMixin",
        "GuangYaCandidateFilterMixin",
        "GuangYaFolderStreamMixin",
        "GuangYaOrganizerMixin",
    )
    positions = [mro.index(name) for name in expected]
    assert positions == sorted(positions)


def test_folder_stream_never_calls_moviepilot_dispatcher_handle_file():
    assert "self._dispatch_to_moviepilot(item)" in STREAM
    assert ".handle_file(" not in STREAM
    assert "TransferChain().do_transfer" not in STREAM
    # Actual transfer submission is owned by the isolated recovery layer.
    assert "TransferChain().do_transfer(**kwargs)" in RECOVERY
    assert '"background": False' in RECOVERY


def test_active_candidate_filter_has_no_dispatcher_or_queue_state():
    assert "TransferDispatcher" not in FILTER
    assert "TransferChain" not in FILTER
    assert "get_runtime_setting" in FILTER
    for key in ("RMT_MEDIAEXT", "RMT_SUBEXT", "RMT_AUDIOEXT", "DOWNLOAD_TMPEXT"):
        assert key in FILTER, key
    assert "def retry_pending" in FILTER
    assert "return None" in FILTER


def test_folder_stream_keeps_subdirectory_progress_and_safe_inventory_reconcile():
    for token in (
        "_iter_folder_groups",
        "group_complete",
        "groups_discovered",
        "groups_scanned",
        "inventory_paths",
        "reconcile_inventory",
        "truncated",
        "_organize_active_group_path",
        "_organize_active_batch_id",
    ):
        assert token in STREAM, token
    assert "state.mark_submitting" in STREAM
    assert "state.mark_completed" in STREAM
    assert "state.mark_failed" in STREAM


def test_folder_history_is_grouped_without_business_rule_duplication():
    for token in (
        "_folder_history_groups",
        '"folder_history"',
        '"completed": "completed"',
        '"queued": "inflight"',
        '"failed": "retry"',
        '"blocked": "blocked"',
    ):
        assert token in HISTORY, token
    for forbidden in (
        "DirectoryHelper",
        "TransferChain",
        "MediaChain",
        "target_directory",
        "transfer_type",
    ):
        assert forbidden not in HISTORY, forbidden


def test_hot_reload_guard_prevents_two_private_workers():
    for token in (
        "_OWNER_ATTR",
        "weakref.ref(self)",
        "_claim_isolated_runtime",
        "_release_isolated_runtime",
        "旧插件实例仍在收尾",
        "暂不启动新 worker",
        "旧实例仍在执行，当前文件延后",
    ):
        assert token in GUARD, token
    assert "MoviePilot 的整理队列和 worker" in GUARD


def test_worker_shutdown_does_not_drop_runtime_during_active_sync_transfer():
    for token in (
        "_isolated_deferred_shutdown",
        "_finish_deferred_shutdown_from_worker",
        "停止等待超时",
        "保留 owner",
        "插件停止已进入延迟收尾",
        "当前文件完成后自动释放旧实例",
    ):
        assert token in GUARD, token
    # Persistent recovery uses a per-instance boolean, never a persisted Python object id.
    recovery_block = GUARD.split("def _recover_isolated_inflight_once", 1)[1]
    assert "id(self)" not in recovery_block
    assert "process_token" not in recovery_block


def test_v340_has_no_shared_queue_backpressure_module_in_active_mro():
    assert "GuangYaBackpressureMixin" not in INIT
    assert "organizer_backpressure" not in INIT
    assert "max_inflight" not in INIT
    assert "TRANSFER_THREADS" not in INIT
