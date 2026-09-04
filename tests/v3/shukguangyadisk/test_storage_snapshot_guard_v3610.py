from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
PATCH = (PLUGIN / "storage_snapshot_guard_v3610.py").read_text(encoding="utf-8")
EXECUTION = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")
LEGACY_API = (PLUGIN / "guangya_api_legacy.py").read_text(encoding="utf-8")


def _between(text: str, start: str, end: str) -> str:
    a = text.index(start)
    b = text.index(end, a + len(start))
    return text[a:b]


def test_v3610_patch_is_valid_python():
    ast.parse(PATCH)
    ast.parse(EXECUTION)


def test_legacy_list_can_return_empty_after_remote_error_so_guard_is_required():
    block = _between(LEGACY_API, "def list(self", "def create_folder")
    assert 'if response.get("code", -1) != 0 and response.get("msg") != "success":' in block
    assert "break" in block
    assert "return results" in block


def test_v3610_snapshot_uses_list_strict_not_legacy_list():
    snapshot = _between(PATCH, "def snapshot_storage", "V3StorageContractMixin.snapshot_storage =")
    assert 'strict_list = getattr(api, "list_strict", None)' in snapshot
    assert "sub_files = list(strict_list(fileitem) or [])" in snapshot
    assert "api.list(" not in snapshot


def test_v3610_failed_directory_read_preserves_previous_subtree():
    snapshot = _between(PATCH, "def snapshot_storage", "V3StorageContractMixin.snapshot_storage =")
    strict_pos = snapshot.index("sub_files = list(strict_list(fileitem) or [])")
    except_pos = snapshot.index("except Exception as err", strict_pos)
    remove_pos = snapshot.index("remove_deleted_children(fileitem, sub_files)", except_pos)
    return_pos = snapshot.index("return", except_pos)
    assert strict_pos < except_pos < return_pos < remove_pos
    assert "保留上一轮子树" in snapshot


def test_v3610_only_successful_empty_list_can_remove_deleted_children():
    snapshot = _between(PATCH, "def snapshot_storage", "V3StorageContractMixin.snapshot_storage =")
    strict_pos = snapshot.index("sub_files = list(strict_list(fileitem) or [])")
    remove_pos = snapshot.index("remove_deleted_children(fileitem, sub_files)")
    assert strict_pos < remove_pos
    assert "只有上面的严格读取成功后，空列表才具有“真实空目录”语义" in snapshot


def test_v3610_root_network_failure_returns_previous_snapshot_not_empty():
    snapshot = _between(PATCH, "def snapshot_storage", "V3StorageContractMixin.snapshot_storage =")
    root_pos = snapshot.index("root_item = api.get_item(Path(path))")
    except_pos = snapshot.index("except Exception as err", root_pos)
    keep_pos = snapshot.index("return files_info", except_pos)
    missing_pos = snapshot.index("if not root_item:", keep_pos)
    empty_pos = snapshot.index("return {}", missing_pos)
    assert root_pos < except_pos < keep_pos < missing_pos < empty_pos
    assert "根路径读取失败，本轮保留上一快照" in snapshot
    assert "根路径已明确不存在，返回空快照" in snapshot


def test_v3610_is_installed_after_v369_strict_path_capability():
    import_path = EXECUTION.index("from .guangya_path_resolution_v369 import install_path_resolution_v369")
    import_snapshot = EXECUTION.index("from .storage_snapshot_guard_v3610 import install_storage_snapshot_guard_v3610")
    install_path = EXECUTION.index("install_path_resolution_v369()")
    install_snapshot = EXECUTION.index("install_storage_snapshot_guard_v3610()")
    class_pos = EXECUTION.index("class GuangYaOrganizerExecutionV360Mixin")
    assert import_path < import_snapshot < install_path < install_snapshot < class_pos
    assert '"runtime_hardening": "v3.6.10"' in EXECUTION


def test_v3610_does_not_change_media_or_destructive_operations():
    for forbidden in (
        "target_directory",
        "rename_format",
        "category.yaml",
        "MediaType.TV",
        "MediaType.MOVIE",
        "delete_file",
        ".delete(",
        "move_item",
        "purge",
        "overwrite",
    ):
        assert forbidden not in PATCH, forbidden
