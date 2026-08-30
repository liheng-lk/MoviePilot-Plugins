from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"


def test_shukguangya_v356_history_and_current_version_are_consistent():
    init_text = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
    plugin = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    remote = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")

    current = str(package["ShukGuangYaDisk"]["version"])
    assert plugin["version"] == current
    assert f'plugin_version = "{current}"' in init_text
    assert f"?v={current}" in remote

    # 本文件继续保护 v3.5.6 的升级自愈发布历史，但不能把未来当前版本永久钉死在 3.5.6。
    assert "v3.5.6" in plugin["history"]
    assert "v3.5.6" in package["ShukGuangYaDisk"]["history"]
