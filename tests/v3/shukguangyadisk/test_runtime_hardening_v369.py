from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
PATH_PATCH = (PLUGIN / "guangya_path_resolution_v369.py").read_text(encoding="utf-8")
MONITOR_PATCH = (PLUGIN / "organizer_hardening_v369.py").read_text(encoding="utf-8")
EXECUTION = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")


def test_v369_modules_are_valid_python():
    ast.parse(PATH_PATCH)
    ast.parse(MONITOR_PATCH)
    ast.parse(EXECUTION)


def test_v369_path_resolution_paginates_every_parent_segment():
    block = PATH_PATCH[PATH_PATCH.index("def _path_to_id"):PATH_PATCH.index("def list_strict")]
    assert "page = 0" in block
    assert "while True:" in block
    assert "page=page" in block
    assert "page += 1" in block
    assert "_page_has_more" in block
    assert "FileNotFoundError" in block
    # API读取失败与真实不存在必须是两种语义。
    assert "raise RuntimeError(" in block


def test_v369_path_resolution_can_find_items_beyond_first_100_children():
    assert "accumulated += len(items)" in PATH_PATCH
    assert 'str(item.get("fileName") or "") == part' in PATH_PATCH
    assert "if found is not None:" in PATH_PATCH
    assert "return accumulated < total" in PATH_PATCH
    assert "return page_items >= page_size" in PATH_PATCH


def test_v369_guangya_cache_is_instance_scoped_not_shared_across_hot_reload():
    init = PATH_PATCH[PATH_PATCH.index("def __init__(self: GuangYaApi"):PATH_PATCH.index("def _path_to_id")]
    assert "previous_init(self, *args, **kwargs)" in init
    assert "self._id_cache = {}" in init
    assert "self._item_cache = {}" in init
    assert "类属性" in PATH_PATCH


def test_v369_strict_list_never_turns_upstream_error_into_empty_directory():
    block = PATH_PATCH[PATH_PATCH.index("def list_strict"):PATH_PATCH.index("def get_item")]
    assert "if not _response_success(response):" in block
    assert "raise RuntimeError(" in block
    assert "page += 1" in block
    assert "return results" in block


def test_v369_get_item_reuses_path_resolution_cache_and_has_explicit_refresh():
    block = PATH_PATCH[PATH_PATCH.index("def get_item"):PATH_PATCH.index("def refresh_item")]
    assert "self._path_to_id(normalized)" in block
    assert "resolved = self._restore_cached_item(normalized)" in block
    assert "return resolved" in block
    refresh = PATH_PATCH[PATH_PATCH.index("def refresh_item"):PATH_PATCH.index("GuangYaApi.__init__")]
    assert "self._invalidate_path_cache(normalized)" in refresh


def test_v369_known_resource_remote_budget_is_bounded():
    assert "_KNOWN_SCAN_BUDGET = 24" in MONITOR_PATCH
    assert "_v366._KNOWN_SCAN_LIMIT = min(" in MONITOR_PATCH
    assert "_KNOWN_SCAN_BUDGET" in MONITOR_PATCH


def test_v369_unchanged_known_scan_still_advances_new_resource_discovery():
    block = MONITOR_PATCH[MONITOR_PATCH.index("def run_monitor_scan"):MONITOR_PATCH.index("GuangYaOrganizerEngineV360Mixin._v360_list_directory")]
    assert "result = previous_monitor_scan(plugin, manual=manual)" in block
    assert 'if not data.get("known_scan"):' in block
    assert "GuangYaOrganizerEngineV360Mixin.run_organize_monitor_scan(plugin, manual=False)" in block
    assert 'discovery_data["continuous_discovery"] = True' in block
    # 连续 discovery 完成一个 cycle 后刷新 baseline 时间，不能再等待固定30分钟。
    assert 'if discovery_data.get("cycle_complete"):' in block
    assert "_v366_mark_baseline_complete" in block


def test_v369_directory_read_refreshes_stale_fileid_once_but_propagates_real_failure():
    block = MONITOR_PATCH[MONITOR_PATCH.index("def list_directory"):MONITOR_PATCH.index("def run_monitor_scan")]
    assert 'strict_list = getattr(api, "list_strict", None)' in block
    assert 'refresher = getattr(api, "refresh_item", None)' in block
    assert "refresher(Path(path))" in block
    assert "严格读取目录失败，已刷新 fileId 仍不可用" in block
    assert "raise RuntimeError(" in block


def test_v369_state_cleanup_is_direct_directory_only_and_requires_successful_listing():
    helper = MONITOR_PATCH[MONITOR_PATCH.index("def _reconcile_direct_state"):MONITOR_PATCH.index("def _split_children")]
    assert "_direct_parent(plugin, path) != group" in helper
    assert "if path in present:" in helper
    assert "mapping.pop(raw_path, None)" in helper
    assert "_v360_is_under" not in helper
    # 成功 strict_list 后才对 files 做局部回收；失败分支不会以 [] 继续执行。
    listing = MONITOR_PATCH[MONITOR_PATCH.index("def list_directory"):MONITOR_PATCH.index("def run_monitor_scan")]
    assert "dirs, files = _split_children(plugin, children)" in listing
    assert "pruned = _reconcile_direct_state(plugin, path, files)" in listing


def test_v369_network_unavailable_defers_continuous_discovery_without_state_loss():
    block = MONITOR_PATCH[MONITOR_PATCH.index("def run_monitor_scan"):MONITOR_PATCH.index("GuangYaOrganizerEngineV360Mixin._v360_list_directory")]
    assert "network = _network_status(plugin)" in block
    assert "if not network.get(\"available\", True):" in block
    assert '"network_deferred": True' in block
    assert "保留状态" in block


def test_v369_wiring_applies_path_patch_before_runtime_operations_and_monitor_patch_lazily():
    assert "from .guangya_path_resolution_v369 import install_path_resolution_v369" in EXECUTION
    import_pos = EXECUTION.index("from .guangya_path_resolution_v369 import install_path_resolution_v369")
    install_pos = EXECUTION.index("install_path_resolution_v369()")
    class_pos = EXECUTION.index("class GuangYaOrganizerExecutionV360Mixin")
    assert import_pos < install_pos < class_pos
    init = EXECUTION[EXECUTION.index("def init_organizer_monitor"):EXECUTION.index("def _execute_isolated_transfer")]
    assert "from .organizer_hardening_v369 import install_organizer_hardening_v369" in init
    assert "install_organizer_hardening_v369()" in init
    assert init.index("install_organizer_hardening_v369()") < init.index("install_move_confirmation_v360()")


def test_v369_does_not_add_a_second_moviepilot_media_policy():
    combined = PATH_PATCH + "\n" + MONITOR_PATCH
    for forbidden in (
        "target_directory",
        "rename_format",
        "category.yaml",
        "tmdbid=",
        "recognize_by_meta",
        "MediaType.TV",
        "MediaType.MOVIE",
        "overwrite",
        "scrape",
    ):
        assert forbidden not in combined, forbidden
