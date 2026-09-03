import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
RECEIPT = (PLUGIN / "receipt_completion_v1124.py").read_text(encoding="utf-8")


class GuangYaReceiptCompletionV1124Tests(unittest.TestCase):
    def test_sources_parse_and_layer_is_outermost(self):
        ast.parse(ENTRY)
        ast.parse(RECEIPT)
        self.assertIn("from .receipt_completion_v1124 import GuangYaReceiptCompletionV1124Mixin", ENTRY)
        class_head = ENTRY.split("class GuangYaTransferAssistant(", 1)[1].split("):", 1)[0]
        first_mixin = next(line.strip().rstrip(",") for line in class_head.splitlines() if line.strip())
        self.assertEqual(first_mixin, "GuangYaReceiptCompletionV1124Mixin")

    def test_tv_success_receipt_is_persisted_before_next_search(self):
        method = RECEIPT.split("    def _save_xunlei_state(", 1)[1]
        self.assertLess(method.index("super()._save_xunlei_state(state)"), method.index("_remember_episode_facts"))
        self.assertIn('origin="xunlei_receipt_v1124"', method)
        self.assertIn("self._sync_media_facts_progress(subscribe)", method)
        self.assertIn("后续检索不再选择这些集", method)

    def test_movie_success_receipt_finishes_subscription_immediately(self):
        method = RECEIPT.split("    def _save_xunlei_state(", 1)[1]
        movie = method.split("if self._is_movie_subscription(subscribe):", 1)[1].split("episodes = sorted", 1)[0]
        self.assertIn("_remember_verified_movie_v1121", movie)
        self.assertIn("self._finish_subscription_if_complete(subscribe)", movie)
        self.assertIn("电影正片已成功存入光鸭", movie)

    def test_planner_keeps_only_one_video_for_same_episode(self):
        planner = RECEIPT.split("    def _planner_file_selection(", 1)[1].split("    def _save_xunlei_state(", 1)[0]
        self.assertIn("claimed: set[int] = set()", planner)
        self.assertIn("new_episodes = episodes - claimed", planner)
        self.assertIn("if not new_episodes:", planner)
        self.assertIn("keep_videos.add", planner)
        self.assertIn("单集单资源保护", planner)

    def test_movie_planner_reduces_source_to_one_primary_video(self):
        planner = RECEIPT.split("    def _planner_file_selection(", 1)[1].split("# TV：", 1)[0]
        self.assertIn("primary = max(videos", planner)
        self.assertIn("keep = {primary_index}", planner)
        self.assertIn("电影单资源保护", planner)


if __name__ == "__main__":
    unittest.main()
