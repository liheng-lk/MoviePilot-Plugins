from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
INIT = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
STREAM = (PLUGIN / "organizer_folder_stream.py").read_text(encoding="utf-8")


def test_folder_stream_mixin_is_first_in_runtime_mro():
    assert "from .organizer_folder_stream import GuangYaFolderStreamMixin" in INIT
    class_block = INIT.split("class ShukGuangYaDisk(", 1)[1].split("):", 1)[0]
    assert class_block.index("GuangYaFolderStreamMixin") < class_block.index("GuangYaOrganizerMixin")


def test_scans_and_dispatches_by_monitor_root_direct_subfolder():
    for token in (
        "def _iter_folder_groups(",
        "def _process_folder_group(",
        "yield group_path, group_files",
        "yield normalized_root, root_files",
        "group_files.sort(key=self._file_sort_key)",
    ):
        assert token in STREAM, token
    assert "path.relative_to(root)" in STREAM
    assert "root / relative.parts[0]" in STREAM


def test_group_is_complete_before_it_is_submitted():
    scan_group = STREAM.index("yield group_path, group_files")
    group_complete_guard = STREAM.index("if not group_complete:")
    queue_creation = STREAM.index("queue = deque([group_dir])")
    assert queue_creation < group_complete_guard < scan_group
    assert "当前目录不提交，保留已有状态" in STREAM


def test_folder_queue_preserves_moviepilot_as_only_business_organizer():
    assert "accepted = self._dispatch_to_moviepilot(item)" in STREAM
    for forbidden in (
        "TransferChain()",
        "self._guangya_api.move(",
        "self._guangya_api.copy(",
        "TMDB",
        "target_dir",
    ):
        assert forbidden not in STREAM, forbidden


def test_folder_queue_has_backpressure_and_prioritizes_current_folder():
    assert 'existing_inflight = int(state.stats().get("inflight") or 0)' in STREAM
    assert '"remaining": max(self._organize_monitor_batch_size - existing_inflight, 0)' in STREAM
    assert 'if submit_budget["remaining"] <= 0:' in STREAM
    assert 'submit_budget["remaining"] -= 1' in STREAM
    # 扫描器逐组调用 _process_folder_group；预算耗尽后后续组仍扫描，但不会抢占提交槽位。
    group_loop = STREAM.index("for group_path, files in self._iter_folder_groups")
    process = STREAM.index("group_result = self._process_folder_group", group_loop)
    assert group_loop < process


def test_history_is_enriched_with_folder_and_batch_identity():
    for token in (
        '"group_path"',
        '"group_name"',
        '"batch_id"',
        'result": "folder_batch"',
        "目录批次：文件",
    ):
        assert token in STREAM, token
    assert "def _append_monitor_history" in STREAM


def test_inventory_reconciliation_only_happens_after_group_iteration_finishes():
    group_loop = STREAM.index("for group_path, files in self._iter_folder_groups")
    reconcile = STREAM.index("state.reconcile_inventory(")
    assert group_loop < reconcile
    exception_block = STREAM.split("except Exception as err", 1)[1]
    assert "故意不 reconcile_inventory" in exception_block
    assert "partial=True" in exception_block


def test_live_status_exposes_folder_stream_progress():
    for token in (
        'scan_mode=self._organize_scan_mode',
        'scan_in_progress=True',
        'current_group=group_path',
        'groups_discovered=scan_meta["groups_discovered"]',
        'groups_scanned=scan_meta["groups_scanned"]',
        'groups_queued=scan_meta["groups_queued"]',
        'queue_limit=self._organize_monitor_batch_size',
        'queue_slots=submit_budget["remaining"]',
    ):
        assert token in STREAM, token
