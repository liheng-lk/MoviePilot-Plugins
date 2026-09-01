import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_package_and_plugin_metadata_retain_v180_native_offline_history():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    local = json.loads((ROOT / "plugins.v3" / "guangyatransferassistant" / "plugin.json").read_text(encoding="utf-8"))
    assert package["version"] == local["version"] == "1.9.1"
    assert "Magnet" in package["description"] and "ED2K" in package["description"]
    assert "原生云添加" in package["description"]
    assert "v1.8.0" in package["history"]
    assert "不经过 MoviePilot 下载器" in package["history"]["v1.8.0"]
    assert "v1.9.0" in package["history"]
    assert "ResourceGroup" in package["history"]["v1.9.0"]
    assert "v1.9.1" in package["history"]
    assert "紧凑" in package["history"]["v1.9.1"]
