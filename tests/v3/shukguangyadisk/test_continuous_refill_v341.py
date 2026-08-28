from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
FILTER = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")
STREAM = (PLUGIN / "organizer_folder_stream.py").read_text(encoding="utf-8")
RECOVERY = (PLUGIN / "organizer_queue_recovery.py").read_text(encoding="utf-8")
SINGLE = (PLUGIN / "organizer_single_flight_v350.py").read_text(encoding="utf-8")


def test_fast_refill_is_independent_from_normal_discovery_interval():
    for token in (
        "_monitor_heartbeat = 10",
        "_isolated_refill_low_watermark = 0",
        "_fast_refill_needed",
        "capacity_wait",
        "stability_wait",
        "_organize_monitor_last_tick = now",
        "self.run_organize_monitor_scan(manual=False)",
        "【单任务流水】【连续补充】触发下一资源扫描",
    ):
        assert token in FILTER, token


def test_fast_refill_never_scans_while_single_worker_is_busy():
    assert 'running_path = str(isolated.get("running_path") or "")' in FILTER
    assert 'if running_path or queued > 0:' in FILTER
    assert 'return False, "worker_busy"' in FILTER
    assert "_schedule_refill" in SINGLE
    assert "threading.Timer" in SINGLE


def test_refill_does_not_touch_moviepilot_global_background_queue():
    # 文档字符串允许解释历史 TransferDispatcher 风险；这里只禁止真实依赖/调用。
    for forbidden in (
        "from app.monitor.dispatcher import",
        "from app.chain.transfer import",
        ".handle_file(",
        "TransferChain()",
        "get_queue_tasks(",
        "remove_from_queue(",
        "put_to_queue(",
    ):
        assert forbidden not in FILTER, forbidden
    assert '"background": False' in RECOVERY


def test_folder_stream_capacity_wait_remains_observable_but_no_backlog_is_created():
    assert '"capacity_wait": 0' in STREAM
    assert 'capacity_wait=totals.get("capacity_wait", 0)' in STREAM
    assert "worker 正忙，不预排后续任务" in SINGLE
    assert "_isolated_queue_capacity = 1" in SINGLE
