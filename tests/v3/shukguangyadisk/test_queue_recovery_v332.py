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
    assert 'plugin_version = "3.3.2"' in INIT


def test_recovery_only_targets_guangya_monitor_pending_rows():
    for token in (
        "get_chain_transfer_pending_port",
        ".list_all()",
        "_queue_guard_storage_names",
        "_is_monitored_path",
        "pending_oper.discard",
        "global_vars.stop_transfer",
    ):
        assert token in RECOVERY, token
    assert 'str(storage or "") not in storage_names' in RECOVERY
    assert "not self._queue_guard_path_matches(src_path)" in RECOVERY


def test_recovery_never_mutates_moviepilot_private_queue_or_workers():
    forbidden = (
        "._queue",
        "close_workers(",
        "on_config_changed(",
        "_worker_stop_event",
        "_TransferChain__stop",
        "self._threads",
    )
    for token in forbidden:
        assert token not in RECOVERY, token


def test_recovery_pauses_unsafe_auto_monitor_but_keeps_plugin_storage_enabled():
    assert 'config["enabled"] = False' in RECOVERY
    assert "self._organize_monitor_enabled = False" in RECOVERY
    assert "payload[\"enabled\"] = False" in RECOVERY
    assert "def run_organize_monitor_scan" in RECOVERY
    assert "def organize_monitor_tick" in RECOVERY
    # The guard must not disable the plugin/storage itself.
    assert "self._enabled = False" not in RECOVERY
    assert "self._guangya_api = None" not in RECOVERY


def test_recovery_preserves_quarantined_work_for_future_safe_scheduler():
    for token in (
        "_move_quarantined_inflight_to_retry",
        'state["inflight"]',
        'state["retry"]',
        '"retry_at": 0',
        '"restart_required"',
        '"queue_guard_active"',
    ):
        assert token in RECOVERY, token
    # All quarantined paths are used for state migration, not only a preview slice.
    assert '"paths": quarantined,' in RECOVERY
