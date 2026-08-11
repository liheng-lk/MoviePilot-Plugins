from pathlib import Path

p = Path('plugins.v2/dailynewdrama/__init__.py')
s = p.read_text(encoding='utf-8')

if 'from .platform_sources import fetch_platform_sources' not in s:
    s = s.replace('from app.utils.http import RequestUtils\n', 'from app.utils.http import RequestUtils\n\nfrom .platform_sources import fetch_platform_sources\n', 1)

s = s.replace('    plugin_version = "1.1"', '    plugin_version = "1.2"', 1)
s = s.replace(
    '    plugin_desc = "每天发现豆瓣即将播出和近期热播新剧，过滤已订阅/已入库内容，并支持按序号订阅。"',
    '    plugin_desc = "发现豆瓣及腾讯视频、爱奇艺、优酷、芒果TV、哔哩哔哩近期上线和仍在更新的剧集，自动过滤已订阅/已入库内容。"',
    1,
)
s = s.replace(
    '    plugin_label = "豆瓣,电视剧,订阅,推荐,通知"',
    '    plugin_label = "豆瓣,腾讯视频,爱奇艺,优酷,芒果TV,哔哩哔哩,电视剧,订阅,推荐,通知"',
    1,
)
s = s.replace('        logger.info("【每日新剧助手】开始刷新豆瓣新剧")', '        logger.info("【每日新剧助手】开始刷新多平台新剧/在播剧")', 1)
s = s.replace('            last_status["error"] = "全部豆瓣数据源获取失败，保留上次候选列表。"', '            last_status["error"] = "全部新剧数据源获取失败，保留上次候选列表。"', 1)
s = s.replace('                self.post_message(title="📺 每日新剧助手获取失败", text="豆瓣/RSSHub 数据源暂时不可用，本次未覆盖上次候选列表，请稍后重试。")', '                self.post_message(title="📺 每日新剧助手获取失败", text="豆瓣及视频平台数据源暂时不可用，本次未覆盖上次候选列表，请稍后重试。")', 1)
s = s.replace('            self.post_message(channel=channel, userid=userid, title="📺 今日豆瓣新剧", text="今天没有发现新的、且尚未入库或订阅的剧集。")', '            self.post_message(channel=channel, userid=userid, title="📺 今日新剧/在播剧", text="今天没有发现新的、仍在更新且尚未入库或订阅的剧集。")', 1)
s = s.replace('            title=f"📺 今日豆瓣新剧 · {len(items)} 部可选",', '            title=f"📺 今日新剧/在播剧 · {len(items)} 部可选",', 1)

needle = '    _notify_empty = False\n'
insert = '''    _notify_empty = False\n    _platform_tencent = True\n    _platform_iqiyi = True\n    _platform_youku = True\n    _platform_mgtv = True\n    _platform_bilibili = True\n'''
if '_platform_tencent' not in s:
    s = s.replace(needle, insert, 1)

needle = '        self._notify_empty = bool(config.get("notify_empty", False))\n'
insert = '''        self._notify_empty = bool(config.get("notify_empty", False))\n        self._platform_tencent = bool(config.get("platform_tencent", True))\n        self._platform_iqiyi = bool(config.get("platform_iqiyi", True))\n        self._platform_youku = bool(config.get("platform_youku", True))\n        self._platform_mgtv = bool(config.get("platform_mgtv", True))\n        self._platform_bilibili = bool(config.get("platform_bilibili", True))\n'''
if 'config.get("platform_tencent"' not in s:
    s = s.replace(needle, insert, 1)

