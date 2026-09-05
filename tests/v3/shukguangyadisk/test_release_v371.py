from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
VERSION = "3.7.1"


def test_v371_release_metadata_is_exact_and_cross_plugin_safe():
    init_text = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
    plugin = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    remote = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")
    assert f'plugin_version = "{VERSION}"' in init_text
    assert plugin["version"] == VERSION
    assert package["ShukGuangYaDisk"]["version"] == VERSION
    assert f'?v={VERSION}' in remote
    assert f'v{VERSION}' in plugin["history"]
    assert f'v{VERSION}' in package["ShukGuangYaDisk"]["history"]
    assert package["GuangYaTransferAssistant"]["version"] == "1.12.14"


def test_v371_release_is_phase2_architecture_only():
    execution = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")
    candidate = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")
    for token in (
        "install_conflict_resolution_v353",
        "install_preview_partial_v355",
        "install_preview_retry_wakeup_v356",
    ):
        assert token not in candidate
    assert '"organizer_policy_version": "v3.7.1"' in execution
    assert "_execute_conflict_aware(self, item)" in execution
    assert "rescue_partial_preview_if_needed(self, item, result)" in execution
