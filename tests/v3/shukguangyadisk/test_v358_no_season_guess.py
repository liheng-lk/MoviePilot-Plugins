from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PATCH = (ROOT / "plugins.v3" / "shukguangyadisk" / "organizer_season_context_v358.py").read_text(encoding="utf-8")


def test_unknown_season_is_not_defaulted_to_one():
    assert 'return None, "unknown", None' in PATCH
    assert 'season = 1' not in PATCH
