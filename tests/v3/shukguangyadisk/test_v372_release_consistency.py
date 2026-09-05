import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"


def test_v372_release_surfaces_are_consistent():
    plugin = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    version = plugin["version"]
    assert version == "3.7.2"
    assert package["ShukGuangYaDisk"]["version"] == version
    assert f'plugin_version = "{version}"' in (PLUGIN / "__init__.py").read_text(encoding="utf-8")
    assert f"?v={version}" in (PLUGIN / "dist/assets/remoteEntry.js").read_text(encoding="utf-8")
