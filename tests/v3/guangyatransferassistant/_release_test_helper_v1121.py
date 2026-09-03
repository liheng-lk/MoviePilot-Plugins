from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
CURRENT_VERSION = "1.12.1"
CURRENT_BUILD = "20260903-r46"


def assert_current_release(entry_text: str) -> None:
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    assert package["version"] == local["version"] == CURRENT_VERSION
    assert f'plugin_version = "{CURRENT_VERSION}"' in entry_text
    assert f'build_id = "{CURRENT_BUILD}"' in entry_text
