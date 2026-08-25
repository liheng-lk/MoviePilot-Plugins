from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
INIT = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
RECOVERY = (PLUGIN / "organizer_queue_recovery.py").read_text(encoding="utf-8")
BACKPRESSURE = (PLUGIN / "organizer_backpressure.py").read_text(encoding="utf-8")


def test_queue_recovery_wraps_backpressure_before_folder_scheduler():
    assert "from .organizer_queue_recovery import GuangYaQueueRecoveryMixin" in INIT
    mro = INIT.split("class ShukGuangYaDisk(", 1)[1].split("):", 1)[0]
    assert mro.index("GuangYaQueueRecoveryMixin") < mro.index("GuangYaBackpressureMixin")
    assert mro.index("GuangYaBackpressureMixin") < mro.index("GuangYaFolderStreamMixin")


def test_recovery_reads_moviepilot_native_queue_and_reuses_official_cancel_semantics():
    for token in (
        "TransferChain().get_queue_tasks()",
        "chain.remove_from_queue(fileitem)",
        "global_vars.stop_transfer(path)",
        '"waiting"',
        '"running"',
        "monitor_only",
        "include_running",
    ):
        assert token in RECOVERY, token
    assert "confirm=true" in RECOVERY
    assert '"/organize/monitor/recover-queue"' in RECOVERY
    assert '"methods": ["POST"]' in RECOVERY


def test_recovery_never_mutates_moviepilot_private_worker_or_queue_internals():
    forbidden = (
        "._queue",
        "self._threads",
        "_worker_stop_event",
        "close_workers(",
        "on_config_changed(",
        "_TransferChain__stop",
    )
    joined = RECOVERY + BACKPRESSURE
    for token in forbidden:
        assert token not in joined, token


def test_native_queue_occupancy_is_part_of_real_backpressure():
    for token in (
        "native_guangya_active",
        "native_guangya_waiting",
        "native_guangya_running",
        "native_backlog",
        "occupied = max(plugin_inflight, native_active)",
        "snapshot[\"slots\"] = max(limit - occupied, 0)",
    ):
        assert token in RECOVERY, token


def test_recovery_defaults_to_current_monitor_waiting_tasks_and_pauses_refill():
    assert 'monitor_only = bool(payload.get("monitor_only", True))' in RECOVERY
    assert 'include_running = bool(payload.get("include_running", False))' in RECOVERY
    assert '_queue_recovery_pause_seconds = 120' in RECOVERY
    assert "self._queue_recovery_pause_until = time.time() + self._queue_recovery_pause_seconds" in RECOVERY
    assert "正在释放旧光鸭整理队列" in RECOVERY
    assert "writer([])" in RECOVERY
