from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
GATE = (PLUGIN / "airing_weekly_v1121.py").read_text(encoding="utf-8")
IMPL = (PLUGIN / "airing_weekly_impl_v1121.py").read_text(encoding="utf-8")
CHANNEL = (PLUGIN / "channel_event_v1115.py").read_text(encoding="utf-8")
GOVERNANCE = (PLUGIN / "governance_v1114.py").read_text(encoding="utf-8")
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
    assert 'build_id = "20260903-r48-preview"' in GATE


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
    assert '"poster": poster' in snapshot
    assert '"movie_count": len(movies)' in snapshot
    assert 'self.save_data("airing_week_view_v1121", snapshot)' in snapshot


def test_v1122_final_episode_status_is_exactly_three_states():
    snapshot = GATE[GATE.index("def _weekly_calendar_snapshot_v1121"):GATE.index("def _episode_card_v1121")]
    assert "_sync_media_library_progress(subscribe)" in snapshot
    assert '"status_source": "moviepilot_library_three_state"' in snapshot
    assert 'row["status"], row["status_label"] = "library", "已入库"' in snapshot
    assert 'row["status"], row["status_label"] = "inflight", "转存中"' in snapshot
    assert 'row["status"], row["status_label"] = "pending", "待补"' in snapshot
    for removed in ('"completed", "已完成"', '"unknown", "待确认"', '"scheduled", "待更新"'):
        assert removed not in snapshot
    assert 'episode in state["existing"]' in snapshot
    assert 'episode in state["reserved"]' in snapshot
    assert 'episode in state["claimed"]' in snapshot
    assert 'episode in state["note"] and episode not in state["existing"]' in snapshot


def test_v1122_episode_card_and_day_summary_only_expose_three_states():
    card = GATE[GATE.index("def _episode_card_v1121"):GATE.index("def _weekly_page_v1121")]
    assert '"library": "success"' in card
    assert '"inflight": "warning"' in card
    assert '"pending": "error"' in card
    assert '"completed"' not in card and '"unknown"' not in card and '"scheduled"' not in card
    page = GATE[GATE.index("def _weekly_page_v1121"):GATE.index("def _refresh_channel_cache_v1115")]
    assert '_metric_chip_v1121("转存中"' in page
    assert "已入库" in page and "转存中" in page and "待补" in page


def test_v1122_visible_channel_resources_expire_by_last_seen_not_first_added():
    cache = GATE[GATE.index("def _refresh_channel_cache_v1115"):GATE.index("def _run_reliability_route_batch")]
    assert 'entry["cache_seen_at"] = now' in cache
    assert 'get("cache_seen_at") or (row or {}).get("cache_added_at")' in cache
    assert '"retention_basis": "last_seen"' in cache
    assert "_CHANNEL_CACHE_RETENTION_SECONDS_V1115" in cache
    assert "_CHANNEL_CACHE_MAX_ITEMS_V1115" in cache


def test_v1122_viewing_is_routine_poll_not_add_only_and_cannot_be_starved_by_channel():
    assert "def _viewing_due_subscription_ids_v1115" in CHANNEL
    assert 'trigger="观影定时轮询"' in CHANNEL
    batch = GATE[GATE.index("def _run_reliability_route_batch"):GATE.index("def _spawn_route_prime")]
    assert 'if "频道新增资源" not in text:' in batch
    assert "_viewing_due_subscription_ids_v1115()" in batch
    assert '"viewing_poll"' in batch
    assert "观影不会被频道事件长期饿死" in batch
    assert "int(sid) not in channel_set" in batch


def test_v1122_same_day_miss_retries_after_external_cooldown_until_day_gate_closes():
    due = CHANNEL[CHANNEL.index("def _viewing_due_subscription_ids_v1115"):CHANNEL.index("def _run_v1115_mode_batch")]
    assert "_subscription_missing_episodes(subscribe)" in due
    assert "now - last_at >= cooldown" in due
    assert "_external_search_cooldown_minutes_v1114" in due

    dispatch = SCHEDULER[SCHEDULER.index("def _try_transfer_subscription("):SCHEDULER.index("def _try_transfer_subscription_inner(")]
    assert "_airing_gate_v1120(subscribe)" in dispatch
    assert 'due = list(gate.get("due_uncovered") or [])' in dispatch
    assert "if not due:" in dispatch

    claim = GOVERNANCE[GOVERNANCE.index("def _claim_external_search_round_v1114"):GOVERNANCE.index("def _try_transfer_subscription(")]
    assert '"last_at": now' in claim
    assert "now - last_at >= cooldown" in claim
    assert "self.save_data(\"external_search_guard\", state)" in claim

    # 没搜到资源只进入冷却，不会完成订阅或清除缺集；只要仍在当天门禁内，
    # 下一次 tick 达到冷却后会再次进入观影。跨日后由星期门禁停止普通重试。
    assert "_finish_subscription_if_complete" not in due
    assert "off_day_missing" in GATE


def test_v1122_new_subscription_cache_miss_repairs_channel_once_before_viewing():
    prime = GATE[GATE.index("def _spawn_route_prime"):]
    assert "_cached_matches_for_subscription(subscribe)" in prime
    assert "refresh_channels(force=True)" in prime
    assert 'trigger="新订阅资源匹配"' in prime
    assert "频道缓存未命中" in prime
    assert "继续观影搜索兜底" in prime


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
