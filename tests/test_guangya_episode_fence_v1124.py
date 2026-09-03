import ast
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
FENCE = PLUGIN / "episode_fence_v1124.py"
RECEIPT = PLUGIN / "receipt_completion_v1124.py"
ENTRY = PLUGIN / "__init__.py"


class GuangYaEpisodeFenceV1124Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fence = FENCE.read_text(encoding="utf-8")
        cls.receipt = RECEIPT.read_text(encoding="utf-8")
        cls.entry = ENTRY.read_text(encoding="utf-8")

    def test_sources_parse_and_fence_is_in_runtime_mro(self):
        ast.parse(self.fence, filename=str(FENCE))
        ast.parse(self.receipt, filename=str(RECEIPT))
        self.assertIn("from .episode_fence_v1124 import GuangYaEpisodeFenceV1124Mixin", self.receipt)
        self.assertIn("class GuangYaReceiptCompletionV1124Mixin(GuangYaEpisodeFenceV1124Mixin):", self.receipt)

    def test_success_facts_are_hard_missing_episode_fence(self):
        method = self.fence.split("    def _subscription_missing_episodes(", 1)[1].split(
            "    def _pending_reservations(", 1
        )[0]
        self.assertIn("parent_missing - self._acquired_episode_facts_v1124(subscribe)", method)
        pending = self.fence.split("    def _pending_reservations(", 1)[1].split(
            "    @staticmethod\n    def _planned_path_v1124", 1
        )[0]
        self.assertIn("base[\"episodes\"].update(self._acquired_episode_facts_v1124(subscribe))", pending)

    def test_direct_share_is_filtered_again_after_xunlei_receipt(self):
        helper = self.fence.split("    def _resolved_item_episodes_v1124(", 1)[1].split(
            "    def _filter_inflight_planned_items(", 1
        )[0]
        method = self.fence.split("    def _filter_inflight_planned_items(", 1)[1].split(
            "    @staticmethod\n    def _source_episode_targets_v1124", 1
        )[0]
        self.assertIn("resolve_episode(", helper)
        self.assertIn("self._resolved_item_episodes_v1124(subscribe, item, package_paths)", method)
        self.assertIn("overlap = episodes.intersection(acquired)", method)
        self.assertIn("blocked.append(item)", method)
        self.assertIn("【光鸭转存助手】【集级终止】", method)

    def test_magnet_and_ed2k_recheck_missing_before_create_or_retry(self):
        prepare = self.fence.split("    def _prepare_offline_source_v1124(", 1)[1].split(
            "    def _submit_offline_source(", 1
        )[0]
        self.assertIn("missing = set(self._subscription_missing_episodes(subscribe))", prepare)
        self.assertIn("remaining = targets.intersection(missing)", prepare)
        self.assertIn("/cloudcollection/v2/delete_task", self.fence)
        self.assertIn("target_episodes=sorted(remaining)", prepare)
        self.assertIn("宁可停止等待其它来源，也不重复入库", prepare)

    def test_all_sources_share_one_media_level_submit_lock(self):
        main = self.fence.split("    def _try_transfer_subscription_inner(", 1)[1]
        offline = self.fence.split("    def _submit_offline_source(", 1)[1].split(
            "    def _poll_offline_source(", 1
        )[0]
        self.assertIn("lock = self._episode_fence_lock_v1124(current)", main)
        self.assertIn("with lock:", main)
        self.assertIn("lock = self._episode_fence_lock_v1124(subscribe)", offline)
        self.assertIn("with lock:", offline)

    def test_every_episode_receipt_updates_moviepilot_and_supersedes_competitors(self):
        method = self.fence.split("    def _commit_episode_receipt_v1124(", 1)[1].split(
            "    def _remember_episode_facts(", 1
        )[0]
        self.assertIn("self._sync_media_facts_progress(current)", method)
        self.assertIn("self._supersede_offline_sources_v1124(current, acquired)", method)
        self.assertIn("self._supersede_share_jobs_v1124(current, acquired)", method)
        remember_media = self.fence.split("    def _remember_media_facts(", 1)[1].split(
            "    def _prepare_offline_source_v1124(", 1
        )[0]
        self.assertIn("self._remember_episode_facts(subscribe, episodes", remember_media)


if __name__ == "__main__":
    unittest.main()
