from pathlib import Path

src = Path('plugins.v3/guangyatransferassistant/__init__.py')
text = src.read_text(encoding='utf-8')

# 1) 先读取上次持久任务状态，再写 planned，避免覆盖 submitted/task_confirmed/verifying 导致重启恢复失效。
old = '''            job_key = self._job_key(subscribe, entry)\n            job_paths = [str(item.get("effective_path") or item.get("relative_path") or item.get("name") or "") for item in planned]\n            self._set_job_state(\n                job_key, "planned", subscribe_id=sid, media=self._media_fact_prefix(subscribe),\n                share_id=share_key.split("|", 1)[0], message_id=str(entry.get("message_id") or ""),\n                paths=job_paths, target=target_path, fingerprint=fingerprint,\n            )\n            logger.info(\n                "【光鸭转存助手】【增量】#%s %s share_id=%s 叶子文件=%s，符合范围=%s，新增待转=%s，本轮=%s，库存=%s，剧集过滤=%s",\n                sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0], probe.get("leaf_count") or len(probe.get("files") or []),\n                stats.get("eligible", 0), pending_count, len(planned), stats.get("inventory", 0) + stats.get("fact", 0), stats.get("episode", 0),\n            )\n            pending_job = self._get_job_state(job_key)\n            restored = None\n'''
new = '''            job_key = self._job_key(subscribe, entry)\n            job_paths = [str(item.get("effective_path") or item.get("relative_path") or item.get("name") or "") for item in planned]\n            pending_job = self._get_job_state(job_key)\n            restored = None\n            logger.info(\n                "【光鸭转存助手】【增量】#%s %s share_id=%s 叶子文件=%s，符合范围=%s，新增待转=%s，本轮=%s，库存=%s，剧集过滤=%s",\n                sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0], probe.get("leaf_count") or len(probe.get("files") or []),\n                stats.get("eligible", 0), pending_count, len(planned), stats.get("inventory", 0) + stats.get("fact", 0), stats.get("episode", 0),\n            )\n'''
if old not in text:
    raise SystemExit('runtime recovery planning block not found')
text = text.replace(old, new, 1)

old = '''            if restored is None:\n                restored = self._restore_items(probe, target_path, planned, job_key=job_key)\n'''
new = '''            if restored is None:\n                self._set_job_state(\n                    job_key, "planned", subscribe_id=sid, media=self._media_fact_prefix(subscribe),\n                    share_id=share_key.split("|", 1)[0], message_id=str(entry.get("message_id") or ""),\n                    paths=job_paths, target=target_path, fingerprint=fingerprint,\n                )\n                restored = self._restore_items(probe, target_path, planned, job_key=job_key)\n'''
if old not in text:
    raise SystemExit('restore submission block not found')
text = text.replace(old, new, 1)

# 2) 单次文件上限截断属于部分完成，通知/返回值都应明确仍有待下轮文件。
old = '            partial = bool(errors) and not completed_subscription\n'
new = '            partial = (bool(errors) or remaining_due_to_cap > 0) and not completed_subscription\n'
if old not in text:
    raise SystemExit('partial calculation not found')
text = text.replace(old, new, 1)

# 3) 术语统一。
text = text.replace('仅命中旧缓存，等待频道恢复', '仅命中故障回退索引，等待频道恢复')

# 4) 重启异常时最多等待 15 分钟接管遗留执行锁。
text = text.replace('    _run_lock_minutes = 30\n', '    _run_lock_minutes = 15\n', 1)

# 5) 媒体事实恢复进度只合并当前订阅目标范围，避免同季其它历史集污染 note。
old = '''        payload: Dict[str, Any] = {"note": sorted(merged)}\n        if total >= start:\n            target = set(range(start, total + 1))\n            payload["lack_episode"] = len(target - merged)\n'''
new = '''        if total >= start:\n            target = set(range(start, total + 1))\n            episodes = episodes.intersection(target)\n            merged = current | episodes\n        payload: Dict[str, Any] = {"note": sorted(merged)}\n        if total >= start:\n            payload["lack_episode"] = len(target - merged)\n'''
if old not in text:
    raise SystemExit('media fact target filtering block not found')
text = text.replace(old, new, 1)

src.write_text(text, encoding='utf-8')

# 增加针对真实重启恢复顺序和分批状态的回归合同。
test_path = Path('tests/v3/guangyatransferassistant/test_plugin_contract.py')
tests = test_path.read_text(encoding='utf-8')
addition = r'''


def test_restart_recovery_reads_old_job_before_planned_overwrite():
    flow = text.split('    def _try_transfer_subscription_inner(', 1)[1].split('    def _target_path(', 1)[0]
    read_pos = flow.index('pending_job = self._get_job_state(job_key)')
    planned_marker = 'job_key, "planned", subscribe_id=sid'
    planned_pos = flow.index(planned_marker)
    assert read_pos < planned_pos
    assert 'pending_job.get("status") in ("submitted", "task_confirmed", "verifying")' in flow


def test_file_cap_is_reported_as_partial_until_all_files_processed():
    flow = text.split('    def _try_transfer_subscription_inner(', 1)[1].split('    def _target_path(', 1)[0]
    assert 'partial = (bool(errors) or remaining_due_to_cap > 0) and not completed_subscription' in flow
    assert 'if deferred_for_entry <= 0:' in flow
    assert '本轮完成后仍有 %s 个文件待下轮，不标记消息完成' in flow


def test_media_fact_progress_is_clipped_to_current_subscription_target():
    block = text.split('    def _sync_media_facts_progress(', 1)[1].split('    def _processed_entry_key(', 1)[0]
    assert 'episodes = episodes.intersection(target)' in block
    assert 'merged = current | episodes' in block
'''
if 'test_restart_recovery_reads_old_job_before_planned_overwrite' not in tests:
    tests += addition

test_path.write_text(tests, encoding='utf-8')
print('GuangYa v1.4.0 runtime recovery correction applied')
