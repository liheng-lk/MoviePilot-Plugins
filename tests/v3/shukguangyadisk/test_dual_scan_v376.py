from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
DUAL = PLUGIN / "organizer_dual_scan_v376.py"
FILTER = PLUGIN / "organizer_candidate_filter.py"
PAGE = PLUGIN / "dist" / "assets" / "__federation_expose_AssistantPage-v376.js"
REMOTE = PLUGIN / "dist" / "assets" / "remoteEntry.js"


def test_dual_scan_is_final_monitor_installer_after_partial_revisit():
    source = FILTER.read_text(encoding="utf-8")
    assert "from .organizer_dual_scan_v376 import install_dual_scan_v376" in source
    assert source.index("install_partial_revisit_v375()") < source.index("install_dual_scan_v376()")


def test_incremental_scan_always_advances_discovery_after_known_check():
    source = DUAL.read_text(encoding="utf-8")
    assert 'def run_incremental(self, trigger: str = "monitor")' in source
    assert "original_run(self, manual=True)" in source
    assert "pending→known变化→discovery推进1页" in source


def test_full_scan_is_persistent_until_cycle_complete():
    source = DUAL.read_text(encoding="utf-8")
    assert '"active": True' in source
    assert 'if bool(data.get("cycle_complete")):' in source
    assert 'session.update({"active": False, "completed_at": time.time(), "remaining_dirs": 0})' in source
    assert "全量扫描会话已保留；当前任务结束后自动继续" in source


def test_full_and_incremental_have_separate_manual_api_endpoints():
    source = DUAL.read_text(encoding="utf-8")
    for path in (
        "/organize/monitor/incremental-scan",
        "/organize/monitor/full-scan",
        "/organize/monitor/full-scan/stop",
    ):
        assert path in source
    assert "旧“立即扫描”API 保持兼容，但语义升级为真正完整全量" in source


def test_scan_logs_have_stable_id_and_six_stage_schema():
    source = DUAL.read_text(encoding="utf-8")
    assert 'prefix = "FULL" if mode == "full" else "INC"' in source
    assert "_STAGE_TOTAL = 6" in source
    for marker in ("触发", "准备", "发现", "判定", "入队", "完成"):
        assert marker in source
    assert '"log_stage_schema": "1触发/2准备/3发现/4判定/5入队/6完成"' in source


def test_frontend_exposes_three_explicit_scan_controls_and_progress():
    page = PAGE.read_text(encoding="utf-8")
    assert "增量扫描一次" in page
    assert "开始全量扫描" in page
    assert "停止全量扫描" in page
    assert "/organize/monitor/incremental-scan" in page
    assert "/organize/monitor/full-scan" in page
    assert "/organize/monitor/full-scan/stop" in page
    assert "扫描 ID" in page
    assert "扫描阶段" in page
    assert "剩余游标" in page


def test_federation_entry_points_to_v376_control_page():
    remote = REMOTE.read_text(encoding="utf-8")
    assert "__federation_expose_AssistantPage-v376.js?v=3.7.3" in remote
