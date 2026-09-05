import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"


def test_v372_preserves_v370_policy_history():
    plugin = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    assert "v3.7.0" in plugin["history"]
    assert "未识别原地保留" in plugin["history"]["v3.7.2"]
