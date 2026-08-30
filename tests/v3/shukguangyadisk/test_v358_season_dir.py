from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PATCH = (ROOT / "plugins.v3" / "shukguangyadisk" / "organizer_season_context_v358.py").read_text(encoding="utf-8")


def test_season_directory_patterns_are_supported():
    assert "season1" in PATCH
    assert "season2" in PATCH
    assert "season3" in PATCH
    assert '"season_directory"' in PATCH
