from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PATCH = (ROOT / "plugins.v3" / "shukguangyadisk" / "organizer_season_context_v358.py").read_text(encoding="utf-8")


def test_v358_runtime_log_identifies_season_source():
    assert "MoviePilot season=%s，来源=%s" in PATCH
