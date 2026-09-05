from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"


def test_v372_release_metadata_is_preserved_as_floor():
    init_text = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
    plugin = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    remote = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")
    match = re.search(r'plugin_version = "(\d+)\.(\d+)\.(\d+)"', init_text)
    assert match and tuple(map(int, match.groups())) >= (3, 7, 2)
    assert tuple(map(int, plugin["version"].split("."))) >= (3, 7, 2)
    assert tuple(map(int, package["ShukGuangYaDisk"]["version"].split("."))) >= (3, 7, 2)
    assert f'?v={plugin["version"]}' in remote
    assert "v3.7.2" in plugin["history"]
    assert plugin["history"]["v3.7.2"] == package["ShukGuangYaDisk"]["history"]["v3.7.2"]


def test_v372_release_removes_two_more_runtime_installers_without_new_media_policy():
    candidate = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")
    loss = (PLUGIN / "organizer_loss_guard_v349.py").read_text(encoding="utf-8")
    empty = (PLUGIN / "organizer_empty_folder_guard_v3410.py").read_text(encoding="utf-8")
    execution = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")
    for token in ("install_loss_guard_v349", "install_empty_folder_guard_v3410"):
        assert token not in candidate
        assert token not in loss
        assert token not in empty
    match = re.search(r'"organizer_policy_version": "v(\d+)\.(\d+)\.(\d+)"', execution)
    assert match and tuple(map(int, match.groups())) >= (3, 7, 2)
    assert "_defer_unconfirmed_members(self, item, reason)" in execution
    assert "_guangya_empty_folder_skip_v3410" in execution
    policy = (PLUGIN / "organizer_policy.py").read_text(encoding="utf-8")
    for disposition in ("LEAVE_UNRECOGNIZED", "DELETE_DUPLICATE", "ORGANIZE_VERSION", "BLOCK_SAFETY", "RETIRE_MISSING"):
        assert disposition in policy


def test_v372_cross_plugin_market_entry_is_not_rolled_back():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    transfer = tuple(map(int, package["GuangYaTransferAssistant"]["version"].split(".")))
    assert transfer >= (1, 12, 14)
