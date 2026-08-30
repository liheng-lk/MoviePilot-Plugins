from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PATCH = (ROOT / "plugins.v3" / "shukguangyadisk" / "organizer_season_context_v358.py").read_text(encoding="utf-8")


def test_moviepilot_single_positive_season_is_allowed_as_context():
    assert '"moviepilot_single_season"' in PATCH
    assert "Season 0 不参与单季判断" in PATCH
