import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"


def test_v372_is_current_release():
    plugin = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    assert plugin["version"] == "3.7.2"
