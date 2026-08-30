from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"


def test_current_release_is_v358_everywhere():
    plugin_meta = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    package_meta = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    entry = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
    remote = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")

    assert plugin_meta["version"] == "3.5.8"
    assert package_meta["ShukGuangYaDisk"]["version"] == "3.5.8"
    assert 'plugin_version = "3.5.8"' in entry
    assert '?v=3.5.8' in remote
