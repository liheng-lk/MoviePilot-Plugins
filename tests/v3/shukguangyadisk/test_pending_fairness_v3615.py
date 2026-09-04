from __future__ import annotations

import ast
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
FAIRNESS = (PLUGIN / "organizer_pending_fairness_v3615.py").read_text(encoding="utf-8")
EXECUTION = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")


def _function_node(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(name)


def _nested_function_node(tree: ast.Module, parent: str, name: str) -> ast.FunctionDef:
    parent_node = _function_node(tree, parent)
    for node in parent_node.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{parent}.{name}")


def _compile_helpers():
    tree = ast.parse(FAIRNESS)
    nodes = [
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        _function_node(tree, "_priority_snapshot"),
        _function_node(tree, "_priority_can_yield"),
        _function_node(tree, "_retry_schedule_counts"),
    ]
    module = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
    namespace = {"Any": object, "Dict": dict, "Tuple": tuple}
    exec(compile(module, "<v3615-helpers>", "exec"), namespace)
    return namespace


def _compile_monitor_scan(previous_monitor_scan):
    tree = ast.parse(FAIRNESS)
    helpers = _compile_helpers()
    node = _nested_function_node(tree, "install_pending_fairness_v3615", "monitor_scan")
    module = ast.fix_missing_locations(
        ast.Module(
            body=[
                ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
                node,
            ],
            type_ignores=[],
        )
    )
    helpers.update(
        {
            "previous_monitor_scan": previous_monitor_scan,
            "_SKIP_FLAG": "_v3615_skip_priority_once",
            "_log_yield_once": lambda *args, **kwargs: None,
            "time": time,
            "Any": object,
            "Dict": dict,
        }
    )
    exec(compile(module, "<v3615-monitor>", "exec"), helpers)
    return helpers["monitor_scan"]


class _Plugin:
    def __init__(self):
        self.status = {}

    def _save_monitor_status(self, **kwargs):
        self.status.update(kwargs)


def _priority(phases, *, reason="resource_wait", scheduled=False):
    return {
        "success": True,
        "message": "待稳定资源已优先复查",
        "data": {
            "priority_revisit": True,
            "scheduled": scheduled,
            "path": "/TV/old-show",
            "result": {
                "scheduled": scheduled,
                "reason": reason,
                "phases": dict(phases),
            },
        },
    }


def test_v3615_sources_are_valid_python():
    ast.parse(FAIRNESS)
    ast.parse(EXECUTION)


def test_wait_only_priority_yields_but_active_or_fault_priority_does_not():
    helpers = _compile_helpers()
    can_yield = helpers["_priority_can_yield"]

    assert can_yield(_priority({"history_wait": 1})) is True
    assert can_yield(_priority({"retry_wait": 2})) is True
    assert can_yield(_priority({"stabilizing": 1})) is True
    assert can_yield(_priority({"completed": 3}, reason="no_ready")) is True

    assert can_yield(_priority({"inflight": 1})) is False
    assert can_yield(_priority({"ready": 1}, reason="worker_not_accept")) is False
    assert can_yield(_priority({"history_wait": 1}, scheduled=True)) is False
    assert can_yield({
        "success": True,
        "data": {"priority_revisit": True, "scheduled": False, "path": "/TV/read-error"},
    }) is False


def test_history_wait_priority_revisit_continues_existing_monitor_in_same_tick():
    calls = []

    def previous(plugin, manual=False):
        calls.append(bool(getattr(plugin, "_v3615_skip_priority_once", False)))
        if len(calls) == 1:
            return _priority({"history_wait": 1})
        assert getattr(plugin, "_v3615_skip_priority_once", False) is True
        return {
            "success": True,
            "message": "continuous discovery progressed",
            "data": {"known_scan": True, "continuous_discovery": True, "scheduled": False},
        }

    plugin = _Plugin()
    monitor_scan = _compile_monitor_scan(previous)
    result = monitor_scan(plugin, manual=False)

    assert calls == [False, True]
    assert getattr(plugin, "_v3615_skip_priority_once", False) is False
    assert result["data"]["continuous_discovery"] is True
    assert result["data"]["priority_revisit_yielded"] is True
    assert result["data"]["priority_revisit_path"] == "/TV/old-show"
    assert result["data"]["priority_revisit_reason"] == "resource_wait"
    assert result["data"]["priority_revisit_phases"] == {"history_wait": 1}
    assert plugin.status["priority_revisit_yielded"] is True


def test_inflight_priority_keeps_single_resource_boundary_and_never_runs_second_scan():
    calls = []

    def previous(plugin, manual=False):
        calls.append(bool(getattr(plugin, "_v3615_skip_priority_once", False)))
        return _priority({"inflight": 1})

    plugin = _Plugin()
    monitor_scan = _compile_monitor_scan(previous)
    result = monitor_scan(plugin, manual=False)

    assert calls == [False]
    assert result["data"]["result"]["phases"] == {"inflight": 1}
    assert "priority_revisit_yielded" not in result["data"]


def test_retry_stats_split_future_backoff_from_already_due_rows():
    helpers = _compile_helpers()
    counts = helpers["_retry_schedule_counts"](
        {
            "retry": {
                "/TV/future.mkv": {"retry_at": 130, "attempts": 2},
                "/TV/due.mkv": {"retry_at": 90, "attempts": 5},
                "/TV/legacy.mkv": {"retry_at": 0, "attempts": 1},
            }
        },
        now=100,
    )
    assert counts == {
        "retry_total": 3,
        "retry_wait": 1,
        "retry_due": 2,
        "retry_max_attempts": 5,
    }


def test_v3615_is_installed_after_pending_truth_and_reports_runtime_hardening():
    init_start = EXECUTION.index("def init_organizer_monitor")
    execute_start = EXECUTION.index("def _execute_isolated_transfer", init_start)
    init = EXECUTION[init_start:execute_start]
    pending = init.index("install_pending_truth_v3612()")
    fairness = init.index("install_pending_fairness_v3615()")
    assert pending < fairness
    assert "from .organizer_pending_fairness_v3615 import install_pending_fairness_v3615" in init
    assert '"runtime_hardening": "v3.6.15"' in EXECUTION


def test_v3615_does_not_reimplement_media_or_destructive_policy():
    for forbidden in (
        "target_directory",
        "rename_format",
        "MediaType.TV",
        "MediaType.MOVIE",
        "move_item",
        "delete_file",
        "overwrite_mode",
        "do_transfer(",
        "planning_input",
    ):
        assert forbidden not in FAIRNESS, forbidden
