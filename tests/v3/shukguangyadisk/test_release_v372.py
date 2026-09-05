from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
VERSION = "3.7.2"


def test_v372_release_metadata_is_exact():
    init_text = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
    plugin = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    remote = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")
    assert f'plugin_version = "{VERSION}"' in init_text
    assert plugin["version"] == VERSION
    assert package["ShukGuangYaDisk"]["version"] == VERSION
    assert f'?v={VERSION}' in remote
    assert f'v{VERSION}' in plugin["history"]
    assert plugin["history"][f'v{VERSION}'] == package["ShukGuangYaDisk"]["history"][f'v{VERSION}']


def test_v372_release_removes_two_more_runtime_installers_without_new_media_policy():
    candidate = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")
    loss = (PLUGIN / "organizer_loss_guard_v349.py").read_text(encoding="utf-8")
    empty = (PLUGIN / "organizer_empty_folder_guard_v3410.py").read_text(encoding="utf-8")
    execution = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")
    for token in ("install_loss_guard_v349", "install_empty_folder_guard_v3410"):
        assert token not in candidate
        assert token not in loss
        assert token not in empty
    assert '"organizer_policy_version": "v3.7.2"' in execution
    assert "_defer_unconfirmed_members(self, item, reason)" in execution
    assert "_guangya_empty_folder_skip_v3410" in execution
    policy = (PLUGIN / "organizer_policy.py").read_text(encoding="utf-8")
    for disposition in ("LEAVE_UNRECOGNIZED", "DELETE_DUPLICATE", "ORGANIZE_VERSION", "BLOCK_SAFETY", "RETIRE_MISSING"):
        assert disposition in policy


def test_v372_cross_plugin_market_entry_is_not_rolled_back():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    transfer = tuple(map(int, package["GuangYaTransferAssistant"]["version"].split(".")))
    assert transfer >= (1, 12, 14)
