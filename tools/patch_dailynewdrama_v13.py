from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1]
P = ROOT / 'plugins.v2/dailynewdrama/__init__.py'
text = P.read_text(encoding='utf-8')

# metadata/runtime
text = text.replace('plugin_desc = "每天发现豆瓣及腾讯视频、爱奇艺、优酷、芒果TV、哔哩哔哩的近期上线和仍在更新剧集，过滤已订阅/已入库内容，并支持按序号订阅。"',
                    'plugin_desc = "聚合豆瓣及腾讯视频、爱奇艺、优酷、芒果TV、哔哩哔哩的新剧与在播剧，仅过滤已入库/已订阅内容，页面不限候选数量并支持一键订阅。"')
text = text.replace('plugin_version = "1.2"', 'plugin_version = "1.3"')

# candidate limits: remove display cap, increase Douban source breadth to max supported by current adapter
text = text.replace('    _max_items = 12\n', '')
text = text.replace('        self._max_items = self._to_int(config.get("max_items"), 12, 1, 30)\n', '')
text = text.replace('    _coming_count = 40\n', '    _coming_count = 100\n')
text = text.replace('        self._coming_count = self._to_int(config.get("coming_count"), 40, 10, 100)\n',
                    '        self._coming_count = self._to_int(config.get("coming_count"), 100, 10, 100)\n')
text = text.replace('        candidates = candidates[: self._max_items]\n', '')
text = text.replace('            "max_items": 12,\n', '')
text = text.replace('            "coming_count": 40,\n', '            "coming_count": 100,\n')
text = text.replace('            "max_items": self._max_items,\n', '')

# allow larger index ranges for unlimited page candidates
text = text.replace('            if end - start <= 100:\n', '            if end - start <= 1000:\n')

# config form: remove max push count and make remaining two fields balanced
old_form = '''                            {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [\n                                {"component": "VCronField", "props": {"model": "cron", "label": "每日推送时间", "placeholder": "0 9 * * *"}}\n                            ]},\n                            {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [\n                                {"component": "VTextField", "props": {"model": "max_items", "label": "最多推送数量", "placeholder": "12", "type": "number"}}\n                            ]},\n                            {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [\n                                {"component": "VTextField", "props": {"model": "vote", "label": "最低评分", "placeholder": "0 表示不限", "type": "number"}}\n                            ]},'''
new_form = '''                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [\n                                {"component": "VCronField", "props": {"model": "cron", "label": "每日推送时间", "placeholder": "0 9 * * *"}}\n                            ]},\n                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [\n                                {"component": "VTextField", "props": {"model": "vote", "label": "最低评分", "placeholder": "0 表示不限", "type": "number"}}\n                            ]},'''
if old_form not in text:
    raise SystemExit('config form pattern not found')
text = text.replace(old_form, new_form)
text = text.replace('{"component": "VTextField", "props": {"model": "coming_count", "label": "豆瓣新剧抓取数量", "placeholder": "40", "type": "number"}}',
                    '{"component": "VTextField", "props": {"model": "coming_count", "label": "豆瓣单次抓取数量（最多100）", "placeholder": "100", "type": "number"}}')
text = text.replace('"text": "候选来源：豆瓣即将播出 + 近期热门，以及腾讯视频、爱奇艺、优酷、芒果TV、哔哩哔哩的近期上线/仍在更新剧集。数据源失败时自动尝试 FlareSolverr（开启时）。同剧多平台自动合并，媒体库已有和现有订阅统一过滤。",',
                    '"text": "页面候选不限数量，仅过滤媒体库已有和 MoviePilot 已订阅内容；重复提醒间隔只影响消息推送，不会让候选从页面消失。每张剧集卡片可直接点击订阅。",')

# Page: keep batch id and add direct subscribe action button.
text = text.replace('        items = data.get("items") or []\n        contents: List[dict] = []\n',
                    '        items = data.get("items") or []\n        batch_id = str(data.get("batch_id") or "")\n        contents: List[dict] = []\n')
