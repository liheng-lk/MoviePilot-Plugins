from __future__ import annotations

import ast
import time
from types import SimpleNamespace
from typing import Any, Dict, Sequence

from source_helper import source_text


def _method_function(source: str, class_name: str, method_name: str, extra_globals: dict):
    tree = ast.parse(source)
    class_node = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    method = next(
        node for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method_name
    )
    module = ast.Module(body=[method], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "Any": Any,
        "Dict": Dict,
        "Sequence": Sequence,
        **extra_globals,
    }
    exec(compile(module, f"<contract:{method_name}>", "exec"), namespace, namespace)
    return namespace[method_name]


class _Logger:
    def __init__(self):
        self.lines = []

    def info(self, *args, **kwargs):
        self.lines.append(("info", args, kwargs))

    def warning(self, *args, **kwargs):
        self.lines.append(("warning", args, kwargs))

    def error(self, *args, **kwargs):
        self.lines.append(("error", args, kwargs))


def test_waiting_head_cannot_starve_ready_resource_in_same_dispatch_round():
    source = source_text("organizer_monitor_final_v390.py")
    logger = _Logger()

    class Watch:
        _RESOURCE_KEY = "resource"

        def __init__(self):
            self.calls = 0
            self.rows = {
                "/movie/waiting": {"next_due": 0, "first_seen": 1, "priority": 10},
                "/tv/ready": {"next_due": 0, "first_seen": 2, "priority": 10},
            }

        def _load_rows(self, plugin, key):
            assert key == self._RESOURCE_KEY
            return dict(self.rows)

        def _dispatch_one(self, plugin, trigger):
            self.calls += 1
            if self.calls == 1:
                self.rows["/movie/waiting"]["next_due"] = time.time() + 30
                return {
                    "scheduled": False,
                    "reason": "member_wait",
                    "queue_depth": 2,
                    "path": "/movie/waiting",
                    "phases": {"stabilizing": 1},
                }
            return {
                "scheduled": True,
                "reason": "queued",
                "queue_depth": 2,
                "path": "/tv/ready",
            }

    watch = Watch()
    dispatch = _method_function(
        source,
        "GuangYaFinalMonitorV390Mixin",
        "_v390_dispatch_one",
        {
            "_watch": watch,
            "_DISPATCH_PROBE_BUDGET": 64,
            "_DISPATCH_WAIT_LOG_SECONDS": 30.0,
            "time": time,
            "logger": logger,
        },
    )

    class Plugin:
        _organize_monitor_batch_size = 100

        def __init__(self):
            self.status = {}

        def _save_monitor_status(self, **kwargs):
            self.status.update(kwargs)
            return self.status

    plugin = Plugin()
    result = dispatch(plugin, trigger="contract")

    assert result["scheduled"] is True
    assert result["path"] == "/tv/ready"
    assert watch.calls == 2
    assert result["dispatch_probe_count"] == 2
    assert result["dispatch_skipped_waiting"] == 1
    assert plugin.status["resource_dispatch_last_scheduled"] is True


def test_worker_completion_immediately_requests_next_dispatch():
    source = source_text("organizer_monitor_final_v390.py")
    logger = _Logger()
    continuation = _method_function(
        source,
        "GuangYaFinalMonitorV390Mixin",
        "_on_isolated_worker_item_finished",
        {"time": time, "logger": logger},
    )

    class Plugin:
        _isolated_stop = None
        _organize_monitor_enabled = True

        def __init__(self):
            self.triggers = []
            self.status = {}

        def _v390_dispatch_one(self, *, trigger):
            self.triggers.append(trigger)
            return {"scheduled": True, "reason": "queued"}

        def _save_monitor_status(self, **kwargs):
            self.status.update(kwargs)
            return self.status

    plugin = Plugin()
    continuation(plugin, path="/a.mkv", success=True, message="ok")

    assert plugin.triggers == ["worker-finished"]
    assert plugin.status["worker_continuation_scheduled"] is True
    assert plugin.status["worker_continuation_from"] == "/a.mkv"


def test_old_remote_file_does_not_restart_stability_clock_at_first_dispatch():
    source = source_text("organizer_monitor_final_v390.py")
    logger = _Logger()
    seed = _method_function(
        source,
        "GuangYaFinalMonitorV390Mixin",
        "_v310_seed_primary_observation",
        {"time": time, "logger": logger},
    )

    class Store:
        def __init__(self):
            self.state = {
                "completed": {},
                "ignored": {},
                "blocked": {},
                "inflight": {},
                "retry": {},
                "stabilizing": {},
            }

        @staticmethod
        def _row_fingerprint(row):
            return str((row or {}).get("fingerprint") or "")

        def mutate(self, fn):
            return fn(self.state)

    class Plugin:
        _organize_monitor_stability = 30

        def __init__(self):
            self.store = Store()

        def _state(self):
            return self.store

        @staticmethod
        def _v360_member_identity(member):
            return member.path, member.fingerprint

    observed_at = time.time()
    member = SimpleNamespace(
        path="/tv/show/E01.mkv",
        fingerprint="fp1",
        modify_time=observed_at - 300,
    )
    plugin = Plugin()
    seeded = seed(plugin, [member], observed_at=observed_at)
    row = plugin.store.state["stabilizing"][member.path]

    assert seeded == 1
    assert row["seeded_by"] == "v3.10.0_remote_mtime"
    assert row["first_seen"] <= observed_at - plugin._organize_monitor_stability


def test_runtime_contains_no_destructive_legacy_host_queue_mutation():
    recovery = source_text("organizer_queue_recovery.py")
    cleanup = source_text("organizer_legacy_queue_cleanup_v343.py")
    candidate = source_text("organizer_candidate_filter.py")

    for token in (
        "pending_oper.discard(",
        "remove_from_queue(",
        "global_vars.stop_transfer(",
        "TransferPendingOper()",
    ):
        assert token not in recovery
        assert token not in cleanup

    assert "install_legacy_queue_cleanup_v343()" not in candidate


def test_logs_do_not_emit_access_or_refresh_token_fragments():
    plugin = source_text("_plugin_legacy.py")
    client = source_text("guangya_client_legacy.py")
    network = source_text("guangya_network_resilience_v347.py")

    for source in (plugin, client, network):
        assert "access_token=%s" not in source
        assert "refresh_token=%s" not in source
        assert "old_access_token=%s" not in source
        assert "old_refresh_token=%s" not in source
