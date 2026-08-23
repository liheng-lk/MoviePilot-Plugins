from pathlib import Path
import json

p = Path('plugins.v3/guangyatransferassistant/__init__.py')
text = p.read_text(encoding='utf-8')

if 'from app.schemas import NotificationType' not in text:
    text = text.replace('from app.plugins import _PluginBase\n', 'from app.plugins import _PluginBase\nfrom app.schemas import NotificationType\n', 1)
text = text.replace('plugin_version = "1.0.0"', 'plugin_version = "1.0.1"', 1)

# 详情页显示最近一次转存时间和结果。
text = text.replace(
    '            state_text = recent[0].get("message") if recent else "等待频道匹配"\n',
    '            state_text = (f"{recent[0].get(\'time\') or \'-\'} · {recent[0].get(\'message\') or \'-\'}" if recent else "等待频道匹配")\n',
    1,
)

# 未命中和命中分享都留下可筛选后台日志。
text = text.replace(
    '        if not matches:\n            return {"success": False, "handled": False, "message": "频道未匹配到光鸭分享"}\n',
    '        if not matches:\n            logger.info("【光鸭转存助手】【匹配】#%s %s 未命中频道分享；%s", sid, getattr(subscribe, "name", ""), "将回退原生下载" if self._fallback_native else "原生下载回退已关闭")\n            return {"success": False, "handled": False, "message": "频道未匹配到光鸭分享"}\n        logger.info("【光鸭转存助手】【匹配】#%s %s 命中 %s 个频道分享", sid, getattr(subscribe, "name", ""), len(matches))\n',
    1,
)
text = text.replace(
    '            if not probe.get("success"):\n                errors.append(probe.get("message") or "分享读取失败")\n                continue\n',
    '            if not probe.get("success"):\n                error = str(probe.get("message") or "分享读取失败")\n                logger.warning("【光鸭转存助手】【匹配】分享读取失败 share_id=%s：%s", share_key.split("|", 1)[0], error)\n                errors.append(error)\n                continue\n',
    1,
)
text = text.replace(
    '            target_path = self._target_path(subscribe)\n            transferred = self._restore_share(share_url, target_path, probe=probe)\n',
    '            target_path = self._target_path(subscribe)\n            logger.info("【光鸭转存助手】【转存】准备转存 #%s %s：share_id=%s -> %s，扫描项目=%s，根项目=%s", sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0], target_path, probe.get("file_count") or 0, len(probe.get("root_ids") or []))\n            transferred = self._restore_share(share_url, target_path, probe=probe)\n',
    1,
)

# 历史记录增加任务确认信息。
text = text.replace(
    '                "message": transferred.get("message") or "",\n            }\n',
    '                "message": transferred.get("message") or "",\n                "task_id": transferred.get("task_id") or "",\n                "confirmed": bool(transferred.get("confirmed")),\n                "confirmation": transferred.get("confirmation") or "",\n                "root_count": transferred.get("root_count") or len(probe.get("root_ids") or []),\n                "file_count": transferred.get("file_count") or probe.get("file_count") or 0,\n            }\n',
    1,
)

