from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
FILTER = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")
STREAM = (PLUGIN / "organizer_folder_stream.py").read_text(encoding="utf-8")
RECOVERY = (PLUGIN / "organizer_queue_recovery.py").read_text(encoding="utf-8")


def test_fast_refill_is_independent_from_normal_discovery_interval():
    for token in (
        "_monitor_heartbeat = 10",
        "_isolated_refill_low_watermark",
        "_fast_refill_needed",
        "capacity_wait",
        "stability_wait",
        "_organize_monitor_last_tick = now",
        "self.run_organize_monitor_scan(manual=False)",
        "【连续补充】触发下一批扫描",
    ):
        assert token in FILTER, token


def test_fast_refill_only_runs_when_private_queue_is_low():
    assert 'queued > self._isolated_refill_low_watermark' in FILTER
    assert 'return False, "queue_has_buffer"' in FILTER
    assert 'queued == 0 and not str(isolated.get("running_path") or "")' in FILTER


def test_refill_does_not_touch_moviepilot_global_background_queue():
    for forbidden in (
        "TransferDispatcher",
        "TransferChain",
        "get_queue_tasks",
        "remove_from_queue",
        "put_to_queue",
        "_queue",
    ):
        assert forbidden not in FILTER, forbidden
    assert '"background": False' in RECOVERY


def test_folder_stream_still_exposes_capacity_wait_for_refill_controller():
    assert '"capacity_wait": 0' in STREAM
    assert 'counters["capacity_wait"] += 1' in STREAM
    assert 'capacity_wait=totals.get("capacity_wait", 0)' in STREAM
