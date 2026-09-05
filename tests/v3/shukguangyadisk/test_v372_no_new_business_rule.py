import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"


def test_v372_is_architecture_only_release():
    text = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))["history"]["v3.7.2"]
    assert "文件处置规则完全继承 v3.7.0" in text
