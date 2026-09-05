import ast
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
FENCE = PLUGIN / "episode_fence_v1124.py"
FINAL = PLUGIN / "episode_fence_final_v1124.py"
RECEIPT = PLUGIN / "receipt_completion_v1124.py"
ENTRY = PLUGIN / "__init__.py"


class GuangYaEpisodeFenceV1124Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fence = FENCE.read_text(encoding="utf-8")
        cls.final = FINAL.read_text(encoding="utf-8")
        cls.receipt = RECEIPT.read_text(encoding="utf-8")
        cls.entry = ENTRY.read_text(encoding="utf-8")

    def test_sources_parse_and_fence_is_in_runtime_mro(self):
        ast.parse(self.fence, filename=str(FENCE))
        ast.parse(self.final, filename=str(FINAL))
        ast.parse(self.receipt, filename=str(RECEIPT))
        ast.parse(self.entry, filename=str(ENTRY))
        self.assertIn("from .episode_fence_v1124 import GuangYaEpisodeFenceV1124Mixin", self.receipt)
        self.assertIn("class GuangYaReceiptCompletionV1124Mixin(GuangYaEpisodeFenceV1124Mixin):", self.receipt)
        self.assertIn("from .episode_fence_final_v1124 import GuangYaEpisodeFenceFinalV1124Mixin", self.entry)
        self.assertLess(
            self.entry.index("    GuangYaMediaIdentityGuardV1111Mixin,"),
            self.entry.index("    GuangYaEpisodeFenceFinalV1124Mixin,"),
        )
        self.assertLess(
            self.entry.index("    GuangYaEpisodeFenceFinalV1124Mixin,"),
            self.entry.index("    GuangYaReceiptCompletionV1124Mixin,"),
        )
        self.assertIn('build_id = "20260906-r63"', self.entry)

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

    def test_inflight_magnet_ed2k_claims_block_other_sources_but_not_themselves(self):
        method = self.final.split("    def _pending_reservations(", 1)[1].split(
            "    def _mark_uncancellable_source_v1124(", 1
        )[0]
        self.assertIn("_EXTERNAL_INFLIGHT_V1124", method)
        self.assertIn("current_source_id = self._episode_fence_current_source_v1124()", method)
        self.assertIn("source_id == current_source_id", method)
        self.assertIn("active_episode_claims.update(self._source_episode_targets_v1124(source))", method)
        self.assertIn("base[\"episodes\"].update(active_episode_claims)", method)
        self.assertIn("base[\"movie\"] = True", method)

    def test_magnet_and_ed2k_recheck_missing_before_create_retry_or_poll(self):
        prepare = self.final.split("    def _prepare_offline_source_v1124(", 1)[1].split(
            "    def _supersede_offline_sources_v1124(", 1
        )[0]
        self.assertIn("missing = set(self._subscription_missing_episodes(subscribe))", prepare)
        self.assertIn("remaining = targets.intersection(missing)", prepare)
        self.assertIn("self._delete_offline_task_v1124(source)", prepare)
        self.assertIn("target_episodes=sorted(remaining)", prepare)
        self.assertIn("resolved_episodes=[]", prepare)
        self.assertIn("selected_indexes=[]", prepare)
        self.assertIn("旧任务无法安全裁剪，已停止以避免重复", prepare)

    def test_success_receipt_immediately_cancels_or_resizes_other_offline_tasks(self):
        method = self.final.split("    def _supersede_offline_sources_v1124(", 1)[1].split(
            "    def _submit_offline_source(", 1
        )[0]
        self.assertIn("overlap = targets.intersection(acquired)", method)
        self.assertIn("self._prepare_offline_source_v1124(source, subscribe)", method)
        self.assertIn("self._spawn_source_dispatch(source_id)", method)
        self.assertIn("worker 会在当前媒体 RLock 释放后才真正提交", method)

    def test_poll_never_uses_cancelled_old_task_id(self):
        method = self.final.split("    def _poll_offline_source(", 1)[1].split(
            "    def _dispatch_xunlei_flash(", 1
        )[0]
        self.assertIn("allowed, prepared, message = self._prepare_offline_source_v1124(latest, fresh)", method)
        self.assertIn('if not str(prepared.get("task_id") or "").strip():', method)
        self.assertIn("super(GuangYaEpisodeFenceV1124Mixin, self)._poll_offline_source(prepared)", method)
        self.assertNotIn("_poll_offline_source(latest)\n        finally", method)

    def test_all_sources_share_one_media_level_submit_lock(self):
        main = self.fence.split("    def _try_transfer_subscription_inner(", 1)[1]
        offline = self.fence.split("    def _submit_offline_source(", 1)[1].split(
            "    def _poll_offline_source(", 1
        )[0]
        self.assertIn("lock = self._episode_fence_lock_v1124(current)", main)
        self.assertIn("with lock:", main)
        self.assertIn("lock = self._episode_fence_lock_v1124(subscribe)", offline)
        self.assertIn("with lock:", offline)
        final_submit = self.final.split("    def _submit_offline_source(", 1)[1].split(
            "    def _poll_offline_source(", 1
        )[0]
        self.assertIn("context.source_id = str(source_id or \"\")", final_submit)
        self.assertIn("return super()._submit_offline_source(source_id)", final_submit)

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

    def test_movie_inflight_source_blocks_second_xunlei_movie(self):
        method = self.final.split("    def _dispatch_xunlei_flash(", 1)[1]
        self.assertIn("pending = dict(self._pending_reservations(subscribe) or {})", method)
        self.assertIn('if bool(pending.get("movie")):', method)
        self.assertIn("电影已有成功/在途获取任务，跳过重复迅雷秒传", method)


if __name__ == "__main__":
    unittest.main()
