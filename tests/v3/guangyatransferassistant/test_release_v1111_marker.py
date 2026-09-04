from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"


def test_v1111_release_marker():
    entry = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    assert package["version"] == local["version"] == "1.12.4"
    assert 'plugin_version = "1.12.4"' in entry
    assert 'build_id = "20260904-r50"' in entry
    assert "v1.12.4" in package["history"]
    assert "v1.12.3" in package["history"]
    assert "v1.10.13" in package["history"]
    assert "v1.10.12" in package["history"]
    assert "v1.10.11" in package["history"]
