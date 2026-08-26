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
        'scan_meta["grouping_mode"] = "deep_direct_files"',
    ):
        assert token in DEEP, token

    # 旧实现会在第一层目录里递归收集 group_files，导致 /剧/国产剧/片名/Season 1 被合成 /剧 一个任务。
    assert "group_files.append(child)" not in DEEP
    assert "root / relative.parts[0]" not in DEEP


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


def test_fix_does_not_create_media_classification_or_naming_rules():
    for forbidden in (
        "CategoryHelper",
        "RENAME_FORMAT",
        "get_rename_path",
        "tmdb_id",
        "media_id",
        '"国产剧"',
        '"日韩剧"',
        '"欧美剧"',
    ):
        assert forbidden not in DEEP, forbidden
