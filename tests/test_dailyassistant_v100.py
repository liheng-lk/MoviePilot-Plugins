import ast
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v3" / "dailyassistant"
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
SOURCES = (PLUGIN / "sources.py").read_text(encoding="utf-8")


class DailyAssistantContract(unittest.TestCase):
    def test_python_sources_parse(self):
        ast.parse(ENTRY)
        ast.parse(SOURCES)

    def test_plugin_identity_and_gysub_bridge(self):
        self.assertIn('plugin_name = "每日助手"', ENTRY)
        self.assertIn('plugin_version = "1.0.0"', ENTRY)
        self.assertIn('"action": "guangya_direct_subscribe"', ENTRY)
        self.assertIn("eventmanager.send_event(EventType.PluginAction", ENTRY)
        self.assertIn("MediaSource.TMDB", ENTRY)
        self.assertIn('"api": "plugin/DailyAssistant/gysub"', ENTRY)
        self.assertIn('"apikey": settings.API_TOKEN', ENTRY)

    def test_all_media_catalog_is_present(self):
        required = (
            "纪录片", "日漫", "综艺",
            "Netflix · 电影榜", "Netflix · 剧集榜", "Netflix · 混合榜",
            "HBO / Max · 电影榜", "Apple TV+ · 剧集榜", "Disney+ · 剧集榜",
            "Crunchyroll · 剧集榜", "Amazon Prime · 电影榜", "Amazon · 剧集榜",
            "Hulu · 剧集榜", "猫眼 · 电影榜", "猫眼 · 剧集榜", "猫眼 · 综艺榜",
            "豆瓣 · 正在上映", "豆瓣 · 热门电影", "豆瓣 · 热门剧集",
            "热门 · IMDb 热门电影", "热门 · IMDb 热门剧集", "热门 · TMDB 趋势",
            "热门 · AniList 热门", "热门 · Bangumi 今日动漫", "腾讯视频 · 热播",
        )
        for token in required:
            self.assertIn(token, SOURCES)

    def test_catalog_uses_host_chains_and_public_rank_sources(self):
        for token in (
            "RecommendChain", "with_watch_providers", "with_genres",
            "all-weeks-global.tsv", "api.graphql.imdb.com",
            "piaofang.maoyan.com", "AniListChain",
        ):
            self.assertIn(token, SOURCES)

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
