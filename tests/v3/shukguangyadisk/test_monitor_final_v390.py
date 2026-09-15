from __future__ import annotations

from source_helper import single_init_plugin_path

import ast
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = single_init_plugin_path(ROOT / "plugins.v3" / "shukguangyadisk")
ENTRY = PLUGIN / "__init__.py"
FINAL = PLUGIN / "organizer_monitor_final_v390.py"
EXECUTION = PLUGIN / "organizer_execution_v360.py"
CORE = PLUGIN / "organizer_watch_pipeline_v380.py"
REMOTE = PLUGIN / "dist" / "assets" / "remoteEntry.js"
PAGE = PLUGIN / "dist" / "assets" / "__federation_expose_AssistantPage-v390.js"


class FinalMonitorV390ContractTest(unittest.TestCase):
    def test_sources_parse(self):
        for path in (ENTRY, FINAL, EXECUTION):
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_final_monitor_is_first_mro_and_release_is_v390(self):
        entry = ENTRY.read_text(encoding="utf-8")
        self.assertIn('plugin_version = "3.9.13"', entry)
        class_slice = entry.split("class ShukGuangYaDisk(", 1)[1].split("):", 1)[0]
        self.assertLess(class_slice.index("_GuangYaFinalMonitorV390Mixin"), class_slice.index("_GuangYaOrganizerMonitorV366Mixin"))
        self.assertIn("as _GuangYaFinalMonitorV390Mixin", entry)
        for public in (
            "GuangYaOrganizerMonitorV366Mixin,",
            "GuangYaOrganizerExecutionV360Mixin,",
            "GuangYaOrganizerMixin,",
        ):
            self.assertNotIn("    " + public, class_slice)

    def test_get_service_is_install_registration_side_effect_free(self):
        source = FINAL.read_text(encoding="utf-8")
        body = source.split("    def get_service", 1)[1].split("    def _v390_ensure_monitor", 1)[0]
        self.assertNotIn("init_organizer_monitor(", body)
        self.assertNotIn("_watch_pulse(", body)
        self.assertNotIn("_start_full(", body)
        self.assertNotIn("_guangya_api", body)
        self.assertIn("IntervalTrigger", body)
        self.assertIn("self.organize_monitor_tick", body)

    def test_legacy_dynamic_monitor_patch_stack_is_not_installed(self):
        source = EXECUTION.read_text(encoding="utf-8")
        forbidden = (
            "install_dual_scan_v376",
            "install_partial_scheduler_v380",
            "install_watch_pipeline_v380",
            "install_watch_policy_v380",
            "install_runtime_survival_v382",
        )
        for marker in forbidden:
            self.assertNotIn(marker, source)
        self.assertIn("install_organizer_hardening_v369", source)
        self.assertIn("install_move_transaction_guard_v364", source)

    def test_detection_is_independent_from_worker_dispatch(self):
        source = FINAL.read_text(encoding="utf-8")
        tick = source.split("    def organize_monitor_tick", 1)[1].split("    def run_organize_monitor_scan", 1)[0]
        self.assertLess(tick.index("_watch._watch_pulse("), tick.index("_v390_dispatch_one(trigger=\"monitor\")"))
        core = CORE.read_text(encoding="utf-8")
        pulse = core.split("def _watch_pulse", 1)[1].split("def _full_load", 1)[0]
        self.assertNotIn("_v360_worker_busy", pulse)
        dispatch = core.split("def _dispatch_one", 1)[1].split("def install_watch_pipeline_v380", 1)[0]
        self.assertIn("_v360_worker_busy", dispatch)

    def test_resource_queue_is_persistent_and_half_organized_resource_is_retained(self):
        core = CORE.read_text(encoding="utf-8")
        self.assertIn('"organize_v380_resource_queue"', core)
        dispatch = core.split("def _dispatch_one", 1)[1].split("def install_watch_pipeline_v380", 1)[0]
        scheduled = dispatch.split('if result.get("scheduled"):', 1)[1].split("if _queue_terminal", 1)[0]
        self.assertIn("rows[path] = row", scheduled)
        self.assertNotIn("rows.pop(path", scheduled)

    def test_partial_ready_is_static_not_monkey_patch(self):
        source = FINAL.read_text(encoding="utf-8")
        schedule = source.split("    def _v360_schedule_resource", 1)[1]
        self.assertIn("all_primary_ready", schedule)
        self.assertIn("and all_primary_ready", schedule)
        self.assertIn("_WAIT_PHASES", source)
        self.assertIn("partial_wait", source)

    def test_tick_has_plugin_survival_boundary_and_boot_grace(self):
        source = FINAL.read_text(encoding="utf-8")
        tick = source.split("    def organize_monitor_tick", 1)[1].split("    def run_organize_monitor_scan", 1)[0]
        self.assertIn("except Exception as err", tick)
        self.assertIn("cooldown_until", tick)
        self.assertIn("_FAILURE_LIMIT", tick)
        due = source.split("    def _v390_full_due", 1)[1].split("    def _v390_start_full", 1)[0]
        self.assertIn("_BOOT_GRACE_SECONDS", due)
        self.assertIn("suppressed_until", due)

    def test_federation_uses_fresh_v390_chunk(self):
        remote = REMOTE.read_text(encoding="utf-8")
        page = PAGE.read_text(encoding="utf-8")
        self.assertIn("__federation_expose_AssistantPage-v390.js?v=3.9.13", remote)
        self.assertNotIn("AssistantPage-v381.js?v=3.8.1", remote)
        self.assertIn("整理监控控制 · v3.9.13", page)
        self.assertIn("install_registration_safe", page)

    def test_loose_container_skips_waiting_or_terminal_members(self):
        source = FINAL.read_text(encoding="utf-8")
        schedule = source.split("    def _v360_schedule_resource", 1)[1].split("    def organize_monitor_tick", 1)[0]
        self.assertIn("for member in primary:", schedule)
        self.assertIn("if loose:", schedule)
        self.assertIn("break", schedule)
        self.assertNotIn("primary[:1] if loose", schedule)

    def test_dispatch_skips_deferred_resource_and_tries_next_due_item(self):
        source = FINAL.read_text(encoding="utf-8")
        dispatch = source.split("    def _v390_dispatch_one", 1)[1].split("    def organize_monitor_tick", 1)[0]
        self.assertIn("_DEFERRED_RESOURCE_REASONS", source)
        self.assertIn("if reason in _DEFERRED_RESOURCE_REASONS:", dispatch)
        self.assertIn("continue", dispatch)
        self.assertIn('"worker_not_accept"', dispatch)

    def test_deep_unscanned_directory_cannot_be_starved_by_shallow_budget(self):
        core = CORE.read_text(encoding="utf-8")
        tree = ast.parse(core)
        selector = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_select_watch_paths"
        )
        module = ast.Module(body=[selector], type_ignores=[])
        ast.fix_missing_locations(module)

        def ensure_watch_row(rows, path, root):
            rows.setdefault(path, {
                "path": path,
                "depth": 0,
                "last_checked": 0,
                "first_seen": 0,
                "hot_until": 0,
            })

        namespace = {
            "Dict": dict,
            "List": list,
            "Any": object,
            "_ensure_watch_row": ensure_watch_row,
            "_depth": lambda path, root: 0,
        }
        exec(compile(module, "<deep-watch-selector>", "exec"), namespace)
        select = namespace["_select_watch_paths"]

        now = 1000.0
        rows = {
            "/root": {
                "path": "/root", "depth": 0, "last_checked": now - 120,
                "first_seen": 1, "hot_until": 0,
            }
        }
        for index in range(12):
            path = f"/root/shallow-{index:02d}"
            rows[path] = {
                "path": path, "depth": 1, "last_checked": now - 120,
                "first_seen": index + 2, "hot_until": 0,
            }
        deep = "/root/a/b/c/d/Season 01"
        rows[deep] = {
            "path": deep, "depth": 6, "last_checked": 0,
            "first_seen": 99, "hot_until": 0,
        }

        selected = select(rows, root="/root", now=now, interval=60, budget=4)
        self.assertIn(deep, selected)
        self.assertLessEqual(len(selected), 4)

        # 已经扫描过的深层目录也应按用户 interval 参与公平轮转，
        # 不能再固定等待旧版 15 分钟 cold recheck。
        deep_known = "/root/a/b/c/d/e/Season 02"
        rows2 = {
            "/root": {
                "path": "/root", "depth": 0, "last_checked": now,
                "first_seen": 1, "hot_until": 0,
            },
            deep_known: {
                "path": deep_known, "depth": 7, "last_checked": now - 61,
                "first_seen": 2, "hot_until": 0,
            },
        }
        selected2 = select(rows2, root="/root", now=now, interval=60, budget=2)
        self.assertIn(deep_known, selected2)

    def test_new_multilevel_frontier_is_drilled_in_same_pulse(self):
        core = CORE.read_text(encoding="utf-8")
        tree = ast.parse(core)
        pulse_node = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_watch_pulse"
        )
        module = ast.Module(body=[pulse_node], type_ignores=[])
        ast.fix_missing_locations(module)

        scan_order = []

        class FakeTime:
            @staticmethod
            def time():
                return 1000.0

        class FakeLock:
            def acquire(self, blocking=False):
                return True

            def release(self):
                return None

        class Plugin:
            _enabled = True
            _guangya_api = object()

            def _save_monitor_status(self, **kwargs):
                self.status = kwargs

        watch_rows = {
            "/root": {"path": "/root", "depth": 0, "last_checked": 0},
            "/root/old-1": {"path": "/root/old-1", "depth": 1, "last_checked": 0},
            "/root/old-2": {"path": "/root/old-2", "depth": 1, "last_checked": 0},
            "/root/old-3": {"path": "/root/old-3", "depth": 1, "last_checked": 0},
        }
        resource_rows = {}

        def scan_directory(plugin, path, watch, resources, *, reason, force_resource):
            del plugin, watch, resources, reason, force_resource
            scan_order.append(path)
            chain = {
                "/root": "/root/A",
                "/root/A": "/root/A/B",
                "/root/A/B": "/root/A/B/Season 01",
            }
            child = chain.get(path)
            return {
                "changed": child is not None,
                "queued": path.endswith("Season 01"),
                "refreshed": False,
                "state_recheck": False,
                "primary": 1 if path.endswith("Season 01") else 0,
                "files": 1 if path.endswith("Season 01") else 0,
                "new_children": [child] if child else [],
            }

        namespace = {
            "Any": object,
            "Dict": dict,
            "List": list,
            "time": FakeTime,
            "_WATCH_BUDGET": 64,
            "_WATCH_KEY": "watch",
            "_RESOURCE_KEY": "resource",
            "_scan_id": lambda prefix: prefix + "-test",
            "_root": lambda plugin: "/root",
            "_watch_interval": lambda plugin: 60.0,
            "_watch_lock": lambda plugin: FakeLock(),
            "_load_rows": lambda plugin, key: watch_rows if key == "watch" else resource_rows,
            "_select_watch_paths": lambda rows, **kwargs: [
                "/root", "/root/old-1", "/root/old-2", "/root/old-3"
            ],
            "_scan_directory": scan_directory,
            "_save_rows": lambda *args, **kwargs: None,
            "_log": lambda *args, **kwargs: None,
        }
        exec(compile(module, "<deep-watch-pulse>", "exec"), namespace)
        pulse = namespace["_watch_pulse"]

        result = pulse(Plugin(), trigger="test", budget=4)

        self.assertEqual(
            scan_order,
            ["/root", "/root/A", "/root/A/B", "/root/A/B/Season 01"],
        )
        self.assertEqual(result["data"]["watch_queued"], 1)

    def test_watch_log_separates_created_refreshed_and_state_rechecks(self):
        core = CORE.read_text(encoding="utf-8")
        self.assertIn('"refreshed": refreshed', core)
        self.assertIn('"state_recheck": state_recheck', core)
        self.assertIn("watch_refreshed=refreshed", core)
        self.assertIn("watch_state_rechecks=state_rechecks", core)
        self.assertIn("状态复核={state_rechecks}", core)

    def test_unchanged_blocked_resource_is_requeued_at_its_recheck_time(self):
        core = CORE.read_text(encoding="utf-8")
        scan = core.split("def _scan_directory", 1)[1].split("def _watch_pulse", 1)[0]
        self.assertIn("_blocked_recheck_at(plugin, primary)", scan)
        self.assertIn("changed or force_resource or state_recheck", scan)
        self.assertIn('f"{reason}:blocked-recheck"', scan)
        self.assertIn('"next_due": max(float(blocked_recheck_at or 0), now)', scan)
        self.assertIn('"state_recheck": "blocked"', scan)

    def test_blocked_terminal_row_is_retained_until_recheck_at(self):
        core = CORE.read_text(encoding="utf-8")
        dispatch = core.split("def _dispatch_one", 1)[1].split("def install_watch_pipeline_v380", 1)[0]
        self.assertIn('if int(phases.get("blocked") or 0) > 0', dispatch)
        self.assertIn("_blocked_recheck_at(plugin", dispatch)
        self.assertIn('"last_result": "blocked_wait"', dispatch)
        self.assertIn('"state_recheck": "blocked"', dispatch)
        self.assertIn("blocked>0 但 queue=0", dispatch)
        self.assertIn("rows[path] = row", dispatch)

    def test_manual_full_scan_dispatches_and_wait_reason_is_visible(self):
        source = FINAL.read_text(encoding="utf-8")
        self.assertIn("def _v394_manual_full_with_dispatch", source)
        self.assertIn('trigger=f"{trigger}-full"', source)
        self.assertIn("resource_dispatch_last_reason", source)
        self.assertIn("resource_dispatch_wait_seconds", source)
        self.assertIn("_DISPATCH_WAIT_LOG_SECONDS = 30.0", source)

    def test_plugin_json_is_v390(self):
        data = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(data["version"], "3.9.13")
        self.assertIn("v3.9.13", data.get("history") or {})


if __name__ == "__main__":
    unittest.main()
