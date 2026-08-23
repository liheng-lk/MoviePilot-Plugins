from pathlib import Path
import json

ROOT = Path('.')
SRC = ROOT / 'plugins.v3' / 'guangyatransferassistant' / '__init__.py'
TEST = ROOT / 'tests' / 'v3' / 'guangyatransferassistant' / 'test_plugin_contract.py'
PACKAGE = ROOT / 'package.v3.json'
PLUGIN = ROOT / 'plugins.v3' / 'guangyatransferassistant' / 'plugin.json'

text = SRC.read_text(encoding='utf-8')


def replace_once(old: str, new: str, label: str) -> None:
    global text
    if old not in text:
        raise SystemExit(f'{label} anchor not found')
    text = text.replace(old, new, 1)


# Cron service support for optional daily summary.
replace_once(
    'from urllib.parse import parse_qs, urlencode, unquote, urljoin, urlsplit, urlunsplit\n\nfrom app.chain.subscribe',
    'from urllib.parse import parse_qs, urlencode, unquote, urljoin, urlsplit, urlunsplit\n\nfrom apscheduler.triggers.cron import CronTrigger\n\nfrom app.chain.subscribe',
    'cron import',
)

# Season 0 must participate in explicit season matching.
replace_once(
    '    if season not in (None, "", 0, "0"):\n        explicit = re.findall(r"(?i)\\bS(?:eason)?\\s*0*(\\d{1,2})\\b", text_value)\n        if explicit and int(season) not in {int(value) for value in explicit}:\n            return False\n',
    '    if season not in (None, ""):\n        explicit = re.findall(r"(?i)\\bS(?:eason)?\\s*0*(\\d{1,2})\\b", text_value)\n        if explicit and int(season) not in {int(value) for value in explicit}:\n            return False\n',
    'season matcher',
)

# Special/OVA/OAD/SP files are season 0 facts. Only use the special parser when
# no normal episode token has already been identified, avoiding mixed-token pollution.
replace_once(
    '    # 中文 第23-25集 / 第23至25话。\n    for matched in re.finditer(r"第\\s*(\\d{1,4})(?:\\s*[-~—至]\\s*(\\d{1,4}))?\\s*[集话]", value):\n        start = int(matched.group(1))\n        end = int(matched.group(2)) if matched.group(2) else start\n        if end >= start and end - start <= 300:\n            episodes.update(range(start, end + 1))\n\n    return season, sorted(ep for ep in episodes if ep > 0)\n',
    '    # 中文 第23-25集 / 第23至25话。\n    for matched in re.finditer(r"第\\s*(\\d{1,4})(?:\\s*[-~—至]\\s*(\\d{1,4}))?\\s*[集话]", value):\n        start = int(matched.group(1))\n        end = int(matched.group(2)) if matched.group(2) else start\n        if end >= start and end - start <= 300:\n            episodes.update(range(start, end + 1))\n\n    # 特别篇 / SP / OVA / OAD 属于 Season 0。只有没有普通季集标记时才启用，\n    # 防止 Show.S01E08.SP1 把 SP1 误并入第一季完成集。\n    if not episodes:\n        special = re.search(\n            r"(?i)(?:^|[^A-Za-z0-9])(?:SP|SPECIAL|OVA|OAD)[\\s._-]*0*(\\d{1,4})(?=[^0-9]|$)",\n            value,\n        )\n        if not special:\n            special = re.search(r"(?:特别篇|番外|特典)\\s*0*(\\d{1,4})(?=[^0-9]|$)", value)\n        if special:\n            season = 0\n            episodes.add(int(special.group(1)))\n\n    return season, sorted(ep for ep in episodes if ep > 0)\n',
    'special parser',
)

replace_once('    plugin_version = "1.5.0"\n', '    plugin_version = "1.6.0"\n', 'plugin version')
replace_once(
    '    _notify = True\n    _auto_transfer_on_refresh = True\n',
    '    _notify = True\n    _daily_summary = False\n    _summary_cron = "30 22 * * *"\n    _auto_transfer_on_refresh = True\n',
    'class summary config',
)
replace_once('    _data_schema_version = 4\n', '    _data_schema_version = 5\n', 'schema version')

