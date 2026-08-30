from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PATCH = (ROOT / "plugins.v3" / "shukguangyadisk" / "organizer_season_context_v358.py").read_text(encoding="utf-8")


def test_plugin_only_hands_season_to_moviepilot_kwargs():
    assert 'kwargs["season"] = season' in PATCH
    assert 'MoviePilot season=%s' in PATCH
    assert '不拼接目标路径、不修改命名模板' in PATCH
