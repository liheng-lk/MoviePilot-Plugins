from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
PATCH = (PLUGIN / "organizer_media_type_disambiguation_v363.py").read_text(encoding="utf-8")
FILTER = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
REMOTE = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")


def test_v363_is_installed_after_season_context_and_before_discovery_layer():
    assert "from .organizer_media_type_disambiguation_v363 import install_media_type_disambiguation_v363" in FILTER
    season = FILTER.index("install_season_context_v358()")
    disambiguation = FILTER.index("install_media_type_disambiguation_v363()")
    discovery = FILTER.index("install_paged_scan_handoff_v359(GuangYaCandidateFilterMixin)")
    assert season < disambiguation < discovery


def test_v363_only_rechecks_tv_single_video_without_episode_evidence():
    assert "not _is_tv_media(media)" in PATCH
    assert 'if kwargs.get("epformat")' in PATCH
    assert "members = list(_media_members(item))" in PATCH
    assert "if len(members) != 1:" in PATCH
    assert "if _episode_token(name):" in PATCH
    assert "identity = _resource_identity_path(plugin, current)" in PATCH
    assert "if identity != current:" in PATCH
    # season 仅由 TV 元数据推导时不能阻止电影复核；真正 Season/Sxx 或 SxxExx 已由上面的路径/文件证据挡住。
    eligible = PATCH[PATCH.index("def _eligible"):PATCH.index("def _plan_error_allows_movie_recheck")]
    assert 'kwargs.get("season")' not in eligible


def test_v363_movie_candidate_is_generated_only_by_moviepilot_movie_constraint():
    assert "MediaChain().recognize_by_meta(" in PATCH
    assert "mtype=MediaType.MOVIE" in PATCH
    assert "_moviepilot_directory_context(path)" in PATCH
    assert "MoviePilot 在电影类型下未识别到该目录" in PATCH
    assert "MoviePilot 电影约束识别结果类型不是电影" in PATCH


def test_v363_requires_title_match_and_non_conflicting_year():
    assert "tv_titles.isdisjoint(movie_titles)" in PATCH
    assert "电影候选与原电视剧候选标题不一致" in PATCH
    assert "tv_year != movie_year" in PATCH
    assert "年份冲突：TV=" in PATCH
    assert "unicodedata.normalize" in PATCH


def test_v363_only_overrides_tv_specific_season_plan_error():
    assert '_TV_SEASON_PLAN_ERROR = "电视剧季号上下文未确认"' in PATCH
    assert "def _plan_error_allows_movie_recheck" in PATCH
    assert "return _TV_SEASON_PLAN_ERROR in str(plan_error)" in PATCH
    assert "if not _plan_error_allows_movie_recheck(plan_error):" in PATCH


def test_v363_confirmed_movie_clears_tv_context_and_uses_moviepilot_media():
    assert 'current_kwargs.pop("epformat", None)' in PATCH
    assert 'current_kwargs.pop("season", None)' in PATCH
    assert 'current_kwargs["mediainfo"] = movie_media' in PATCH
    assert 'current_kwargs["mtype"] = MediaType.MOVIE' in PATCH
    assert '"from": "TV"' in PATCH
    assert '"to": "MOVIE"' in PATCH


def test_v363_does_not_introduce_second_naming_classification_or_target_policy():
    for forbidden in (
        "target_directory",
        "rename_format",
        "get_rename_path",
        "category.yaml",
        "tmdbid=",
        "target_path",
    ):
        assert forbidden not in PATCH, forbidden


def test_v363_runtime_logs_expose_attempt_reject_and_accept_states():
    assert "TV 已识别但无有效剧集结构" in PATCH
    assert "电影复核未确认，保留 MoviePilot 原 TV 结果" in PATCH
    assert "电影候选一致性未通过" in PATCH
    assert "本次按电影继续整理" in PATCH
    assert "TV→MOVIE 安全消歧已启用" in PATCH


def test_v363_release_metadata_is_consistent():
    plugin_meta = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    package_meta = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    assert plugin_meta["version"] == "3.6.3"
    assert package_meta["ShukGuangYaDisk"]["version"] == "3.6.3"
    assert 'plugin_version = "3.6.3"' in ENTRY
    assert '?v=3.6.3' in REMOTE
    assert "v3.6.3" in plugin_meta["history"]