old_card = '''            cards.append({\n                "component": "VCard",\n                "props": {"variant": "tonal"},\n                "content": [\n                    {"component": "VCardTitle", "text": f"{item.get('index')}. {item.get('title')} ({item.get('year') or '-'})"},\n                    {"component": "VCardText", "text": f"{source} · {air} · 评分 {vote} · TMDB {item.get('tmdbid') or '-'}"},\n                ],\n            })'''
new_card = '''            remarks = [str(x).strip() for x in (item.get("platform_remarks") or []) if str(x).strip()]\n            detail = f"{source} · {air} · 评分 {vote} · TMDB {item.get('tmdbid') or '-'}"\n            if remarks:\n                detail += " · " + " / ".join(remarks[:2])\n            cards.append({\n                "component": "VCard",\n                "props": {"variant": "tonal", "class": "h-100"},\n                "content": [\n                    {"component": "VCardTitle", "text": f"{item.get('index')}. {item.get('title')} ({item.get('year') or '-'})"},\n                    {"component": "VCardText", "text": detail},\n                    {\n                        "component": "VCardActions",\n                        "content": [\n                            {"component": "VSpacer"},\n                            {\n                                "component": "VBtn",\n                                "props": {"color": "primary", "variant": "flat", "size": "small", "prepend-icon": "mdi-plus-circle"},\n                                "text": "订阅",\n                                "events": {\n                                    "click": {\n                                        "api": "plugin/DailyNewDrama/subscribe",\n                                        "method": "post",\n                                        "params": {"indexes": str(item.get("index") or ""), "batch_id": batch_id},\n                                    }\n                                },\n                            },\n                        ],\n                    },\n                ],\n            })'''
if old_card not in text:
    raise SystemExit('page card pattern not found')
text = text.replace(old_card, new_card)

# API subscribe: remove successfully handled items from current page cache.
old_api = '''    def api_subscribe(self, payload: dict) -> Dict[str, Any]:\n        """按请求中的 indexes 字段订阅当前候选序号。"""\n        payload = payload or {}\n        indexes = self._parse_indexes(str(payload.get("indexes") or ""))\n        batch_id = str(payload.get("batch_id") or "")\n        return self._subscribe_indexes(indexes=indexes, batch_id=batch_id)\n'''
new_api = '''    def api_subscribe(self, payload: dict) -> Dict[str, Any]:\n        """订阅页面/消息中的候选序号，并从当前页面移除已处理条目。"""\n        payload = payload or {}\n        indexes = self._parse_indexes(str(payload.get("indexes") or ""))\n        batch_id = str(payload.get("batch_id") or "")\n        result = self._subscribe_indexes(indexes=indexes, batch_id=batch_id)\n        handled = [int(i) for i in (result.get("handled_indexes") or []) if str(i).isdigit()]\n        if handled:\n            self._remove_current_candidates(handled, batch_id=batch_id)\n        return result\n\n    def _remove_current_candidates(self, indexes: List[int], batch_id: str = "") -> None:\n        """从当前页面缓存移除已成功订阅或已确认入库/订阅的条目，历史批次保持不变。"""\n        current = self.get_data("daily_candidates") or {}\n        if batch_id and str(current.get("batch_id") or "") != str(batch_id):\n            return\n        remove_set = {int(i) for i in indexes}\n        items = [item for item in (current.get("items") or []) if int(item.get("index") or 0) not in remove_set]\n        if len(items) == len(current.get("items") or []):\n            return\n        current["items"] = items\n        self.save_data("daily_candidates", current)\n        status = self.get_data("last_run") or {}\n        if status:\n            status["candidate_count"] = len(items)\n            self.save_data("last_run", status)\n'''
if old_api not in text:
    raise SystemExit('api subscribe pattern not found')
text = text.replace(old_api, new_api)

