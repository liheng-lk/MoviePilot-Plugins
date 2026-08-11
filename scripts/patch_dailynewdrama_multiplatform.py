from pathlib import Path

p = Path('plugins.v2/dailynewdrama/__init__.py')
s = p.read_text(encoding='utf-8')

if 'from .platform_sources import fetch_platform_sources' not in s:
    s = s.replace('from app.utils.http import RequestUtils\n', 'from app.utils.http import RequestUtils\n\nfrom .platform_sources import fetch_platform_sources\n', 1)

s = s.replace('    plugin_version = "1.1"', '    plugin_version = "1.2"', 1)

needle = '    _notify_empty = False\n'
insert = '''    _notify_empty = False\n    _platform_tencent = True\n    _platform_iqiyi = True\n    _platform_youku = True\n    _platform_mgtv = True\n    _platform_bilibili = True\n'''
if '_platform_tencent' not in s:
    s = s.replace(needle, insert, 1)

needle = '        self._notify_empty = bool(config.get("notify_empty", False))\n'
insert = '''        self._notify_empty = bool(config.get("notify_empty", False))\n        self._platform_tencent = bool(config.get("platform_tencent", True))\n        self._platform_iqiyi = bool(config.get("platform_iqiyi", True))\n        self._platform_youku = bool(config.get("platform_youku", True))\n        self._platform_mgtv = bool(config.get("platform_mgtv", True))\n        self._platform_bilibili = bool(config.get("platform_bilibili", True))\n'''
if 'config.get("platform_tencent"' not in s:
    s = s.replace(needle, insert, 1)

# Add platform switches before informational alert.
alert_marker = '''                    {\n                        "component": "VAlert",\n                        "props": {\n                            "type": "info",\n                            "variant": "tonal",\n                            "text": "数据源自动降级：豆瓣直连 → RSSHub → FlareSolverr（开启时）。RSSHub 仅作为备用；FlareSolverr 建议与 MoviePilot 放在同一 Docker 网络，地址可填 http://flaresolverr:8191。媒体库已有和 MoviePilot 已订阅内容会自动过滤。",\n                        },\n                    },'''
platform_row = '''                    {\n                        "component": "VRow",\n                        "content": [\n                            {"component": "VCol", "props": {"cols": 6, "md": 2}, "content": [{"component": "VSwitch", "props": {"model": "platform_tencent", "label": "腾讯视频"}}]},\n                            {"component": "VCol", "props": {"cols": 6, "md": 2}, "content": [{"component": "VSwitch", "props": {"model": "platform_iqiyi", "label": "爱奇艺"}}]},\n                            {"component": "VCol", "props": {"cols": 6, "md": 2}, "content": [{"component": "VSwitch", "props": {"model": "platform_youku", "label": "优酷"}}]},\n                            {"component": "VCol", "props": {"cols": 6, "md": 2}, "content": [{"component": "VSwitch", "props": {"model": "platform_mgtv", "label": "芒果TV"}}]},\n                            {"component": "VCol", "props": {"cols": 6, "md": 2}, "content": [{"component": "VSwitch", "props": {"model": "platform_bilibili", "label": "哔哩哔哩"}}]},\n                        ],\n                    },\n                    {\n                        "component": "VAlert",\n                        "props": {\n                            "type": "info",\n                            "variant": "tonal",\n                            "text": "候选来源：豆瓣即将播出 + 近期热门，以及腾讯视频、爱奇艺、优酷、芒果TV、哔哩哔哩的近期上线/仍在更新剧集。数据源失败时自动尝试 FlareSolverr（开启时）。同剧多平台自动合并，媒体库已有和现有订阅统一过滤。",\n                        },\n                    },'''
if '"model": "platform_tencent"' not in s and alert_marker in s:
    s = s.replace(alert_marker, platform_row, 1)

needle = '            "notify_empty": False,\n'
insert = '''            "notify_empty": False,\n            "platform_tencent": True,\n            "platform_iqiyi": True,\n            "platform_youku": True,\n            "platform_mgtv": True,\n            "platform_bilibili": True,\n'''
if '"platform_tencent": True' not in s:
    s = s.replace(needle, insert, 1)

