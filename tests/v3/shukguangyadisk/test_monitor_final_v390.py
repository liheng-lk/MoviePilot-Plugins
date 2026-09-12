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

    def test_final_monitor_is_first_mro_and_release_is_v3100(self):
        entry = ENTRY.read_text(encoding="utf-8")
        self.assertIn('plugin_version = "3.10.0"', entry)
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

    def test_dispatch_skips_waiting_candidates_and_worker_finishes_with_immediate_continuation(self):
        source = FINAL.read_text(encoding="utf-8")
        dispatch = source.split("    def _v390_dispatch_one", 1)[1].split("    def _on_isolated_worker_item_finished", 1)[0]
        self.assertIn("_DISPATCH_PROBE_BUDGET = 64", source)
        self.assertIn("dispatch_skipped_waiting", dispatch)
        self.assertIn('"member_wait"', dispatch)
        self.assertIn('"resource_wait"', dispatch)
        self.assertIn('"read_error"', dispatch)
        continuation = source.split("    def _on_isolated_worker_item_finished", 1)[1].split("    def organize_monitor_tick", 1)[0]
        self.assertIn('trigger="worker-finished"', continuation)

    def test_remote_mtime_can_seed_stability_without_rewaiting_from_discovery_time(self):
        source = FINAL.read_text(encoding="utf-8")
        self.assertIn("def _v310_seed_primary_observation", source)
        self.assertIn('seeded_by": "v3.10.0_remote_mtime"', source)
        core = CORE.read_text(encoding="utf-8")
        self.assertIn('getattr(plugin, "_v310_seed_primary_observation", None)', core)
        self.assertIn("seed_observation(primary, observed_at=now)", core)

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
        self.assertIn("__federation_expose_AssistantPage-v390.js?v=3.10.0", remote)
        self.assertNotIn("AssistantPage-v381.js?v=3.8.1", remote)
        self.assertIn("整理监控控制 · v3.10.0", page)
        self.assertIn("install_registration_safe", page)

    def test_manual_full_scan_dispatches_and_wait_reason_is_visible(self):
        source = FINAL.read_text(encoding="utf-8")
        self.assertIn("def _v394_manual_full_with_dispatch", source)
        self.assertIn('trigger=f"{trigger}-full"', source)
        self.assertIn("resource_dispatch_last_reason", source)
        self.assertIn("resource_dispatch_wait_seconds", source)
        self.assertIn("_DISPATCH_WAIT_LOG_SECONDS = 30.0", source)

    def test_plugin_json_is_v3100(self):
        data = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(data["version"], "3.10.0")
        self.assertIn("v3.10.0", data.get("history") or {})


if __name__ == "__main__":
    unittest.main()
