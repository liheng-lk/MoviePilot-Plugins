from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
PROBE_PATH = PLUGIN / "organizer_admission_conflict_probe_v3621.py"
EXEC_PATH = PLUGIN / "organizer_execution_v360.py"
PROBE = PROBE_PATH.read_text(encoding="utf-8")
EXEC = EXEC_PATH.read_text(encoding="utf-8")


def test_v3621_sources_parse():
    ast.parse(PROBE, filename=str(PROBE_PATH))
    ast.parse(EXEC, filename=str(EXEC_PATH))


def test_v3621_is_installed_after_durable_bridge_before_pending_layers():
    init = EXEC[EXEC.index("def init_organizer_monitor"):EXEC.index("def _execute_isolated_transfer")]
    durable = "install_durable_retry_v3611()"
    probe = "install_admission_conflict_probe_v3621()"
    pending = "install_pending_truth_v3612()"
    fairness = "install_pending_fairness_v3615()"
    assert "from .organizer_admission_conflict_probe_v3621 import install_admission_conflict_probe_v3621" in init
    assert init.index(durable) < init.index(probe) < init.index(pending) < init.index(fairness)


def test_v3621_wraps_actual_monitor_fallback_not_lower_priority_execution_fallback():
    assert "monitor_cls = _monitor_class()" in PROBE
    assert "previous_fallback = monitor_cls._fallback_terminal_state" in PROBE
    assert "monitor_cls._fallback_terminal_state = fallback" in PROBE
    assert "execution_cls._fallback_terminal_state = fallback" not in PROBE


def test_v3621_host_probe_is_observation_only_and_never_mutates_durable_repository():
    assert "original_admit(repository" in PROBE
    assert "except Exception as err" in PROBE
    assert "            raise\n" in PROBE
    for forbidden in (
        ".discard(",
        ".delete(",
        "request_retry(",
        "release_claim(",
        "record_enqueue_failure(",
        "planning_input=",
        "delete_file",
        "move_item",
    ):
        assert forbidden not in PROBE, forbidden


def test_v3621_matches_conflict_by_both_storage_and_exact_source_path():
    assert "storage in allowed_storages and member is not None" in PROBE
    assert "path = _norm(plugin, row.get(\"src_path\"))" in PROBE
    assert "member = members.get(path)" in PROBE


def test_v3621_preserves_original_fallback_for_non_conflict_members():
    assert "return previous_fallback(plugin, item, success=success, message=message)" in PROBE
    assert "已经 blocked/completed 的成员已退出 inflight" in PROBE


def test_v3621_public_failure_text_is_not_used_as_conflict_heuristic():
    # 用户现场的通用错误只能作为宿主返回值；不能把所有这类失败猜成准入冲突。
    assert "整理任务处理失败，请稍后重试" in PROBE
    conflict_fn = PROBE[PROBE.index("def _is_exact_admission_conflict"):PROBE.index("def install_moviepilot_admission_probe_v3621")]
    assert "整理任务处理失败，请稍后重试" not in conflict_fn
    assert "TransferAdmissionConflictError" in conflict_fn
    assert "整理源文件已按不同输入准入" in conflict_fn
