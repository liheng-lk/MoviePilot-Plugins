from pathlib import Path

SRC = Path('plugins.v3/guangyatransferassistant/__init__.py')
TEST = Path('tests/v3/guangyatransferassistant/test_plugin_contract.py')
text = SRC.read_text(encoding='utf-8')

helper_anchor = '''    def _cancel_pending_jobs(self, subscribe: Any) -> Dict[str, Any]:\n'''
helper = r'''    def _pending_reservations(self, subscribe: Any, exclude_job_key: str = "") -> Dict[str, Any]:
        """收集同媒体其它在途任务已占用的路径/剧集，避免新频道消息重复提交相同内容。"""
        prefix = self._media_fact_prefix(subscribe)
        pending_status = {"submitted", "task_confirmed", "verifying"}
        paths = set()
        episodes = set()
        movie_pending = False
        for key, row in (self.get_data("transfer_jobs") or {}).items():
            if str(key) == str(exclude_job_key or "") or not isinstance(row, dict):
                continue
            if str(row.get("media") or "") != prefix or str(row.get("status") or "") not in pending_status:
                continue
            for raw_path in (row.get("paths") or []):
                path = _safe_relative_path(raw_path)
                if not path:
                    continue
                paths.add(path.lower())
                if _is_video(path) or _is_subtitle(path):
                    _, values = _episode_numbers(path)
                    episodes.update(int(value) for value in values)
                if self._is_movie_subscription(subscribe) and _is_video(path):
                    movie_pending = True
        return {"paths": paths, "episodes": episodes, "movie": movie_pending}

    def _filter_inflight_planned_items(
        self, subscribe: Any, planned: List[Dict[str, Any]], exclude_job_key: str = "",
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        reservations = self._pending_reservations(subscribe, exclude_job_key=exclude_job_key)
        if not reservations["paths"] and not reservations["episodes"] and not reservations["movie"]:
            return list(planned), []
        ready: List[Dict[str, Any]] = []
        held: List[Dict[str, Any]] = []
        for item in planned:
            path = _safe_relative_path(item.get("effective_path") or item.get("relative_path") or item.get("name") or "")
            lowered = path.lower()
            blocked = bool(lowered and lowered in reservations["paths"])
            if not blocked and reservations["movie"] and self._is_movie_subscription(subscribe):
                blocked = bool(_is_video(path) or _is_subtitle(path))
            if not blocked and reservations["episodes"]:
                _, values = _episode_numbers(path)
                blocked = bool(set(values).intersection(reservations["episodes"]))
            (held if blocked else ready).append(item)
        return ready, held

'''
if helper_anchor not in text:
    raise SystemExit('pending helper anchor not found')
text = text.replace(helper_anchor, helper + helper_anchor, 1)

old = '''            planned = self._plan_incremental_files(probe, assets, subscribe=subscribe, target_path=target_path, stats=stats)\n            valid_route_match = True\n            if stats.get("eligible", 0) <= 0:\n'''
new = '''            planned = self._plan_incremental_files(probe, assets, subscribe=subscribe, target_path=target_path, stats=stats)\n            valid_route_match = True\n            job_key = self._job_key(subscribe, entry)\n            planned, inflight_held = self._filter_inflight_planned_items(subscribe, planned, exclude_job_key=job_key)\n            if inflight_held:\n                pending_verification = True\n                logger.info(\n                    "【光鸭转存助手】【在途去重】#%s %s share_id=%s 新消息中 %s 个文件/剧集已被其它待落盘任务占用，本轮不重复提交",\n                    sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0], len(inflight_held),\n                )\n            if stats.get("eligible", 0) <= 0:\n'''
if old not in text:
    raise SystemExit('planner reservation insertion anchor not found')
text = text.replace(old, new, 1)

old = '''            if not planned:\n                synchronized_match = True\n                self._mark_entry_processed(entry, "synced", "库存或订阅进度已覆盖，无新增文件", subscribe)\n                logger.info(\n                    "【光鸭转存助手】【去重】#%s %s share_id=%s 无新增文件（库存=%s，已完成剧集/范围过滤=%s），跳过",\n                    sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0], stats.get("inventory", 0), stats.get("episode", 0),\n                )\n                continue\n\n            attempted_new = True\n'''
new = '''            if not planned:\n                synchronized_match = True\n                if inflight_held:\n                    logger.info(\n                        "【光鸭转存助手】【在途去重】#%s %s share_id=%s 本条新消息可转内容全部已在其它任务中，保留消息为待检查，不标记永久处理",\n                        sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0],\n                    )\n                    continue\n                self._mark_entry_processed(entry, "synced", "库存或订阅进度已覆盖，无新增文件", subscribe)\n                logger.info(\n                    "【光鸭转存助手】【去重】#%s %s share_id=%s 无新增文件（库存=%s，已完成剧集/范围过滤=%s），跳过",\n                    sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0], stats.get("inventory", 0), stats.get("episode", 0),\n                )\n                continue\n\n            attempted_new = True\n'''
if old not in text:
    raise SystemExit('inflight empty planner anchor not found')
text = text.replace(old, new, 1)

# job_key is already calculated before in-flight filtering; remove the later duplicate assignment.
old = '''            job_key = self._job_key(subscribe, entry)\n            job_paths = [str(item.get("effective_path") or item.get("relative_path") or item.get("name") or "") for item in planned]\n'''
new = '''            job_paths = [str(item.get("effective_path") or item.get("relative_path") or item.get("name") or "") for item in planned]\n'''
if old not in text:
    raise SystemExit('later job key anchor not found')
text = text.replace(old, new, 1)

SRC.write_text(text, encoding='utf-8')

tests = TEST.read_text(encoding='utf-8')
addition = r'''


def test_inflight_reservations_prevent_cross_message_duplicate_submission():
    assert '_pending_reservations' in text and '_filter_inflight_planned_items' in text
    flow = text.split('    def _try_transfer_subscription_inner(', 1)[1].split('    def _target_path(', 1)[0]
    plan_pos = flow.index('_plan_incremental_files')
    reserve_pos = flow.index('_filter_inflight_planned_items')
    submit_pos = flow.index('_restore_items')
    assert plan_pos < reserve_pos < submit_pos
    assert '【光鸭转存助手】【在途去重】' in flow
    assert '可转内容全部已在其它任务中' in flow
    helper = text.split('    def _pending_reservations(', 1)[1].split('    def _cancel_pending_jobs(', 1)[0]
    assert '{"submitted", "task_confirmed", "verifying"}' in helper
    assert 'episodes.update' in helper
    assert 'movie_pending = True' in helper


def test_inflight_only_message_is_not_marked_permanently_processed():
    flow = text.split('    def _try_transfer_subscription_inner(', 1)[1].split('    def _target_path(', 1)[0]
    block = flow.split('if not planned:', 1)[1].split('attempted_new = True', 1)[0]
    inflight = block.split('if inflight_held:', 1)[1].split('self._mark_entry_processed', 1)[0]
    assert 'continue' in inflight
    assert '_mark_entry_processed' not in inflight
'''
if 'test_inflight_reservations_prevent_cross_message_duplicate_submission' not in tests:
    tests += addition
TEST.write_text(tests, encoding='utf-8')
print('GuangYa v1.6.0 in-flight reservation safety applied')
