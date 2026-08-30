from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PATCH = (ROOT / "plugins.v3" / "shukguangyadisk" / "organizer_season_context_v358.py").read_text(encoding="utf-8")


def test_empty_season_retry_migration_is_one_time_and_narrow():
    assert '_MARKER_KEY = "organize_v358_empty_season_retry_wakeup"' in PATCH
    assert 'if isinstance(marker, dict) and marker.get("applied"):' in PATCH
    assert 'Season\\s+目录获取失败' in PATCH
    assert 'row["retry_at"] = 0' in PATCH
    assert 'plugin.save_data(_MARKER_KEY, marker)' in PATCH
