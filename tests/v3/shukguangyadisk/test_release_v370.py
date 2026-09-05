from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
VERSION = "3.7.0"


def test_v370_release_metadata_is_preserved_as_floor():
    import re

    init_text = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
    plugin = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    remote = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")

    match = re.search(r'plugin_version = "(\d+)\.(\d+)\.(\d+)"', init_text)
    assert match and tuple(map(int, match.groups())) >= (3, 7, 0)
    assert tuple(map(int, plugin["version"].split("."))) >= (3, 7, 0)
    assert tuple(map(int, package["ShukGuangYaDisk"]["version"].split("."))) >= (3, 7, 0)
    assert f'?v={plugin["version"]}' in remote
    assert "v3.7.0" in plugin["history"]
    assert "v3.7.0" in package["ShukGuangYaDisk"]["history"]
def test_v370_preserves_current_transfer_assistant_release():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    assert package["GuangYaTransferAssistant"]["version"] == "1.12.14"


def test_v370_status_exposes_policy_version_separately_from_legacy_hardening():
    import re

    execution = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")
    match = re.search(r'"organizer_policy_version": "v(\d+)\.(\d+)\.(\d+)"', execution)
    assert match, "organizer policy version missing"
    assert tuple(map(int, match.groups())) >= (3, 7, 0)
    assert '"runtime_hardening": "v3.6.20"' in execution

def test_v370_startup_banner_uses_current_policy_semantics_not_old_conflict_version():
    execution = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")
    conflict = (PLUGIN / "organizer_conflict_resolution_v353.py").read_text(encoding="utf-8")
    assert "policy 执行链已显式接管" in execution
    assert "【v3.5.3】电影重复目标与剧集局部冲突消歧已启用" not in conflict
    assert "install_conflict_resolution_v353" not in conflict