old_success = '''            if transferred.get("success"):\n                logger.info("【光鸭转存助手】转存成功: #%s %s -> %s", sid, getattr(subscribe, "name", ""), target_path)\n                if self._notify:\n                    self.post_message(title="☁️ 光鸭转存成功", text=f"{getattr(subscribe, 'name', '')} ({getattr(subscribe, 'year', '') or '-'})\\n来源：{entry.get('source_label')}\\n目标：{target_path}")\n                return {"success": True, "handled": True, "message": "光鸭转存成功", "target_path": target_path, "share_url": share_url}\n            errors.append(transferred.get("message") or "转存失败")\n        return {"success": False, "handled": False, "message": "；".join(errors[:4]) or "匹配分享均不可用"}\n'''
new_success = '''            if transferred.get("success"):\n                logger.info(\n                    "【光鸭转存助手】【转存】成功 #%s %s -> %s；task_id=%s；确认=%s；根项目=%s；扫描项目=%s",\n                    sid, getattr(subscribe, "name", ""), target_path,\n                    transferred.get("task_id") or "无",\n                    transferred.get("confirmation") or "接口返回成功",\n                    transferred.get("root_count") or len(probe.get("root_ids") or []),\n                    transferred.get("file_count") or probe.get("file_count") or 0,\n                )\n                if self._notify:\n                    season = getattr(subscribe, "season", None)\n                    media_text = f"{getattr(subscribe, 'name', '')} ({getattr(subscribe, 'year', '') or '-'})"\n                    if season not in (None, "", 0, "0"):\n                        media_text += f" S{int(season):02d}"\n                    lines = [\n                        f"媒体：{media_text}",\n                        "状态：已确认转存完成" if transferred.get("confirmed") else "状态：光鸭接口已返回成功",\n                        f"来源：{entry.get('source_label') or '-'}",\n                        f"目标：{target_path}",\n                        f"根项目：{transferred.get('root_count') or len(probe.get('root_ids') or [])} 个",\n                        f"扫描项目：{transferred.get('file_count') or probe.get('file_count') or 0} 个",\n                    ]\n                    if transferred.get("task_id"):\n                        lines.append(f"任务ID：{transferred.get('task_id')}")\n                    if transferred.get("confirmation"):\n                        lines.append(f"确认：{transferred.get('confirmation')}")\n                    self.post_message(mtype=NotificationType.Plugin, title="✅ 光鸭转存成功", text="\\n".join(lines))\n                    logger.info("【光鸭转存助手】【通知】已发送转存成功通知：#%s %s", sid, getattr(subscribe, "name", ""))\n                return {\n                    "success": True, "handled": True, "message": "光鸭转存成功",\n                    "target_path": target_path, "share_url": share_url,\n                    "task_id": transferred.get("task_id") or "",\n                    "confirmed": bool(transferred.get("confirmed")),\n                }\n            error = str(transferred.get("message") or "转存失败")\n            logger.warning("【光鸭转存助手】【转存】失败 #%s %s share_id=%s：%s", sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0], error)\n            errors.append(error)\n        final_message = "；".join(errors[:4]) or "匹配分享均不可用"\n        logger.warning("【光鸭转存助手】【回退】#%s %s 转存未成功：%s；%s", sid, getattr(subscribe, "name", ""), final_message, "将回退 MoviePilot 原生下载" if self._fallback_native else "原生下载回退已关闭")\n        if self._notify and matches:\n            try:\n                self.post_message(\n                    mtype=NotificationType.Plugin,\n                    title="⚠️ 光鸭转存失败",\n                    text=(\n                        f"媒体：{getattr(subscribe, 'name', '')} ({getattr(subscribe, 'year', '') or '-'})\\n"\n                        f"状态：转存未完成\\n原因：{final_message}\\n"\n                        + ("后续：将回退 MoviePilot 原生下载" if self._fallback_native else "后续：原生下载回退已关闭")\n                    ),\n                )\n                logger.info("【光鸭转存助手】【通知】已发送转存失败通知：#%s %s", sid, getattr(subscribe, "name", ""))\n            except Exception as err:\n                logger.warning("【光鸭转存助手】【通知】发送失败通知异常：%s", err)\n        return {"success": False, "handled": False, "message": final_message}\n'''
assert old_success in text
text = text.replace(old_success, new_success, 1)