replace_once(
    '        self._notify = bool(config.get("notify", True))\n        self._auto_transfer_on_refresh = bool(config.get("auto_transfer_on_refresh", True))\n',
    '        self._notify = bool(config.get("notify", True))\n        self._daily_summary = bool(config.get("daily_summary", False))\n        self._summary_cron = str(config.get("summary_cron") or "30 22 * * *").strip()\n        self._auto_transfer_on_refresh = bool(config.get("auto_transfer_on_refresh", True))\n',
    'init summary config',
)

# Interval watcher + optional cron summary.
replace_once(
    '''    def get_service(self) -> List[Dict[str, Any]]:\n        if not self._enabled:\n            return []\n        return [{\n            "id": "GuangYaTransferAssistantTick",\n            "name": "光鸭转存助手频道刷新与路由守护",\n            "trigger": "interval",\n            "func": self._tick,\n            "kwargs": {"minutes": self._refresh_minutes},\n        }]\n''',
    '''    def get_service(self) -> List[Dict[str, Any]]:\n        if not self._enabled:\n            return []\n        services: List[Dict[str, Any]] = [{\n            "id": "GuangYaTransferAssistantTick",\n            "name": "光鸭转存助手频道刷新与路由守护",\n            "trigger": "interval",\n            "func": self._tick,\n            "kwargs": {"minutes": self._refresh_minutes},\n        }]\n        if self._daily_summary:\n            try:\n                summary_trigger = CronTrigger.from_crontab(self._summary_cron)\n            except Exception:\n                logger.warning("【光鸭转存助手】【日报】Cron 配置无效，回退到每天 22:30")\n                summary_trigger = CronTrigger.from_crontab("30 22 * * *")\n            services.append({\n                "id": "GuangYaTransferAssistantDailySummary",\n                "name": "光鸭转存助手每日摘要",\n                "trigger": summary_trigger,\n                "func": self._send_daily_summary,\n                "kwargs": {},\n            })\n        return services\n''',
    'service block',
)

# Add daily summary form controls after the top switches.
form_anchor = '''                {"component": "VRow", "content": [\n                    {"component": "VCol", "props": {"cols": 12, "md": 7}, "content": [{"component": "VAutocomplete", "props": {"model": "selected_subscriptions", "label": "搜索并选择仅使用光鸭转存的订阅", "items": subscriptions, "multiple": True, "chips": True, "closable-chips": True, "clearable": True, "hide-selected": False, "hint": "可按剧名、年份、季、类型或订阅ID搜索", "persistent-hint": True, "prepend-inner-icon": "mdi-magnify"}}]},\n'''
form_insert = '''                {"component": "VRow", "content": [\n                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "daily_summary", "label": "每日转存摘要"}}]},\n                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VTextField", "props": {"model": "summary_cron", "label": "摘要 Cron", "hint": "默认每天 22:30；关闭摘要时不会注册任务", "persistent-hint": True}}]},\n                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [{"component": "VAlert", "props": {"type": "info", "variant": "tonal", "text": "日报只汇总当天新增文件、失败/待落盘任务和缺集/连载状态，不改变任何订阅或转存路线。"}}]},\n                ]},\n''' + form_anchor
replace_once(form_anchor, form_insert, 'summary form')

replace_once(
    '            "notify": self._notify,\n            "auto_transfer_on_refresh": self._auto_transfer_on_refresh,\n',
    '            "notify": self._notify,\n            "daily_summary": self._daily_summary,\n            "summary_cron": self._summary_cron or "30 22 * * *",\n            "auto_transfer_on_refresh": self._auto_transfer_on_refresh,\n',
    'form defaults summary',
)

# Console gains cancelled state visibility.
replace_once(
    '        failed_jobs = [row for row in jobs if str(row.get("status") or "") == "failed"]\n',
    '        failed_jobs = [row for row in jobs if str(row.get("status") or "") == "failed"]\n        cancelled_jobs = [row for row in jobs if str(row.get("status") or "") == "cancelled"]\n',
    'console cancelled jobs',
)
replace_once(
    '        elif latest_status == "failed" and failed_jobs:\n            label = "最近转存失败，等待新消息/重试"\n            alert_type = "error"\n',
    '        elif latest_status == "failed" and failed_jobs:\n            label = "最近转存失败，等待新消息/重试"\n            alert_type = "error"\n        elif latest_status == "cancelled" and cancelled_jobs:\n            label = "旧卡住任务已忽略 · 等待新消息"\n            alert_type = "warning"\n',
    'console cancelled label',
)
replace_once(
    '            "pending_jobs": len(pending_jobs), "failed_jobs": len(failed_jobs),\n',
    '            "pending_jobs": len(pending_jobs), "failed_jobs": len(failed_jobs), "cancelled_jobs": len(cancelled_jobs),\n',
    'console cancelled return',
)

