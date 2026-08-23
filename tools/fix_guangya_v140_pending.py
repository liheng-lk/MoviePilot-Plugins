from pathlib import Path

src = Path('plugins.v3/guangyatransferassistant/__init__.py')
text = src.read_text(encoding='utf-8')

# 聚合“已提交、等待落盘”状态，不把它当作普通失败，更不能自动重复提交。
old = '''        attempted_new = False\n        remaining_due_to_cap = 0\n        match_reasons = set()\n'''
new = '''        attempted_new = False\n        remaining_due_to_cap = 0\n        pending_verification = False\n        match_reasons = set()\n'''
if old not in text:
    raise SystemExit('state aggregation block not found')
text = text.replace(old, new, 1)

old = '''            if not force and pending_job.get("status") in ("submitted", "task_confirmed", "verifying") and set(pending_job.get("paths") or []) == set(job_paths):\n                updated = self._parse_datetime(pending_job.get("updated"))\n                age = (datetime.datetime.now() - updated).total_seconds() if updated else self._retry_minutes * 60 + 1\n                recovered = self._verify_restored_items(target_path, planned, max_try=1)\n                if recovered.get("success"):\n                    restored = {\n                        "success": True, "message": "恢复上次任务：目标文件已确认可见",\n                        "completed_items": list(recovered.get("verified_items") or planned),\n                        "task_ids": list(pending_job.get("task_ids") or []),\n                        "confirmation": "重启恢复后通过目标文件可见性确认",\n                    }\n                    self._set_job_state(job_key, "verified", recovered=True)\n                elif age < self._retry_minutes * 60:\n                    errors.append(f"share_id={share_key.split('|', 1)[0]} 已有任务待落盘确认，暂不重复提交")\n                    logger.info("【光鸭转存助手】【恢复】#%s %s share_id=%s 已有持久任务待确认，本轮不重复转存", sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0])\n                    continue\n'''
new = '''            if not force and pending_job.get("status") in ("submitted", "task_confirmed", "verifying") and set(pending_job.get("paths") or []) == set(job_paths):\n                updated = self._parse_datetime(pending_job.get("updated"))\n                age = (datetime.datetime.now() - updated).total_seconds() if updated else self._retry_minutes * 60 + 1\n                recovered = self._verify_restored_items(target_path, planned, max_try=1)\n                if recovered.get("success"):\n                    restored = {\n                        "success": True, "message": "恢复上次任务：目标文件已确认可见",\n                        "completed_items": list(recovered.get("verified_items") or planned),\n                        "task_ids": list(pending_job.get("task_ids") or []),\n                        "confirmation": "重启恢复后通过目标文件可见性确认",\n                    }\n                    self._set_job_state(job_key, "verified", recovered=True)\n                else:\n                    pending_verification = True\n                    wait_text = "等待落盘确认" if age < self._retry_minutes * 60 else "落盘确认已超等待窗口，保持待确认以避免重复提交"\n                    self._set_job_state(job_key, "verifying", verification_message=wait_text)\n                    logger.warning(\n                        "【光鸭转存助手】【恢复】#%s %s share_id=%s %s；已提交任务不会自动重复提交",\n                        sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0], wait_text,\n                    )\n                    continue\n'''
if old not in text:
    raise SystemExit('pending recovery block not found')
text = text.replace(old, new, 1)

# 底层可见性未确认不是“明确失败”，返回 pending_verification，让上层保留 verifying。
old = '''                    return {"success": False, "message": message, "completed_items": completed, "task_ids": task_ids}\n                completed.extend(verified.get("verified_items") or group)\n'''
new = '''                    return {\n                        "success": False, "pending_verification": True, "message": message,\n                        "completed_items": completed, "task_ids": task_ids,\n                    }\n                completed.extend(verified.get("verified_items") or group)\n'''
if old not in text:
    raise SystemExit('verification pending return not found')
text = text.replace(old, new, 1)

