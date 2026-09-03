from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v3/guangyatransferassistant"
spec = importlib.util.spec_from_file_location("guangya_media_identity_v1111", PLUGIN / "media_identity_v1111.py")
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


class GuangYaMediaIdentityV1111Tests(unittest.TestCase):
    def test_release_layer_is_outermost_and_versioned(self):
        entry = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
        start = entry.index("class GuangYaTransferAssistant(")
        self.assertLess(
            entry.index("GuangYaMediaIdentityGuardV1111Mixin,", start),
            entry.index("GuangYaReleaseV1110Mixin,", start),
        )
        self.assertIn('plugin_version = "1.11.1"', entry)
        self.assertIn('build_id = "20260903-r42"', entry)
        package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
        local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(package["version"], "1.11.1")
        self.assertEqual(local["version"], "1.11.1")

    def test_release_name_cleanup_keeps_real_title_and_rejects_related_title(self):
        self.assertTrue(mod.strong_title_match_v1111("The Last of Us", "The.Last.of.Us.2025.S02E03.2160p.WEB-DL.mkv", 2025))
        self.assertFalse(mod.strong_title_match_v1111("Fallout", "Fallout.Shelter.2024.S01E01.1080p.WEB-DL.mkv", 2024))
        self.assertFalse(mod.strong_title_match_v1111("逆局", "逆局外传.S01E01.2160p.mkv", 2021))

    def test_numeric_title_is_not_mistaken_for_release_year(self):
        self.assertTrue(mod.title_key_v1111("1923.S02E01.1080p.WEB-DL.mkv", 2025).startswith("1923"))
        self.assertEqual(mod.explicit_years_v1111(["1923.S02E01.2025.1080p.mkv"], ["1923"]), {"2025"})

    def test_high_season_requires_explicit_actual_season(self):
        ok, reason = mod.validate_media_evidence_v1111(
            aliases=["The Last of Us"], expected_year=2025, expected_season=2, is_movie=False,
            evidences=["The.Last.of.Us.2025.E03.2160p.mkv"], require_title=True, require_explicit_season=True,
        )
        self.assertFalse(ok)
        self.assertIn("缺少季号证据", reason)
        ok, _ = mod.validate_media_evidence_v1111(
            aliases=["The Last of Us"], expected_year=2025, expected_season=2, is_movie=False,
            evidences=["The.Last.of.Us.2025.S02E03.2160p.mkv"], require_title=True, require_explicit_season=True,
        )
        self.assertTrue(ok)

    def test_explicit_wrong_year_or_season_is_rejected(self):
        ok, reason = mod.validate_media_evidence_v1111(
            aliases=["Demo Show"], expected_year=2026, expected_season=1, is_movie=False,
            evidences=["Demo.Show.2025.S01E01.mkv"], require_title=True,
        )
        self.assertFalse(ok)
        self.assertIn("年份冲突", reason)
        ok, reason = mod.validate_media_evidence_v1111(
            aliases=["Demo Show"], expected_year=2026, expected_season=1, is_movie=False,
            evidences=["Demo.Show.2026.S02E01.mkv"], require_title=True,
        )
        self.assertFalse(ok)
        self.assertIn("季号冲突", reason)

    def test_search_card_cannot_rescue_xunlei_actual_payload(self):
        guard = (PLUGIN / "media_identity_guard_v1111.py").read_text(encoding="utf-8")
        method = guard.split("    def _xunlei_json_identity_matches_v1123(", 1)[1].split("    def _resolve_offline_source", 1)[0]
        self.assertIn('resource_name.casefold() == search_title.casefold()', method)
        self.assertIn("validate_media_evidence_v1111", method)
        self.assertNotIn("search_title", method.split("actual =", 1)[1].split("ok, reason", 1)[0])

    def test_offline_resolve_has_final_payload_gate_before_cloud_create(self):
        guard = (PLUGIN / "media_identity_guard_v1111.py").read_text(encoding="utf-8")
        method = guard.split("    def _resolve_offline_source(", 1)[1].split("    def _plan_incremental_files", 1)[0]
        self.assertIn('data.get("btResInfo")', method)
        self.assertIn('bt_info.get("subfiles")', method)
        self.assertIn("validate_media_evidence_v1111", method)
        self.assertIn("EPISODE_AMBIGUOUS:", guard)

    def test_channel_match_is_strong_and_high_season_fails_closed(self):
        legacy = (PLUGIN / "legacy.py").read_text(encoding="utf-8")
        method = legacy.split("def _entry_matches_subscription(", 1)[1].split("def _subscription_aliases", 1)[0]
        self.assertIn("strong_title_match_v1111", method)
        self.assertIn("wanted_season > 1 and not seasons", method)
        self.assertNotIn("value in haystack", method)

    def test_final_provider_matcher_checks_year_and_season(self):
        guard = (PLUGIN / "media_identity_guard_v1111.py").read_text(encoding="utf-8")
        matcher = guard.split("    def _provider_candidate_matches(", 1)[1].split("    def _xunlei_json_identity_matches_v1123", 1)[0]
        self.assertIn("explicit_years_v1111", matcher)
        self.assertIn("explicit_seasons_v1111", matcher)
        self.assertIn("season not in seasons", matcher)


if __name__ == "__main__":
    unittest.main()