# Candidate list should not be suppressed by notification history.
recent_block = '''                if suppress_recent and self._recently_notified(mediainfo.tmdb_id, notified, today):\n                    logger.debug("【每日新剧助手】过滤近期已提醒: %s", mediainfo.title_year)\n                    continue\n\n'''
if recent_block not in text:
    raise SystemExit('recent notification filter pattern not found')
text = text.replace(recent_block, '')

old_send = '''        if send_message and (candidates or self._notify_empty):\n            self._send_candidates(candidates, batch_id=batch_id)\n            if candidates:\n                for item in candidates:\n                    notified[str(item.get("tmdbid"))] = today.isoformat()\n                self.save_data("notified_history", notified)\n        return candidates\n'''
new_send = '''        notify_candidates = candidates\n        if suppress_recent:\n            notify_candidates = [\n                item for item in candidates\n                if not self._recently_notified(item.get("tmdbid"), notified, today)\n            ]\n        last_status["notification_count"] = len(notify_candidates)\n        self.save_data("last_run", last_status)\n\n        if send_message and (notify_candidates or self._notify_empty):\n            self._send_candidates(notify_candidates, batch_id=batch_id)\n            if notify_candidates:\n                for item in notify_candidates:\n                    notified[str(item.get("tmdbid"))] = today.isoformat()\n                self.save_data("notified_history", notified)\n        return candidates\n'''
if old_send not in text:
    raise SystemExit('notification send pattern not found')
text = text.replace(old_send, new_send)

# Chunk large notifications instead of losing candidates or exceeding channel payload limits.
start = text.index('    def _send_candidates(')
end = text.index('    def _subscribe_indexes(', start)
new_send_func = '''    def _send_candidates(self, items: List[Dict[str, Any]], channel=None, userid=None, batch_id: str = "") -> None:\n        """分批发送全部候选，避免数量较多时超过消息渠道长度/按钮限制。"""\n        if not items:\n            self.post_message(channel=channel, userid=userid, title="📺 今日新剧/在播剧", text="今天没有发现新的、仍在更新且尚未入库或订阅的剧集。")\n            return\n        if not batch_id:\n            batch_id = str((self.get_data("daily_candidates") or {}).get("batch_id") or "")\n\n        today = datetime.date.today()\n        chunk_size = 20\n        total_chunks = (len(items) + chunk_size - 1) // chunk_size\n        for chunk_no, offset in enumerate(range(0, len(items), chunk_size), start=1):\n            chunk = items[offset: offset + chunk_size]\n            lines = ["已过滤媒体库已有和现有订阅；重复提醒只影响消息，不影响插件页面候选：", ""]\n            buttons: List[List[dict]] = []\n            row: List[dict] = []\n            for item in chunk:\n                air_date = _parse_date_value(item.get("air_date"))\n                timing = _format_air_timing_value(air_date, today)\n                vote_text = f"⭐ {item.get('vote')}" if item.get("vote") else "暂无评分"\n                if item.get("source") == "coming":\n                    source_text = "待播"\n                elif item.get("source") == "hot":\n                    source_text = "新近开播"\n                else:\n                    source_text = item.get("source_label") or ("更新中" if item.get("ongoing") else "近期上线")\n                remarks = [str(x).strip() for x in (item.get("platform_remarks") or []) if str(x).strip()]\n                remark_text = f" · {' / '.join(remarks[:2])}" if remarks else ""\n                lines.append(f"{item['index']}. {item['title']} ({item.get('year') or '-'}) · {source_text}{remark_text} · {timing} · {vote_text}")\n                row.append({\n                    "text": f"{item['index']}. {str(item['title'])[:10]}",\n                    "callback_data": f"[PLUGIN]{self.__class__.__name__}|sub|{batch_id}|{item['index']}",\n                })\n                if len(row) == 2:\n                    buttons.append(row)\n                    row = []\n            if row:\n                buttons.append(row)\n            lines.extend(["", "普通消息渠道可发送：", "`/newdrama_sub 1,3` 或 `/newdrama_sub 1-3`"])\n            suffix = f" · {chunk_no}/{total_chunks}" if total_chunks > 1 else ""\n            self.post_message(\n                channel=channel,\n                userid=userid,\n                title=f"📺 今日新剧/在播剧 · {len(items)} 部可选{suffix}",\n                text="\\n".join(lines),\n                image=chunk[0].get("poster") or None,\n                buttons=buttons,\n            )\n\n'''
text = text[:start] + new_send_func + text[end:]

