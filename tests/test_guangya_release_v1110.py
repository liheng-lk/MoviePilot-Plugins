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
        self.assertEqual(mixins[:17], [
            "GuangYaFoundationOpsV209Mixin",
            "GuangYaEpisodeRuntimeV211Mixin",
            "GuangYaEpisodeTargetV210Mixin",
            "GuangYaCalendarDrivenV209Mixin",
            "GuangYaPowSingleflightV209Mixin",
            "GuangYaProductionSafetyV208Mixin",
            "GuangYaPagePerfV1123Mixin",
            "GuangYaMovieIdentityV1129Mixin",
            "GuangYaResourceGateV1127Mixin",
            "GuangYaFastRecallV1126Mixin",
            "GuangYaDispatchPolicyFinalV1125Mixin",
            "GuangYaDispatchPolicyV1125Mixin",
            "GuangYaAiringWeeklyV1121Mixin",
            "GuangYaAiringSchedulerV1120Mixin",
            "GuangYaMediaIdentityGuardV1111Mixin",
            "GuangYaReleaseV1110Mixin",
            "GuangYaEpisodeFenceFinalV1124Mixin",
        ])
        self.assertIn("GuangYaReleaseV1110Mixin", ENTRY)
        self.assertIn("plugin_version = ", ENTRY)
        self.assertIn("build_id = ", ENTRY)
        cal = (PLUGIN / "calendar_driven_v209.py").read_text(encoding="utf-8")
        self.assertIn("GuangYaTransferAssistantDailyReconcile", cal)
        self.assertIn("0 21 * * *", cal)

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

    def test_calendar_page_and_history_markers_are_published(self):
        self.assertIn("追更日历与每日补漏", RELEASE)
        package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
        current = str(package["GuangYaTransferAssistant"]["version"] or "")
        self.assertTrue(current)
        self.assertEqual(PLUGIN_JSON["version"], current)
        history = package["GuangYaTransferAssistant"]["history"]
        self.assertIn("v1.12.25", history)
        self.assertIn("v1.12.24", history)
        self.assertIn("v1.12.5", history)
        self.assertIn("v1.12.3", history)
        self.assertIn("v1.12.2", history)
        self.assertIn("v1.12.1", history)
        self.assertIn("v1.11.0", history)
        self.assertIn("v1.11.2", history)


if __name__ == "__main__":
    unittest.main()