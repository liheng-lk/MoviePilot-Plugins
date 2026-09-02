from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
PATCH = PLUGIN / "channel_event_v1115.py"
UI = PLUGIN / "gying_ui_v1109.py"

patch = PATCH.read_text(encoding="utf-8")
ui = UI.read_text(encoding="utf-8")


def _method(name: str, next_name: str) -> str:
    return patch.split(f"    def {name}(", 1)[1].split(f"    def {next_name}(", 1)[0]


def test_v1115_layer_parses_and_is_wired_above_xunlei_final():
    ast.parse(patch, filename=str(PATCH))
    ast.parse(ui, filename=str(UI))
    assert "class GuangYaChannelEventV1115Mixin(GuangYaXunleiFinalV1114Mixin):" in patch
    assert "from .channel_event_v1115 import GuangYaChannelEventV1115Mixin" in ui
    assert "class GuangYaGyingUiV1109Mixin(GuangYaChannelEventV1115Mixin):" in ui
    assert 'build_id = "20260902-r26"' in patch


def test_channel_cache_is_seven_days_and_weekly_pruned():
    assert "_CHANNEL_CACHE_RETENTION_SECONDS_V1115 = 7 * 24 * 60 * 60" in patch
    assert "_CHANNEL_CACHE_CLEANUP_SECONDS_V1115 = 7 * 24 * 60 * 60" in patch
    cache = _method("_refresh_channel_cache_v1115", "_channel_cache_rows_v1115")
    assert "cache_added_at" in cache
    assert "cache_seen_at" in cache
    assert "cutoff = now - _CHANNEL_CACHE_RETENTION_SECONDS_V1115" in cache
    assert '"retention_days": 7' in cache


def test_tick_only_routes_new_channel_matches_not_every_selected_subscription():
    tick = _method("_tick", "_startup_check")
    assert "self.refresh_channels(force=False)" in tick
    assert "_subscriptions_for_new_channel_entries_v1115" in tick
    assert 'trigger="频道新增资源"' in tick
    assert "_process_selected_subscriptions" not in tick
    assert "if channel_ids:" in tick
    assert "return" in tick


def test_new_channel_match_checks_title_and_missing_episode_hint_before_execution():
    match = _method("_subscriptions_for_new_channel_entries_v1115", "_claim_external_search_round_v1114")
    assert "_entry_match_reason(entry, subscribe)" in match
    assert "_entry_can_cover_missing_v1115(entry, subscribe)" in match
    cover = _method("_entry_can_cover_missing_v1115", "_subscriptions_for_new_channel_entries_v1115")
    assert "_subscription_missing_episodes(subscribe)" in cover
    assert "resolve_episode(hint" in cover
    assert "explicit.intersection(missing)" in cover


def test_channel_event_does_not_consume_viewing_search_cooldown():
    claim = _method("_claim_external_search_round_v1114", "_viewing_due_subscription_ids_v1115")
    assert '== "channel_event"' in claim
    assert "_external_round_allowed_v1114[sid] = False" in claim
    assert "return False" in claim
    assert "super()._claim_external_search_round_v1114" in claim


def test_viewing_poll_is_independent_and_only_schedules_due_missing_subscriptions():
    due = _method("_viewing_due_subscription_ids_v1115", "_run_v1115_mode_batch")
    assert "_external_search_state_v1114()" in due
    assert "_external_search_cooldown_minutes_v1114" in due
    assert "_subscription_missing_episodes(subscribe)" in due
    assert "now - last_at >= cooldown" in due
    tick = _method("_tick", "_startup_check")
    assert 'trigger="观影定时轮询"' in tick


def test_new_subscription_uses_cache_then_viewing_without_forcing_channel_refresh():
    prime = patch.split("    def _spawn_route_prime(", 1)[1].split("\n\n\n__all__", 1)[0]
    assert 'trigger="新订阅资源匹配"' in prime
    assert "refresh_channels(force=True)" not in prime
    mode = _method("_run_reliability_route_batch", "_tick")
    assert '"新订阅资源匹配"' in mode
    assert '"subscription_prime", force=True' in mode


def test_cached_resources_are_hydrated_only_for_matching_subscription():
    hydrate = _method("_hydrate_channel_index_for_subscription_v1115", "_cached_matches_for_subscription")
    assert "_entry_match_reason(row, subscribe)" in hydrate
    assert 'restored["cached_index"] = True' in hydrate
    assert "self.save_data(\"channel_index\", index)" in hydrate
