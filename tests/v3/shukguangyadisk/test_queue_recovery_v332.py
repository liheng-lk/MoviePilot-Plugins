from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
INIT = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
RECOVERY = (PLUGIN / "organizer_queue_recovery.py").read_text(encoding="utf-8")


def test_queue_recovery_mixin_precedes_organizer_submission_mixin():
    assert "from .organizer_queue_recovery import GuangYaQueueRecoveryMixin" in INIT
    mro = INIT.split("class ShukGuangYaDisk(", 1)[1].split("):", 1)[0]
    assert mro.index("GuangYaQueueRecoveryMixin") < mro.index("GuangYaOrganizerMixin")


def test_legacy_recovery_only_targets_guangya_monitor_pending_rows():
    for token in (
        "TransferPendingOper",
        ".list_all()",
        "_queue_guard_storage_names",
        "_queue_guard_path_matches",
        "pending_oper.discard",
        "global_vars.stop_transfer",
    ):
        assert token in RECOVERY, token
    assert "from app.db.transferpending_oper import TransferPendingOper" in RECOVERY
    assert "app.application.chain.data" not in RECOVERY
    assert 'str(storage or "") not in storage_names' in RECOVERY
    assert "not self._queue_guard_path_matches(src_path)" in RECOVERY


def test_isolated_worker_never_mutates_moviepilot_private_queue_or_workers():
    forbidden_code = (
        "TransferChain()._queue",
        "TransferChain()._threads",
        "TransferChain()._worker_stop_event",
        "close_workers(",
        "on_config_changed(",
        "_TransferChain__stop",
    )
    for token in forbidden_code:
        assert token not in RECOVERY, token


def test_v340_uses_plugin_private_queue_and_sync_moviepilot_business_chain():
    for token in (
        "queue.Queue(maxsize=self._isolated_queue_capacity)",
        "threading.Thread(",
        'name="ShukGuangYa-IsolatedTransfer"',
        "def _isolated_worker_loop",
        "def _execute_isolated_transfer",
        "TransferChain().do_transfer(**kwargs)",
        '"background": False',
        '"manual": False',
        '"mode": "isolated_sync_worker"',
    ):
        assert token in RECOVERY, token
    assert "TransferDispatcher" not in RECOVERY


def test_v340_no_longer_forces_auto_monitor_disabled():
    assert 'config["enabled"] = False' not in RECOVERY
    assert 'payload["enabled"] = False' not in RECOVERY
    assert "self._organize_monitor_enabled = False" not in RECOVERY
    assert "def api_organize_monitor_save" in RECOVERY
    assert "return super().api_organize_monitor_save" not in RECOVERY
    assert "super().api_organize_monitor_save(dict(payload or {}))" in RECOVERY


def test_old_global_queue_is_live_gate_and_stale_warning_is_cleared():
    for token in (
        "TransferChain().get_queue_tasks()",
        "_legacy_global_queue_snapshot",
        "_legacy_queue_blocks_isolated_start",
        "_queue_guard_message",
        "_refresh_queue_guard_status",
        "无需反复重启 MoviePilot",
        "queue_guard_restart_required=False",
    ):
        assert token in RECOVERY, token
    # 该执行层仍只读取 MP 公共队列；真正的安全清理由 v3.4.3 迁移补丁负责。
    assert "remove_from_queue(" not in RECOVERY


def test_private_worker_restart_reopens_inflight_instead_of_mp_replay():
    for token in (
        "_recover_isolated_inflight_once",
        'state["inflight"] = inflight',
        'state["retry"] = retry',
        '"retry_at": 0',
        "v3.4 私有整理 worker 重启恢复",
        "_monitor_inflight_lease = 7 * 24 * 3600",
    ):
        assert token in RECOVERY, token


def test_terminal_result_prefers_moviepilot_event_with_return_value_fallback():
    for token in (
        "_fallback_terminal_state",
        "still_inflight",
        "state_store.mark_completed",
        "state_store.mark_failed",
    ):
        assert token in RECOVERY, token


def test_stop_service_only_stops_plugin_owned_worker():
    for token in (
        "def _stop_isolated_worker",
        "self._isolated_stop",
        "worker.join",
        "def stop_service",
        "return super().stop_service()",
    ):
        assert token in RECOVERY, token
    assert "TransferChain().close" not in RECOVERY
    assert "TransferChain().close_workers" not in RECOVERY
