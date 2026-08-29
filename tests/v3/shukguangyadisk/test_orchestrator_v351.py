from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
ORCH = (PLUGIN / "organizer_orchestrator_v351.py").read_text(encoding="utf-8")
FILTER = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
REMOTE = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")


def test_generic_container_is_single_file_even_when_only_one_video_remains():
    for token in (
        "泛化目录判断必须早于 len(media) 和 configured_type",
        "if normalized_group == normalized_root:",
        "if name in _generic_container_names(plugin):",
        "return True",
        "纪录片",
        "华语电影",
    ):
        assert token in ORCH, token
    assert ORCH.index("if name in _generic_container_names(plugin):") < ORCH.index(
        "if _single._has_episode_structure(plugin, group_path, files):"
    )


def test_sidecar_only_directory_cannot_trigger_moviepilot_video_organize():
    for token in (
        "_primary_media_files",
        "RMT_MEDIAEXT",
        "主视频门禁",
        "跳过无视频目录，不触发 MoviePilot 影视识别",
        "当前仅有字幕/音频等旁路文件",
        "if files and not _primary_media_files(files):",
    ):
        assert token in ORCH, token


def test_specific_title_folder_remains_folder_identity_source():
    for token in (
        "_is_specific_media_folder",
        "具体作品文件夹优先保护",
        "目录名正确但文件名错误",
    ):
        assert token in ORCH, token


def test_runtime_status_and_moviepilot_history_are_projected():
    for token in (
        '"runtime_phase"',
        '"current_task_path"',
        '"completed_total"',
        '"mp_history_confirmed_total"',
        '"transfer_history_id"',
        "真实整理已落库",
        "last_counted_transfer_history_id",
    ):
        assert token in ORCH, token


def test_v351_installs_after_v350_single_flight():
    assert "install_orchestrator_v351()" in FILTER
    assert FILTER.index("install_single_flight_v350()") < FILTER.index("install_orchestrator_v351()")
    assert FILTER.index("install_single_flight_refill_v350()") < FILTER.index("install_orchestrator_v351()")


def test_v351_remains_enabled_in_current_release():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["ShukGuangYaDisk"]
    local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    current = package["version"]
    assert local["version"] == current
    assert f'plugin_version = "{current}"' in ENTRY
    assert f"__federation_expose_AssistantPage-v352.js?v={current}" in REMOTE
    assert package["history"]["v3.5.1"] == "修复电影容器整目录预览积压，并校正运行状态和 MoviePilot 整理历史确认。"
