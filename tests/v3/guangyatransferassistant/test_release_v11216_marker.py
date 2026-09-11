from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
BRIDGE = (PLUGIN / "movie_bilingual_identity_v11216.py").read_text(encoding="utf-8")
PLUGIN_JSON = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
PACKAGE = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
CHANGELOG = (PLUGIN / "CHANGELOG.md").read_text(encoding="utf-8")


def test_v11217_public_release_truth_promotes_v11216_history():
    assert 'plugin_version = "2.0.13"' in ENTRY
    assert PLUGIN_JSON["version"] == "2.0.13"
    assert PACKAGE["GuangYaTransferAssistant"]["version"] == "2.0.13"
    assert "v1.12.17" in PACKAGE["GuangYaTransferAssistant"]["history"]


def test_v11216_release_keeps_strict_bilingual_bridge_not_fuzzy_identity():
    assert "同一分享双语闭环" in BRIDGE
    assert "实际资源顶层标题与订阅不一致" in BRIDGE
    lowered = BRIDGE.lower()
    assert "levenshtein" not in lowered
    assert "fuzzywuzzy" not in lowered
    assert "pinyin" not in lowered
    assert "downloadchain" not in lowered


def test_v11216_release_keeps_source_priority_and_previous_safety_history():
    # 当前运行合同留在 final entry；历史版本事实属于 package history / CHANGELOG，
    # 不再要求 __init__.py 充当 changelog。
    assert "观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K" in ENTRY
    history = PACKAGE["GuangYaTransferAssistant"]["history"]
    for version in ("v1.12.15", "v1.12.14", "v1.12.13", "v1.12.10"):
        assert version in history
        assert version in CHANGELOG

