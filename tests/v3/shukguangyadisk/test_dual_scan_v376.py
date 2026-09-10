import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
DUAL = PLUGIN / "organizer_dual_scan_v376.py"
FILTER = PLUGIN / "organizer_candidate_filter.py"
PAGE = PLUGIN / "dist" / "assets" / "__federation_expose_AssistantPage-v376.js"
REMOTE = PLUGIN / "dist" / "assets" / "remoteEntry.js"


class DualScanV376ContractTest(unittest.TestCase):
    def test_dual_scan_is_final_monitor_installer_after_partial_revisit(self):
        source = FILTER.read_text(encoding="utf-8")
        self.assertIn("from .organizer_dual_scan_v376 import install_dual_scan_v376", source)
        self.assertLess(source.index("install_partial_revisit_v375()"), source.index("install_dual_scan_v376()"))

    def test_incremental_scan_always_advances_discovery_after_known_check(self):
        source = DUAL.read_text(encoding="utf-8")
        self.assertIn('def run_incremental(self, trigger: str = "monitor")', source)
        self.assertIn("original_run(self, manual=True)", source)
        self.assertIn("pending→known变化→discovery推进1页", source)
        self.assertIn("pending回访", source)
        self.assertIn("known检查=", source)

    def test_full_scan_is_persistent_until_cycle_complete(self):
        source = DUAL.read_text(encoding="utf-8")
        self.assertIn('"active": True', source)
        self.assertIn('if bool(data.get("cycle_complete")):', source)
        self.assertIn('session.update({"active": False, "completed_at": time.time(), "remaining_dirs": 0})', source)
        self.assertIn("全量扫描会话已保留；当前任务结束后自动继续", source)

    def test_full_progress_does_not_fake_zero_when_fast_path_has_no_cursor_count(self):
        source = DUAL.read_text(encoding="utf-8")
        self.assertIn('if "remaining_dirs" in data:', source)
        self.assertIn('session["remaining_dirs"] = int(data.get("remaining_dirs") or 0)', source)
        self.assertIn('"log_filter_hint": "【光鸭云盘助手】【整理】"', source)

    def test_manual_stop_suppresses_only_automatic_full_restart(self):
        source = DUAL.read_text(encoding="utf-8")
        self.assertIn('suppressed_until = float(raw.get("suppressed_until") or 0)', source)
        self.assertIn('if suppressed_until > now:', source)
        self.assertIn('"suppressed_until": stopped_at + _FULL_SCAN_INTERVAL', source)
        self.assertIn("30 分钟内不会自动重启全量", source)
        start_block = source.split('def start_full(self, trigger: str = "manual")', 1)[1].split('def stop_full', 1)[0]
        self.assertNotIn("suppressed_until", start_block)

    def test_full_and_incremental_have_separate_manual_api_endpoints(self):
        source = DUAL.read_text(encoding="utf-8")
        for path in (
            "/organize/monitor/incremental-scan",
            "/organize/monitor/full-scan",
            "/organize/monitor/full-scan/stop",
        ):
            self.assertIn(path, source)

    def test_scan_logs_have_stable_id_and_six_stage_schema(self):
        source = DUAL.read_text(encoding="utf-8")
        self.assertIn('prefix = "FULL" if mode == "full" else "INC"', source)
        self.assertIn("_STAGE_TOTAL = 6", source)
        for marker in ("触发", "准备", "发现", "判定", "入队", "完成"):
            self.assertIn(marker, source)
        self.assertIn('"log_stage_schema": "1触发/2准备/3发现/4判定/5入队/6完成"', source)

    def test_frontend_exposes_three_explicit_scan_controls_and_progress(self):
        page = PAGE.read_text(encoding="utf-8")
        self.assertIn("增量扫描一次", page)
        self.assertIn("开始全量扫描", page)
        self.assertIn("停止全量扫描", page)
        self.assertIn("/organize/monitor/incremental-scan", page)
        self.assertIn("/organize/monitor/full-scan", page)
        self.assertIn("/organize/monitor/full-scan/stop", page)
        self.assertIn("扫描 ID", page)
        self.assertIn("扫描阶段", page)
        self.assertIn("剩余游标", page)

    def test_federation_entry_points_to_v376_control_page(self):
        remote = REMOTE.read_text(encoding="utf-8")
        self.assertIn("__federation_expose_AssistantPage-v376.js?v=3.7.3", remote)


if __name__ == "__main__":
    unittest.main()
