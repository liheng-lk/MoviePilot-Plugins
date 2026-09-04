from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
BRIDGE = (PLUGIN / "organizer_durable_retry_v3611.py").read_text(encoding="utf-8")
HISTORY = (PLUGIN / "organizer_history.py").read_text(encoding="utf-8")
EXECUTION = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")


def _between(text: str, start_token: str, end_token: str) -> str:
    start = text.index(start_token)
    end = text.index(end_token, start + len(start_token))
    return text[start:end]


def test_v3611_modules_are_valid_python():
    ast.parse(BRIDGE)
    ast.parse(HISTORY)
    ast.parse(EXECUTION)


def test_history_preflight_exposes_durable_identity_without_changing_gate():
    assert "def _history_identity" in HISTORY
    for token in (
        '"history_id"',
        '"history_status"',
        '"transfer_task_id"',
        '"transfer_settlement_revision"',
        "evaluate_history_gate(",
        "describe_history_gate(",
    ):
        assert token in HISTORY
    # 插件仍只消费宿主 gate，不自行实现失败次数或媒体规则。
    assert "record_transfer_failure" not in HISTORY
    assert "max_failed_retries" not in HISTORY


def test_failed_durable_history_requests_existing_moviepilot_task_not_new_planning():
    block = _between(BRIDGE, "def _request_durable_retry", "def install_durable_retry_v3611")
    assert "TransferExecutionCommand(repository).request_retry(" in block
    assert 'requested_by="shukguangyadisk_auto"' in block
    assert 'task_id=task_id' in block
    # durable bridge 本身绝不能重新调用整理链形成第二份 planning_input。
    assert "do_transfer(" not in block
    assert "planning_input" not in block
    assert "admit(" not in block


def test_plugin_claims_inflight_before_external_durable_retry_to_close_fast_callback_race():
    block = _between(BRIDGE, "def _request_durable_retry", "def install_durable_retry_v3611")
    mark_pos = block.index("_mark_durable_inflight(")
    request_pos = block.index("TransferExecutionCommand(repository).request_retry(")
    assert mark_pos < request_pos
    assert '"v3611_durable_retry": True' in BRIDGE


def test_durable_request_is_idempotent_for_moviepilot_active_states_and_never_resubmits():
    assert '_ACTIVE_DURABLE_STATES = {"running", "settling", "retry_wait"}' in BRIDGE
    block = _between(BRIDGE, "def _request_durable_retry", "def install_durable_retry_v3611")
    assert "if accepted or state in _ACTIVE_DURABLE_STATES:" in block
    assert 'return "inflight", None' in block
    assert "已在等待重试" not in BRIDGE  # 不匹配文案，按 typed state/accepted 判定。


def test_durable_retry_port_failure_returns_plugin_retry_instead_of_fresh_planning():
    block = _between(BRIDGE, "def _request_durable_retry", "def install_durable_retry_v3611")
    assert "plugin._state().mark_failed(" in block
    assert 'return "retry_wait", None' in block
    assert "不重新准入" in block


def test_version_changed_durable_failure_is_blocked_until_old_plan_is_explicitly_released():
    prepare = _between(BRIDGE, "def prepare_member", "def fallback_terminal")
    assert "_PASS_FAILED_VERSION_CHANGED" in prepare
    assert "transfer_task_id" in prepare
    assert "请先在 MoviePilot 放弃/删除该失败任务后重新规划" in prepare
    assert '_persist_admission_block(' in prepare
    assert 'return "blocked", None' in prepare


def test_legacy_failed_history_without_durable_task_keeps_existing_compatibility_path():
    prepare = _between(BRIDGE, "def prepare_member", "def fallback_terminal")
    assert "legacy 失败历史没有 transfer_task_id" in prepare
    assert "return phase, row" in prepare
    request = _between(BRIDGE, "def _request_durable_retry", "def install_durable_retry_v3611")
    assert 'if not task_id:' in request
    assert 'return "ready", (member, path, fingerprint)' in request


def test_existing_admission_conflict_is_intercepted_before_old_10_min_classify_reopens_it():
    prepare = _between(BRIDGE, "def prepare_member", "def fallback_terminal")
    existing_pos = prepare.index("existing_block = _blocked_row(plugin, path)")
    previous_pos = prepare.index("phase, row = previous_prepare(plugin, member)")
    assert existing_pos < previous_pos
    assert "_is_admission_conflict(existing_block.get(\"reason\"))" in prepare
    assert "_PASS_FAILED and task_id" in prepare
    assert "_request_durable_retry(" in prepare


def test_admission_conflict_fallback_becomes_persistent_and_only_evidence_change_reopens():
    assert "_PERSISTENT_RECHECK_AT = 32503680000.0" in BRIDGE
    persist = _between(BRIDGE, "def _persist_admission_block", "def _admission_evidence_changed")
    assert '"recheck_at": _PERSISTENT_RECHECK_AT' in persist
    assert '"v3611_persistent_admission": True' in persist
    assert '"v3611_transfer_task_id"' in persist
    assert '"v3611_settlement_revision"' in persist

    prepare = _between(BRIDGE, "def prepare_member", "def fallback_terminal")
    assert "_admission_evidence_changed(existing_block, decision)" in prepare
    fallback = _between(BRIDGE, "def fallback_terminal", "GuangYaOrganizerEngineV360Mixin._v360_prepare_member")
    assert "admission_conflict_persistent=True" in fallback
    assert "不再按 10 分钟自动重撞" in fallback


def test_bridge_never_directly_mutates_moviepilot_transferpending_database():
    for forbidden in (
        "TransferPendingOper",
        "from app.db",
        ".discard(",
        "delete_terminal_failure",
        "stage_request_execution_retry",
    ):
        assert forbidden not in BRIDGE, forbidden
    assert "TransferExecutionCommand" in BRIDGE


def test_v3611_wiring_is_lazy_and_after_v369_runtime_hardening():
    init = _between(EXECUTION, "def init_organizer_monitor", "def _execute_isolated_transfer")
    assert "install_organizer_hardening_v369()" in init
    assert "from .organizer_durable_retry_v3611 import install_durable_retry_v3611" in init
    assert "install_durable_retry_v3611()" in init
    assert init.index("install_organizer_hardening_v369()") < init.index("install_durable_retry_v3611()")
    assert '"runtime_hardening": "v3.6.11"' in EXECUTION


def test_v3611_does_not_add_media_policy():
    for forbidden in (
        "target_directory",
        "rename_format",
        "category.yaml",
        "tmdbid=",
        "recognize_by_meta",
        "MediaType.TV",
        "MediaType.MOVIE",
        "overwrite",
        "scrape",
    ):
        assert forbidden not in BRIDGE, forbidden
