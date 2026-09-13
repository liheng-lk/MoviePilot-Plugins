from __future__ import annotations

from source_helper import single_init_plugin_path

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = single_init_plugin_path(ROOT / "plugins.v3" / "shukguangyadisk")
GUARD = (PLUGIN / "organizer_worker_guard.py").read_text(encoding="utf-8")
ACCOUNT_PAGE = (PLUGIN / "dist" / "assets" / "__federation_expose_AssistantPage-dev.js").read_text(encoding="utf-8")


def test_new_instance_can_force_old_queue_to_stop_after_current_task():
    for token in (
        "_request_old_owner_handoff",
        "_drain_owner_waiting_queue",
        "stop.set()",
        "q.get_nowait()",
        "q.put_nowait(None)",
        "仅保留当前任务收尾",
    ):
        assert token in GUARD, token


def test_waiting_folder_members_return_to_immediate_retry_not_exponential_backoff():
    for token in (
        "_return_items_to_retry_now",
        '"retry_at": 0',
        'state["inflight"] = inflight',
        'state["retry"] = retry',
        "旧 worker 未开始任务已退回待处理",
    ):
        assert token in GUARD, token


def test_owner_conflict_warning_is_rate_limited():
    assert "_WARN_INTERVAL = 30.0" in GUARD
    assert "_WARN_AT_ATTR" in GUARD
    assert "now - last < _WARN_INTERVAL" in GUARD


def test_account_page_contains_no_hardcoded_internal_version_badge():
    assert "gy-version" not in ACCOUNT_PAGE
    assert "v2.2.15" not in ACCOUNT_PAGE
    assert "光鸭云盘助手" in ACCOUNT_PAGE


def test_live_foreign_owner_blocks_inflight_recovery_until_takeover():
    recovery = GUARD.split("def _recover_isolated_inflight_once", 1)[1].split("def _ensure_isolated_worker", 1)[0]
    for token in (
        "_runtime_owner()",
        "owner is not self",
        "owner_worker.is_alive()",
        "foreign_owner_alive",
        "return 0",
    ):
        assert token in recovery, token
    assert recovery.index("if foreign_owner_alive:") < recovery.index("self._isolated_recovery_done = True")


def test_stale_old_owner_is_reclaimed_only_without_live_inflight():
    for token in (
        "_owner_running_state_evidence",
        "_reclaim_stale_old_owner",
        'state.get("inflight")',
        "if inflight:",
        "return False",
        "source_terminal",
        "global_vars.stop_transfer",
        "已撤销陈旧旧实例 owner",
        "weakref.ref(self)",
    ):
        assert token in GUARD, token


def test_deferred_recovery_runs_after_owner_claim_before_new_worker_start():
    ensure = GUARD.split("def _ensure_isolated_worker", 1)[1].split("def _dispatch_to_moviepilot", 1)[0]
    assert ensure.index("_claim_isolated_runtime()") < ensure.index("_recover_isolated_inflight_once()")
    assert ensure.index("_recover_isolated_inflight_once()") < ensure.index("super()._ensure_isolated_worker()")
