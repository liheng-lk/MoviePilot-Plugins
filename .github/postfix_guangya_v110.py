from pathlib import Path

src = Path('plugins.v3/guangyatransferassistant/__init__.py')
text = src.read_text(encoding='utf-8')

# Preserve the established success notification title while reporting incremental details in the body.
text = text.replace('title="✅ 光鸭增量转存成功"', 'title="✅ 光鸭转存成功"')

# Track whether there was actually new content to restore. A readable match with a failed new-file restore
# must not be misclassified as "already synchronized".
text = text.replace('        valid_match = False\n        target_path = self._target_path(subscribe)', '        valid_match = False\n        attempted_new = False\n        target_path = self._target_path(subscribe)', 1)
text = text.replace('            logger.info("【光鸭转存助手】【增量】#%s %s share_id=%s 扫描文件=%s，新增待转=%s，已记录=%s",', '            attempted_new = True\n            logger.info("【光鸭转存助手】【增量】#%s %s share_id=%s 扫描文件=%s，新增待转=%s，已记录=%s",', 1)
text = text.replace('        if valid_match:\n            # 有可读匹配分享但没有新增，说明该订阅已经被光鸭路线满足，不能再触发原生下载造成重复。', '        if valid_match and not attempted_new:\n            # 有可读匹配分享且没有新增，说明该订阅已经被光鸭路线满足，不能再触发原生下载造成重复。', 1)

old = '''        final_message = "；".join(errors[:4]) or "匹配分享均不可用"\n        logger.warning("【光鸭转存助手】【回退】#%s %s 转存资源不可用：%s；%s", sid, getattr(subscribe, "name", ""), final_message, "将回退 MoviePilot 原生下载" if self._fallback_native else "原生下载回退已关闭")\n        return {"success": False, "handled": False, "message": final_message}\n'''
new = '''        final_message = "；".join(errors[:4]) or "匹配分享均不可用"\n        logger.warning("【光鸭转存助手】【回退】#%s %s 增量转存未完成：%s；%s", sid, getattr(subscribe, "name", ""), final_message, "将回退 MoviePilot 原生下载" if self._fallback_native else "原生下载回退已关闭")\n        if self._notify and matches:\n            notices = self.get_data("failure_notices") or {}\n            notice_key = f"{sid}:{hashlib.sha256(final_message.encode('utf-8')).hexdigest()[:12]}"\n            last_notice = self._parse_datetime(notices.get(notice_key))\n            now = datetime.datetime.now()\n            if not last_notice or (now - last_notice).total_seconds() >= 6 * 3600:\n                try:\n                    self.post_message(\n                        mtype=NotificationType.Plugin,\n                        title="⚠️ 光鸭转存失败",\n                        text=(\n                            f"媒体：{getattr(subscribe, 'name', '')} ({getattr(subscribe, 'year', '') or '-'})\\n"\n                            f"状态：增量转存未完成\\n原因：{final_message}\\n"\n                            + ("后续：将回退 MoviePilot 原生下载" if self._fallback_native else "后续：原生下载回退已关闭")\n                        ),\n                    )\n                    notices[notice_key] = now.strftime("%Y-%m-%d %H:%M:%S")\n                    self.save_data("failure_notices", notices)\n                    logger.info("【光鸭转存助手】【通知】已发送转存失败通知：#%s %s（相同错误 6 小时内不重复推送）", sid, getattr(subscribe, "name", ""))\n                except Exception as err:\n                    logger.warning("【光鸭转存助手】【通知】发送失败通知异常：%s", err)\n        return {"success": False, "handled": False, "message": final_message}\n'''
assert old in text
text = text.replace(old, new, 1)
src.write_text(text, encoding='utf-8')

# Align old notification contract with the incremental implementation.
test_path = Path('tests/v3/guangyatransferassistant/test_plugin_contract.py')
test = test_path.read_text(encoding='utf-8')
test = test.replace("assert '光鸭异步任务已确认完成' in text", "assert '所有增量转存任务已确认完成' in text")
test = test.replace("assert 'task_id' in text", "assert 'task_ids' in text")
if 'failure_notices' not in test:
    test += '''\n\ndef test_incremental_failure_is_not_misclassified_and_is_rate_limited():\n    text = SRC.read_text(encoding="utf-8")\n    assert 'attempted_new = False' in text\n    assert 'if valid_match and not attempted_new:' in text\n    assert 'failure_notices' in text\n    assert '6 * 3600' in text\n    assert '⚠️ 光鸭转存失败' in text\n'''
test_path.write_text(test, encoding='utf-8')
