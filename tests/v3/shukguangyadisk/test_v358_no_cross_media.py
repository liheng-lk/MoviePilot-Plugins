from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PATCH = (ROOT / "plugins.v3" / "shukguangyadisk" / "organizer_season_context_v358.py").read_text(encoding="utf-8")


def test_movie_tasks_return_without_season_mutation():
    assert "if plan_error or not _is_tv_kwargs" in PATCH
