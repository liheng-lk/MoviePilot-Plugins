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


def test_plugin_does_not_extract_or_force_media_identity_in_v346():
    for forbidden in (
        "_release_parent_title",
        "recognize_by_meta",
        "tmdb_id=",
        "media_id=",
        "hk_title",
        "tw_title",
        "overlap >=",
    ):
        assert forbidden not in CONTEXT, forbidden


def test_weak_episode_folder_uses_moviepilot_native_episode_format_recommender():
    assert "recommend_episode_format" in CONTEXT
    assert "EpisodeFormat(format=episode_format)" in CONTEXT
    assert "不在插件里维护正则规则" in CONTEXT


def test_monitor_root_is_not_recursively_submitted_as_one_directory():
    assert "_is_monitor_root_folder_task" in CONTEXT
    assert "return previous_execute(self, item)" in CONTEXT


def test_v344_safe_recognition_stays_removed_and_v346_context_remains_installed():
    assert "install_safe_recognition_v344" not in FILTER
    assert "install_mp_folder_context_v346" in FILTER
    assert "install_mp_folder_context_v346()" in FILTER
    assert "install_network_resilience_v347" in FILTER
