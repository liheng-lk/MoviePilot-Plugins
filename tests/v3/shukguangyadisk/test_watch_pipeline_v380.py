from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
WATCH = PLUGIN / "organizer_watch_pipeline_v380.py"
PARTIAL = PLUGIN / "organizer_partial_scheduler_v380.py"
POLICY = PLUGIN / "organizer_watch_policy_v380.py"
EXECUTION = PLUGIN / "organizer_execution_v360.py"
PAGE = PLUGIN / "dist" / "assets" / "__federation_expose_AssistantPage-v376.js"
REMOTE = PLUGIN / "dist" / "assets" / "remoteEntry.js"


class WatchPipelineV380ContractTest(unittest.TestCase):
    def test_python_sources_parse(self):
        ast.parse(WATCH.read_text(encoding="utf-8"))
        ast.parse(PARTIAL.read_text(encoding="utf-8"))
        ast.parse(POLICY.read_text(encoding="utf-8"))
        ast.parse(EXECUTION.read_text(encoding="utf-8"))

    def test_runtime_install_order_is_safe_and_final(self):
        source = EXECUTION.read_text(encoding="utf-8")
        watch_source = WATCH.read_text(encoding="utf-8")
        hardening = source.index("install_organizer_hardening_v369()")
        dual = source.index("install_dual_scan_v376()")
        partial = source.index("install_partial_scheduler_v380()")
        watch = source.index("install_watch_pipeline_v380()")
        policy = source.index("install_watch_policy_v380()")
        self.assertLess(hardening, dual)
        self.assertLess(dual, partial)
        self.assertLess(partial, watch)
        self.assertLess(watch, policy)
        self.assertNotIn("install_watch_pipeline_v380()\n\n\n__all__", watch_source)
        self.assertIn("_v380_watch_policy_patch_ready", source)

    def test_detection_happens_before_worker_dispatch_and_is_not_worker_gated(self):
        source = WATCH.read_text(encoding="utf-8")
        tick = source.split("    def tick(self) -> None:", 1)[1].split("    def api_scan", 1)[0]
        self.assertLess(tick.index("_watch_pulse("), tick.index("_dispatch_one(self, trigger=\"monitor\")"))
        pulse = source.split("def _watch_pulse", 1)[1].split("def _full_load", 1)[0]
        self.assertNotIn("_v360_worker_busy", pulse)
        self.assertIn("detection_runs_while_worker_busy=True", source)

    def test_full_scan_is_independent_from_worker_execution(self):
        source = WATCH.read_text(encoding="utf-8")
        full_step = source.split("def _full_step", 1)[1].split("def _stop_full", 1)[0]
        self.assertIn("_scan_directory(", full_step)
        self.assertNotIn("_v360_worker_busy", full_step)
        self.assertIn("_FULL_STEP_BUDGET = 50", source)
        self.assertIn("force_resource=bool(state.get(\"force_verify\"))", full_step)

    def test_worker_busy_only_blocks_consumer_not_persistent_resource_queue(self):
        source = WATCH.read_text(encoding="utf-8")
        dispatch = source.split("def _dispatch_one", 1)[1].split("def install_watch_pipeline_v380", 1)[0]
        self.assertIn("if plugin._v360_worker_busy(snapshot):", dispatch)
        self.assertIn('resource_dispatch_wait_reason="worker_busy"', dispatch)
        scheduled = dispatch.split('if result.get("scheduled"):', 1)[1].split("if _queue_terminal", 1)[0]
        self.assertIn("rows[path] = row", scheduled)
        self.assertNotIn("rows.pop(path", scheduled)
        self.assertIn("防止半整理丢失", scheduled)

    def test_directory_signature_contains_cloud_identity_size_and_mtime(self):
        source = WATCH.read_text(encoding="utf-8")
        token = source.split("def _item_token", 1)[1].split("def _directory_signature", 1)[0]
        for marker in ("fileid", "path", "name", "size", "modify_time", "type"):
            self.assertIn(marker, token)
        signature = source.split("def _directory_signature", 1)[1].split("def _latest_mtime", 1)[0]
        self.assertIn("hashlib.sha1", signature)

    def test_watch_selector_prioritizes_structure_new_hot_then_cold(self):
        source = WATCH.read_text(encoding="utf-8")
        selector = source.split("def _select_watch_paths", 1)[1].split("def _watch_pulse", 1)[0]
        positions = [
            selector.index("# P0"),
            selector.index("# P1"),
            selector.index("# P2"),
            selector.index("# P3"),
        ]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("depth <= 1", selector)
        self.assertIn("hot_until", selector)
        self.assertIn("_COLD_RECHECK_SECONDS", selector)

    def test_successful_parent_listing_prunes_only_vanished_subtrees(self):
        source = WATCH.read_text(encoding="utf-8")
        scan = source.split("def _scan_directory", 1)[1].split("def _select_watch_paths", 1)[0]
        self.assertIn("vanished = old_children - new_children", scan)
        self.assertIn("_drop_subtree(watch_rows, missing)", scan)
        self.assertIn("_drop_subtree(resource_rows, missing)", scan)
        self.assertLess(scan.index("_v360_list_directory"), scan.index("vanished ="))

    def test_partial_ready_scheduler_no_longer_has_whole_resource_hard_wait(self):
        source = PARTIAL.read_text(encoding="utf-8")
        schedule = source.split("    def schedule", 1)[1].split("    _MonitorMixin._v366_finish_schedule", 1)[0]
        self.assertIn("hard_wait =", schedule)
        self.assertIn("if not rows:", schedule)
        self.assertNotIn("if hard_wait:\n", schedule)
        self.assertIn("all_primary_ready", schedule)
        self.assertIn("and all_primary_ready", schedule)
        self.assertIn("partial_wait", source)

    def test_stop_suppresses_scheduled_full_and_manual_can_upgrade_force_verify(self):
        source = POLICY.read_text(encoding="utf-8")
        self.assertIn('if float(raw.get("suppressed_until") or 0) > now:', source)
        self.assertIn('"suppressed_until": now + _watch._FULL_SCAN_INTERVAL', source)
        self.assertIn('if existing.get("active") and force_verify and not existing.get("force_verify"):', source)
        self.assertIn('existing["force_verify"] = True', source)
        self.assertIn("manual-force-upgrade", source)

    def test_monitor_ui_explains_real_pipeline_and_exposes_controls(self):
        page = PAGE.read_text(encoding="utf-8")
        for label in ("增量观察一次", "强制全量巡检", "停止全量巡检", "刷新状态"):
            self.assertIn(label, page)
        for marker in ("watch_registry_total", "watch_hot_total", "resource_queue_depth", "full_scan_remaining_dirs"):
            self.assertIn(marker, page)
        self.assertIn("正在整理时监控不会停止", page)

    def test_public_release_is_real_v380_update(self):
        package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["ShukGuangYaDisk"]
        plugin = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
        init = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
        remote = REMOTE.read_text(encoding="utf-8")
        self.assertEqual(package["version"], "3.8.0")
        self.assertEqual(plugin["version"], "3.8.0")
        self.assertIn('plugin_version = "3.8.0"', init)
        self.assertIn('__federation_expose_AssistantPage-v376.js?v=3.8.0', remote)
        self.assertIn("v3.8.0", package["history"])
        self.assertEqual(package["history"]["v3.8.0"], plugin["history"]["v3.8.0"])


if __name__ == "__main__":
    unittest.main()
