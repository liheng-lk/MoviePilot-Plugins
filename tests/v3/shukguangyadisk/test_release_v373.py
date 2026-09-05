from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
VERSION = "3.7.3"


def test_v373_release_metadata_is_exact_and_cross_plugin_safe():
    init_text = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
    plugin = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    remote = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")
    execution = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")
    assert f'plugin_version = "{VERSION}"' in init_text
    assert plugin["version"] == VERSION
    assert package["ShukGuangYaDisk"]["version"] == VERSION
    assert f'?v={VERSION}' in remote
    assert f'v{VERSION}' in plugin["history"]
    assert plugin["history"][f'v{VERSION}'] == package["ShukGuangYaDisk"]["history"][f'v{VERSION}']
    assert '"organizer_policy_version": "v3.7.3"' in execution
    assert tuple(map(int, package["GuangYaTransferAssistant"]["version"].split("."))) >= (1, 12, 14)


def test_v373_release_removes_three_recognition_preview_installers_and_bridge_module():
    candidate = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")
    episode = (PLUGIN / "organizer_episode_name_adapter_v3411.py").read_text(encoding="utf-8")
    category = (PLUGIN / "organizer_category_consistency_v3412.py").read_text(encoding="utf-8")
    loss = (PLUGIN / "organizer_loss_guard_v349.py").read_text(encoding="utf-8")
    for token in (
        "install_episode_name_adapter_v3411",
        "install_episode_sample_bridge_v3411",
        "install_category_consistency_v3412",
    ):
        assert token not in candidate
    assert not (PLUGIN / "organizer_episode_sample_bridge_v3411.py").exists()
    assert "_build_moviepilot_kwargs =" not in episode
    assert "_audit_preview =" not in episode
    assert "_build_moviepilot_kwargs =" not in category
    assert "apply_episode_name_adapter(" in loss
    assert "apply_category_consistency(" in loss
    assert "audit_episode_expectations(" in loss


def test_v373_release_keeps_one_disposition_policy_and_moviepilot_authority():
    policy = (PLUGIN / "organizer_policy.py").read_text(encoding="utf-8")
    episode = (PLUGIN / "organizer_episode_name_adapter_v3411.py").read_text(encoding="utf-8")
    category = (PLUGIN / "organizer_category_consistency_v3412.py").read_text(encoding="utf-8")
    assert "recommend_episode_format(" in episode
    assert "FormatParser(eformat=template)" in episode
    assert "CategoryHelper" in category
    for disposition in ("LEAVE_UNRECOGNIZED", "DELETE_DUPLICATE", "ORGANIZE_VERSION", "BLOCK_SAFETY", "RETIRE_MISSING"):
        assert disposition in policy
    for source in (episode, category):
        for forbidden in ("tmdb_id=", "media_id=", "DirectoryHelper().get_dir(", "self._guangya_api.move", "self._guangya_api.copy"):
            assert forbidden not in source
