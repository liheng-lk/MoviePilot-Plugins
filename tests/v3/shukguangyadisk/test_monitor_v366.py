from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
PATCH = (PLUGIN / "organizer_monitor_v366.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")


def test_v366_patch_is_valid_python_and_first_mro_authority():
    ast.parse(PATCH)
    assert "from .organizer_monitor_v366 import GuangYaOrganizerMonitorV366Mixin" in ENTRY
    class_start = ENTRY.index("class ShukGuangYaDisk(")
    patch_pos = ENTRY.index("GuangYaOrganizerMonitorV366Mixin,", class_start)
    pending_pos = ENTRY.index("GuangYaOrganizerPendingRevisitV361Mixin,", class_start)
    engine_pos = ENTRY.index("GuangYaOrganizerExecutionV360Mixin,", class_start)
    assert patch_pos < pending_pos < engine_pos


def test_v366_partial_ready_directory_cannot_use_native_directory_batch():
    assert "all_primary_ready = (" in PATCH
    assert "len(selected) == len(primary)" in PATCH
    assert 'int(phases.get("ready") or 0) == len(primary)' in PATCH
    assert "all_primary_ready\n                and _can_use_native_directory_batch" in PATCH
    assert '"v366_selected_member": True' in PATCH


def test_v366_real_interval_gates_heartbeat():
    tick = PATCH[PATCH.index("def organize_monitor_tick"):PATCH.index("def _v366_baseline_due")]
    assert "_organize_monitor_interval" in tick
    assert "now - last < interval" in tick
    assert "self._v360_last_tick = now" in tick
    assert "self.run_organize_monitor_scan(manual=False)" in tick


def test_v366_known_resource_signature_skips_unchanged_history():
    assert '_KNOWN_KEY = "organize_v366_known_resources"' in PATCH
    assert "def _v366_resource_signature" in PATCH
    assert "if old_signature and old_signature == signature:" in PATCH
    assert "continue" in PATCH[PATCH.index("if old_signature and old_signature == signature:"):]
    assert "_FULL_DISCOVERY_INTERVAL = 1800.0" in PATCH


def test_v366_empty_known_resource_is_removed_instead_of_scanned_forever():
    scan = PATCH[PATCH.index("def _v366_scan_known_resources"):PATCH.index("def run_organize_monitor_scan")]
    assert "if not primary:" in scan
    assert "rows.pop(group_path, None)" in scan
    assert "known_resource_removed" in scan


def test_v366_admission_conflict_is_blocked_not_normal_retry():
    fallback = PATCH[PATCH.index("def _fallback_terminal_state"):PATCH.index("def organize_monitor_tick")]
    assert "整理源文件已按不同输入准入" in PATCH
    assert "TransferAdmissionConflictError" in PATCH
    assert "store.mark_blocked(" in fallback
    assert "停止分钟级重复提交" in fallback
    assert "return super()._fallback_terminal_state" in fallback


def test_v366_pending_revisit_still_receives_waiting_results():
    finish = PATCH[PATCH.index("def _v366_finish_schedule"):PATCH.index("def _v360_schedule_resource")]
    assert "_v361_register_pending" in finish
    assert "_v361_remove_pending" in finish
    for phase in ("stabilizing", "history_wait", "retry_wait", "inflight"):
        assert phase in finish
