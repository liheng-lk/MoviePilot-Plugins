import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"


def test_v372_release_description_mentions_removed_installers():
    plugin = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    text = plugin["history"]["v3.7.2"]
    assert "organizer_loss_guard_v349" in text
    assert "organizer_empty_folder_guard_v3410" in text
