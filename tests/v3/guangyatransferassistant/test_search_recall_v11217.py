from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
SOURCE = PLUGIN / "search_recall_v11217.py"
MEDIA_IDENTITY = PLUGIN / "media_identity_v1111.py"


def _media_namespace():
    spec = importlib.util.spec_from_file_location("guangya_media_identity_v1111_v11217_test", MEDIA_IDENTITY)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


MEDIA = _media_namespace()


def _entry_key(row):
    row = dict(row or {})
    return str(row.get("message_id") or row.get("resource_group_id") or row.get("share_url") or row.get("display_title") or "")


class _Legacy:
    RequestUtils = object
    settings = SimpleNamespace(PROXY=None)


class _Base:
    def __init__(self):
        self.store = {
            "channel_index": {"items": [], "channel_cursors": {"a": "100"}},
            "channel_targeted_search_v11217": {},
        }
        self.cache_rows = []
        self.logs = []
        self.target_calls = 0
        self.mode = ""
        self._selected_subscriptions = []
        self._proxy = False

    def init_plugin(self, config=None):
        return None

    def _plugin_log(self, *args):
        self.logs.append(args)

    @staticmethod
    def _is_movie_subscription(subscribe):
        raw = str(getattr(subscribe, "type", "") or "")
        return "电影" in raw or "movie" in raw.lower()

    @staticmethod
    def _identity_aliases_v1111(subscribe):
        rows = [str(getattr(subscribe, "name", "") or "")]
        rows.extend(list(getattr(subscribe, "aliases", []) or []))
        return rows

    @staticmethod
    def _tv_tmdb_aliases_v11214(subscribe):
        return list(getattr(subscribe, "tv_aliases", []) or [])

    def _provider_candidate_matches(self, subscribe, row):
        return False

    def _gying_alias_keywords_v11212(self, subscribe, primary):
        return [primary]

    def get_data(self, key):
        return self.store.get(key)

    def save_data(self, key, value):
        self.store[key] = value

    def _channel_cache_rows_v1115(self):
        return list(self.cache_rows)

    def _refresh_channel_cache_v1115(self, rows):
        known = {_entry_key(row): dict(row) for row in self.cache_rows}
        for row in rows or []:
            known[_entry_key(row)] = dict(row)
        self.cache_rows = list(known.values())
        return []

    def _cached_matches_for_subscription(self, subscribe):
        return []

    def _subscriptions_for_new_channel_entries_v1115(self):
        return []

    def _list_subscriptions(self, _state=None):
        return []

    @staticmethod
    def _is_guangya_route(_subscribe):
        return True

    @staticmethod
    def _entry_can_cover_missing_v1115(_entry, _subscribe):
        return True

    @staticmethod
    def _channel_passive_gap_v11215(_subscribe):
        return (1,)

    def _history_backfill_for_subscriptions_v11215(self, subscriptions):
        return {"fallback_count": len(list(subscriptions or []))}

    def _source_urls(self):
        return ["https://tgm.example/channel-a", "https://tgm.example/channel-b"]

    @staticmethod
    def _channel_label_v11215(_source):
        return "测试频道"

    def _route_mode_v11214(self):
        return self.mode

    def _try_transfer_subscription_inner(self, subscribe, force=False, refresh_channel=True):
        return {"base": True, "force": force, "refresh_channel": refresh_channel}


def _namespace():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    body = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level:
            continue
        body.append(node)
    module = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "_legacy_module": _Legacy,
        "_entry_key_v1115": _entry_key,
        "GuangYaManualCheckV11211Mixin": _Base,
        "explicit_seasons_v1111": MEDIA.explicit_seasons_v1111,
        "explicit_years_v1111": MEDIA.explicit_years_v1111,
        "title_key_v1111": MEDIA.title_key_v1111,
    }
    exec(compile(module, str(SOURCE), "exec"), namespace)
    return namespace


NS = _namespace()
ProbeBase = NS["GuangYaSearchRecallV11217Mixin"]
release_candidates = NS["_release_title_candidates_v11217"]
channel_query_url = NS["_channel_query_url_v11217"]


class Probe(ProbeBase):
    def __init__(self):
        super().__init__()
        self.disambiguation = (True, "MoviePilot 同作品消歧：TMDB 命中")
        self.fetch_rows = []

    def _same_work_disambiguation_v11217(self, subscribe, release_title):
        self.disambiguation_calls = getattr(self, "disambiguation_calls", 0) + 1
        return self.disambiguation

    def _fetch_channel_query_v11217(self, source_url, query):
        self.target_calls += 1
        rows = []
        for base in self.fetch_rows:
            row = dict(base)
            row.setdefault("source_url", source_url)
            row.setdefault("source_label", "测试频道")
            row.setdefault("targeted_query_v11217", query)
            rows.append(row)
        return rows, ""


