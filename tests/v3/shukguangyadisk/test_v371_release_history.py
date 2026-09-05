import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_v371_history_exists_in_plugin_and_market():
    plugin = json.loads((ROOT / "plugins.v3/shukguangyadisk/plugin.json").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    assert "v3.7.1" in plugin["history"]
    assert "v3.7.1" in package["ShukGuangYaDisk"]["history"]
