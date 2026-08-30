from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
ENGINE = (PLUGIN / "organizer_engine_v360.py").read_text(encoding="utf-8")
EXECUTION = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")
HISTORY = (PLUGIN / "organizer_folder_history.py").read_text(encoding="utf-8")
MOVE = (PLUGIN / "guangya_move_confirmation_v360.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
REMOTE = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")


def test_v360_engine_is_explicit_first_mro_authority():
    assert "class GuangYaFolderHistoryMixin:" in HISTORY
    assert "organizer_execution_v360" not in HISTORY
    assert "class GuangYaOrganizerExecutionV360Mixin(GuangYaOrganizerEngineV360Mixin):" in EXECUTION
    class_start = ENTRY.index("class ShukGuangYaDisk(")
    execution_pos = ENTRY.index("GuangYaOrganizerExecutionV360Mixin,", class_start)
    history_pos = ENTRY.index("GuangYaFolderHistoryMixin,", class_start)
    worker_pos = ENTRY.index("GuangYaWorkerGuardMixin,", class_start)
    candidate_pos = ENTRY.index("GuangYaCandidateFilterMixin,", class_start)
    assert execution_pos < history_pos < worker_pos < candidate_pos


def test_v360_import_order_breaks_history_orchestrator_cycle():
    history_import = ENTRY.index("from .organizer_folder_history import GuangYaFolderHistoryMixin")
    engine_import = ENTRY.index("from .organizer_execution_v360 import GuangYaOrganizerExecutionV360Mixin")
    assert history_import < engine_import
    assert "不再让历史模块反向导入 Engine" in HISTORY


def test_v360_all_scan_entries_gate_on_worker_owner_before_directory_discovery():
    run_start = ENGINE.index("def run_organize_monitor_scan")
    owner_pos = ENGINE.index("owner_ok, snapshot = self._v360_owner_gate()", run_start)
    list_pos = ENGINE.index("self._v360_list_directory(current_path)", run_start)
    assert owner_pos < list_pos
    assert "旧 Worker 正在交接，本轮不扫描、不入队、不修改 retry" in ENGINE
    assert "Worker 交接中，不扫描、不入队、不写 retry" in ENGINE


def test_v360_discovery_is_bounded_to_50_directories_with_persistent_cursor():
    for token in (
        '_CURSOR_KEY = "organize_v360_discovery_cursor"',
        "_PAGE_DIR_LIMIT = 50",
        "while queue and dirs_scanned < _PAGE_DIR_LIMIT:",
        '"queue": queue',
        '"seen": list(seen)',
        "无全库重扫、无 discovery→retry",
    ):
        assert token in ENGINE, token


def test_v360_migration_removes_legacy_retry_stabilizing_and_sticky_only():
    assert 'state["retry"] = {}' in ENGINE
    assert 'state["stabilizing"] = {}' in ENGINE
    assert 'sticky_tv_group_path=""' in ENGINE
    assert "completed/blocked 保留" in ENGINE
    assert '"preserved_completed"' in ENGINE
    assert '"preserved_blocked"' in ENGINE
    assert 'state["completed"] = {}' not in ENGINE
    assert 'state["blocked"] = {}' not in ENGINE


def test_v360_worker_rejection_and_handoff_never_write_retry():
    assert "def _v360_return_members_to_pending" in ENGINE
    assert 'state["retry"] = retry' in ENGINE
    assert "stabilizing[path]" in ENGINE
    assert "私有 worker 暂未接收；仅回 discovery pending" in ENGINE
    assert "已回 pending，不写 retry" in ENGINE
    scheduling = ENGINE[ENGINE.index("def _v360_schedule_resource"):ENGINE.index("# ------------------------------------------------------------------\n    # public scan/tick authority")]
    assert ".mark_deferred(" not in scheduling
    assert ".mark_failed(" not in scheduling


def test_v360_only_real_execution_failure_creates_retry():
    fallback = ENGINE[ENGINE.index("def _fallback_terminal_state"):ENGINE.index("# ------------------------------------------------------------------\n    # owner / runtime status")]
    assert "if not success:" in fallback
    assert "store.mark_failed(" in fallback
    success_half = fallback[fallback.index("if not success:") + len("if not success:"):]
    assert "v360_sync_success" in success_half
    assert "等待最终事件/历史" in success_half
    assert "不把等待证据写成失败" in success_half


def test_v360_weak_name_execution_uses_new_fallback_not_captured_old_completion():
    assert "if not isinstance(item, _FolderBatchEnvelope) or item.directory_mode:" in EXECUTION
    assert "self._fallback_terminal_state(member" in EXECUTION
    assert "TransferComplete/TransferFailed" in EXECUTION


def test_v360_status_overrides_legacy_sticky_and_cursor_projection():
    assert "def api_organize_monitor_status" in EXECUTION
    assert '"organizer_engine": "v3.6.0"' in EXECUTION
    assert '"scheduler_mode": "single_resource_worker"' in EXECUTION
    assert '"sticky_tv_group_path": ""' in EXECUTION
    assert '"sticky_tv_group_active": False' in EXECUTION
    assert "self._v360_load_cursor(root)" in EXECUTION


def test_v360_move_confirmation_does_not_compare_old_source_fileid_after_cross_dir_move():
    assert "compare_fileid=False" in MOVE
    assert "目标名+大小确认" in MOVE
    assert "self.move(fileitem, path, target_name)" in MOVE
    assert "compare_fileid=True" not in MOVE


def test_v360_keeps_moviepilot_business_rules_out_of_engine():
    for forbidden in (
        "target_directory",
        "rename_format",
        "get_rename_path",
        "category.yaml",
        "tmdbid=",
    ):
        assert forbidden not in ENGINE, forbidden


def test_v360_release_metadata_is_consistent():
    plugin_meta = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    package_meta = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    assert plugin_meta["version"] == "3.6.0"
    assert package_meta["ShukGuangYaDisk"]["version"] == "3.6.0"
    assert 'plugin_version = "3.6.0"' in ENTRY
    assert '?v=3.6.0' in REMOTE
    assert "v3.6.0" in plugin_meta["history"]


def test_v360_startup_log_exposes_new_state_machine():
    assert "统一整理引擎已启用" in ENGINE
    assert "50目录 discovery → 单资源 scheduler → 私有 worker → MoviePilot 最终证据" in ENGINE
