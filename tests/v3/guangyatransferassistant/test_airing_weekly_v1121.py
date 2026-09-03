from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
WEEKLY = (PLUGIN / "airing_weekly_v1121.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
SCHEDULER = (PLUGIN / "airing_scheduler_v1120.py").read_text(encoding="utf-8")
RELEASE = (PLUGIN / "release_v1110.py").read_text(encoding="utf-8")


def test_v1121_parses_and_is_above_v1120_scheduler():
    ast.parse(WEEKLY)
    ast.parse(ENTRY)
    assert "from .airing_weekly_v1121 import GuangYaAiringWeeklyV1121Mixin" in ENTRY
    start = ENTRY.index("class GuangYaTransferAssistant(")
    weekly = ENTRY.index("GuangYaAiringWeeklyV1121Mixin,", start)
    scheduler = ENTRY.index("GuangYaAiringSchedulerV1120Mixin,", start)
    assert weekly < scheduler
    # 预览分支暂不改市场版本，真实 MoviePilot 页面验证后再发布 1.12.1。
    assert 'plugin_version = "1.12.0"' in ENTRY


def test_v1121_date_precision_never_crosses_to_previous_day():
    gate = WEEKLY[WEEKLY.index("def _airing_gate_v1120"):WEEKLY.index("def _poster_v1121")]
    assert 'str(row.get("precision") or "") != "date"' in gate
    assert "air_date > today" in gate
    assert "due.discard(episode)" in gate
    assert "future.add(episode)" in gate
    assert '"date_strict": True' in gate


def test_v1121_infers_weekly_release_day_only_from_stable_history():
    pattern = WEEKLY[WEEKLY.index("def _weekly_pattern_v1121"):WEEKLY.index("def _scheduled_rows_v1121")]
    assert "Counter(day.weekday()" in pattern
    assert "_weekday_sample_limit_v1121 = 16" in WEEKLY
    assert "_weekday_confidence_min_v1121 = 0.60" in WEEKLY
    assert "hits < 2" in pattern
    assert '"weekday_label"' in pattern


def test_v1121_unscheduled_gap_only_runs_on_inferred_weekday():
    gate = WEEKLY[WEEKLY.index("def _airing_gate_v1120"):WEEKLY.index("def _poster_v1121")]
    assert "int(inferred_weekday) == today.weekday()" in gate
    assert "fallback_episode = min(unscheduled)" in gate
    assert "due.add(fallback_episode)" in gate
    assert '"weekday_fallback": bool(fallback_episode)' in gate
    assert "【星期排期】" in gate


def test_v1121_week_view_has_seven_days_status_and_posters():
    snapshot = WEEKLY[WEEKLY.index("def _weekly_calendar_snapshot_v1121"):WEEKLY.index("def _legacy_calendar_card_v1121")]
    assert "for index in range(7)" in snapshot
    for token in ('"scheduled", "待更新"', '"inflight", "转存中"', '"pending", "待补"', '"library", "已入库"'):
        assert token in snapshot
    assert '"poster": poster' in snapshot
    assert '"movie_count": len(movies)' in snapshot
    assert 'self.save_data("airing_week_view_v1121", snapshot)' in snapshot


def test_v1121_page_matches_calendar_card_product_direction():
    page = WEEKLY[WEEKLY.index("def _weekly_page_v1121"):]
    for token in (
        '"追剧日历"',
        '"本周更新"',
        '"今日更新"',
        '"已入库"',
        '"待补"',
        '"电影待匹配"',
        '"VImg"',
        '"VRow"',
    ):
        assert token in page
    assert "《完美世界》只在周四进入日常搜索" in page
    assert "《沧元图》只在周五进入日常搜索" in page


def test_v1121_movies_keep_unscheduled_behavior_and_daily_catchup_survives():
    # v1.12.0 电影本身不经过剧集日历 gate；每日全员补漏仍保留完整 force 路径。
    run = SCHEDULER[SCHEDULER.index("def _run_airing_subscription_v1120"):SCHEDULER.index("def _try_transfer_subscription(")]
    assert "if self._is_movie_subscription(subscribe):" in run
    assert "if force and not due_force:" in run
    assert "def _daily_full_catchup_v1110" in RELEASE
    assert "04:10" in WEEKLY
