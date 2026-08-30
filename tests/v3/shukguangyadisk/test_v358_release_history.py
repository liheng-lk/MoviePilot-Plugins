from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"


def test_v358_history_mentions_empty_season_fix():
    meta = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    text = meta["history"]["v3.5.8"]
    assert "season" in text
    assert "空 Season" in text
