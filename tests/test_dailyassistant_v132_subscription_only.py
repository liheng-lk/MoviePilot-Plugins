from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = (ROOT / "plugins.v3/dailyassistant/__init__.py").read_text(encoding="utf-8")
SOURCES = (ROOT / "plugins.v3/dailyassistant/sources.py").read_text(encoding="utf-8")
BACKENDS = (ROOT / "plugins.v3/dailyassistant/source_backends.py").read_text(encoding="utf-8")
PACKAGE = (ROOT / "package.v3.json").read_text(encoding="utf-8")


def test_dailyassistant_v132_is_subscription_only():
    assert 'plugin_version = "1.3.2"' in ENTRY
    assert "SubscribeChain().add" not in ENTRY  # use local chain instance, not legacy string contract
    assert "chain.add(" in ENTRY
    assert "EventType.PluginAction" not in ENTRY
    assert "guangya" not in ENTRY.lower()
    assert "gysub" not in ENTRY.lower()


def test_dailyassistant_v132_latest_sources_are_primary():
    assert '"tmdb_latest_movie"' in ENTRY
    assert '"tmdb_latest_tv"' in ENTRY
    assert '"tmdb_trending"' not in ENTRY.split("LATEST_SOURCE_KEYS", 1)[1].split("]", 1)[0]
    assert 'SourceSpec("tmdb_latest_movie"' in SOURCES
    assert 'SourceSpec("tmdb_latest_tv"' in SOURCES
    assert 'sort_by="primary_release_date.desc"' in BACKENDS
    assert 'sort_by="first_air_date.desc"' in BACKENDS


def test_dailyassistant_v132_manifest_is_valid_json():
    import json
    data = json.loads(PACKAGE)
    assert data["DailyAssistant"]["version"] == "1.3.2"


def test_dailyassistant_v133_has_library_any_content_guard_and_persistent_ledger():
    assert "def _library_has_content" in ENTRY
    assert 'self.get_data("dailyassistant_processed")' in ENTRY
    assert 'self.save_data("dailyassistant_processed", data)' in ENTRY
    assert 'self._remember_processed(row, "created"' in ENTRY
    assert 'self._remember_processed(row, "exists"' in ENTRY
    assert 'self._remember_processed(row, "library"' in ENTRY
    assert "processed_skip" in ENTRY


def test_dailyassistant_v134_resolves_real_tv_season():
    assert "def _resolve_tv_season" in ENTRY
    assert 'item.get("season_number")' in ENTRY
    assert 'item.get("air_date")' in ENTRY
    assert "season_number <= 0" in ENTRY
    assert 'row["season"] = season' in ENTRY
    assert 'raw_season = row.get("season")' in ENTRY
    assert 'getattr(info, "season", None)' in ENTRY  # fallback only
