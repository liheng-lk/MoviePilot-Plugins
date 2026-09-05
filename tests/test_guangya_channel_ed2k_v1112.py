from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v3/guangyatransferassistant"


class GuangYaChannelEd2kV1112Tests(unittest.TestCase):
    def test_ed2k_channel_candidate_gets_resolve_first_chance(self):
        text = (PLUGIN / "resource_planner_v190.py").read_text(encoding="utf-8")
        method = text.split("    def _candidate_target_episodes(", 1)[1].split("    def _save_resource_plan", 1)[0]
        self.assertIn('{"magnet", "ed2k"}', method)
        self.assertIn('return set(uncovered)', method)

    def test_single_file_ed2k_backfills_real_episode_before_cloud_create(self):
        text = (PLUGIN / "resource_planner_v190.py").read_text(encoding="utf-8")
        method = text.split("    def _resolve_offline_source(", 1)[1].split("    def _mark_offline_failure", 1)[0]
        self.assertIn('source_type == "ed2k"', method)
        self.assertIn('no_subfiles', method)
        self.assertIn('resolve_episode(', method)
        self.assertIn('matched_episodes = actual_episodes.intersection(allowed_target)', method)
        self.assertIn('selection["episodes"] = sorted(matched_episodes)', method)
        self.assertIn('【频道云添加】', method)
        self.assertIn('ED2K 已解析但真实文件无法确认覆盖当前缺集', method)

    def test_release_metadata_is_v1112(self):
        entry = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
        package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
        local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(package["version"], "1.12.13")
        self.assertEqual(local["version"], "1.12.13")
        self.assertIn('plugin_version = "1.12.13"', entry)
        self.assertIn('build_id = "20260905-r59"', entry)
        self.assertIn('v1.11.2', package.get("history") or {})


if __name__ == "__main__":
    unittest.main()