# restore_share：只有光鸭任务确认后才标记成功，并输出任务日志。
old_restore_tail = '''            data = response.get("data") or {}\n            task_id = str(data.get("taskId") or data.get("task_id") or "") if isinstance(data, dict) else ""\n            if task_id and hasattr(api, "_wait_task_done"):\n                done = api._wait_task_done(task_id, max_try=120, interval=1, allow_missing=True)\n                if not done:\n                    return {"success": False, "message": f"转存任务 {task_id} 未确认完成"}\n            return {"success": True, "message": f"已提交 {len(root_ids)} 个根目录项目到 {normalized}", "task_id": task_id}\n        except Exception as err:\n            return {"success": False, "message": f"光鸭转存异常: {err}"}\n'''
new_restore_tail = '''            data = response.get("data") or {}\n            task_id = str(data.get("taskId") or data.get("task_id") or "") if isinstance(data, dict) else ""\n            confirmed = False\n            if task_id and hasattr(api, "_wait_task_done"):\n                logger.info("【光鸭转存助手】【转存】等待光鸭任务完成：task_id=%s", task_id)\n                done = api._wait_task_done(task_id, max_try=120, interval=1, allow_missing=True)\n                if not done:\n                    logger.warning("【光鸭转存助手】【转存】任务未确认完成：task_id=%s", task_id)\n                    return {\n                        "success": False, "message": f"转存任务 {task_id} 未确认完成",\n                        "task_id": task_id, "confirmed": False,\n                        "root_count": len(root_ids), "file_count": probe.get("file_count") or 0,\n                    }\n                confirmed = True\n                confirmation = "光鸭异步任务已确认完成"\n                logger.info("【光鸭转存助手】【转存】任务已确认完成：task_id=%s", task_id)\n            else:\n                confirmed = True\n                confirmation = "光鸭接口同步返回成功（无异步任务ID）"\n                logger.info("【光鸭转存助手】【转存】接口同步返回成功，无异步 task_id")\n            return {\n                "success": True,\n                "message": f"已转存 {len(root_ids)} 个根目录项目到 {normalized}",\n                "task_id": task_id, "confirmed": confirmed, "confirmation": confirmation,\n                "root_count": len(root_ids), "file_count": probe.get("file_count") or 0,\n            }\n        except Exception as err:\n            logger.exception("【光鸭转存助手】【转存】执行转存发生异常：target=%s", save_path)\n            return {"success": False, "message": f"光鸭转存异常: {err}"}\n'''
assert old_restore_tail in text
text = text.replace(old_restore_tail, new_restore_tail, 1)
p.write_text(text, encoding='utf-8')

plugin_path = Path('plugins.v3/guangyatransferassistant/plugin.json')
plugin = json.loads(plugin_path.read_text(encoding='utf-8'))
plugin['version'] = '1.0.1'
plugin_path.write_text(json.dumps(plugin, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

package_path = Path('package.v3.json')
package = json.loads(package_path.read_text(encoding='utf-8'))
info = package['GuangYaTransferAssistant']
info['version'] = '1.0.1'
history = info.setdefault('history', {})
info['history'] = {
    'v1.0.1': '增加转存成功/失败 MoviePilot 消息推送、光鸭任务完成确认和后台分阶段日志；成功通知显示目标目录、来源频道、任务ID与文件数量。',
    **history,
}
package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

test_path = Path('tests/v3/guangyatransferassistant/test_plugin_contract.py')
test = test_path.read_text(encoding='utf-8')
if 'test_transfer_notification_and_logging_contract' not in test:
    test += '''\n\ndef test_transfer_notification_and_logging_contract():\n    text = PLUGIN.read_text(encoding="utf-8")\n    assert 'from app.schemas import NotificationType' in text\n    assert 'mtype=NotificationType.Plugin' in text\n    assert '✅ 光鸭转存成功' in text\n    assert '⚠️ 光鸭转存失败' in text\n    assert '【光鸭转存助手】【转存】' in text\n    assert '【光鸭转存助手】【回退】' in text\n    assert '【光鸭转存助手】【通知】' in text\n    assert '光鸭异步任务已确认完成' in text\n    assert 'confirmed' in text\n    assert 'task_id' in text\n'''
test_path.write_text(test, encoding='utf-8')
