import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v2" / "dailynewdrama"
SOURCE = (PLUGIN / "__init__.py").read_text(encoding="utf-8")


class DailyNewDramaV13Tests(unittest.TestCase):
    def test_v13_metadata_is_consistent(self):
        self.assertIn('plugin_version = "1.3.6"', SOURCE)
        local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
        package = json.loads((ROOT / "package.v2.json").read_text(encoding="utf-8"))["DailyNewDrama"]
        index = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))["DailyNewDrama"]
        self.assertEqual(local["version"], "1.3.6")
        self.assertEqual(package["version"], "1.3.6")
        self.assertEqual(index["version"], "1.3.6")

    def test_page_candidates_have_no_hard_display_limit(self):
        self.assertNotIn("_max_items", SOURCE)
        self.assertNotIn("candidates = candidates[:", SOURCE)
        self.assertNotIn('"model": "max_items"', SOURCE)

    def test_page_has_direct_subscribe_button(self):
        self.assertIn('"text": "订阅"', SOURCE)
        self.assertIn('"api": "plugin/DailyNewDrama/subscribe"', SOURCE)
        self.assertIn('"method": "get"', SOURCE)
        self.assertIn('"batch_id": batch_id', SOURCE)
        self.assertIn('"indexes": str(item.get("index") or "")', SOURCE)
        self.assertIn('"apikey": settings.API_TOKEN', SOURCE)

    def test_recent_notification_only_suppresses_message(self):
        self.assertNotIn("过滤近期已提醒", SOURCE)
        self.assertIn("notify_candidates = candidates", SOURCE)
        self.assertIn("self._recently_notified(item.get(\"tmdbid\"), notified, today)", SOURCE)
        self.assertIn('last_status["notification_count"]', SOURCE)

    def test_primary_visibility_filters_remain(self):
        self.assertIn("DownloadChain().get_no_exists_info", SOURCE)
        self.assertIn("subscribe_chain.exists", SOURCE)
        self.assertIn("过滤媒体库已存在", SOURCE)
        self.assertIn("过滤已订阅", SOURCE)

    def test_subscribe_removes_handled_item_from_current_page(self):
        self.assertIn("handled_indexes", SOURCE)
        self.assertIn("def _remove_current_candidates", SOURCE)
        self.assertIn("self._remove_current_candidates(handled, batch_id=batch_id)", SOURCE)
        self.assertIn('status["candidate_count"] = len(items)', SOURCE)

    def test_notification_is_chunked_instead_of_candidate_truncation(self):
        self.assertIn("chunk_size = 20", SOURCE)
        self.assertIn("total_chunks =", SOURCE)
        self.assertIn("for chunk_no, offset in enumerate", SOURCE)

    def test_source_fetch_breadth_defaults_to_100(self):
        self.assertIn("_coming_count = 100", SOURCE)
        self.assertIn('config.get("coming_count"), 100, 10, 100', SOURCE)

    def test_onlyonce_save_keeps_source_configuration(self):
        self.assertIn('"flaresolverr_enabled": self._flaresolverr_enabled', SOURCE)
        self.assertIn('"flaresolverr_url": self._flaresolverr_url', SOURCE)
        for key in ("platform_tencent", "platform_iqiyi", "platform_youku", "platform_mgtv", "platform_bilibili"):
            self.assertIn(f'"{key}": self._{key}', SOURCE)


if __name__ == "__main__":
    unittest.main()
