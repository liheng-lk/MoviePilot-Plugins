from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = (ROOT / "plugins.v3/dailyassistant/__init__.py").read_text(encoding="utf-8")
SOURCES = (ROOT / "plugins.v3/dailyassistant/sources.py").read_text(encoding="utf-8")
BACKENDS = (ROOT / "plugins.v3/dailyassistant/source_backends.py").read_text(encoding="utf-8")
PACKAGE = (ROOT / "package.v3.json").read_text(encoding="utf-8")


def test_dailyassistant_v132_is_subscription_only():
    assert 'plugin_version = "1.3.6"' in ENTRY
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
    assert data["DailyAssistant"]["version"] == "1.3.6"


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


def test_dailyassistant_v135_expands_tv_seasons_and_self_heals_ledger():
    assert "def _expand_candidates" in ENTRY
    assert 'candidate["season"] = season_number' in ENTRY
    assert "def _processed_valid" in ENTRY
    assert 'datetime.timedelta(hours=24)' in ENTRY
    assert 'datetime.timedelta(days=7)' in ENTRY
    assert 'processed.pop(identity, None)' in ENTRY
    assert 'recent_days=self._recent_days' in ENTRY
    assert 'row["season"] = row.get("season") or getattr(info, "season", None)' not in ENTRY
    assert 'release_date=lower_bound' in BACKENDS


def test_dailyassistant_v136_domestic_and_anime_defaults():
    defaults = ENTRY.split("LATEST_SOURCE_KEYS", 1)[1].split("]", 1)[0]
    for key in (
        "tencent_direct_tv", "iqiyi_tv", "youku_tv", "mgtv_tv",
        "bilibili_tv", "bilibili_anime", "bilibili_guochuang",
        "bangumi_calendar", "douban_animation",
    ):
        assert f'"{key}"' in defaults
    for key in ("netflix_tv", "hbo_tv", "disney_tv", "prime_tv"):
        assert f'"{key}"' not in defaults
    assert 'SourceSpec("tencent_direct_tv"' in SOURCES
    assert 'SourceSpec("iqiyi_tv"' in SOURCES
    assert 'SourceSpec("youku_tv"' in SOURCES
    assert 'SourceSpec("mgtv_tv"' in SOURCES
    assert 'SourceSpec("bilibili_anime"' in SOURCES
    assert 'SourceSpec("bilibili_guochuang"' in SOURCES
    assert 'mtype == MediaType.MOVIE and wanted_year' in ENTRY
