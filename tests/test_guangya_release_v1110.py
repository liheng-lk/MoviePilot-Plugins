import ast
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
RELEASE = (PLUGIN / "release_v1110.py").read_text(encoding="utf-8")
PLUGIN_JSON = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))


class GuangYaReleaseV1110Tests(unittest.TestCase):
    def test_release_layer_parses_and_calendar_layer_remains_above_episode_fence(self):
        ast.parse(ENTRY)
        ast.parse(RELEASE)
        self.assertIn("from .release_v1110 import GuangYaReleaseV1110Mixin", ENTRY)
        self.assertIn("from .dispatch_policy_v1125 import GuangYaDispatchPolicyV1125Mixin", ENTRY)
        self.assertIn("from .dispatch_policy_final_v1125 import GuangYaDispatchPolicyFinalV1125Mixin", ENTRY)
        head = ENTRY.split("class GuangYaTransferAssistant(", 1)[1].split("):", 1)[0]
        mixins = [line.strip().rstrip(",") for line in head.splitlines() if line.strip()]
        self.assertEqual(mixins[:11], [
            "GuangYaPagePerfV1123Mixin",
            "GuangYaResourceGateV1127Mixin",
            "GuangYaFastRecallV1126Mixin",
            "GuangYaDispatchPolicyFinalV1125Mixin",
            "GuangYaDispatchPolicyV1125Mixin",
            "GuangYaAiringWeeklyV1121Mixin",
            "GuangYaAiringSchedulerV1120Mixin",
            "GuangYaMediaIdentityGuardV1111Mixin",
            "GuangYaReleaseV1110Mixin",
            "GuangYaEpisodeFenceFinalV1124Mixin",
            "GuangYaReceiptCompletionV1124Mixin",
        ])
        self.assertIn('plugin_version = "1.12.8"', ENTRY)
        self.assertIn('build_id = "20260905-r54"', ENTRY)

    def test_daily_full_catchup_is_independent_of_new_channel_messages(self):
        self.assertIn('"id": "GuangYaTransferAssistantDailyCatchup"', RELEASE)
        self.assertIn('_daily_catchup_cron_v1110 = "10 4 * * *"', RELEASE)
        method = RELEASE.split("    def _daily_full_catchup_v1110(", 1)[1].split("    def get_page(", 1)[0]
        self.assertIn("self.refresh_channels(force=True)", method)
        self.assertIn("for sid in selected:", method)
        self.assertIn("self._try_transfer_subscription(fresh, force=True, refresh_channel=False)", method)
        self.assertIn('self.save_data("daily_catchup_v1110", payload)', method)

    def test_airing_calendar_uses_moviepilot_tmdb_next_episode(self):
        self.assertIn("MediaSource.TMDB", RELEASE)
        self.assertIn("next_episode_to_air", RELEASE)
        self.assertIn('"air_date"', RELEASE)
        self.assertIn('"episode_number"', RELEASE)
        self.assertIn('"season_number"', RELEASE)
        self.assertIn('self.save_data("airing_calendar_v1110", payload)', RELEASE)

    def test_due_window_catches_early_release_without_poll_storm(self):
        self.assertIn("today - datetime.timedelta(days=1)", RELEASE)
        self.assertIn("today + datetime.timedelta(days=1)", RELEASE)
        self.assertIn("_calendar_due_check_minutes_v1110 = 60", RELEASE)
        self.assertIn("_calendar_per_sub_cooldown_hours_v1110 = 2", RELEASE)
        self.assertIn("datetime.timedelta(hours=self._calendar_per_sub_cooldown_hours_v1110)", RELEASE)
        self.assertIn("self._is_guangya_route(subscribe)", RELEASE)

    def test_calendar_page_and_current_metadata_are_published(self):
        self.assertIn("追更日历与每日补漏", RELEASE)
        package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
        self.assertEqual(package["GuangYaTransferAssistant"]["version"], "1.12.8")
        self.assertEqual(PLUGIN_JSON["version"], "1.12.8")
        self.assertIn("v1.12.5", package["GuangYaTransferAssistant"]["history"])
        self.assertIn("v1.12.3", package["GuangYaTransferAssistant"]["history"])
        self.assertIn("v1.12.2", package["GuangYaTransferAssistant"]["history"])
        self.assertIn("v1.12.1", package["GuangYaTransferAssistant"]["history"])
        self.assertIn("v1.11.0", package["GuangYaTransferAssistant"]["history"])
        self.assertIn("v1.11.2", package["GuangYaTransferAssistant"]["history"])


if __name__ == "__main__":
    unittest.main()