# Reset explicitly clears cancelled jobs; that is the intentional way to retry an old ignored message.
replace_once(
    'str(row.get("status") or "") in {"failed", "synced", "verified"}',
    'str(row.get("status") or "") in {"failed", "synced", "verified", "cancelled"}',
    'reset cancelled jobs',
)

# Insert operations helpers before get_page.
page_marker = '    def get_page(self) -> Optional[List[dict]]:\n'
if page_marker not in text:
    raise SystemExit('get_page marker not found')
helpers = r'''    def _pending_jobs_for_subscription(self, subscribe: Any) -> List[Tuple[str, Dict[str, Any]]]:
        prefix = self._media_fact_prefix(subscribe)
        pending_status = {"submitted", "task_confirmed", "verifying"}
        rows = []
        for key, row in (self.get_data("transfer_jobs") or {}).items():
            if not isinstance(row, dict) or str(row.get("media") or "") != prefix:
                continue
            if str(row.get("status") or "") in pending_status:
                rows.append((str(key), dict(row)))
        rows.sort(key=lambda pair: str((pair[1] or {}).get("updated") or ""), reverse=True)
        return rows

    def _cancel_pending_jobs(self, subscribe: Any) -> Dict[str, Any]:
        """人工忽略当前媒体所有待落盘任务；旧消息保持 cancelled，不会自动重新提交。"""
        pending = self._pending_jobs_for_subscription(subscribe)
        if not pending:
            return {"success": False, "message": "当前没有待落盘任务"}
        jobs = self.get_data("transfer_jobs") or {}
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for key, row in pending:
            current = dict(jobs.get(key) or row)
            current["status"] = "cancelled"
            current["updated"] = now
            current["cancel_reason"] = "用户手动忽略待落盘任务；等待新消息，旧任务不自动重放"
            jobs[key] = current
        self.save_data("transfer_jobs", jobs)
        logger.warning(
            "【光鸭转存助手】【人工任务】#%s %s 已忽略 %s 个待落盘任务；旧消息不会自动重放，若需重试旧消息请先使用重置检查状态",
            int(getattr(subscribe, "id", 0) or 0), getattr(subscribe, "name", ""), len(pending),
        )
        return {"success": True, "count": len(pending), "message": f"已忽略 {len(pending)} 个待落盘任务；旧消息不会自动重放，等待新消息"}

    def _task_audit_rows(self, limit: int = 40) -> List[Dict[str, Any]]:
        jobs = self.get_data("transfer_jobs") or {}
        rows = []
        for key, raw in jobs.items():
            if not isinstance(raw, dict):
                continue
            row = dict(raw)
            row["job_key"] = str(key)
            rows.append(row)
        rows.sort(key=lambda row: str(row.get("updated") or ""), reverse=True)
        return rows[:max(1, min(int(limit or 40), 100))]

    def _send_daily_summary(self, force: bool = False) -> Dict[str, Any]:
        """发送当天运行摘要；定时任务按日期去重，手动触发可 force。"""
        now = datetime.datetime.now()
        day = now.strftime("%Y-%m-%d")
        state = self.get_data("daily_summary_state") or {}
        if not force and str(state.get("date") or "") == day:
            return {"success": True, "skipped": True, "message": "今日摘要已发送"}

        history = self.get_data("transfer_history") or {}
        today_history = [row for row in history.values() if isinstance(row, dict) and str(row.get("time") or "").startswith(day)]
        successful = [row for row in today_history if bool(row.get("success"))]
        new_files = sum(max(0, int(row.get("new_count") or 0)) for row in successful)

        jobs = [row for row in (self.get_data("transfer_jobs") or {}).values() if isinstance(row, dict) and str(row.get("updated") or "").startswith(day)]
        failed = sum(1 for row in jobs if str(row.get("status") or "") == "failed")
        pending = sum(1 for row in jobs if str(row.get("status") or "") in {"submitted", "task_confirmed", "verifying"})
        cancelled = sum(1 for row in jobs if str(row.get("status") or "") == "cancelled")

        index_items = (self.get_data("channel_index") or {}).get("items") or []
        selected = set(self._selected_subscriptions)
        subs = [sub for sub in self._list_subscriptions(None) if int(getattr(sub, "id", 0) or 0) in selected]
        missing_subs = 0
        ongoing_subs = 0
        for sub in subs:
            snap = self._subscription_console_snapshot(sub, index_items)
            if int(snap.get("lack") or 0) > 0:
                missing_subs += 1
            if bool((snap.get("channel_state") or {}).get("ongoing")):
                ongoing_subs += 1

        lines = [
            f"日期：{day}",
            f"本日新增文件：{new_files}",
            f"成功转存记录：{len(successful)}",
            f"失败任务：{failed}",
            f"待落盘确认：{pending}",
            f"已人工忽略任务：{cancelled}",
            f"当前转存订阅：{len(subs)}",
            f"仍有缺集订阅：{missing_subs}",
            f"连载中订阅：{ongoing_subs}",
        ]
        try:
            self.post_message(mtype=NotificationType.Plugin, title="📊 光鸭转存日报", text="\n".join(lines))
            self.save_data("daily_summary_state", {"date": day, "time": now.strftime("%Y-%m-%d %H:%M:%S")})
            logger.info("【光鸭转存助手】【日报】已发送：新增文件=%s，失败=%s，待落盘=%s，订阅=%s", new_files, failed, pending, len(subs))
            return {"success": True, "message": "每日摘要已发送", "new_files": new_files, "failed": failed, "pending": pending}
        except Exception as err:
            logger.warning("【光鸭转存助手】【日报】发送失败：%s", err)
            return {"success": False, "message": f"摘要发送失败：{err}"}

'''
text = text.replace(page_marker, helpers + page_marker, 1)

