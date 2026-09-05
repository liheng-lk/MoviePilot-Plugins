from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
VERSION = "3.7.0"


def test_v370_release_metadata_is_consistent():
    init_text = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
    plugin = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    remote = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")

    assert f'plugin_version = "{VERSION}"' in init_text
    assert plugin["version"] == VERSION
    assert package["ShukGuangYaDisk"]["version"] == VERSION
    assert f"?v={VERSION}" in remote
    assert f"v{VERSION}" in plugin["history"]
    assert f"v{VERSION}" in package["ShukGuangYaDisk"]["history"]


def test_v370_preserves_current_transfer_assistant_release():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    assert package["GuangYaTransferAssistant"]["version"] == "1.12.14"


def test_v370_status_exposes_policy_version_separately_from_legacy_hardening():
    execution = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")
    assert '"organizer_policy_version": "v3.7.0"' in execution
    assert '"runtime_hardening": "v3.6.20"' in execution


def test_v370_startup_banner_uses_current_policy_semantics_not_old_conflict_version():
    conflict = (PLUGIN / "organizer_conflict_resolution_v353.py").read_text(encoding="utf-8")
    assert "【整理策略 v3.7.0】统一文件处置已启用" in conflict
    assert "未识别原地保留；同大小精准去重；不同大小多版本；未知事实安全阻断" in conflict
    assert "【v3.5.3】电影重复目标与剧集局部冲突消歧已启用" not in conflict
