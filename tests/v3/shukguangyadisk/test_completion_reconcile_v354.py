from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
RECONCILE = (PLUGIN / "organizer_completion_reconcile_v354.py").read_text(encoding="utf-8")
CANDIDATE = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")


def test_v354_requeues_legacy_completed_for_moviepilot_revalidation():
    for token in (
        'organize_v354_completion_reconcile',
        'state["completed"] = completed',
        'state["retry"] = retry',
        '"retry_at": 0',
        '旧 completed 缓存必须重新经过 MoviePilot 成功历史确认',
        '真实已整理项会被 MP 历史直接确认，未真实整理项会重新提交',
    ):
        assert token in RECONCILE, token


def test_success_fallback_requires_moviepilot_completion_evidence():
    for token in (
        '_inflight_rows(self, item) if success else []',
        'plugin._preflight_history(member, path)',
        'if decision == "completed"',
        '_force_retry(',
        '禁止写入假 completed',
        'completion_unverified',
    ):
        assert token in RECONCILE, token


def test_real_terminal_members_are_not_reopened_by_fallback_reconcile():
    assert '只抓 fallback 调用前仍在 inflight 的成员' in RECONCILE
    assert 'if not isinstance(state_row, dict):' in RECONCILE
    assert 'if str(state_row.get("fingerprint") or "") != fingerprint:' in RECONCILE


def test_v354_runs_after_existing_single_flight_sticky_and_conflict_layers():
    conflict_pos = CANDIDATE.index('install_conflict_resolution_v353()')
    reconcile_pos = CANDIDATE.index('install_completion_reconcile_v354()')
    assert reconcile_pos > conflict_pos
    assert 'from .organizer_completion_reconcile_v354 import install_completion_reconcile_v354' in CANDIDATE


def test_scan_emits_hidden_state_diagnostics_when_submission_is_zero():
    for token in (
        '【自动整理】【状态诊断】',
        '待处理=%s',
        '等待稳定=%s',
        '状态完成缓存=%s',
        '历史本轮确认=%s',
        '提交=%s',
    ):
        assert token in RECONCILE, token
