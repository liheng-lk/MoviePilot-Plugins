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
        self.assertIn('plugin_version = "1.0.0"', ENTRY)
        self.assertIn('"action": "guangya_direct_subscribe"', ENTRY)
        self.assertIn("eventmanager.send_event(EventType.PluginAction", ENTRY)
        self.assertIn("MediaSource.TMDB", ENTRY)
        self.assertIn('"api": "plugin/DailyAssistant/gysub"', ENTRY)
        self.assertIn('"apikey": settings.API_TOKEN', ENTRY)

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
        for family in ("HBO / Max", "Apple TV+", "Disney+", "Crunchyroll", "Amazon Prime", "Amazon", "Hulu"):
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
        self.assertIn('"tencent:10751"', SOURCES)

    def test_candidate_and_auto_modes_are_separate(self):
        self.assertIn("auto_gysub", ENTRY)
        self.assertIn("auto_source_keys", ENTRY)
        self.assertIn("if self._auto_gysub and self._auto_source_keys:", ENTRY)
        self.assertIn('if row.get("source_key") not in self._auto_source_keys', ENTRY)

    def test_package_index_publishes_dailyassistant(self):
        package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
        item = package["DailyAssistant"]
        self.assertEqual(item["version"], "1.0.0")
        self.assertEqual(item["system_version"], ">=3.0.0")
        self.assertIn("GYSub", item["description"])


if __name__ == "__main__":
    unittest.main()
