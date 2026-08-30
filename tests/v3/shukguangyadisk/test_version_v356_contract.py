from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"


def test_shukguangya_v356_version_is_consistent():
    init_text = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
    plugin = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    remote = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")

    assert 'plugin_version = "3.5.6"' in init_text
    assert plugin["version"] == "3.5.6"
    assert "v3.5.6" in plugin["history"]
    assert package["ShukGuangYaDisk"]["version"] == "3.5.6"
    assert "v3.5.6" in package["ShukGuangYaDisk"]["history"]
    assert "?v=3.5.6" in remote