# 上层不要覆盖 verifying -> failed；真正任务/API失败仍走 failed。
old = '''            else:\n                self._set_job_state(job_key, "failed", error=str(restored.get("message") or "增量转存失败"))\n                errors.append(str(restored.get("message") or "增量转存失败"))\n\n        unique_paths = []\n'''
new = '''            else:\n                if restored.get("pending_verification"):\n                    pending_verification = True\n                    self._set_job_state(job_key, "verifying", verification_message=str(restored.get("message") or "等待落盘确认"))\n                    logger.warning(\n                        "【光鸭转存助手】【落盘确认】#%s %s share_id=%s 任务已提交但文件尚未全部确认；保持待确认，不自动重复提交",\n                        sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0],\n                    )\n                else:\n                    self._set_job_state(job_key, "failed", error=str(restored.get("message") or "增量转存失败"))\n                    errors.append(str(restored.get("message") or "增量转存失败"))\n\n        unique_paths = []\n'''
if old not in text:
    raise SystemExit('caller failure overwrite block not found')
text = text.replace(old, new, 1)

# 有部分文件已完成、另一些待落盘时，通知明确为部分状态。
old = '            partial = (bool(errors) or remaining_due_to_cap > 0) and not completed_subscription\n'
new = '            partial = (bool(errors) or remaining_due_to_cap > 0 or pending_verification) and not completed_subscription\n'
if old not in text:
    raise SystemExit('partial state block not found')
text = text.replace(old, new, 1)

# 没有任何新文件完成，但已有任务待落盘时直接返回“待确认”，不发普通失败通知。
needle = '''        final_message = "；".join(dict.fromkeys(errors))[:1200] or "匹配分享均不可用"\n'''
insert = '''        if pending_verification and not errors:\n            logger.info(\n                "【光鸭转存助手】【落盘确认】#%s %s 已有转存任务等待目标文件确认；本轮不重复提交、不触发失败通知",\n                sid, getattr(subscribe, "name", ""),\n            )\n            return {\n                "success": True, "handled": True, "pending": True,\n                "message": "转存任务已提交，等待目标文件落盘确认；不会重复提交",\n            }\n\n        final_message = "；".join(dict.fromkeys(errors))[:1200] or "匹配分享均不可用"\n'''
if needle not in text:
    raise SystemExit('final failure block not found')
text = text.replace(needle, insert, 1)

src.write_text(text, encoding='utf-8')

test_path = Path('tests/v3/guangyatransferassistant/test_plugin_contract.py')
tests = test_path.read_text(encoding='utf-8')
addition = r'''


def test_pending_visibility_never_downgrades_to_failed_or_auto_replays():
    flow = text.split('    def _try_transfer_subscription_inner(', 1)[1].split('    def _target_path(', 1)[0]
    assert 'pending_verification = False' in flow
    assert '已提交任务不会自动重复提交' in flow
    assert 'if restored.get("pending_verification"):' in flow
    pending_branch = flow.split('if restored.get("pending_verification"):', 1)[1].split('else:', 1)[0]
    assert '_set_job_state(job_key, "verifying"' in pending_branch
    assert '_set_job_state(job_key, "failed"' not in pending_branch
    assert 'if pending_verification and not errors:' in flow
    assert '不会重复提交' in flow


def test_visibility_timeout_remains_pending_until_manual_force():
    flow = text.split('    def _try_transfer_subscription_inner(', 1)[1].split('    def _target_path(', 1)[0]
    recovery = flow.split('pending_job.get("status") in ("submitted", "task_confirmed", "verifying")', 1)[1].split('if restored is None:', 1)[0]
    assert '落盘确认已超等待窗口，保持待确认以避免重复提交' in recovery
    assert 'continue' in recovery
    assert 'force' in flow
    restore = text.split('    def _restore_items(', 1)[1].split('    def _restore_share(', 1)[0]
    assert '"pending_verification": True' in restore
'''
if 'test_pending_visibility_never_downgrades_to_failed_or_auto_replays' not in tests:
    tests += addition

test_path.write_text(tests, encoding='utf-8')
print('GuangYa v1.4.0 pending verification safety applied')