alert_marker = '''                    {\n                        "component": "VAlert",\n                        "props": {\n                            "type": "info",\n                            "variant": "tonal",\n                            "text": "数据源自动降级：豆瓣直连 → RSSHub → FlareSolverr（开启时）。RSSHub 仅作为备用；FlareSolverr 建议与 MoviePilot 放在同一 Docker 网络，地址可填 http://flaresolverr:8191。媒体库已有和 MoviePilot 已订阅内容会自动过滤。",\n                        },\n                    },'''
platform_row = '''                    {\n                        "component": "VRow",\n                        "content": [\n                            {"component": "VCol", "props": {"cols": 6, "md": 2}, "content": [{"component": "VSwitch", "props": {"model": "platform_tencent", "label": "腾讯视频"}}]},\n                            {"component": "VCol", "props": {"cols": 6, "md": 2}, "content": [{"component": "VSwitch", "props": {"model": "platform_iqiyi", "label": "爱奇艺"}}]},\n                            {"component": "VCol", "props": {"cols": 6, "md": 2}, "content": [{"component": "VSwitch", "props": {"model": "platform_youku", "label": "优酷"}}]},\n                            {"component": "VCol", "props": {"cols": 6, "md": 2}, "content": [{"component": "VSwitch", "props": {"model": "platform_mgtv", "label": "芒果TV"}}]},\n                            {"component": "VCol", "props": {"cols": 6, "md": 2}, "content": [{"component": "VSwitch", "props": {"model": "platform_bilibili", "label": "哔哩哔哩"}}]},\n                        ],\n                    },\n                    {\n                        "component": "VAlert",\n                        "props": {\n                            "type": "info",\n                            "variant": "tonal",\n                            "text": "候选来源：豆瓣即将播出 + 近期热门，以及腾讯视频、爱奇艺、优酷、芒果TV、哔哩哔哩的近期上线/仍在更新剧集。数据源失败时自动尝试 FlareSolverr（开启时）。同剧多平台自动合并，媒体库已有和现有订阅统一过滤。",\n                        },\n                    },'''
if '"model": "platform_tencent"' not in s and alert_marker in s:
    s = s.replace(alert_marker, platform_row, 1)

needle = '            "notify_empty": False,\n'
insert = '''            "notify_empty": False,\n            "platform_tencent": True,\n            "platform_iqiyi": True,\n            "platform_youku": True,\n            "platform_mgtv": True,\n            "platform_bilibili": True,\n'''
if '"platform_tencent": True' not in s:
    s = s.replace(needle, insert, 1)

needle = '            items.extend(hot)\n        return items, status\n'
insert = '''            items.extend(hot)\n\n        platform_items, platform_status = fetch_platform_sources(\n            {\n                "tencent": self._platform_tencent,\n                "iqiyi": self._platform_iqiyi,\n                "youku": self._platform_youku,\n                "mgtv": self._platform_mgtv,\n                "bilibili": self._platform_bilibili,\n            },\n            proxy=self._proxy,\n            flaresolverr_enabled=self._flaresolverr_enabled,\n            flaresolverr_url=self._flaresolverr_url,\n        )\n        items.extend(platform_items)\n        status.update(platform_status)\n        return items, status\n'''
if 'platform_items, platform_status = fetch_platform_sources' not in s:
    s = s.replace(needle, insert, 1)

needle = '''        if source == "hot":\n            if not air_date:\n                return False\n            days = (today - air_date).days\n            return 0 <= days <= self._recent_days\n        return False\n'''
insert = '''        if source == "hot":\n            if not air_date:\n                return False\n            days = (today - air_date).days\n            return 0 <= days <= self._recent_days\n        if source == "platform_ongoing":\n            return True\n        if source == "platform_recent":\n            if not air_date:\n                return True\n            days = (today - air_date).days\n            return -self._coming_days <= days <= max(self._recent_days, 60)\n        return False\n'''
if 'source == "platform_ongoing"' not in s:
    s = s.replace(needle, insert, 1)

