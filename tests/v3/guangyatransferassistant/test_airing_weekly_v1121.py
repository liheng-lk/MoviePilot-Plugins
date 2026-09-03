from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
GATE = (PLUGIN / "airing_weekly_v1121.py").read_text(encoding="utf-8")
IMPL = (PLUGIN / "airing_weekly_impl_v1121.py").read_text(encoding="utf-8")
WEEKLY = IMPL + "\n" + GATE
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
SCHEDULER = (PLUGIN / "airing_scheduler_v1120.py").read_text(encoding="utf-8")
RELEASE = (PLUGIN / "release_v1110.py").read_text(encoding="utf-8")


def test_v1121_parses_and_is_above_v1120_scheduler():
    ast.parse(GATE)
    ast.parse(IMPL)
    ast.parse(ENTRY)
    assert "from .airing_weekly_v1121 import GuangYaAiringWeeklyV1121Mixin" in ENTRY
    start = ENTRY.index("class GuangYaTransferAssistant(")
    weekly = ENTRY.index("GuangYaAiringWeeklyV1121Mixin,", start)
    scheduler = ENTRY.index("GuangYaAiringSchedulerV1120Mixin,", start)
    assert weekly < scheduler
    assert 'plugin_version = "1.12.1"' in ENTRY
    assert 'build_id = "20260903-r46"' in ENTRY


def test_v1121_date_precision_never_crosses_to_previous_day():
    assert "air_date == today" in GATE
    assert "air_date > today" in GATE
    assert '"off_day_missing"' in GATE
    assert '"weekday_strict": True' in GATE


def test_v1121_past_scheduled_episode_is_not_searched_on_wrong_weekday():
    assert "off_day.add(episode)" in GATE
    assert '"due_missing": sorted(active)' in GATE
    assert '"due_uncovered": sorted(active - reserved - claimed)' in GATE
    assert "window_end = datetime.datetime.combine" in GATE
    assert "window_start <= now < window_end" in GATE


def test_v1121_infers_weekly_release_day_only_from_stable_history():
    pattern = IMPL[IMPL.index("def _weekly_pattern_v1121"):IMPL.index("def _scheduled_rows_v1121")]
    assert "Counter(day.weekday()" in pattern
    assert "_weekday_sample_limit_v1121 = 16" in IMPL
    assert "_weekday_confidence_min_v1121 = 0.60" in IMPL
    assert "hits < 2" in pattern
    assert '"weekday_label"' in pattern


def test_v1121_unscheduled_gap_only_runs_on_inferred_weekday():
    legacy_gate = IMPL[IMPL.index("def _airing_gate_v1120"):IMPL.index("def _poster_v1121")]
    assert "int(inferred_weekday) == today.weekday()" in legacy_gate
    assert "fallback_episode = min(unscheduled)" in legacy_gate
    assert "due.add(fallback_episode)" in legacy_gate
    assert '"weekday_fallback": bool(fallback_episode)' in legacy_gate
    assert "【星期排期】" in legacy_gate
    assert 'bool(result.get("weekday_fallback"))' in GATE
    assert 'int(result.get("weekday")) == today.weekday()' in GATE


def test_v1121_week_view_has_seven_days_status_and_posters():
    snapshot = IMPL[IMPL.index("def _weekly_calendar_snapshot_v1121"):IMPL.index("def _legacy_calendar_card_v1121")]
    assert "for index in range(7)" in snapshot
    for token in ('"scheduled", "待更新"', '"inflight", "转存中"', '"pending", "待补"', '"library", "已入库"'):
        assert token in snapshot
    assert '"poster": poster' in snapshot
    assert '"movie_count": len(movies)' in snapshot
    assert 'self.save_data("airing_week_view_v1121", snapshot)' in snapshot


def test_v1121_episode_status_uses_moviepilot_library_truth_before_air_date():
    snapshot = GATE[GATE.index("def _weekly_calendar_snapshot_v1121"):GATE.index("def _episode_card_v1121")]
    assert "_sync_media_library_progress(subscribe)" in snapshot
    assert '"status_source": "moviepilot_library"' in snapshot
    assert 'row["status"], row["status_label"] = "library", "已入库"' in snapshot
    assert 'row["status"], row["status_label"] = "inflight", "转存中"' in snapshot
    assert 'row["status"], row["status_label"] = "completed", "已完成"' in snapshot
    assert 'row["status"], row["status_label"] = "unknown", "待确认"' in snapshot
    library_pos = snapshot.index('episode in state["existing"]')
    inflight_pos = snapshot.index('episode in state["reserved"] or episode in state["claimed"]')
    date_pos = snapshot.index("day_value and day_value > today")
    assert library_pos < inflight_pos < date_pos


def test_v1121_sync_failure_never_guesses_not_missing_as_library():
    snapshot = GATE[GATE.index("def _weekly_calendar_snapshot_v1121"):GATE.index("def _episode_card_v1121")]
    assert 'elif episode in state["raw_missing"]:' in snapshot
    assert 'else:\n                    row["status"], row["status_label"] = "unknown", "待确认"' in snapshot
    assert "非缺集" in snapshot and "误当已入库" in snapshot


def test_v1121_episode_card_colors_completed_and_unknown_explicitly():
    card = GATE[GATE.index("def _episode_card_v1121"):]
    assert '"completed": "success"' in card
    assert '"unknown": "secondary"' in card
    assert '"scheduled": "info"' in card


def test_v1121_page_matches_calendar_card_product_direction():
    page = IMPL[IMPL.index("def _weekly_page_v1121"):]
    for token in (
        '"追剧日历"',
        '"本周更新"',
        '"今日更新"',
        '"已入库"',
        '"待补"',
        '"电影待匹配"',
        '"VRow"',
    ):
        assert token in page
    assert '"VImg"' in IMPL
    assert "《完美世界》只在周四进入日常搜索" in page
    assert "《沧元图》只在周五进入日常搜索" in page


def test_v1121_movies_keep_unscheduled_behavior_and_daily_catchup_survives():
    run = SCHEDULER[SCHEDULER.index("def _run_airing_subscription_v1120"):SCHEDULER.index("def _try_transfer_subscription(")]
    assert "if self._is_movie_subscription(subscribe):" in run
    assert "if force and not due_force:" in run
    assert "def _daily_full_catchup_v1110" in RELEASE
    assert "04:10" in IMPL
