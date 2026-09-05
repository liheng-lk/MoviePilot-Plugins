from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
BRIDGE = (PLUGIN / "movie_bilingual_identity_v11216.py").read_text(encoding="utf-8")
PLUGIN_JSON = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
PACKAGE = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))


def test_v11216_public_release_truth_is_consistent():
    assert 'plugin_version = "1.12.16"' in ENTRY
    assert 'build_id = "20260906-r63"' in ENTRY
    assert PLUGIN_JSON["version"] == "1.12.16"
    assert PACKAGE["GuangYaTransferAssistant"]["version"] == "1.12.16"
    assert "v1.12.16" in PACKAGE["GuangYaTransferAssistant"]["history"]


def test_v11216_release_keeps_strict_bilingual_bridge_not_fuzzy_identity():
    assert "同一分享双语闭环" in BRIDGE
    assert "实际资源顶层标题与订阅不一致" in BRIDGE
    lowered = BRIDGE.lower()
    assert "levenshtein" not in lowered
    assert "fuzzywuzzy" not in lowered
    assert "pinyin" not in lowered
    assert "downloadchain" not in lowered


def test_v11216_release_keeps_source_priority_and_previous_safety_layers():
    assert "观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K" in ENTRY
    assert "v1.12.15" in ENTRY
    assert "v1.12.14" in ENTRY
    assert "v1.12.13" in ENTRY
    assert "v1.12.10" in ENTRY
