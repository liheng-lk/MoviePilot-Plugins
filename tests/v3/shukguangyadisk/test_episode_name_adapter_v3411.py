from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
ADAPTER = (PLUGIN / "organizer_episode_name_adapter_v3411.py").read_text(encoding="utf-8")
FILTER = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
REMOTE = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")


def test_adapter_tries_moviepilot_with_full_scanned_member_list_first():
    for token in (
        "recommend_episode_format(",
        "fileitem=directory_item",
        "fileitems=members",
        "MoviePilot 使用整组文件生成集数模板",
    ):
        assert token in ADAPTER, token


def test_adapter_covers_common_episode_name_families():
    for token in (
        "_SXE_RANGE",
        "_EP_RANGE",
        "_CN_EP",
        "_CN_REVERSE",
        "_CN_SUFFIX",
        "_HASH_EP",
        "_BRACKET_EP",
        "_TILDE_EP",
        "_LEADING_EP",
        "_ONLY_EP",
        "_TRAILING_EP",
        "01 4K",
        "EP01",
        "第01集",
    ):
        assert token in ADAPTER, token


def test_weak_names_require_multiple_unique_samples_and_mp_parser_validation():
    for token in (
        "len(tokens) < 2",
        "weak_single_sample",
        "weak_duplicate_episode",
        "FormatParser(eformat=template)",
        "_validated_expectations",
        "parsed_start != token.start",
    ):
        assert token in ADAPTER, token


def test_preview_rechecks_final_moviepilot_episode_before_real_move():
    for token in (
        "_guangya_episode_expectations_v3411",
        "actual_episode != expected_episode",
        "集号二次校验失败",
        "MoviePilot解析为E",
    ):
        assert token in ADAPTER, token


def test_adapter_does_not_hardcode_media_identity_or_target_policy():
    for forbidden in (
        "tmdb_id=",
        "media_id=",
        "self._guangya_api.move",
        "self._guangya_api.copy",
        "DirectoryHelper().get_dir(",
        "get_rename_path(",
    ):
        assert forbidden not in ADAPTER, forbidden
    assert "_moviepilot_tv_context_from_directory_meta" in ADAPTER


def test_adapter_is_installed_after_loss_and_empty_folder_guards():
    assert "from .organizer_episode_name_adapter_v3411 import install_episode_name_adapter_v3411" in FILTER
    assert "install_episode_name_adapter_v3411()" in FILTER
    assert FILTER.index("install_loss_guard_v349()") < FILTER.index("install_episode_name_adapter_v3411()")
    assert FILTER.index("install_empty_folder_guard_v3410()") < FILTER.index("install_episode_name_adapter_v3411()")


def test_v3411_release_metadata_is_consistent():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["ShukGuangYaDisk"]
    local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    assert package["version"] == "3.4.11"
    assert local["version"] == "3.4.11"
    assert 'plugin_version = "3.4.11"' in ENTRY
    assert "__federation_expose_AssistantPage-v330.js?v=3.4.11" in REMOTE
    assert package["history"]["v3.4.11"] == "增加多形态集号适配和整组校验，支持 01 4K、EP01、第01集等弱命名。"
