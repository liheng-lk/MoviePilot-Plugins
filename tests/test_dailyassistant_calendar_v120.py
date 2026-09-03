from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v3" / "dailyassistant"
CALENDAR = (PLUGIN / "airing_calendar_v120.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")


def test_dailyassistant_calendar_module_parses_and_uses_public_moviepilot_contract():
    ast.parse(CALENDAR)
    assert "from app.chain.media import MediaChain" in CALENDAR
    assert "chain.tmdb_info(" in CALENDAR
    assert "mtype=MediaType.TV" in CALENDAR
    assert "season=season" in CALENDAR
    assert "get_tv_season_detail" not in CALENDAR
    assert "app.modules.themoviedb" not in CALENDAR


def test_dailyassistant_calendar_exports_full_season_episode_schedule():
    assert "def get_airing_schedule_snapshot" in CALENDAR
    assert '"episodes": episodes' in CALENDAR
    assert '"episode": episode' in CALENDAR
    assert '"air_date": air_date' in CALENDAR
    assert '"air_at": air_at' in CALENDAR
    assert '"precision": "datetime" if air_at else ("date" if air_date else "unknown")' in CALENDAR
    assert 'self.save_data("airing_schedule_v120", payload)' in CALENDAR
    assert "_airing_calendar_ttl_v120 = datetime.timedelta(hours=6)" in CALENDAR


def test_dailyassistant_calendar_falls_back_to_next_episode_summary():
    assert "def _fallback_next_episode_v120" in CALENDAR
    assert "next_episode_to_air" in CALENDAR
    assert "if not episodes:" in CALENDAR
    assert "_fallback_next_episode_v120(" in CALENDAR


def test_dailyassistant_calendar_is_final_runtime_authority_and_release_v120():
    assert "from .airing_calendar_v120 import DailyAssistantCalendarV120Mixin" in ENTRY
    start = ENTRY.index("class DailyAssistant(")
    calendar_pos = ENTRY.index("DailyAssistantCalendarV120Mixin,", start)
    hardening_pos = ENTRY.index("DailyAssistantV110Mixin,", start)
    assert calendar_pos < hardening_pos
    assert 'plugin_version = "1.2.0"' in ENTRY
