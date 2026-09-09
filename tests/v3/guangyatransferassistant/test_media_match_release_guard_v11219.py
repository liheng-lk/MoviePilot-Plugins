import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
FAST = (PLUGIN / "fast_recall_v1126.py").read_text(encoding="utf-8")
MATCH = (PLUGIN / "media_match_v11219.py").read_text(encoding="utf-8")
PLUGIN_JSON = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
PACKAGE_JSON = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]


def test_media_match_slice_is_public_v11219_release():
    assert 'plugin_version = "1.12.23"' in ENTRY
    assert 'build_id = "20260909-r70"' in ENTRY
    assert PLUGIN_JSON["version"] == "1.12.23"
    assert PACKAGE_JSON["version"] == "1.12.23"
    assert "v1.12.19" in PACKAGE_JSON["history"]
    assert "GuangYaMediaMatchV11219Mixin" in FAST
    assert "requested_episodes" in MATCH
    assert "transfer_episodes" in MATCH


def test_v11219_description_keeps_v11218_fail_closed_safety_contract():
    local_desc = str(PLUGIN_JSON.get("description") or "")
    package_desc = str(PACKAGE_JSON.get("description") or "")
    assert local_desc == package_desc
    assert "get_item" in local_desc
    assert "fail-closed" in local_desc
    assert "taskId" in local_desc or "taskid" in local_desc.lower()
    assert "观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K" in local_desc