# Add pending-ignore button beside safe recheck.
button_anchor = '''                actions.append({\n                    "component": "VBtn",\n                    "props": {"size": "small", "variant": "outlined", "color": "warning", "prepend-icon": "mdi-file-sync-outline"},\n                    "text": "复查待落盘",\n                    "events": {"click": {"api": "plugin/GuangYaTransferAssistant/recheck_pending", "method": "get", "params": {"subscribe_id": sid, "token": settings.API_TOKEN}}},\n                })\n'''
button_new = button_anchor + '''                actions.append({\n                    "component": "VBtn",\n                    "props": {"size": "small", "variant": "text", "color": "error", "prepend-icon": "mdi-cancel"},\n                    "text": "忽略卡住任务",\n                    "events": {"click": {"api": "plugin/GuangYaTransferAssistant/cancel_pending", "method": "get", "params": {"subscribe_id": sid, "token": settings.API_TOKEN}}},\n                })\n'''
replace_once(button_anchor, button_new, 'pending cancel button')

# Add task audit list after subscription cards and before channel resources.
rows_anchor = '''        if rows:\n            contents.append({"component": "div", "props": {"class": "grid gap-3 grid-info-card mt-3"}, "content": rows})\n\n        resources = []\n'''
audit_block = '''        if rows:\n            contents.append({"component": "div", "props": {"class": "grid gap-3 grid-info-card mt-3"}, "content": rows})\n\n        audit = []\n        for row in self._task_audit_rows(40):\n            paths = [str(value) for value in (row.get("paths") or []) if value]\n            detail = str(row.get("error") or row.get("verification_message") or row.get("cancel_reason") or row.get("message") or "").strip()\n            if paths:\n                detail = (detail + (" · " if detail else "") + "文件：" + "、".join(paths[:4]) + (f" 等{len(paths)}个" if len(paths) > 4 else ""))\n            audit.append({\n                "component": "VListItem",\n                "props": {\n                    "title": f"{row.get('updated') or '-'} · {row.get('status') or '-'} · {row.get('media') or '-'}",\n                    "subtitle": f"消息 {row.get('message_id') or '-'} · 分享 {row.get('share_id') or '-'} · {detail[:500] or '无附加错误'}",\n                },\n            })\n        contents.append({\n            "component": "VCard",\n            "props": {"variant": "outlined", "class": "mt-4"},\n            "content": [\n                {"component": "VCardTitle", "text": f"转存任务审计（最近 {len(audit)} 条）"},\n                {"component": "VCardText", "text": "submitted/task_confirmed/verifying 表示任务已经提交，不能用‘立即检查缺集’强制重放；如确需忽略卡住任务，请使用订阅卡片上的人工操作。"},\n                {"component": "VList", "props": {"density": "compact"}, "content": audit or [{"component": "VListItem", "props": {"title": "暂无转存任务记录"}}]},\n            ],\n        })\n\n        resources = []\n'''
replace_once(rows_anchor, audit_block, 'audit card')

