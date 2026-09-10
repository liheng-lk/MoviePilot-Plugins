from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
DUAL = PLUGIN / "organizer_dual_scan_v376.py"
CANDIDATE = PLUGIN / "organizer_candidate_filter.py"
EXECUTION = PLUGIN / "organizer_execution_v360.py"
PAGE = PLUGIN / "dist" / "assets" / "__federation_expose_AssistantPage-v381.js"
REMOTE = PLUGIN / "dist" / "assets" / "remoteEntry.js"


class DualScanV376ContractTest(unittest.TestCase):
    def test_python_sources_parse(self):
        ast.parse(DUAL.read_text(encoding="utf-8"))
        ast.parse(CANDIDATE.read_text(encoding="utf-8"))
        ast.parse(EXECUTION.read_text(encoding="utf-8"))

    def test_release_version_is_consistent(self):
        package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["ShukGuangYaDisk"]
        plugin = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
        init = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
        remote = REMOTE.read_text(encoding="utf-8")
        self.assertEqual(package["version"], "3.8.1")
        self.assertEqual(plugin["version"], "3.8.1")
        self.assertIn('plugin_version = "3.8.1"', init)
        self.assertIn('__federation_expose_AssistantPage-v381.js?v=3.8.1', remote)
        # v376 作为历史兼容层必须保留，但不再拥有最终监控调度权。
        self.assertIn("v3.7.6", package["history"])
        self.assertEqual(package["history"]["v3.7.6"], plugin["history"]["v3.7.6"])

    def test_dual_scan_install_is_deferred_until_runtime_mro_is_complete(self):
        candidate = CANDIDATE.read_text(encoding="utf-8")
        execution = EXECUTION.read_text(encoding="utf-8")
        self.assertNotIn("from .organizer_dual_scan_v376 import install_dual_scan_v376", candidate)
        self.assertNotIn("install_dual_scan_v376()", candidate)
        init_block = execution.split("def init_organizer_monitor", 1)[1].split("def _execute_isolated_transfer", 1)[0]
        self.assertIn("from .organizer_dual_scan_v376 import install_dual_scan_v376", init_block)
        self.assertIn("_v376_dual_scan_patch_ready", execution)
        self.assertLess(
            init_block.index("install_organizer_hardening_v369()"),
            init_block.index("install_dual_scan_v376()"),
        )
        self.assertLess(
            init_block.index("install_dual_scan_v376()"),
            init_block.index("install_watch_pipeline_v380()"),
        )
        self.assertLess(
            init_block.index("install_watch_pipeline_v380()"),
            init_block.index("install_move_confirmation_v360()"),
        )

    def test_existing_discovery_patch_still_installs_at_import_boundary(self):
        source = CANDIDATE.read_text(encoding="utf-8")
        self.assertIn("install_paged_scan_handoff_v359(GuangYaCandidateFilterMixin)", source)

    def test_v376_full_scan_contract_remains_as_compatibility_layer(self):
        source = DUAL.read_text(encoding="utf-8")
        self.assertIn("_EngineMixin.run_organize_monitor_scan(self, manual=True)", source)
        self.assertIn('if data.get("cycle_complete"):', source)
        self.assertIn('session.update({"active": False, "completed_at": completed_at, "remaining_dirs": 0})', source)
        self.assertIn("全量扫描会话已保留；Worker 空闲后自动继续", source)

    def test_incremental_pending_yield_is_fail_closed(self):
        source = DUAL.read_text(encoding="utf-8")
        self.assertIn("def _safe_pending_yield", source)
        self.assertIn('if not isinstance(nested, dict):', source)
        self.assertIn('if reason == "worker_not_accept":', source)
        self.assertIn('if int(phases.get("inflight") or 0) > 0:', source)

    def test_v376_log_schema_is_retained_for_compatibility(self):
        source = DUAL.read_text(encoding="utf-8")
        self.assertIn("【光鸭云盘助手】【整理】【%s】【%s/%s %s】%s", source)
        self.assertIn('"log_stage_schema": "1触发/2准备/3发现/4判定/5入队/6完成"', source)

    def test_existing_api_paths_are_reused_by_v380_monitor_ui(self):
        backend = DUAL.read_text(encoding="utf-8")
        page = PAGE.read_text(encoding="utf-8")
        endpoints = (
            "/organize/monitor/incremental-scan",
            "/organize/monitor/full-scan",
            "/organize/monitor/full-scan/stop",
        )
        for endpoint in endpoints:
            self.assertIn(endpoint, backend)
            self.assertIn(endpoint, page)
        for label in ("增量观察一次", "强制全量巡检", "停止全量巡检", "刷新状态"):
            self.assertIn(label, page)
        for marker in ("watch_registry_total", "resource_queue_depth", "full_scan_remaining_dirs"):
            self.assertIn(marker, page)


if __name__ == "__main__":
    unittest.main()
