from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
GUARD = (PLUGIN / "organizer_pending_truth_v3612.py").read_text(encoding="utf-8")
EXECUTION = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")


def _between(text: str, start_token: str, end_token: str) -> str:
    start = text.index(start_token)
    end = text.index(end_token, start + len(start_token))
    return text[start:end]


def test_v3612_sources_are_valid_python():
    ast.parse(GUARD)
    ast.parse(EXECUTION)


def test_pending_truth_accepts_only_real_wait_phases():
    assert '_REAL_WAIT_PHASES: Tuple[str, ...] = (' in GUARD
    for phase in ("stabilizing", "history_wait", "retry_wait", "inflight"):
        assert f'"{phase}"' in GUARD
    helper = _between(GUARD, "def _real_wait_phases", "def install_pending_truth_v3612")
    assert "for name in _REAL_WAIT_PHASES:" in helper
    assert "if count > 0:" in helper
    assert "waiting[name] = count" in helper


def test_member_wait_reason_alone_can_never_create_pending_again():
    register = _between(GUARD, "def register_pending", "cls._v361_register_pending = register_pending")
    wait_pos = register.index("waiting = _real_wait_phases(result)")
    delegate_pos = register.index("return previous_register(plugin, group_path, files, result)")
    reason_pos = register.index('reason = str((result or {}).get("reason") or "")')
    assert wait_pos < delegate_pos < reason_pos
    assert "if waiting:" in register
    # reason 只用于诊断，不再参与“是否登记 pending”的业务判定。
    prefix = register[:reason_pos]
    assert "member_wait" not in prefix
    assert "resource_wait" not in prefix


def test_non_wait_member_wait_closes_existing_pending_and_logs_once():
    register = _between(GUARD, "def register_pending", "cls._v361_register_pending = register_pending")
    assert 'remover = getattr(plugin, "_v361_remove_pending", None)' in register
    assert "remover(group_path)" in register
    assert 'reason not in {"member_wait", "resource_wait"}' in register
    assert 'signature = (normalized, reason,' in register
    assert "if signature in seen:" in register
    assert "非等待态不进入优先回访" in register


def test_true_retry_and_durable_inflight_still_use_existing_pending_semantics():
    register = _between(GUARD, "def register_pending", "cls._v361_register_pending = register_pending")
    assert "if waiting:" in register
    assert "return previous_register(plugin, group_path, files, result)" in register
    # v3.6.11 durable bridge 的 active task 以 inflight phase 表达，必须被保留。
    assert '"inflight"' in GUARD
    assert '"retry_wait"' in GUARD


def test_v3612_is_installed_after_v3611_durable_bridge():
    init = _between(EXECUTION, "def init_organizer_monitor", "def _execute_isolated_transfer")
    durable = init.index("install_durable_retry_v3611()")
    pending = init.index("install_pending_truth_v3612()")
    assert durable < pending
    assert "from .organizer_pending_truth_v3612 import install_pending_truth_v3612" in init
    assert '"runtime_hardening": "v3.6.12"' in EXECUTION


def test_v3612_does_not_mutate_moviepilot_or_media_policy():
    for forbidden in (
        "TransferPendingOper",
        "TransferExecutionCommand",
        "do_transfer(",
        "planning_input",
        "target_directory",
        "rename_format",
        "MediaType.TV",
        "MediaType.MOVIE",
        "move_item",
        "delete_file",
        "overwrite_mode",
    ):
        assert forbidden not in GUARD, forbidden
