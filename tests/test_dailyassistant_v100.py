import ast
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v3" / "dailyassistant"
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
SOURCES = (PLUGIN / "sources.py").read_text(encoding="utf-8")
BACKENDS = (PLUGIN / "source_backends.py").read_text(encoding="utf-8")
ALL_SOURCES = SOURCES + "\n" + BACKENDS


class DailyAssistantContract(unittest.TestCase):
    def test_python_sources_parse(self):
        ast.parse(ENTRY)
        ast.parse(SOURCES)
        ast.parse(BACKENDS)

    def test_plugin_identity_and_gysub_bridge(self):
        self.assertIn('plugin_name = "每日助手"', ENTRY)
        self.assertIn('plugin_version = "1.1.0"', ENTRY)
        self.assertIn('"action": "guangya_direct_subscribe"', ENTRY)
        self.assertIn("eventmanager.send_event(EventType.PluginAction", ENTRY)
        self.assertIn("MediaSource.TMDB", ENTRY)
        self.assertIn('"api": "plugin/DailyAssistant/gysub"', ENTRY)
        self.assertIn('"apikey": settings.API_TOKEN', ENTRY)

    def test_gysub_delivery_is_confirmed_from_moviepilot_subscription_facts(self):
        self.assertIn("from app.chain.subscribe import SubscribeChain", ENTRY)
        self.assertIn("def _subscription_exists", ENTRY)
        self.assertIn("SubscribeChain().exists(mediainfo=info, meta=meta)", ENTRY)
        self.assertIn('self.save_data("gysub_pending", pending)', ENTRY)
        self.assertIn("def _reconcile_pending_gysub", ENTRY)
        self.assertIn('"confirmed_at"', ENTRY)
        self.assertIn("等待 MoviePilot 订阅落库确认", ENTRY)
        dispatch_start = ENTRY.index("def _dispatch_gysub")
        refresh_start = ENTRY.index("def refresh", dispatch_start)
        dispatch = ENTRY[dispatch_start:refresh_start]
        send_pos = dispatch.index("eventmanager.send_event")
        pending_pos = dispatch.index('self.save_data("gysub_pending", pending)')
        self.assertLess(send_pos, pending_pos)
        self.assertNotIn('submitted[identity] = datetime.datetime.now().isoformat', dispatch)

    def test_gysub_identity_separates_tv_seasons(self):
        self.assertIn('return f"tmdb:{tmdb_id}:{media_type}:s{season:02d}"', ENTRY)
        self.assertIn('_safe_int(item.get("season"), 1, 1, 99)', ENTRY)
        self.assertNotIn('return f"tmdb:{tmdb_id}:{item.get(\'media_type\') or \'\'}"', ENTRY)

    def test_auto_gysub_relies_on_existing_subscription_and_pending_ttl_not_permanent_emit_dedupe(self):
        self.assertIn("_gysub_pending_ttl = datetime.timedelta(minutes=15)", ENTRY)
        self.assertIn("reconcile = self._reconcile_pending_gysub()", ENTRY)
        self.assertIn('result.get("status") == "requested"', ENTRY)
        auto_start = ENTRY.index("if self._auto_gysub and self._auto_source_keys:")
        api_start = ENTRY.index("def api_refresh", auto_start)
        auto_block = ENTRY[auto_start:api_start]
        self.assertNotIn('if self._candidate_identity(row) in submitted:', auto_block)

    def test_all_media_catalog_is_present(self):
        static_required = (
            "纪录片", "日漫", "综艺",
            "Netflix · 电影榜", "Netflix · 剧集榜", "Netflix · 混合榜",
            "猫眼 · 电影榜", "猫眼 · 剧集榜", "猫眼 · 综艺榜", "猫眼 · 混合榜",
            "豆瓣 · 正在上映", "豆瓣 · 即将上映", "豆瓣 · 新片榜", "豆瓣 · 一周口碑榜",
            "豆瓣 · 北美票房榜", "豆瓣 · 热门电影", "豆瓣 · 剧集近期值得看",
            "豆瓣 · 热门剧集", "豆瓣 · 推荐", "豆瓣 · 混合榜",
            "热门 · IMDb 热门电影", "热门 · IMDb 热门剧集", "热门 · TMDB 趋势",
            "热门 · AniList 热门", "热门 · Bangumi 今日动漫", "热门 · 混合榜",
            "腾讯视频 · 热播", "腾讯视频 · 电影", "腾讯视频 · 电视剧",
            "腾讯视频 · 综艺", "腾讯视频 · 少儿",
        )
        for token in static_required:
            self.assertIn(token, SOURCES)
        for family in ("HBO", "Apple TV+", "Disney+", "Crunchyroll", "Amazon Prime", "Amazon", "Hulu"):
            self.assertIn(f'"{family}"', SOURCES)
        self.assertIn('(("movie", "电影榜"), ("tv", "剧集榜"), ("mixed", "混合榜"))', SOURCES)

    def test_catalog_uses_host_chains_and_public_rank_sources(self):
        for token in (
            "RecommendChain", "with_watch_providers", "with_genres",
            "all-weeks-global.tsv", "api.graphql.imdb.com",
            "piaofang.maoyan.com", "AniListChain",
        ):
            self.assertIn(token, ALL_SOURCES)
        self.assertIn("from .source_backends import", SOURCES)

    def test_douban_catalog_uses_current_live_contracts(self):
        for token in (
            "rexxar/api/v2/subject_collection", "movie_soon", "movie_weekly_best",
            "movie_real_time_hotest", "tv_real_time_hotest",
            "movie.douban.com/chart", "BeautifulSoup",
            'chain.douban_movies(sort=spec.arg or "U"',
        ):
            self.assertIn(token, ALL_SOURCES)
        self.assertIn("_douban_subject_id", SOURCES)
        self.assertIn("_year_value", SOURCES)
        self.assertIn("北美票房页面结构已变化", BACKENDS)

    def test_imdb_uses_live_moviemeter_graphql_shape(self):
        self.assertIn("MOST_POPULAR_MOVIES", BACKENDS)
        self.assertIn("MOST_POPULAR_TV_SHOWS", BACKENDS)
        self.assertIn("AdvancedTitleSearchSort", BACKENDS)
        self.assertIn('"sortBy": "POPULARITY"', BACKENDS)
        self.assertIn("chartTitles", BACKENDS)

    def test_tencent_movie_tv_variety_and_kids_have_distinct_routes(self):
        self.assertIn('"tencent": "623|1170"', SOURCES)
        self.assertIn('SourceSpec("tencent_movie"', SOURCES)
        self.assertIn('SourceSpec("tencent_tv"', SOURCES)
        self.assertIn('SourceSpec("tencent_variety"', SOURCES)
        self.assertIn('SourceSpec("tencent_kids"', SOURCES)
        self.assertIn('"watch_provider_genre"', SOURCES)
        self.assertIn('"tencent:10762"', SOURCES)

    def test_candidate_and_auto_modes_are_separate(self):
        self.assertIn("auto_gysub", ENTRY)
        self.assertIn("auto_source_keys", ENTRY)
        self.assertIn("if self._auto_gysub and self._auto_source_keys:", ENTRY)
        self.assertIn('if row.get("source_key") not in self._auto_source_keys', ENTRY)

    def test_package_index_publishes_dailyassistant(self):
        package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
        item = package["DailyAssistant"]
        self.assertEqual(item["version"], "1.1.0")
        self.assertEqual(item["system_version"], ">=3.0.0")
        self.assertIn("GYSub", item["description"])


if __name__ == "__main__":
    unittest.main()
