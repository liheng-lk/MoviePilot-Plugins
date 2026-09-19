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
