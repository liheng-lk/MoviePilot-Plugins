import ast
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v3" / "dailyassistant"
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
SOURCES = (PLUGIN / "sources.py").read_text(encoding="utf-8")


class DailyAssistantCurrentContractTests(unittest.TestCase):
    def test_sources_parse_and_final_runtime_is_current(self):
        ast.parse(ENTRY)
        ast.parse(SOURCES)
        self.assertIn("class DailyAssistant(_PluginBase):", ENTRY)
        self.assertIn('plugin_version = "1.3.8"', ENTRY)
        self.assertIn("__all__ = ["DailyAssistant"]", ENTRY)

    def test_source_failures_are_observable_from_host_network(self):
        self.assertIn("SOURCE_TEST_KEYS", ENTRY)
        self.assertIn("def source_test", ENTRY)
        self.assertIn('"elapsed_ms"', ENTRY)
        self.assertIn('"samples"', ENTRY)
        self.assertIn('"error"', ENTRY)
        self.assertIn('self.save_data("dailyassistant_source_test", payload)', ENTRY)
        self.assertIn('{"path": "/source-test"', ENTRY)

    def test_processed_state_revalidates_real_moviepilot_facts(self):
        self.assertIn("def _processed_valid", ENTRY)
        self.assertIn("self._library_has_content(info, row)", ENTRY)
        self.assertIn("SubscribeChain().exists(mediainfo=info, meta=meta)", ENTRY)
        self.assertIn("self._history_exists(info, row)", ENTRY)

    def test_source_catalog_corrections_are_published(self):
        self.assertIn('("hbo", "HBO")', SOURCES)
        self.assertNotIn('("hbo", "HBO / Max")', SOURCES)
        self.assertIn('"tencent:10762"', SOURCES)
        self.assertNotIn('"tencent:10751"', SOURCES)

    def test_package_index_is_current(self):
        package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
        item = package["DailyAssistant"]
        self.assertEqual(item["version"], "1.3.8")
        self.assertEqual(item["system_version"], ">=3.0.0")
        self.assertEqual(next(iter(item["history"])), "v1.3.8")
        self.assertIn("来源实测", item["history"]["v1.3.8"])


if __name__ == "__main__":
    unittest.main()
