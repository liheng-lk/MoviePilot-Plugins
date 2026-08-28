from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
DEEP = (PLUGIN / "organizer_deep_folder_stream_v3413.py").read_text(encoding="utf-8")
FILTER = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")


def test_nested_scan_groups_each_actual_file_directory_instead_of_first_level_container():
    for token in (
        "queue = deque([root])",
        "current = queue.popleft()",
        "direct_files: List[Any] = []",
        "child_dirs: List[Any] = []",
        "direct_files.append(child)",
        "yield current_path, direct_files",
        "queue.extend(child_dirs)",
        'scan_meta["grouping_mode"] = "deep_direct_files_streaming"',
    ):
        assert token in DEEP, token

    assert "group_files.append(child)" not in DEEP
    assert "root / relative.parts[0]" not in DEEP


def test_large_generic_container_streams_primary_video_before_inventory_cap():
    for token in (
        "_STREAMING_CONTAINER_NAMES",
        "_is_streaming_container",
        "_runtime_media_exts()",
        'scan_meta["streaming_discovery"] = True',
        "yield current_path, [child]",
        "不对同级全部主视频消耗 visited/inventory cap",
        "纪录片",
        "华语电影",
    ):
        assert token in DEEP, token


def test_sidecar_only_files_do_not_form_streaming_video_groups():
    assert "suffix in media_exts" in DEEP
    assert "primary_files.append(child)" in DEEP
    assert "yield current_path, [child]" in DEEP
    assert "RMT_AUDIOEXT" not in DEEP
    assert "RMT_SUBEXT" not in DEEP


def test_parent_and_child_folders_cannot_be_recursively_submitted_twice():
    for token in (
        "_direct_child_state",
        "has_child_dir",
        "为避免递归重复整理",
        "return False",
        "_folder_batch._can_use_native_directory_batch = can_use_native_directory_batch",
    ):
        assert token in DEEP, token


def test_deep_grouping_is_installed_before_network_resilience_wraps_iterator():
    assert "from .organizer_deep_folder_stream_v3413 import install_deep_folder_stream_v3413" in FILTER
    assert "install_deep_folder_stream_v3413()" in FILTER
    assert FILTER.index("install_mp_folder_context_v346()") < FILTER.index("install_deep_folder_stream_v3413()")
    assert FILTER.index("install_deep_folder_stream_v3413()") < FILTER.index("install_network_resilience_v347()")


def test_streaming_container_names_are_structural_only_not_business_classification():
    for forbidden in (
        "CategoryHelper",
        "RENAME_FORMAT",
        "get_rename_path",
        "tmdb_id=",
        "media_id=",
        "get_tv_category(",
        "get_movie_category(",
    ):
        assert forbidden not in DEEP, forbidden
