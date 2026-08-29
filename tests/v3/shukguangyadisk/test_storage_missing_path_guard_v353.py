from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
PATCH = (PLUGIN / "storage_missing_path_guard_v353.py").read_text(encoding="utf-8")
FILTER = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")


def test_any_files_missing_path_is_false_not_dispatcher_exception():
    assert "except FileNotFoundError:" in PATCH
    assert "return False" in PATCH
    assert "any_files 检查时目录已不存在，按无文件处理" in PATCH
    assert "original_any_files(self, fileitem, extensions)" in PATCH


def test_list_files_missing_path_is_empty_but_write_operations_are_not_swallowed():
    assert "return []" in PATCH
    assert "list_files 检查时目录已不存在，按空目录处理" in PATCH
    for forbidden in (
        "original_delete",
        "original_move",
        "original_copy",
        "original_rename",
        "except Exception:",
    ):
        assert forbidden not in PATCH


def test_missing_path_guard_installs_at_storage_boundary_before_organizer_patches():
    assert "from .storage_missing_path_guard_v353 import install_storage_missing_path_guard_v353" in FILTER
    assert "install_storage_missing_path_guard_v353()" in FILTER
    assert FILTER.index("install_rename_integrity_v3414()") < FILTER.index("install_storage_missing_path_guard_v353()")
    assert FILTER.index("install_storage_missing_path_guard_v353()") < FILTER.index("install_folder_batch_v342()")
