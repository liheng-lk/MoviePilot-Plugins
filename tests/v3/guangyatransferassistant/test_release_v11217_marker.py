from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
RECALL = (PLUGIN / "search_recall_v11217.py").read_text(encoding="utf-8")
BRIDGE = (PLUGIN / "movie_bilingual_identity_v11216.py").read_text(encoding="utf-8")
PLUGIN_JSON = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
PACKAGE = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))


def test_v11217_public_release_truth_is_consistent():
    assert 'plugin_version = "2.0.9"' in ENTRY
    assert PLUGIN_JSON["version"] == "2.0.9"
    assert PACKAGE["GuangYaTransferAssistant"]["version"] == "2.0.9"
    assert "v1.12.17" in PACKAGE["GuangYaTransferAssistant"]["history"]
    assert "v1.12.16" in PACKAGE["GuangYaTransferAssistant"]["history"]


def test_v11217_recall_is_nested_without_replacing_v11216_final_identity_bridge():
    assert "from .search_recall_v11217 import GuangYaSearchRecallV11217Mixin" in BRIDGE
    assert "class GuangYaMovieBilingualIdentityV11216Mixin(GuangYaSearchRecallV11217Mixin):" in BRIDGE
    assert 'plugin_version = "1.12.16"' in BRIDGE
    assert 'build_id = "20260906-r63"' in BRIDGE


def test_v11217_is_wide_recall_strict_write_and_passive_tick_safe():
    assert "_release_title_candidates_v11217" in RECALL
    assert "_same_work_disambiguation_v11217" in RECALL
    assert "recognize_by_meta" in RECALL
    assert "_targeted_channel_search_v11217" in RECALL
    assert "channel_event" in RECALL
    assert "channel_cursors" in RECALL
    assert "DownloadChain" not in RECALL
    assert "cloudcollection/v1/create_task" not in RECALL
    assert "rapid_transfer" not in RECALL
    assert "观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K" in ENTRY

