from __future__ import annotations

from source_helper import single_init_plugin_path
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = single_init_plugin_path(ROOT / "plugins.v3" / "shukguangyadisk")
INIT = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
RECOVERY = (PLUGIN / "organizer_queue_recovery.py").read_text(encoding="utf-8")


def test_queue_recovery_mixin_precedes_organizer_submission_mixin():
    assert "from .organizer_queue_recovery import GuangYaQueueRecoveryMixin" in INIT
    mro = INIT.split("class ShukGuangYaDisk(", 1)[1].split("):", 1)[0]
    assert mro.index("GuangYaQueueRecoveryMixin") < mro.index("GuangYaOrganizerMixin")


def test_v3100_host_global_queue_is_readonly_and_never_blocks_private_worker():
    for token in (
        "TransferChain().get_queue_tasks()",
        "_legacy_global_queue_snapshot",
        "observer_only",
        "destructive_cleanup_disabled",
        "return False, snapshot",
        "不删除、不 stop、不阻塞插件私有 Worker",
    ):
        assert token in RECOVERY, token
    for forbidden in (
        "TransferPendingOper",
        "pending_oper.discard(",
        "global_vars.stop_transfer(",
        "remove_from_queue(",
    ):
        assert forbidden not in RECOVERY, forbidden


def test_private_worker_uses_sync_moviepilot_business_chain_and_continuation_hook():
    for token in (
        "queue.Queue(maxsize=self._isolated_queue_capacity)",
        "threading.Thread(",
        'name="ShukGuangYa-IsolatedTransfer"',
        "TransferChain().do_transfer(**kwargs)",
        '"background": False',
        '"manual": False',
        "_on_isolated_worker_item_finished",
        "continuation(path=path",
    ):
        assert token in RECOVERY, token


def test_private_worker_restart_reopens_inflight_instead_of_mp_replay():
    for token in (
        "_recover_isolated_inflight_once",
        'state["inflight"] = inflight',
        'state["retry"] = retry',
        '"retry_at": 0',
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