# API endpoints.
replace_once(
    '            {"path": "/reset_state", "endpoint": self.api_reset_state, "methods": ["GET"], "summary": "安全重置指定订阅的频道检查状态，保留媒体事实/库存/进度"},\n',
    '            {"path": "/reset_state", "endpoint": self.api_reset_state, "methods": ["GET"], "summary": "安全重置指定订阅的频道检查状态，保留媒体事实/库存/进度"},\n            {"path": "/cancel_pending", "endpoint": self.api_cancel_pending, "methods": ["GET"], "summary": "人工忽略指定订阅待落盘任务，旧消息不自动重放"},\n            {"path": "/daily_summary", "endpoint": self.api_daily_summary, "methods": ["GET"], "summary": "立即发送一次光鸭转存摘要"},\n',
    'api routes',
)

# Manual missing check must never force through an unresolved submitted task.
replace_once(
    '''        if sid not in set(self._selected_subscriptions):\n            return {"success": False, "message": "该订阅当前不是光鸭固定转存路线"}\n        self.refresh_channels(force=True)\n        self._inspect_cache.clear()\n        result = self._try_transfer_subscription(subscribe, force=True)\n''',
    '''        if sid not in set(self._selected_subscriptions):\n            return {"success": False, "message": "该订阅当前不是光鸭固定转存路线"}\n        pending = self._pending_jobs_for_subscription(subscribe)\n        if pending:\n            return {\n                "success": False, "pending": True,\n                "message": f"仍有 {len(pending)} 个已提交任务等待落盘确认；请先使用‘复查待落盘’，不会强制重复提交",\n            }\n        self.refresh_channels(force=True)\n        self._inspect_cache.clear()\n        result = self._try_transfer_subscription(subscribe, force=True)\n''',
    'manual pending guard',
)

# New APIs inserted before release_native.
release_marker = '    def api_release_native(self, subscribe_id: int = 0) -> Dict[str, Any]:\n'
if release_marker not in text:
    raise SystemExit('release api marker not found')
api_addition = r'''    def api_cancel_pending(self, subscribe_id: int = 0) -> Dict[str, Any]:
        sid = int(subscribe_id or 0)
        subscribe = self._find_subscription(sid)
        if not sid or not subscribe:
            return {"success": False, "message": "订阅不存在"}
        if sid not in set(self._selected_subscriptions):
            return {"success": False, "message": "该订阅当前不是光鸭固定转存路线"}
        return self._cancel_pending_jobs(subscribe)

    def api_daily_summary(self) -> Dict[str, Any]:
        return self._send_daily_summary(force=True)

'''
text = text.replace(release_marker, api_addition + release_marker, 1)

# Save config additions.
replace_once(
    '            "notify": self._notify,\n            "auto_transfer_on_refresh": self._auto_transfer_on_refresh,\n',
    '            "notify": self._notify,\n            "daily_summary": self._daily_summary,\n            "summary_cron": self._summary_cron,\n            "auto_transfer_on_refresh": self._auto_transfer_on_refresh,\n',
    'save summary config',
)

# Show S00 in selector instead of hiding zero season.
replace_once(
    '            suffix = f" S{int(season):02d}" if season not in (None, 0) else ""\n',
    '            suffix = f" S{int(season):02d}" if season not in (None, "") else ""\n',
    'selector season zero',
)

