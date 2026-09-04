from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
DIAG = (PLUGIN / "organizer_blocked_diagnostics_v3617.py").read_text(encoding="utf-8")
EXECUTION = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")


def _between(text: str, start_token: str, end_token: str) -> str:
    start = text.index(start_token)
    end = text.index(end_token, start + len(start_token))
    return text[start:end]


def _version(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def test_v3617_sources_parse():
    ast.parse(DIAG)
    ast.parse(EXECUTION)


def test_v3617_blocked_diagnostics_are_strictly_read_only():
    helper = _between(DIAG, "def blocked_diagnostics", "def log_blocked_diagnostics")
    assert "plugin._state().load()" in helper
    for forbidden in (
        ".mutate(",
        ".clear_blocked(",
        ".mark_blocked(",
        ".mark_failed(",
        ".mark_completed(",
        ".mark_submitting(",
        "save_data(",
        "delete_file(",
        "move_item(",
    ):
        assert forbidden not in helper, forbidden


def test_v3617_exposes_actual_member_reason_and_durable_identity():
    for token in (
        '"path": str(raw_path or "")',
        '"reason": _redact_text(row.get("reason") or "")',
        '"persistent_admission": is_persistent',
        '"history_id": int(row.get("v3611_history_id") or 0)',
        '"transfer_task_id": _short_task_id(row.get("v3611_transfer_task_id") or "")',
        '"settlement_revision": int(row.get("v3611_settlement_revision") or 0)',
        '"recheck_due": bool(not is_persistent and recheck_at <= current)',
    ):
        assert token in DIAG, token


def test_v3617_redacts_common_credentials_before_logging_reason():
    for token in (
        "access[_-]?token",
        "refresh[_-]?token",
        "authorization",
        "Bearer",
        "<redacted>",
    ):
        assert token in DIAG, token
    assert "reason=%s" in DIAG


def test_v3617_logs_only_once_after_real_monitor_init():
    init = _between(EXECUTION, "def init_organizer_monitor", "def _execute_isolated_transfer")
    assert "result = super().init_organizer_monitor()" in init
    assert "if not self._v3617_blocked_diag_logged:" in init
    assert "self._v3617_blocked_diag_logged = True" in init
    assert "log_blocked_diagnostics(self)" in init
    assert init.index("result = super().init_organizer_monitor()") < init.index("log_blocked_diagnostics(self)")


def test_v3617_status_projects_blocked_summary_without_changing_scheduler():
    status = _between(EXECUTION, "def api_organize_monitor_status", "__all__")
    for token in (
        "blocked_diagnostics(self)",
        'status["blocked_diagnostics"] = blocked_diag',
        'status["blocked_persistent"]',
        'status["blocked_due"]',
        'status["blocked_timed"]',
    ):
        assert token in status, token
    runtime = re.search(r'"runtime_hardening": "v([0-9]+\.[0-9]+\.[0-9]+)"', status)
    assert runtime, "runtime_hardening version missing"
    assert _version(runtime.group(1)) >= (3, 6, 17)
    for forbidden in (
        "clear_blocked(",
        "mark_blocked(",
        "request_retry(",
        "do_transfer(",
        "move_item(",
        "delete_file(",
    ):
        assert forbidden not in status, forbidden


def test_v3617_is_diagnostics_only_not_media_policy():
    for forbidden in (
        "MediaType.TV",
        "MediaType.MOVIE",
        "target_directory",
        "rename_format",
        "overwrite_mode",
        "tmdb",
        "season=",
        "episode=",
    ):
        assert forbidden not in DIAG, forbidden
