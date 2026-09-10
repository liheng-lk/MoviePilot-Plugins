from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = PLUGIN / "__init__.py"
LOCAL = PLUGIN / "plugin.json"
PACKAGE = ROOT / "package.v3.json"
GUARD = PLUGIN / "empty_dir_guard_v11218.py"
RECALL = PLUGIN / "search_recall_v11217.py"
TEMP = ROOT / ".github/workflows/prepare-guangya-v11218.yml"


def test_final_v11218_release_truth_and_historical_recall_marker():
    entry = ENTRY.read_text(encoding="utf-8")
    local = json.loads(LOCAL.read_text(encoding="utf-8"))
    package = json.loads(PACKAGE.read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    recall = RECALL.read_text(encoding="utf-8")

    assert 'plugin_version = "2.0.4"' in entry
    assert 'build_id = "20260910-r84"' in entry
    assert local["version"] == "2.0.4"
    assert package["version"] == "2.0.4"
    assert "v1.12.18" in package.get("history", {})

    # v1.12.17 is a historical search/recall layer, not mechanically promoted.
    assert 'plugin_version = "1.12.17"' in recall
    assert 'build_id = "20260906-r64"' in recall


def test_final_v11218_tree_contains_guard_and_no_release_tooling():
    ast.parse(GUARD.read_text(encoding="utf-8"), filename=str(GUARD))
    assert GUARD.exists()
    assert not TEMP.exists()


def test_final_v11218_keeps_source_priority_and_native_cloudcollection():
    entry = ENTRY.read_text(encoding="utf-8")
    multi = (PLUGIN / "multisource_v180.py").read_text(encoding="utf-8")
    assert "观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K" in entry
    assert "/cloudcollection/v1/create_task" in multi
    lowered = GUARD.read_text(encoding="utf-8").lower()
    assert "qbittorrent" not in lowered
    assert "transmission" not in lowered


def test_final_v11218_release_history_documents_read_only_and_fail_closed_cleanup():
    package = json.loads(PACKAGE.read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    desc = str(package.get("description") or "")
    history = str(package.get("history", {}).get("v1.12.18") or "")
    assert "目录事实未知" in history
    assert "taskId" in history or "taskid" in history.lower()
    assert "get_item" in history
    assert "观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K" in desc

