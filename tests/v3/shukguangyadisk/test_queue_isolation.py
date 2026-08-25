from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
INIT = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
BACKPRESSURE = (PLUGIN / "organizer_backpressure.py").read_text(encoding="utf-8")
DISPATCH = (PLUGIN / "organizer_dispatch.py").read_text(encoding="utf-8")
FOLDER_STREAM = (PLUGIN / "organizer_folder_stream.py").read_text(encoding="utf-8")
RECOGNITION = (PLUGIN / "organizer_recognition.py").read_text(encoding="utf-8")


def test_plugin_composes_queue_guard_before_folder_stream_and_dispatch_boundary():
    assert "from .organizer_backpressure import GuangYaBackpressureMixin" in INIT
    assert "from .organizer_dispatch import GuangYaDispatchMixin" in INIT
    mro = INIT.split("class ShukGuangYaDisk(", 1)[1].split("):", 1)[0]
    assert mro.index("GuangYaBackpressureMixin") < mro.index("GuangYaFolderStreamMixin")
    assert mro.index("GuangYaDispatchMixin") < mro.index("GuangYaOrganizerMixin")


def test_dispatch_boundary_owns_contextual_transferchain_submission():
    assert "class GuangYaDispatchMixin" in DISPATCH
    assert "TransferChain().do_transfer(" in DISPATCH
    assert "_MonitorOrganizerMixin._dispatch_to_moviepilot" in DISPATCH
    assert "返回值仅表示 MoviePilot 是否接受" in DISPATCH
    # 识别层仍保留兼容实现，但真实 MRO 必须由 dispatch mixin 抢先接管。
    assert "def _build_context_meta" in RECOGNITION


def test_backpressure_separates_scan_batch_from_mp_inflight_limit():
    assert "_monitor_default_max_inflight = 1" in BACKPRESSURE
    assert "_monitor_default_stall_timeout = 900" in BACKPRESSURE
    assert "_monitor_inflight_lease = 21600" in BACKPRESSURE
    assert 'config.setdefault("max_inflight"' in BACKPRESSURE
    assert 'config.setdefault("stall_timeout"' in BACKPRESSURE
    assert "_organize_monitor_batch_size" in BACKPRESSURE
    assert "_organize_monitor_max_inflight" in BACKPRESSURE
    assert "min(" in BACKPRESSURE
    assert 'snapshot.get("slots")' in BACKPRESSURE


def test_host_worker_reservation_is_best_effort_and_never_mutates_moviepilot():
    assert "get_runtime_setting(\"TRANSFER_THREADS\")" in BACKPRESSURE
    assert "effective_max = min(configured_max, max(host_threads - 1, 1))" in BACKPRESSURE
    assert "strict_isolation = host_threads >= 2" in BACKPRESSURE
    assert '"dispatch_host_transfer_threads"' in BACKPRESSURE
    assert '"dispatch_strict_isolation"' in BACKPRESSURE
    assert "isolation_limited" in BACKPRESSURE


def test_folder_priority_and_heartbeat_refill_do_not_rescan_whole_tree():
    for token in (
        "_read_pending_groups",
        "_write_pending_groups",
        "priority_group",
        "_load_pending_group_files",
        "_pump_pending_group",
        "【背压补槽】",
    ):
        assert token in BACKPRESSURE, token
    tick = BACKPRESSURE.split("def organize_monitor_tick", 1)[1]
    assert "pending_groups" in tick
    assert "_pump_pending_group" in tick
    assert "return super().organize_monitor_tick()" in tick
    assert "_iter_folder_groups" in FOLDER_STREAM


def test_stall_breaker_stops_new_plugin_submissions_without_touching_mp_workers():
    for token in (
        '"stalled": stalled',
        'slots = 0 if stalled',
        "dispatch_paused=True",
        "已停止新增任务",
        "等待 MoviePilot 消化或恢复",
    ):
        assert token in BACKPRESSURE, token
    forbidden = (
        "close_workers",
        "on_config_changed",
        "_TransferChain__stop",
        "_worker_stop_event",
        "_queue.put",
        "_threads",
    )
    joined = BACKPRESSURE + DISPATCH + FOLDER_STREAM
    for token in forbidden:
        assert token not in joined, token


def test_status_reports_real_plugin_queue_occupancy_not_batch_size():
    for token in (
        '"queue_limit": snapshot["max_inflight"]',
        '"queue_slots": snapshot["slots"]',
        '"dispatch_inflight": snapshot["inflight"]',
        '"dispatch_stalled": snapshot["stalled"]',
        '"dispatch_oldest_age_seconds": snapshot["oldest_age_seconds"]',
    ):
        assert token in BACKPRESSURE, token


def test_pending_groups_are_persisted_as_scheduler_state():
    assert 'status.get("pending_groups")' in BACKPRESSURE
    assert "pending_group_count" in BACKPRESSURE
    assert "pending_group=normalized[0] if normalized else" in BACKPRESSURE
    assert "capacity_wait > 0" in BACKPRESSURE
