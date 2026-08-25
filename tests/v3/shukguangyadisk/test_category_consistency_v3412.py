from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
CATEGORY = (PLUGIN / "organizer_category_consistency_v3412.py").read_text(encoding="utf-8")
FILTER = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
REMOTE = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")


def test_category_reconciliation_uses_moviepilot_category_helper_only():
    for token in (
        "CategoryHelper",
        "get_tv_category",
        "get_movie_category",
        "tmdb_info",
        "deepcopy(media)",
        "corrected.category = expected",
        "origin_country",
        "original_language",
        "production_countries",
        "分类一致性",
    ):
        assert token in CATEGORY, token
    for forbidden in (
        'expected = "国产剧"',
        'expected = "欧美剧"',
        'expected = "日韩剧"',
        "DirectoryHelper().get_dir(",
        "self._guangya_api.move",
        "self._guangya_api.copy",
    ):
        assert forbidden not in CATEGORY, forbidden


def test_category_consistency_is_installed_after_episode_compatibility():
    assert "from .organizer_category_consistency_v3412 import install_category_consistency_v3412" in FILTER
    assert "install_category_consistency_v3412()" in FILTER
    assert FILTER.index("install_episode_name_adapter_v3411()") < FILTER.index("install_category_consistency_v3412()")
    assert FILTER.index("install_episode_sample_bridge_v3411()") < FILTER.index("install_category_consistency_v3412()")


def test_category_verification_fails_closed_when_moviepilot_rules_cannot_be_checked():
    for token in (
        "识别结果缺少 TMDB 原始详情，无法核对 MoviePilot 分类规则",
        "MoviePilot CategoryHelper 分类核验异常",
        "已阻止真实整理",
        "return transfer_chain, directory_item, kwargs, category_error",
    ):
        assert token in CATEGORY, token


def test_category_diagnostics_expose_moviepilot_facts():
    for token in (
        "MoviePilot 当前分类=%s",
        "origin_country=%s",
        "production_countries=%s",
        "original_language=%s",
        "识别上下文分类与 MoviePilot 当前 category.yaml 不一致",
    ):
        assert token in CATEGORY, token


def test_v3412_release_metadata_is_consistent():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["ShukGuangYaDisk"]
    local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    assert package["version"] == "3.4.12"
    assert local["version"] == "3.4.12"
    assert 'plugin_version = "3.4.12"' in ENTRY
    assert "__federation_expose_AssistantPage-v330.js?v=3.4.12" in REMOTE
    assert package["history"]["v3.4.12"] == "按 MoviePilot 当前 category.yaml 重新核验分类，修复缓存或外部识别源残留分类导致的错误目录。"
