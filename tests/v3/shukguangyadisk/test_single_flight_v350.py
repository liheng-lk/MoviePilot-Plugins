from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
SINGLE = (PLUGIN / "organizer_single_flight_v350.py").read_text(encoding="utf-8")
FILTER = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")


def test_single_flight_never_prefetches_while_worker_busy():
    for token in (
        "_isolated_queue_capacity = 1",
        "running_path",
        'int(snapshot.get("queued") or 0) > 0',
        'int(snapshot.get("owned") or 0) > 0',
        "worker 正忙，不预排后续任务",
    ):
        assert token in SINGLE, token


def test_scan_stops_after_first_resource_claim_and_preserves_unseen_state():
    for token in (
        "_guangya_single_flight_claimed_v350",
        'scan_meta["truncated"] = True',
        'scan_meta["single_flight_partial"] = True',
        "只完成当前资源的发现",
    ):
        assert token in SINGLE, token


def test_loose_movie_container_is_not_submitted_as_one_directory_batch():
    for token in (
        "_is_loose_container",
        "_process_one_loose_resource",
        "resource_mode",
        "loose_single",
        "发现一个→识别一个→整理一个",
        "华语电影",
        '"mp"',
    ):
        assert token in SINGLE, token


def test_episode_folders_remain_one_folder_transaction():
    for token in (
        "_has_episode_structure",
        "_is_season_dir",
        "_episode_token",
        "len(tokens) >= max(2, len(media) - 1)",
    ):
        assert token in SINGLE, token


def test_worker_completion_schedules_next_discovery_without_building_backlog():
    for token in (
        "_schedule_refill",
        "threading.Timer",
        "run_organize_monitor_scan(manual=False)",
        "_fallback_terminal_state = fallback",
    ):
        assert token in SINGLE, token


def test_v350_single_flight_installed_last():
    assert "from .organizer_single_flight_v350 import install_single_flight_v350" in FILTER
    assert "install_single_flight_v350()" in FILTER
    assert FILTER.index("install_rename_diagnostics_v3414()") < FILTER.index("install_single_flight_v350()")
