from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
INTEGRITY = (PLUGIN / "guangya_rename_integrity_v3414.py").read_text(encoding="utf-8")
DIAGNOSTICS = (PLUGIN / "organizer_rename_diagnostics_v3414.py").read_text(encoding="utf-8")
FILTER = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
REMOTE = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")


def test_storage_rename_is_not_success_until_remote_name_is_visible():
    for token in (
        "original_rename(self, fileitem, target_name)",
        "self._invalidate_path_cache(old_path)",
        "self._invalidate_path_cache(expected_path)",
        "_confirmed_named_item(",
        "远端重命名未确认，拒绝向 MoviePilot 返回成功",
        "return False",
    ):
        assert token in INTEGRITY, token


def test_moviepilot_receives_real_fileitem_for_same_cloud_move_and_copy():
    for token in (
        "def move_item(",
        "def copy_item(",
        "original_move(self, fileitem, path, new_name)",
        "original_copy(self, fileitem, path, new_name)",
        "GuangYaApi.move_item = move_item",
        "GuangYaApi.copy_item = copy_item",
        "只有真实目标 FileItem 可见才成功",
    ):
        assert token in INTEGRITY, token


def test_move_identity_uses_fileid_and_copy_uses_name_size_confirmation():
    assert "compare_fileid=True" in INTEGRITY
    assert "compare_fileid=False" in INTEGRITY
    assert "expected_id == actual_id" in INTEGRITY
    assert "int(expected_size) == int(actual_size)" in INTEGRITY


def test_rename_diagnostics_respects_moviepilot_directory_setting():
    for token in (
        "DirectoryHelper().get_dir(",
        "renaming = bool(getattr(directory, \"renaming\", False))",
        "智能重命名=开启",
        "智能重命名=关闭",
        "按 MP 当前规则本次会保留源文件名",
        "preview_unchanged_names",
    ):
        assert token in DIAGNOSTICS, token
    for forbidden in (
        "RENAME_FORMAT(",
        "get_rename_path(",
        'target_name = "花开锦绣',
        "self._guangya_api.move(",
    ):
        assert forbidden not in DIAGNOSTICS, forbidden


def test_v3414_patches_install_in_correct_order():
    assert "install_rename_integrity_v3414()" in FILTER
    assert "install_rename_diagnostics_v3414()" in FILTER
    assert FILTER.index("install_rename_integrity_v3414()") < FILTER.index("install_folder_batch_v342()")
    assert FILTER.index("install_folder_identity_v350()") < FILTER.index("install_rename_diagnostics_v3414()")


def test_v3414_integrity_remains_enabled_in_v350_release():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["ShukGuangYaDisk"]
    local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    assert package["version"] == "3.5.0"
    assert local["version"] == "3.5.0"
    assert 'plugin_version = "3.5.0"' in ENTRY
    assert "__federation_expose_AssistantPage-v330.js?v=3.5.0" in REMOTE
    assert package["history"]["v3.4.14"] == "增加远端重命名终态确认，修复整理成功但目标文件仍保留原名的问题。"
