from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
FENCE = (PLUGIN / "xunlei_existing_fence_v11213.py").read_text(encoding="utf-8")
ALIAS = (PLUGIN / "gying_alias_query_v11212.py").read_text(encoding="utf-8")
LOCAL = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
PACKAGE = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]


def test_v11213_public_release_is_single_truth():
    assert LOCAL["version"] == PACKAGE["version"] == "1.12.13"
    assert 'plugin_version = "1.12.13"' in ENTRY
    assert 'build_id = "20260905-r59"' in ENTRY
    assert "v1.12.13" in PACKAGE["history"]


def test_v11213_hard_fence_is_nested_without_moving_top_level_mro():
    ast.parse(FENCE)
    assert 'plugin_version = "1.12.13"' in FENCE
    assert 'build_id = "20260905-r59"' in FENCE
    assert "GuangYaXunleiExistingEpisodeFenceV11213Mixin" not in ENTRY.split("class GuangYaTransferAssistant(", 1)[1].split("):", 1)[0]
    assert "from .xunlei_existing_fence_v11213 import GuangYaXunleiExistingEpisodeFenceV11213Mixin" in (PLUGIN / "manual_check_v11211.py").read_text(encoding="utf-8")


def test_v11213_keeps_v11212_alias_layer_historical_marker():
    assert 'plugin_version = "1.12.12"' in ALIAS
    assert 'build_id = "20260905-r58"' in ALIAS


def test_v11213_release_documents_fail_closed_and_final_import_filter():
    history = PACKAGE["history"]["v1.12.13"]
    assert "library missing" in history
    assert "logical/fact missing" in history
    assert "batch import" in history
    assert "fail closed" in history
    assert "E09-E11" in history


def test_v11213_source_priority_is_unchanged():
    text = LOCAL["description"] + PACKAGE["description"]
    assert "观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K" in text