def movie(name="荣光与暗影", year="2026", tmdb="999", aliases=None):
    return SimpleNamespace(
        id=174,
        name=name,
        year=year,
        season=0,
        type="电影",
        media_source="tmdb",
        media_id=str(tmdb),
        aliases=list(aliases or []),
    )


def tv(name="家族计划", year="2024", season=1, tmdb="236356", aliases=None):
    return SimpleNamespace(
        id=175,
        name=name,
        year=year,
        season=season,
        type="电视剧",
        media_source="tmdb",
        media_id=str(tmdb),
        aliases=list(aliases or []),
        tv_aliases=[],
    )


def test_release_parser_removes_real_world_noise_without_fuzzy_matching():
    rows = dict(release_candidates(
        "Les.rayons.et.les.ombres.2026.READNFO.FRENCH.1080p.WEB.H264-PiCKLES.mkv",
        "2026",
    ))
    assert MEDIA.title_key_v1111("Les rayons et les ombres", expected_year="2026") in rows
    rows = dict(release_candidates("Runaway.Jury.2003.1080p.BluRay.x264-GROUP.mkv", "2003"))
    assert MEDIA.title_key_v1111("Runaway Jury", expected_year="2003") in rows


def test_release_parser_extracts_bilingual_sides_and_bracket_title():
    keys = {key for key, _ in release_candidates("🌈荣光与暗影 Les rayons et les ombres (2026)", "2026")}
    assert MEDIA.title_key_v1111("荣光与暗影", expected_year="2026") in keys
    assert MEDIA.title_key_v1111("Les rayons et les ombres", expected_year="2026") in keys
    bracket = {key for key, _ in release_candidates("⭐⭐---【荣光与暗影】【剧情/传记】---", "2026")}
    assert MEDIA.title_key_v1111("荣光与暗影", expected_year="2026") in bracket


def test_structured_match_rescues_noisy_exact_alias_but_keeps_wrong_year_hard_reject():
    probe = Probe()
    sub = movie(name="失控陪审团", year="2003", tmdb="11329", aliases=["Runaway Jury"])
    ok, detail = probe._structured_candidate_match_v11217(
        sub,
        {"name": "Runaway.Jury.2003.READNFO.1080p.WEB-DL.H264-GROUP.mkv"},
    )
    assert ok is True
    assert detail["matched_alias"] == "Runaway Jury"
    bad, reason = probe._structured_candidate_match_v11217(
        sub,
        {"name": "Runaway.Jury.2004.1080p.WEB-DL.mkv"},
    )
    assert bad is False
    assert "年份冲突" in reason["reason"]


def test_wrong_season_and_explicit_wrong_tmdb_are_never_recalled():
    probe = Probe()
    sub = tv(name="家族计划", year="2024", season=2, aliases=["Family Matters"])
    wrong_season, detail = probe._structured_candidate_match_v11217(
        sub,
        {"name": "Family.Matters.2024.S01E01.1080p.WEB-DL.mkv"},
    )
    assert wrong_season is False
    assert "季号冲突" in detail["reason"]

    wrong_id, detail = probe._structured_candidate_match_v11217(
        sub,
        {"name": "家族计划 2024 S02", "tmdb_id": "30161"},
    )
    assert wrong_id is False
    assert "TMDB" in detail["reason"]


def test_explicit_same_tmdb_is_highest_discovery_evidence_but_still_checks_year():
    probe = Probe()
    sub = movie(name="荣光与暗影", year="2026", tmdb="12345")
    ok, detail = probe._structured_candidate_match_v11217(
        sub,
        {"name": "weird release label", "tmdb_id": "12345", "year": "2026"},
    )
    assert ok is True
    assert detail["score"] == 100
    bad, detail = probe._structured_candidate_match_v11217(
        sub,
        {"name": "weird release 2025", "tmdb_id": "12345", "year": "2025"},
    )
    assert bad is False
    assert "年份冲突" in detail["reason"]


def test_no_year_secondary_alias_requires_moviepilot_same_work_disambiguation():
    probe = Probe()
    sub = tv(name="家族计划", year="2024", season=1, tmdb="236356", aliases=["Family Matters"])
    probe.disambiguation = (False, "MoviePilot 同作品消歧：TMDB 30161 不匹配")
    ok, detail = probe._structured_candidate_match_v11217(
        sub,
        {"name": "Family.Matters.S01.1080p.WEBRip.x264-TrollHD"},
    )
    assert ok is False
    assert "30161" in detail["reason"]
    assert probe.disambiguation_calls == 1

    probe.disambiguation = (True, "MoviePilot 同作品消歧：TMDB 236356 命中")
    ok, detail = probe._structured_candidate_match_v11217(
        sub,
        {"name": "Family.Matters.S01.1080p.WEBRip.x264-GROUP2"},
    )
    assert ok is True
    assert detail["score"] == 92