# handled index reporting for page cache removal
text = text.replace('        failed: List[str] = []\n\n        for index in indexes:', '        failed: List[str] = []\n        handled_indexes: List[int] = []\n\n        for index in indexes:')
text = text.replace('                    skipped.append(f"{index}.{item.get(\'title\')}(已入库)")\n                    continue', '                    skipped.append(f"{index}.{item.get(\'title\')}(已入库)")\n                    handled_indexes.append(index)\n                    continue')
text = text.replace('                    skipped.append(f"{index}.{item.get(\'title\')}(已订阅)")\n                    continue', '                    skipped.append(f"{index}.{item.get(\'title\')}(已订阅)")\n                    handled_indexes.append(index)\n                    continue')
text = text.replace('                if sid:\n                    success.append(f"{index}.{mediainfo.title_year}")', '                if sid:\n                    success.append(f"{index}.{mediainfo.title_year}")\n                    handled_indexes.append(index)')
text = text.replace('        return {"success": bool(success), "message": "\\n\\n".join(parts) or "没有可处理的条目"}\n',
                    '        return {"success": bool(success), "message": "\\n\\n".join(parts) or "没有可处理的条目", "handled_indexes": handled_indexes}\n')

# save complete config when onlyonce is reset (fix previously dropped provider/Flaresolverr fields)
text = text.replace('            "rsshub": self._rsshub,\n            "vote": self._vote,',
                    '            "rsshub": self._rsshub,\n            "flaresolverr_enabled": self._flaresolverr_enabled,\n            "flaresolverr_url": self._flaresolverr_url,\n            "vote": self._vote,')
text = text.replace('            "notify_empty": self._notify_empty,\n        })',
                    '            "notify_empty": self._notify_empty,\n            "platform_tencent": self._platform_tencent,\n            "platform_iqiyi": self._platform_iqiyi,\n            "platform_youku": self._platform_youku,\n            "platform_mgtv": self._platform_mgtv,\n            "platform_bilibili": self._platform_bilibili,\n        })')

P.write_text(text, encoding='utf-8')

# metadata indexes
history = '页面候选取消数量硬上限；重复提醒仅抑制消息、不再删除页面候选；每张剧集卡片新增一键订阅；订阅成功/已入库/已订阅后自动从当前页面移除；大量候选通知按20部自动分批。'
for fp in [ROOT / 'package.v2.json', ROOT / 'plugin.json']:
    data = json.loads(fp.read_text(encoding='utf-8'))
    meta = data['DailyNewDrama']
    meta['version'] = '1.3'
    meta['description'] = '聚合豆瓣及腾讯视频、爱奇艺、优酷、芒果TV、哔哩哔哩的新剧与在播剧，仅过滤已入库/已订阅内容，页面不限候选数量并支持一键订阅。'
    old = meta.get('history') or {}
    meta['history'] = {'v1.3': history, **old}
    fp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

fp = ROOT / 'plugins.v2/dailynewdrama/plugin.json'
data = json.loads(fp.read_text(encoding='utf-8'))
data['version'] = '1.3'
data['description'] = '聚合豆瓣及腾讯视频、爱奇艺、优酷、芒果TV、哔哩哔哩的新剧与在播剧，仅过滤已入库/已订阅内容，页面不限候选数量并支持一键订阅。'
old = data.get('history') or {}
data['history'] = {'v1.3': history, **old}
fp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

print('DailyNewDrama v1.3 patch applied')