needle = '''                if mediainfo.tmdb_id in seen_tmdb:\n                    continue\n                seen_tmdb.add(mediainfo.tmdb_id)\n'''
insert = '''                if mediainfo.tmdb_id in seen_tmdb:\n                    for existing in candidates:\n                        if existing.get("tmdbid") == mediainfo.tmdb_id:\n                            merged_platforms = list(dict.fromkeys((existing.get("platforms") or []) + (raw.get("platforms") or [])))\n                            existing["platforms"] = merged_platforms\n                            if merged_platforms:\n                                state = "更新中" if raw.get("ongoing") or existing.get("ongoing") else "近期上线"\n                                existing["source_label"] = " / ".join(merged_platforms) + f" · {state}"\n                            existing["ongoing"] = bool(existing.get("ongoing") or raw.get("ongoing"))\n                            remarks = list(existing.get("platform_remarks") or [])\n                            new_remark = str(raw.get("platform_remark") or "").strip()\n                            if new_remark and new_remark not in remarks:\n                                remarks.append(new_remark)\n                            existing["platform_remarks"] = remarks\n                            break\n                    continue\n                seen_tmdb.add(mediainfo.tmdb_id)\n'''
if 'remarks = list(existing.get("platform_remarks")' not in s:
    if 'merged_platforms = list(dict.fromkeys' in s:
        old = '''                if mediainfo.tmdb_id in seen_tmdb:\n                    for existing in candidates:\n                        if existing.get("tmdbid") == mediainfo.tmdb_id:\n                            merged_platforms = list(dict.fromkeys((existing.get("platforms") or []) + (raw.get("platforms") or [])))\n                            existing["platforms"] = merged_platforms\n                            if merged_platforms:\n                                state = "更新中" if raw.get("ongoing") or existing.get("ongoing") else "近期上线"\n                                existing["source_label"] = " / ".join(merged_platforms) + f" · {state}"\n                            existing["ongoing"] = bool(existing.get("ongoing") or raw.get("ongoing"))\n                            break\n                    continue\n                seen_tmdb.add(mediainfo.tmdb_id)\n'''
        s = s.replace(old, insert, 1)
    else:
        s = s.replace(needle, insert, 1)

needle = '''                    "source": raw.get("source"),\n                    "source_label": "豆瓣即将播出" if raw.get("source") == "coming" else "豆瓣近期热播",\n                })\n'''
insert = '''                    "source": raw.get("source"),\n                    "source_label": raw.get("source_label") or ("豆瓣即将播出" if raw.get("source") == "coming" else "豆瓣近期热播"),\n                    "platforms": raw.get("platforms") or [],\n                    "ongoing": bool(raw.get("ongoing")),\n                    "platform_remark": raw.get("platform_remark") or "",\n                    "platform_remarks": [raw.get("platform_remark")] if raw.get("platform_remark") else [],\n                })\n'''
if '"platform_remarks": [raw.get("platform_remark")]' not in s:
    if '"platform_remark": raw.get("platform_remark") or "",' in s:
        s = s.replace('                    "platform_remark": raw.get("platform_remark") or "",\n', '                    "platform_remark": raw.get("platform_remark") or "",\n                    "platform_remarks": [raw.get("platform_remark")] if raw.get("platform_remark") else [],\n', 1)
    else:
        s = s.replace(needle, insert, 1)

needle = '            source_text = "待播" if item.get("source") == "coming" else "新近开播"\n'
insert = '''            if item.get("source") == "coming":\n                source_text = "待播"\n            elif item.get("source") == "hot":\n                source_text = "新近开播"\n            else:\n                source_text = item.get("source_label") or ("更新中" if item.get("ongoing") else "近期上线")\n'''
if 'source_text = item.get("source_label")' not in s:
    s = s.replace(needle, insert, 1)

old_line = '            lines.append(f"{item[\'index\']}. {item[\'title\']} ({item.get(\'year\') or \'-\'}) · {source_text} · {timing} · {vote_text}")\n'
new_lines = '''            remarks = [str(x).strip() for x in (item.get("platform_remarks") or []) if str(x).strip()]\n            remark_text = f" · {' / '.join(remarks[:2])}" if remarks else ""\n            lines.append(f"{item['index']}. {item['title']} ({item.get('year') or '-'}) · {source_text}{remark_text} · {timing} · {vote_text}")\n'''
if 'remark_text = f" · {' in s:
    pass
elif old_line in s:
    s = s.replace(old_line, new_lines, 1)

p.write_text(s, encoding='utf-8')
print('patched multiplatform integration')
