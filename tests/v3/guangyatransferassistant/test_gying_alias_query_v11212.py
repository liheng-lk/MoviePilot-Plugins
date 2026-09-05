from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
PATCH = PLUGIN / "gying_alias_query_v11212.py"
ENTRY = PLUGIN / "__init__.py"


def _mixin_class():
    spec = importlib.util.spec_from_file_location("gying_alias_query_v11212_test", PATCH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module.GuangYaGyingAliasQueryV11212Mixin


MOVIE = SimpleNamespace(id=209, name="失控陪审团", year=2003, type="电影", season=0)
TV = SimpleNamespace(id=210, name="测试剧", year=2026, type="电视剧", season=1)


class _Base:
    def __init__(self):
        self.raw_calls = []
        self.xunlei_calls = []
        self.alias_calls = 0
        self._selected_subscriptions = [209]
        self.subscriptions = [MOVIE, TV]
        self.raw_map = {}
        self.xunlei_map = {}

    def _movie_tmdb_aliases_v1129(self, subscribe):
        self.alias_calls += 1
        if int(getattr(subscribe, "id", 0) or 0) == 209:
            return ["失控陪审团", "Runaway Jury"]
        return []

    @staticmethod
    def _is_movie_v1129(subscribe):
        return "电影" in str(getattr(subscribe, "type", "") or "")

    @staticmethod
    def _provider_candidate_matches(subscribe, row):
        title = str((row or {}).get("search_title") or (row or {}).get("name") or "")
        if int(getattr(subscribe, "id", 0) or 0) == 209:
            return title in {"失控陪审团", "Runaway Jury"}
        return title == str(getattr(subscribe, "name", "") or "")

    @staticmethod
    def _provider_keyword(subscribe):
        name = str(getattr(subscribe, "name", "") or "")
        year = str(getattr(subscribe, "year", "") or "")
        season = int(getattr(subscribe, "season", 0) or 0)
        suffix = f" S{season:02d}" if season > 0 else ""
        return f"{name} {year}{suffix}".strip()

    def _list_subscriptions(self, state):
        return list(self.subscriptions)

    def _gying_raw_results(self, keyword, force=False):
        key = " ".join(str(keyword or "").split())
        self.raw_calls.append((key, bool(force)))
        return self.raw_map.get(key, ([], {"success": True, "cards": 0, "message": "empty"}))

    def _search_viewing_xunlei(self, keyword):
        key = " ".join(str(keyword or "").split())
        self.xunlei_calls.append(key)
        return self.xunlei_map.get(key, ([], {"success": True, "message": "empty"}))

    def _viewing_external_candidates_v1113(self, subscribe):
        rows, state = self._gying_raw_results(self._provider_keyword(subscribe), force=False)
        return list(rows or []), dict(state or {})

    def _unified_provider_search(self, keyword):
        rows, state = self._gying_raw_results(keyword, force=False)
        xunlei, xstate = self._search_viewing_xunlei(keyword)
        return {
            "success": bool(state.get("success") or xstate.get("success")),
            "data": list(rows or []),
            "xunlei": list(xunlei or []),
        }


Mixin = _mixin_class()


class _Probe(Mixin, _Base):
    pass


def test_v11212_source_parses_and_runtime_mro_places_alias_query_after_movie_identity_before_resource_gate():
    source = PATCH.read_text(encoding="utf-8")
    entry = ENTRY.read_text(encoding="utf-8")
    ast.parse(source, filename=str(PATCH))
    assert 'plugin_version = "1.12.12"' in source
    assert 'build_id = "20260905-r58"' in source
    assert "from .gying_alias_query_v11212 import GuangYaGyingAliasQueryV11212Mixin" in entry
    head = entry.split("class GuangYaTransferAssistant(", 1)[1].split("):", 1)[0]
    assert head.index("GuangYaMovieIdentityV1129Mixin") < head.index("GuangYaGyingAliasQueryV11212Mixin")
    assert head.index("GuangYaGyingAliasQueryV11212Mixin") < head.index("GuangYaResourceGateV1127Mixin")


def test_runaway_jury_alias_is_added_after_exact_chinese_query():
    probe = _Probe()
    queries = probe._gying_alias_keywords_v11212(MOVIE, "失控陪审团 2003")
    assert queries[0] == "失控陪审团 2003"
    assert "Runaway Jury 2003" in queries
    assert all("模糊" not in query for query in queries)


def test_raw_gying_does_not_stop_on_unrelated_cards_and_retries_exact_tmdb_alias():
    probe = _Probe()
    probe.raw_map = {
        "失控陪审团 2003": ([{"search_title": "别的电影", "name": "别的电影"}], {"success": True, "cards": 3, "message": "cards"}),
        "Runaway Jury 2003": ([{"search_title": "Runaway Jury", "name": "Runaway Jury 1080p"}], {"success": True, "cards": 1, "message": "hit"}),
    }
    with probe._gying_alias_scope_v11212(MOVIE):
        rows, state = probe._gying_raw_results("失控陪审团 2003")
    assert rows[0]["search_title"] == "Runaway Jury"
    assert probe.raw_calls == [("失控陪审团 2003", False), ("Runaway Jury 2003", False)]
    assert state["query_alias_v11212"] == "Runaway Jury 2003"


def test_matching_primary_result_short_circuits_without_alias_request():
    probe = _Probe()
    probe.raw_map = {
        "失控陪审团 2003": ([{"search_title": "失控陪审团", "name": "失控陪审团"}], {"success": True, "cards": 1}),
    }
    with probe._gying_alias_scope_v11212(MOVIE):
        rows, _ = probe._gying_raw_results("失控陪审团 2003")
    assert rows
    assert probe.raw_calls == [("失控陪审团 2003", False)]


def test_network_or_auth_failure_never_triggers_alias_request():
    probe = _Probe()
    probe.raw_map = {
        "失控陪审团 2003": ([], {"success": False, "message": "观影登录失效"}),
    }
    with probe._gying_alias_scope_v11212(MOVIE):
        rows, state = probe._gying_raw_results("失控陪审团 2003")
    assert rows == []
    assert state["success"] is False
    assert probe.raw_calls == [("失控陪审团 2003", False)]


def test_xunlei_search_retries_official_alias_only_after_primary_miss():
    probe = _Probe()
    probe.xunlei_map = {
        "失控陪审团 2003": ([], {"success": True, "message": "no share"}),
        "Runaway Jury 2003": ([{"share_id": "share-1", "search_title": "Runaway Jury"}], {"success": True, "message": "share"}),
    }
    with probe._gying_alias_scope_v11212(MOVIE):
        rows, state = probe._search_viewing_xunlei("失控陪审团 2003")
    assert rows and rows[0]["share_id"] == "share-1"
    assert probe.xunlei_calls == ["失控陪审团 2003", "Runaway Jury 2003"]
    assert state["query_alias_v11212"] == "Runaway Jury 2003"


def test_magnet_entry_gets_subscription_context_without_reimplementing_dispatch():
    probe = _Probe()
    probe.raw_map = {
        "失控陪审团 2003": ([], {"success": True, "cards": 0}),
        "Runaway Jury 2003": ([{"search_title": "Runaway Jury", "name": "Runaway Jury magnet"}], {"success": True, "cards": 1}),
    }
    rows, state = probe._viewing_external_candidates_v1113(MOVIE)
    assert rows and rows[0]["search_title"] == "Runaway Jury"
    assert state["query_alias_v11212"] == "Runaway Jury 2003"


def test_plugin_unified_search_borrows_identity_only_for_unique_selected_subscription():
    probe = _Probe()
    probe.raw_map = {
        "失控陪审团": ([], {"success": True, "cards": 0}),
        "Runaway Jury 2003": ([{"search_title": "Runaway Jury", "name": "Runaway Jury magnet"}], {"success": True, "cards": 1}),
    }
    probe.xunlei_map = {
        "失控陪审团": ([], {"success": True}),
        "Runaway Jury 2003": ([], {"success": True}),
    }
    result = probe._unified_provider_search("失控陪审团")
    assert result["tmdb_alias_query_v11212"] is True
    assert result["subscribe_id_v11212"] == 209
    assert any(call[0] == "Runaway Jury 2003" for call in probe.raw_calls)


def test_arbitrary_unbound_global_keyword_does_not_trigger_tmdb_alias_lookup():
    probe = _Probe()
    result = probe._unified_provider_search("完全无关的电影")
    assert "tmdb_alias_query_v11212" not in result
    assert probe.alias_calls == 0


def test_tv_search_behavior_is_unchanged_by_movie_alias_layer():
    probe = _Probe()
    assert probe._gying_alias_keywords_v11212(TV, "测试剧 2026 S01") == ["测试剧 2026 S01"]
