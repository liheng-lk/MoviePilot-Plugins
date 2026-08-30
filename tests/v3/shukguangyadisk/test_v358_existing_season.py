from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PATCH = (ROOT / "plugins.v3" / "shukguangyadisk" / "organizer_season_context_v358.py").read_text(encoding="utf-8")


def test_existing_moviepilot_season_is_never_overridden():
    assert '"moviepilot_existing"' in PATCH
    assert 'existing = _positive_int(kwargs.get("season"))' in PATCH
