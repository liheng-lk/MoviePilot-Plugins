from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
PATCH = (PLUGIN / "organizer_folder_batch_v342.py").read_text(encoding="utf-8")
FILTER = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
MANIFEST = (PLUGIN / "plugin.json").read_text(encoding="utf-8")


def test_normal_resource_folder_is_one_private_task():
    for token in (
        "class _FolderBatchEnvelope",
        "文件夹任务已进入私有 worker",
        "folder_queued",
        "folder_tasks",
        "不拆文件夹",
    ):
        assert token in PATCH, token


def test_standard_folder_is_submitted_to_moviepilot_as_directory():
    for token in (
        'type="dir"',
        "TransferChain().do_transfer(",
        "fileitem=directory_item",
        "background=False",
        "由 MoviePilot 一次规划整个目录",
    ):
        assert token in PATCH, token


def test_monitor_root_is_never_recursively_submitted_as_one_folder():
    assert "plugin._organize_monitor_path" in PATCH
    assert "return False" in PATCH
    assert "监控根散放文件不能把根目录交给 MP" in PATCH


def test_legacy_weak_episode_fallback_remains_available_for_monitor_root_files():
    for token in (
        "_WEAK_EPISODE_NAME",
        "父目录 + 数字集号",
        "弱命名兼容批量",
        "original_execute(self, member)",
    ):
        assert token in PATCH, token


def test_same_monitor_config_save_does_not_force_next_scan():
    for token in (
        "_install_save_without_forced_rescan",
        "old_tick",
        "self._organize_monitor_last_tick = old_tick",
        "config_save_forced_rescan=False",
    ):
        assert token in PATCH, token


def test_patch_is_installed_before_final_plugin_mro_is_assembled():
    assert "install_folder_batch_v342" in FILTER
    assert "install_folder_batch_v342()" in FILTER


def test_folder_batch_feature_remains_enabled_in_current_release():
    assert 'plugin_version = "3.4.8"' in ENTRY
    assert '"version": "3.4.8"' in MANIFEST
    assert '"v3.4.2"' in MANIFEST
