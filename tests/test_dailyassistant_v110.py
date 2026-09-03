import ast
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v3" / "dailyassistant"
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
HARDENING = (PLUGIN / "hardening_v110.py").read_text(encoding="utf-8")
SOURCES = (PLUGIN / "sources.py").read_text(encoding="utf-8")


class DailyAssistantV110Tests(unittest.TestCase):
    def test_sources_parse_and_final_runtime_is_v110(self):
        ast.parse(ENTRY)
        ast.parse(HARDENING)
        self.assertIn("from .hardening_v110 import DailyAssistantV110Mixin", ENTRY)
        self.assertIn("class DailyAssistant(DailyAssistantCalendarV120Mixin, DailyAssistantV110Mixin, DailyAssistantV100):", ENTRY)
        self.assertIn('plugin_version = "1.2.0"', ENTRY)

    def test_same_media_merges_all_source_provenance(self):
        self.assertIn("def _merge_candidate", HARDENING)
        self.assertIn('row["source_keys"] = source_keys', HARDENING)
        self.assertIn('row["source_labels"] = source_labels', HARDENING)
        self.assertIn('row["fresh_source_keys"] = fresh_keys', HARDENING)
        self.assertIn("if identity in aggregated:", HARDENING)
        self.assertIn("self._merge_candidate(aggregated[identity], row)", HARDENING)

    def test_source_failure_uses_bounded_cache_but_cache_cannot_auto_subscribe(self):
        self.assertIn("_source_cache_ttl = datetime.timedelta(hours=48)", HARDENING)
        self.assertIn('self.get_data("dailyassistant_source_cache")', HARDENING)
        self.assertIn("now - cached_at <= self._source_cache_ttl", HARDENING)
        self.assertIn('row["fresh_source_keys"] = [source_key] if fresh else []', HARDENING)
        self.assertIn('auto_allowed.intersection(set(row.get("fresh_source_keys") or []))', HARDENING)

    def test_gysub_pending_is_reconciled_without_waiting_for_daily_refresh(self):
        self.assertIn('"id": "DailyAssistantGYSubReconcile"', HARDENING)
        self.assertIn('"func": self._reconcile_pending_gysub', HARDENING)
        self.assertIn('"kwargs": {"minutes": 5}', HARDENING)

    def test_source_catalog_corrections_are_published(self):
        self.assertIn('("hbo", "HBO")', SOURCES)
        self.assertNotIn('("hbo", "HBO / Max")', SOURCES)
        self.assertIn('"tencent:10762"', SOURCES)
        self.assertNotIn('"tencent:10751"', SOURCES)

    def test_package_index_is_v110(self):
        package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
        item = package["DailyAssistant"]
        self.assertEqual(item["version"], "1.2.0")
        self.assertIn("v1.1.0", item["history"])
        self.assertIn("48小时", item["history"]["v1.1.0"])


if __name__ == "__main__":
    unittest.main()
