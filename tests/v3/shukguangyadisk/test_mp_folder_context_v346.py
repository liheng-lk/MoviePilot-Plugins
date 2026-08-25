from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
CONTEXT = (PLUGIN / "organizer_mp_folder_context_v346.py").read_text(encoding="utf-8")
FILTER = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")


def test_resource_folder_uses_moviepilot_path_recognition_then_directory_transfer():
    for token in (
        "MediaChain().recognize_by_path",
        'type="dir"',
        "TransferChain()",
        "transfer_chain.do_transfer(**kwargs)",
        '"background": False',
        '"manual": False',
        "识别/分类/命名/目标路径全部由 MoviePilot 执行",
    ):
        assert token in CONTEXT, token


def test_plugin_does_not_extract_or_force_media_identity():
    for forbidden in (
        "_release_parent_title",
        "tmdb_id=",
        "media_id=",
        "hk_title",
        "tw_title",
        "overlap >=",
    ):
        assert forbidden not in CONTEXT, forbidden


def test_episode_structure_is_decided_by_moviepilot_recommender_for_all_resource_folders():
    for token in (
        "recommend_episode_format",
        "EpisodeFormat(format=episode_format)",
        "对所有资源目录都让 MoviePilot 自己判断是否需要集数定位模板",
        "MoviePilot 检测到剧集集数模板",
    ):
        assert token in CONTEXT, token
    assert "if not item.directory_mode" not in CONTEXT


def test_numeric_episode_folder_rechecks_directory_as_tv_without_hard_media_id():
    for token in (
        "MediaType.TV",
        "MediaChain().recognize_by_meta",
        "mtype=MediaType.TV",
        "集数结构已确认，MoviePilot 按电视剧重新识别",
        "已检测到集数结构，但电视剧识别未确认，暂缓整理",
        "01.mp4",
    ):
        assert token in CONTEXT, token


def test_monitor_root_is_not_recursively_submitted_as_one_directory():
    assert "_is_monitor_root_folder_task" in CONTEXT
    assert "return previous_execute(self, item)" in CONTEXT


def test_v344_safe_recognition_stays_removed_and_context_patch_remains_installed():
    assert "install_safe_recognition_v344" not in FILTER
    assert "install_mp_folder_context_v346" in FILTER
    assert "install_mp_folder_context_v346()" in FILTER
    assert "install_network_resilience_v347" in FILTER
