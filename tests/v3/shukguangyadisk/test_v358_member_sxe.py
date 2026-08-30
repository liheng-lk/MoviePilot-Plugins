from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PATCH = (ROOT / "plugins.v3" / "shukguangyadisk" / "organizer_season_context_v358.py").read_text(encoding="utf-8")


def test_explicit_sxe_member_season_is_preserved():
    assert '"member_sxe"' in PATCH
    assert "token.season" in PATCH
