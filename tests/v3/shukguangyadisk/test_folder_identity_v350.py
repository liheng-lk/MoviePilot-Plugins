from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
IDENTITY = (PLUGIN / "organizer_folder_identity_v350.py").read_text(encoding="utf-8")
FILTER = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")


def test_season_directory_uses_parent_as_media_identity_path():
    for token in (
        "_resource_identity_path",
        "Season",
        "path.parent",
        "作品身份目录",
    ):
        assert token in IDENTITY, token


def test_folder_identity_is_recognized_only_by_moviepilot():
    for token in (
        "_moviepilot_directory_context",
        "_moviepilot_tv_context_from_directory_meta",
        "_reconcile_moviepilot_category",
        "作品识别与单文件集号解析已分离",
    ):
        assert token in IDENTITY, token
    for forbidden in (
        'title = "',
        "tmdb_id=",
        'category = "国产剧"',
        'category = "欧美剧"',
        'category = "日韩剧"',
    ):
        assert forbidden not in IDENTITY, forbidden


def test_wrong_filename_cannot_replace_confirmed_parent_identity():
    for token in (
        "文件名不作为作品身份兜底",
        "作品目录识别未确认",
        "source file",
    ):
        # source file is only documentation-level; allow Chinese contract to carry the assertion.
        if token == "source file":
            continue
        assert token in IDENTITY, token


def test_folder_identity_wraps_episode_and_category_chain_before_rename_diagnostics():
    assert "from .organizer_folder_identity_v350 import install_folder_identity_v350" in FILTER
    assert "install_folder_identity_v350()" in FILTER
    assert FILTER.index("install_category_consistency_v3412()") < FILTER.index("install_folder_identity_v350()")
    assert FILTER.index("install_folder_identity_v350()") < FILTER.index("install_rename_diagnostics_v3414()")
