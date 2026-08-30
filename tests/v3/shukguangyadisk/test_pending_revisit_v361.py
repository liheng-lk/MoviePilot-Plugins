from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
PATCH = (PLUGIN / "organizer_pending_revisit_v361.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
REMOTE = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")


def test_v361_repairs_zero_first_seen_in_all_v360_pending_paths():
    assert "def _v361_repair_zero_first_seen" in PATCH
    assert 'row["first_seen"] = now' in PATCH
    assert "def _v360_return_members_to_pending" in PATCH
    assert "self._v361_repair_zero_first_seen(paths)" in PATCH
    assert "def _recover_isolated_inflight_once" in PATCH
    assert "self._v361_repair_zero_first_seen()" in PATCH
    assert "def _v360_reopen_completed" in PATCH
    assert "self._v361_repair_zero_first_seen([path])" in PATCH


def test_v361_pending_resource_queue_is_separate_from_retry_and_sticky():
    assert '_PENDING_KEY = "organize_v361_pending_resources"' in PATCH
    assert "_v361_register_pending" in PATCH
    assert "_v361_remove_pending" in PATCH
    assert "_v361_next_due" in PATCH
    assert ".mark_failed(" not in PATCH
    assert ".mark_deferred(" not in PATCH
    assert "sticky_tv_group" not in PATCH


def test_v361_waiting_resources_are_registered_and_due_resources_run_first():
    schedule_start = PATCH.index("def _v360_schedule_resource")
    due_start = PATCH.index("def _v361_next_due")
    run_start = PATCH.index("def run_organize_monitor_scan")
    assert schedule_start < due_start < run_start
    assert 'reason in {"member_wait", "resource_wait"}' in PATCH
    assert 'phases.get(name) for name in ("stabilizing", "history_wait", "retry_wait", "inflight")' in PATCH
    assert "priority = self._v361_try_due_resource()" in PATCH
    assert "if priority is not None:" in PATCH
    assert "return priority" in PATCH
    assert "return super().run_organize_monitor_scan(manual=manual)" in PATCH


def test_v361_priority_revisit_never_breaks_50_directory_scan_bound():
    assert "每次只回访 1 个目录，因此不会突破 50 目录上限" in PATCH
    assert "self._v360_list_directory(group_path)" in PATCH
    assert "while " not in PATCH[PATCH.index("def _v361_try_due_resource"):PATCH.index("def run_organize_monitor_scan")]


def test_v361_owner_and_worker_gate_still_precede_priority_revisit():
    run = PATCH[PATCH.index("def run_organize_monitor_scan"):]
    owner = run.index("owner_ok, snapshot = self._v360_owner_gate()")
    busy = run.index("if self._v360_worker_busy(snapshot):")
    revisit = run.index("priority = self._v361_try_due_resource()")
    assert owner < busy < revisit
    assert "旧 Worker 正在交接，本轮不扫描、不入队、不修改 retry" in run


def test_v361_is_first_mro_layer_before_v360_engine():
    class_start = ENTRY.index("class ShukGuangYaDisk(")
    v361 = ENTRY.index("GuangYaOrganizerPendingRevisitV361Mixin,", class_start)
    v360 = ENTRY.index("GuangYaOrganizerExecutionV360Mixin,", class_start)
    history = ENTRY.index("GuangYaFolderHistoryMixin,", class_start)
    assert v361 < v360 < history
    assert "from .organizer_pending_revisit_v361 import GuangYaOrganizerPendingRevisitV361Mixin" in ENTRY


def test_v361_does_not_reimplement_moviepilot_business_rules():
    for forbidden in (
        "target_directory",
        "rename_format",
        "get_rename_path",
        "category.yaml",
        "tmdbid=",
        "TransferChain",
    ):
        assert forbidden not in PATCH, forbidden


def test_v361_release_metadata_is_consistent():
    plugin_meta = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    package_meta = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    assert plugin_meta["version"] == "3.6.1"
    assert package_meta["ShukGuangYaDisk"]["version"] == "3.6.1"
    assert 'plugin_version = "3.6.1"' in ENTRY
    assert '?v=3.6.1' in REMOTE
    assert "v3.6.1" in plugin_meta["history"]


def test_v361_startup_and_runtime_logs_are_observable():
    assert "稳定资源优先回访已启用" in PATCH
    assert "【v3.6.1】【优先回访】" in PATCH
    assert "pending 到期即优先处理，不等待整库 cycle" in PATCH