# Media fact prefix must preserve season 0.
replace_once(
    '''        try:\n            season = max(1, int(getattr(subscribe, "season", 0) or 1))\n        except (TypeError, ValueError):\n            season = 1\n        return f"{source}:{media_id}:s{season:02d}"\n''',
    '''        try:\n            raw_season = getattr(subscribe, "season", None)\n            season = 1 if raw_season in (None, "") else max(0, int(raw_season))\n        except (TypeError, ValueError):\n            season = 1\n        return f"{source}:{media_id}:s{season:02d}"\n''',
    'fact prefix season zero',
)

# Special subscriptions only accept explicit season-0 files; normal seasons keep accepting bare E01 names.
replace_once(
    '''        wanted_season = getattr(subscribe, "season", None)\n        file_season, episodes = _episode_numbers(path)\n        if wanted_season not in (None, 0) and file_season not in (None, int(wanted_season)):\n            return []\n        return [f"{prefix}:e{int(ep):04d}" for ep in episodes]\n''',
    '''        wanted_season = getattr(subscribe, "season", None)\n        file_season, episodes = _episode_numbers(path)\n        if wanted_season not in (None, ""):\n            try:\n                wanted_value = int(wanted_season)\n            except (TypeError, ValueError):\n                wanted_value = None\n            if wanted_value is not None:\n                if file_season is not None and file_season != wanted_value:\n                    return []\n                if wanted_value == 0 and file_season is None:\n                    return []\n        return [f"{prefix}:e{int(ep):04d}" for ep in episodes]\n''',
    'fact item season zero',
)

# Planner gets the same season-0 safety rule.
replace_once(
    '''                file_season, episodes = _episode_numbers(effective)\n                if subscribe_season not in (None, 0) and file_season not in (None, int(subscribe_season)):\n                    counters["episode"] += 1\n                    continue\n                if episodes:\n''',
    '''                file_season, episodes = _episode_numbers(effective)\n                if subscribe_season not in (None, ""):\n                    try:\n                        wanted_season = int(subscribe_season)\n                    except (TypeError, ValueError):\n                        wanted_season = None\n                    if wanted_season is not None:\n                        if file_season is not None and file_season != wanted_season:\n                            counters["episode"] += 1\n                            continue\n                        if wanted_season == 0 and file_season is None:\n                            counters["episode"] += 1\n                            continue\n                if episodes:\n''',
    'planner season zero',
)

# A cancelled job is a durable user decision: same old message/job never auto-replays.
pending_anchor = '''            pending_job = self._get_job_state(job_key)\n            restored = None\n            logger.info(\n'''
pending_new = '''            pending_job = self._get_job_state(job_key)\n            restored = None\n            if pending_job.get("status") == "cancelled" and set(pending_job.get("paths") or []) == set(job_paths):\n                synchronized_match = True\n                logger.info(\n                    "【光鸭转存助手】【人工任务】#%s %s share_id=%s 该旧消息任务已人工忽略，本轮不重复提交；等待新消息/新链接",\n                    sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0],\n                )\n                continue\n            logger.info(\n'''
replace_once(pending_anchor, pending_new, 'cancelled replay guard')

# Data migration comment.
replace_once(
    '        # v4 的媒体事实会从当前订阅库存/媒体库按需补建，避免一次性迁移误判。\n',
    '        # v5 延续 v4 媒体事实；新增日报与人工任务状态均为可选数据，无需破坏性迁移。\n',
    'schema comment',
)

SRC.write_text(text, encoding='utf-8')

