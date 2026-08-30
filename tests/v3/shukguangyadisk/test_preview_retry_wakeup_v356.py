from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
PATCH = (PLUGIN / "organizer_preview_retry_wakeup_v356.py").read_text(encoding="utf-8")
CANDIDATE = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")
STATE = (PLUGIN / "organizer_state.py").read_text(encoding="utf-8")


def test_v356_only_wakes_legacy_missing_preview_retry():
    for token in (
        '_MISSING_PREVIEW_TOKEN = "源文件未进入 MoviePilot 预览"',
        'reason = str(raw.get("last_error") or "")',
        'if _MISSING_PREVIEW_TOKEN not in reason:',
        'row["retry_at"] = 0',
        'retry[path] = row',
    ):
        assert token in PATCH, token


def test_v356_preserves_retry_evidence_and_other_failures():
    assert '不修改 attempts/fingerprint' in PATCH
    assert '网络失败、真实整理失败、历史门控失败等其它 retry 完全不动' in PATCH
    assert 'row = dict(raw)' in PATCH
    assert 'row["v356_wakeup_at"] = now' in PATCH


def test_retry_at_zero_becomes_ready_in_existing_state_machine():
    assert 'if float(retry.get("retry_at") or 0) > now:' in STATE
    assert 'return "retry_wait"' in STATE
    assert 'return "ready"' in STATE


def test_v356_runs_once_before_each_scan_then_persists_marker():
    for token in (
        '_MARKER_KEY = "organize_v356_preview_retry_wakeup"',
        'if isinstance(marker, dict) and marker.get("applied"):',
        'plugin.save_data(_MARKER_KEY, marker)',
        '_wake_legacy_preview_retries(self)',
        'return previous_scan(self, manual=manual)',
    ):
        assert token in PATCH, token


def test_v356_installs_after_v355_rescue_layer():
    rescue_pos = CANDIDATE.index('install_preview_partial_v355()')
    wake_pos = CANDIDATE.index('install_preview_retry_wakeup_v356()')
    assert wake_pos > rescue_pos
    assert 'from .organizer_preview_retry_wakeup_v356 import install_preview_retry_wakeup_v356' in CANDIDATE


def test_v356_has_expected_runtime_log_for_real_upgrade_state():
    for token in (
        '【v3.5.6】【升级自愈】',
        '旧版目录预览缺员 retry=%s',
        '已取消旧指数退避',
        '其它 retry 保持原样',
    ):
        assert token in PATCH, token
