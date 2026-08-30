from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PATCH = (ROOT / "plugins.v3" / "shukguangyadisk" / "organizer_season_context_v358.py").read_text(encoding="utf-8")


def test_v358_migration_has_dedicated_marker():
    assert "organize_v358_empty_season_retry_wakeup" in PATCH