# Add platform providers to _fetch_sources before return.
needle = '            items.extend(hot)\n        return items, status\n'
insert = '''            items.extend(hot)\n\n        platform_items, platform_status = fetch_platform_sources(\n            {\n                "tencent": self._platform_tencent,\n                "iqiyi": self._platform_iqiyi,\n                "youku": self._platform_youku,\n                "mgtv": self._platform_mgtv,\n                "bilibili": self._platform_bilibili,\n            },\n            proxy=self._proxy,\n            flaresolverr_enabled=self._flaresolverr_enabled,\n            flaresolverr_url=self._flaresolverr_url,\n        )\n        items.extend(platform_items)\n        status.update(platform_status)\n        return items, status\n'''
if 'platform_items, platform_status = fetch_platform_sources' not in s:
    s = s.replace(needle, insert, 1)

# Extend date eligibility.
needle = '''        if source == "hot":\n            if not air_date:\n                return False\n            days = (today - air_date).days\n            return 0 <= days <= self._recent_days\n        return False\n'''
insert = '''        if source == "hot":\n            if not air_date:\n                return False\n            days = (today - air_date).days\n            return 0 <= days <= self._recent_days\n        if source == "platform_ongoing":\n            return True\n        if source == "platform_recent":\n            if not air_date:\n                return True\n            days = (today - air_date).days\n            return -self._coming_days <= days <= max(self._recent_days, 60)\n        return False\n'''
if 'source == "platform_ongoing"' not in s:
    s = s.replace(needle, insert, 1)

# Merge duplicate TMDB platforms instead of discarding source metadata.
needle = '''                if mediainfo.tmdb_id in seen_tmdb:\n                    continue\n                seen_tmdb.add(mediainfo.tmdb_id)\n'''
insert = '''                if mediainfo.tmdb_id in seen_tmdb:\n                    for existing in candidates:\n                        if existing.get("tmdbid") == mediainfo.tmdb_id:\n                            merged_platforms = list(dict.fromkeys((existing.get("platforms") or []) + (raw.get("platforms") or [])))\n                            existing["platforms"] = merged_platforms\n                            if merged_platforms:\n                                state = "更新中" if raw.get("ongoing") or existing.get("ongoing") else "近期上线"\n                                existing["source_label"] = " / ".join(merged_platforms) + f" · {state}"\n                            existing["ongoing"] = bool(existing.get("ongoing") or raw.get("ongoing"))\n                            break\n                    continue\n                seen_tmdb.add(mediainfo.tmdb_id)\n'''
if 'merged_platforms = list(dict.fromkeys' not in s:
    s = s.replace(needle, insert, 1)

# Candidate payload: preserve platform info and provider label.
needle = '''                    "source": raw.get("source"),\n                    "source_label": "豆瓣即将播出" if raw.get("source") == "coming" else "豆瓣近期热播",\n                })\n'''
insert = '''                    "source": raw.get("source"),\n                    "source_label": raw.get("source_label") or ("豆瓣即将播出" if raw.get("source") == "coming" else "豆瓣近期热播"),\n                    "platforms": raw.get("platforms") or [],\n                    "ongoing": bool(raw.get("ongoing")),\n                    "platform_remark": raw.get("platform_remark") or "",\n                })\n'''
if '"platform_remark": raw.get("platform_remark")' not in s:
    s = s.replace(needle, insert, 1)

# Notification label.
needle = '            source_text = "待播" if item.get("source") == "coming" else "新近开播"\n'
insert = '''            if item.get("source") == "coming":\n                source_text = "待播"\n            elif item.get("source") == "hot":\n                source_text = "新近开播"\n            else:\n                source_text = item.get("source_label") or ("更新中" if item.get("ongoing") else "近期上线")\n'''
if 'source_text = item.get("source_label")' not in s:
    s = s.replace(needle, insert, 1)

p.write_text(s, encoding='utf-8')
print('patched multiplatform integration')