# Package metadata.
package = json.loads(PACKAGE.read_text(encoding='utf-8'))
meta = package['GuangYaTransferAssistant']
meta['version'] = '1.6.0'
meta['description'] = '光鸭订阅固定分流：任务审计、待落盘防误重放/人工忽略、可选每日摘要、Season 0 特别篇识别，并保留媒体幂等/游标/恢复/落盘确认。'
history = meta.get('history') or {}
meta['history'] = {
    'v1.6.0': '操作与审计版本：增加最近转存任务审计列表，明确显示状态/消息/分享/文件/错误；“立即检查缺集”在存在已提交待落盘任务时拒绝强制重放，新增“忽略卡住任务”并将旧任务持久标记 cancelled，只有重置检查状态才允许重试旧消息；增加可选每日转存摘要与手动摘要接口；支持 S00、SP/OVA/OAD/特别篇/番外等 Season 0 识别和去重，防止特别篇混入普通季。',
    **history,
}
PACKAGE.write_text(json.dumps(package, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

plugin = json.loads(PLUGIN.read_text(encoding='utf-8'))
plugin['version'] = '1.6.0'
plugin['description'] = '固定转存订阅：任务审计、待落盘防误重放/人工忽略、每日摘要、Season 0 特别篇识别及完整可靠性闭环。'
PLUGIN.write_text(json.dumps(plugin, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

# Tests.
tests = TEST.read_text(encoding='utf-8')
tests = tests.replace('"1.5.0"', '"1.6.0"')
tests = tests.replace("'plugin_version = \\\"1.5.0\\\"'", "'plugin_version = \\\"1.6.0\\\"'")
# The literal appears without escaped source formatting in the file too.
tests = tests.replace("'plugin_version = \"1.5.0\"'", "'plugin_version = \"1.6.0\"'")
addition = r'''


def test_v160_operations_and_audit_contracts():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    local = json.loads((ROOT / "plugins.v3" / "guangyatransferassistant" / "plugin.json").read_text(encoding="utf-8"))
    assert package["version"] == "1.6.0" and local["version"] == "1.6.0"
    assert 'plugin_version = "1.6.0"' in text
    assert '_task_audit_rows' in text and '转存任务审计' in text
    assert '忽略卡住任务' in text and '/cancel_pending' in text
    assert '旧消息不会自动重放' in text
    assert 'daily_summary' in text and 'summary_cron' in text and '光鸭转存日报' in text
    assert 'CronTrigger.from_crontab' in text
    assert '_data_schema_version = 5' in text


def test_manual_missing_check_refuses_pending_force_replay():
    block = text.split('    def api_check_missing(', 1)[1].split('    def api_recheck_pending(', 1)[0]
    guard_pos = block.index('_pending_jobs_for_subscription(subscribe)')
    force_pos = block.index('_try_transfer_subscription(subscribe, force=True)')
    assert guard_pos < force_pos
    assert '请先使用‘复查待落盘’' in block


def test_cancelled_old_job_never_replays_until_reset():
    flow = text.split('    def _try_transfer_subscription_inner(', 1)[1].split('    def _target_path(', 1)[0]
    assert 'pending_job.get("status") == "cancelled"' in flow
    cancelled = flow.split('pending_job.get("status") == "cancelled"', 1)[1].split('logger.info(', 1)[0]
    assert 'continue' not in cancelled  # continue follows the explanatory log, not before it
    assert '该旧消息任务已人工忽略' in flow and 'continue' in flow
    reset = text.split('    def _reset_subscription_check_state(', 1)[1].split('    def _pending_jobs_for_subscription(', 1)[0]
    assert '"cancelled"' in reset


def test_special_episode_parser_and_season_zero_identity():
    parser = ns['_episode_numbers']
    assert parser('Anime.OVA.01.1080p.mkv') == (0, [1])
    assert parser('Anime.SP02.mkv') == (0, [2])
    assert parser('动画 特别篇3.mp4') == (0, [3])
    assert parser('Show.S00E04.mkv') == (0, [4])
    assert parser('Show.S01E08.SP1.mkv') == (1, [8])
    assert 'wanted_value == 0 and file_season is None' in text
    assert 'wanted_season == 0 and file_season is None' in text


def test_daily_summary_is_optional_and_deduplicated():
    service = text.split('    def get_service(', 1)[1].split('    def get_form(', 1)[0]
    assert 'if self._daily_summary:' in service
    assert 'GuangYaTransferAssistantDailySummary' in service
    summary = text.split('    def _send_daily_summary(', 1)[1].split('    def get_page(', 1)[0]
    assert 'daily_summary_state' in summary
    assert '今日摘要已发送' in summary
    assert 'force: bool = False' in text
'''
if 'test_v160_operations_and_audit_contracts' not in tests:
    tests += addition
TEST.write_text(tests, encoding='utf-8')

print('GuangYa v1.6.0 operations patch applied')
