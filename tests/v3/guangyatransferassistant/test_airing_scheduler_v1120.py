from __future__ import annotations

import ast
import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
SCHEDULER = (PLUGIN / "airing_scheduler_v1120.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
GYING = (PLUGIN / "gying_hardening_v193.py").read_text(encoding="utf-8")


def test_v1120_scheduler_parses_and_is_first_runtime_authority():
    ast.parse(SCHEDULER)
    assert "from .airing_scheduler_v1120 import GuangYaAiringSchedulerV1120Mixin" in ENTRY
    start = ENTRY.index("class GuangYaTransferAssistant(")
    weekly_pos = ENTRY.index("GuangYaAiringWeeklyV1121Mixin,", start)
    scheduler_pos = ENTRY.index("GuangYaAiringSchedulerV1120Mixin,", start)
    identity_pos = ENTRY.index("GuangYaMediaIdentityGuardV1111Mixin,", start)
    release_pos = ENTRY.index("GuangYaReleaseV1110Mixin,", start)
    assert weekly_pos < scheduler_pos < identity_pos < release_pos
    assert 'plugin_version = "1.12.16"' in ENTRY
    assert 'build_id = "20260906-r63"' in ENTRY


def test_v1120_prefers_dailyassistant_and_keeps_tmdb_fallback():
    assert 'running.get("DailyAssistant")' in SCHEDULER
    assert "get_airing_schedule_snapshot" in SCHEDULER
    assert "def _calendar_local_fallback_v1120" in SCHEDULER
    assert "chain.tmdb_info(" in SCHEDULER
    assert "next_episode_to_air" in SCHEDULER
    assert '"dailyassistant": daily_count' in SCHEDULER
    assert '"fallback": fallback_count' in SCHEDULER


def test_v1120_gate_separates_due_future_and_unknown_schedule():
    gate = SCHEDULER[SCHEDULER.index("def _airing_gate_v1120"):SCHEDULER.index("def _refresh_airing_calendar_v1110")]
    for token in (
        '"raw_missing"',
        '"due_missing"',
        '"due_uncovered"',
        '"future_missing"',
        '"unscheduled_missing"',
        '"reserved"',
        '"claimed"',
        '"next_episode"',
        '"next_air_at"',
    ):
        assert token in gate
    assert "due_uncovered = due - reserved - claimed" in gate
    assert "implied_due" in gate


def test_v1120_date_only_schedule_has_explicit_estimated_hour_and_early_window():
    assert "_calendar_default_hour_v1120 = 20" in SCHEDULER
    assert "_calendar_early_hours_v1120 = 12" in SCHEDULER
    assert "datetime.datetime.combine(" in SCHEDULER
    assert "air_at - early" in SCHEDULER
    assert '"precision": "datetime" if air_at else ("date" if air_date else "unknown")' in SCHEDULER

    now = datetime.datetime(2026, 9, 3, 20, 0)
    early = datetime.timedelta(hours=12)
    e12 = datetime.datetime(2026, 9, 10, 20, 0)
    e11 = datetime.datetime(2026, 9, 3, 20, 0)
    assert now < e12 - early
    assert now >= e11 - early


def test_v1120_normal_background_stops_when_current_airing_progress_is_caught_up():
    method = SCHEDULER[SCHEDULER.index("def _run_airing_subscription_v1120"):SCHEDULER.index("def _try_transfer_subscription(")]
    assert 'if not due:' in method
    assert '"calendar_wait": True' in method
    assert "已追平当前播出进度" in method
    assert "with self._due_scope_v1120(subscribe, due):" in method
    assert "calendar_fallback_legacy" in method


def test_v1120_manual_and_daily_catchup_can_still_run_full_missing_set():
    method = SCHEDULER[SCHEDULER.index("def _run_airing_subscription_v1120"):SCHEDULER.index("def _try_transfer_subscription(")]
    assert "if force and not due_force:" in method
    assert "force=True" in method
    due_check = SCHEDULER[SCHEDULER.index("def _calendar_due_check_v1110"):SCHEDULER.index("def _run_airing_subscription_v1120")]
    assert "self._airing_due_force_v1120 = True" in due_check
    assert "self._try_transfer_subscription(subscribe, force=True" in due_check


def test_v1120_due_scope_does_not_corrupt_completion_or_receipt_facts():
    assert "def _subscription_missing_episodes" in SCHEDULER
    assert "def _without_due_scope_v1120" in SCHEDULER
    for method in (
        "def _sync_media_facts_progress",
        "def _finish_subscription_if_complete",
        "def _commit_episode_receipt_v1124",
    ):
        start = SCHEDULER.index(method)
        block = SCHEDULER[start:start + 700]
        assert "with self._without_due_scope_v1120():" in block


def test_v1124_completion_wrapper_preserves_channel_state_abi():
    method = SCHEDULER[
        SCHEDULER.index("def _finish_subscription_if_complete"):
        SCHEDULER.index("def _commit_episode_receipt_v1124")
    ]
    assert "channel_state: Optional[Dict[str, Any]] = None" in method
    assert "channel_state=channel_state" in method
    assert "with self._without_due_scope_v1120():" in method


def test_v1120_serializes_whole_subscription_source_chain():
    method = SCHEDULER[SCHEDULER.index("def _try_transfer_subscription("):SCHEDULER.index("def _try_transfer_subscription_inner(")]
    assert "_episode_fence_lock_v1124" in method
    assert "with lock:" in method
    assert "_run_airing_subscription_v1120" in method


def test_v1120_handled_old_share_no_longer_blocks_uncovered_due_gap():
    method = SCHEDULER[SCHEDULER.index("def _try_transfer_subscription_inner("):]
    assert 'if not bool(result.get("handled")):' in method
    assert "_viewing_gap_v1113" in method
    assert 'if bool(gap.get("covered")):' in method
    assert "【覆盖修正】" in method
    assert "_dispatch_viewing_external_v1113" in method


def test_v1120_gying_keyword_fallback_reuses_per_keyword_cache():
    hardening = GYING[GYING.index("def _gying_raw_results"):GYING.index("@staticmethod\n    def _provider_candidate_matches")]
    assert "force=force or index > 0" not in hardening
    assert "super()._gying_raw_results(variant, force=force)" in hardening
