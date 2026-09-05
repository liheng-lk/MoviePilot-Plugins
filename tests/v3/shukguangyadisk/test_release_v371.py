from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
VERSION = "3.7.1"


def test_v371_release_metadata_is_preserved_as_floor_and_cross_plugin_safe():
    import re

    init_text = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
    plugin = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    remote = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")
    match = re.search(r'plugin_version = "(\d+)\.(\d+)\.(\d+)"', init_text)
    assert match and tuple(map(int, match.groups())) >= (3, 7, 1)
    assert tuple(map(int, plugin["version"].split("."))) >= (3, 7, 1)
    assert tuple(map(int, package["ShukGuangYaDisk"]["version"].split("."))) >= (3, 7, 1)
    assert f'?v={plugin["version"]}' in remote
    assert "v3.7.1" in plugin["history"]
    assert "v3.7.1" in package["ShukGuangYaDisk"]["history"]
    assert tuple(map(int, package["GuangYaTransferAssistant"]["version"].split("."))) >= (1, 12, 14)

def test_v371_release_is_phase2_architecture_floor():
    import re

    execution = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")
    candidate = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")
    for token in (
        "install_conflict_resolution_v353",
        "install_preview_partial_v355",
        "install_preview_retry_wakeup_v356",
    ):
        assert token not in candidate
    match = re.search(r'"organizer_policy_version": "v(\d+)\.(\d+)\.(\d+)"', execution)
    assert match and tuple(map(int, match.groups())) >= (3, 7, 1)
    assert "_execute_conflict_aware(self, item)" in execution
    assert "rescue_partial_preview_if_needed(self, item, result)" in execution
