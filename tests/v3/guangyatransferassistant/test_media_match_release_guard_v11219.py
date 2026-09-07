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
    assert 'plugin_version = "1.12.19"' in ENTRY
    assert 'build_id = "20260907-r66"' in ENTRY
    assert PLUGIN_JSON["version"] == "1.12.19"
    assert PACKAGE_JSON["version"] == "1.12.19"
    assert "v1.12.19" in PACKAGE_JSON["history"]
    assert "GuangYaMediaMatchV11219Mixin" in FAST
    assert "requested_episodes" in MATCH
    assert "transfer_episodes" in MATCH
