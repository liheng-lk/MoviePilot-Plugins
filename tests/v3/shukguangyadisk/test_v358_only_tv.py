from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PATCH = (ROOT / "plugins.v3" / "shukguangyadisk" / "organizer_season_context_v358.py").read_text(encoding="utf-8")


def test_season_bridge_only_applies_to_tv_kwargs():
    assert 'not _is_tv_kwargs(dict(kwargs or {}))' in PATCH