def test_provider_prefilter_can_be_rescued_without_changing_final_payload_gate():
    probe = Probe()
    sub = movie(name="失控陪审团", year="2003", tmdb="11329", aliases=["Runaway Jury"])
    assert probe._provider_candidate_matches(
        sub,
        {"search_title": "Runaway.Jury.2003.READNFO.1080p.WEB-DL.H264-GROUP"},
    ) is True
    assert any("资源召回v1.12.17" in str(row) for row in probe.logs)


def test_gying_queries_keep_old_queries_and_add_bounded_canonical_variants():
    probe = Probe()
    sub = movie(name="失控陪审团", year="2003", aliases=["Runaway Jury", "幕后陪审团"])
    rows = probe._gying_alias_keywords_v11212(sub, "失控陪审团 2003")
    assert rows[0] == "失控陪审团 2003"
    assert "Runaway Jury" in rows
    assert "Runaway Jury 2003" in rows
    assert len(rows) <= probe._search_query_limit_v11217


def test_channel_query_url_preserves_mirror_and_replaces_only_q():
    url = channel_query_url("https://tgm.li668.asia/regengguangya?before=123&q=old", "荣光与暗影 2026")
    parsed = urlsplit(url)
    assert parsed.netloc == "tgm.li668.asia"
    params = parse_qs(parsed.query)
    assert params["before"] == ["123"]
    assert params["q"] == ["荣光与暗影 2026"]

    official = urlsplit(channel_query_url("https://t.me/regengguangya", "荣光与暗影"))
    assert official.path == "/s/regengguangya"
    assert parse_qs(official.query)["q"] == ["荣光与暗影"]


def test_targeted_channel_search_promotes_verified_identity_and_never_moves_cursor():
    probe = Probe()
    sub = movie(name="失控陪审团", year="2003", tmdb="11329", aliases=["Runaway Jury"])
    probe.fetch_rows = [{
        "message_id": "9988",
        "display_title": "Runaway.Jury.2003.READNFO.1080p.WEB-DL",
        "year_hint": 2003,
        "share_url": "https://www.guangyapan.com/s/example",
        "external_sources": [],
    }]
    before_cursor = dict(probe.store["channel_index"]["channel_cursors"])
    result = probe._targeted_channel_search_v11217(sub, force=True)
    assert result["searched"] is True
    assert result["matched"] == 1
    assert probe.target_calls == 8  # 2 channels * 4 bounded queries
    assert probe.store["channel_index"]["channel_cursors"] == before_cursor
    item = probe.store["channel_index"]["items"][0]
    assert item["tmdb_id"] == "11329"
    assert item["display_title"] in {"失控陪审团", "Runaway Jury"}
    assert item["identity_verified_v11217"] is True


def test_targeted_search_is_not_run_from_passive_channel_event_but_runs_for_active_pull():
    probe = Probe()
    sub = movie(name="失控陪审团", year="2003", aliases=["Runaway Jury"])
    calls = []

    def targeted(_subscribe, force=False):
        calls.append(force)
        return {"searched": True, "matched": 0}

    probe._targeted_channel_search_v11217 = targeted
    probe.mode = "channel_event"
    result = probe._try_transfer_subscription_inner(sub, force=False)
    assert result["base"] is True
    assert calls == []

    probe.mode = "airing_pull"
    probe._try_transfer_subscription_inner(sub, force=False)
    assert calls == [False]


def test_new_subscription_backfill_tries_targeted_search_before_legacy_history_pages():
    probe = Probe()
    sub = movie(name="失控陪审团", year="2003", aliases=["Runaway Jury"])
    order = []

    def targeted(_subscribe, force=False):
        order.append(("target", force))
        probe.cache_rows = [{
            "message_id": "1",
            "display_title": "失控陪审团 2003",
            "tmdb_id": "999",
            "share_url": "https://www.guangyapan.com/s/x",
        }]
        return {"matched": 1}

    probe._targeted_channel_search_v11217 = targeted
    result = probe._history_backfill_for_subscriptions_v11215([sub])
    assert order == [("target", True)]
    assert result["targeted_matched_v11217"] == 1
    assert result["fallback_count"] == 0


def test_source_priority_and_final_hard_fence_files_are_not_reimplemented_here():
    text = SOURCE.read_text(encoding="utf-8")
    assert "cloudcollection/v1/create_task" not in text
    assert "rapid_transfer" not in text
    assert "DownloadChain" not in text
    assert "_xunlei_json_identity_matches_v1123" not in text
    assert "_resolve_offline_source" not in text
