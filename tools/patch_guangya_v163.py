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


replace_once('    plugin_version = "1.6.2"\n', '    plugin_version = "1.6.3"\n', 'plugin version')
replace_once(
    'VIDEO_EXTENSIONS = {".mkv", ".mp4", ".ts", ".m2ts", ".avi", ".mov", ".wmv", ".flv", ".webm", ".iso", ".rmvb"}\n',
    'VIDEO_EXTENSIONS = {".mkv", ".mp4", ".ts", ".m2ts", ".mts", ".avi", ".mov", ".wmv", ".flv", ".webm", ".iso", ".rmvb", ".m4v", ".mpg", ".mpeg", ".vob"}\n',
    'video extensions',
)
replace_once(
    'SUBTITLE_EXTENSIONS = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".sup"}\n',
    'SUBTITLE_EXTENSIONS = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".sup", ".smi", ".idx"}\n',
    'subtitle extensions',
)

old_episode_tail = '''    if not episodes:\n        special = re.search(\n            r"(?i)(?:^|[^A-Za-z0-9])(?:SP|SPECIAL|OVA|OAD)[\\s._-]*0*(\\d{1,4})(?=[^0-9]|$)",\n            value,\n        )\n        if not special:\n            special = re.search(r"(?:特别篇|番外|特典)\\s*0*(\\d{1,4})(?=[^0-9]|$)", value)\n        if special:\n            season = 0\n            episodes.add(int(special.group(1)))\n\n    return season, sorted(ep for ep in episodes if ep > 0)\n'''
new_episode_tail = '''    if not episodes:\n        special = re.search(\n            r"(?i)(?:^|[^A-Za-z0-9])(?:SP|SPECIAL|OVA|OAD)[\\s._-]*0*(\\d{1,4})(?=[^0-9]|$)",\n            value,\n        )\n        if not special:\n            special = re.search(r"(?:特别篇|番外|特典)\\s*0*(\\d{1,4})(?=[^0-9]|$)", value)\n        if special:\n            season = 0\n            episodes.add(int(special.group(1)))\n\n    # 动漫/压制组常用弱格式：\"Title - 06\"、\"06.mkv\"、\"[07]\"、\"08v2\"。\n    # 只在所有严格规则都失败时启用；4 位年份/2160p 不会命中，并排除常见编码号。\n    if not episodes:\n        basename = str(value or "").replace("\\\\", "/").rsplit("/", 1)[-1]\n        stem = re.sub(r"\\.[A-Za-z0-9]{2,5}$", "", basename).strip()\n        fallback_patterns = (\n            r"[\\[【(（]\\s*0*(\\d{1,3})(?:v\\d+)?\\s*[\\]】)）]",\n            r"(?:^|[\\s._])[-–—]\\s*0*(\\d{1,3})(?:v\\d+)?(?=\\s|[._\\[(（]|$)",\n            r"^\\s*0*(\\d{1,3})(?:v\\d+)?(?=\\s|[._\\-\\[(（]|$)",\n            r"(?:^|[\\s._-])0*(\\d{1,3})(?:v\\d+)?$",\n        )\n        for pattern in fallback_patterns:\n            matched = re.search(pattern, stem, re.I)\n            if not matched:\n                continue\n            candidate = int(matched.group(1))\n            if 0 < candidate <= 500 and candidate not in {264, 265, 266}:\n                episodes.add(candidate)\n                break\n\n    return season, sorted(ep for ep in episodes if ep > 0)\n'''
replace_once(old_episode_tail, new_episode_tail, 'episode fallback')

# Natural sort is used only for the conservative full-season inference fallback.
anchor = '''def _is_subtitle(value: Any) -> bool:\n    return _file_extension(value) in SUBTITLE_EXTENSIONS\n\n\ndef _extract_result_list(response: Any) -> List[dict]:\n'''
replacement = '''def _is_subtitle(value: Any) -> bool:\n    return _file_extension(value) in SUBTITLE_EXTENSIONS\n\n\ndef _natural_media_sort_key(value: Any) -> tuple:\n    parts = re.split(r"(\\d+)", str(value or "").lower())\n    return tuple((0, int(part)) if part.isdigit() else (1, part) for part in parts if part != "")\n\n\ndef _extract_result_list(response: Any) -> List[dict]:\n'''
replace_once(anchor, replacement, 'natural sort helper')

# More list-field compatibility; useful for diagnosing API shape drift without silently returning zero files.
replace_once(
    '    for key in ("list", "files", "items", "records", "fileList", "infoList"):\n',
    '    for key in ("list", "files", "items", "records", "fileList", "infoList", "rows", "dataList", "resList", "resources"):\n',
    'result list aliases',
)

# Persist only this plugin's own logs. Convert the one static logger-using method to an instance method first,
# then route class logger calls through the plugin log sink.
replace_once(
    '    @staticmethod\n    def _list_subscriptions(state: Optional[str] = "N,R") -> List[Any]:\n',
    '    def _list_subscriptions(self, state: Optional[str] = "N,R") -> List[Any]:\n',
    'list subscriptions instance method',
)
class_marker = 'class GuangYaTransferAssistant(_PluginBase):'
prefix, class_body = text.split(class_marker, 1)
for old, new in (
    ('logger.info(', 'self._plugin_log("INFO", '),
    ('logger.warning(', 'self._plugin_log("WARNING", '),
    ('logger.error(', 'self._plugin_log("ERROR", '),
    ('logger.exception(', 'self._plugin_log("EXCEPTION", '),
):
    class_body = class_body.replace(old, new)
text = prefix + class_marker + class_body

log_anchor = '''    def get_state(self) -> bool:\n        return self._enabled\n\n    def get_service(self) -> List[Dict[str, Any]]:\n'''
log_helper = '''    def get_state(self) -> bool:\n        return self._enabled\n\n    def _plugin_log(self, level: str, message: Any, *args: Any) -> None:\n        \"\"\"同时写 MoviePilot 日志和插件自己的持久日志，页面只展示本插件记录。\"\"\"\n        level_name = str(level or "INFO").upper()\n        try:\n            rendered = str(message) % args if args else str(message)\n        except Exception:\n            rendered = " ".join([str(message), *(str(arg) for arg in args)])\n        method_name = "exception" if level_name == "EXCEPTION" else level_name.lower()\n        log_method = getattr(logger, method_name, logger.info)\n        try:\n            log_method(message, *args)\n        except Exception:\n            pass\n        try:\n            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")\n            with self._state_lock:\n                rows = list(self.get_data("plugin_logs") or [])\n                rows.append({"time": now, "level": level_name, "message": rendered})\n                if len(rows) > 1000:\n                    rows = rows[-1000:]\n                self.save_data("plugin_logs", rows)\n        except Exception:\n            # 日志持久化失败不能影响转存主流程。\n            pass\n\n    def get_service(self) -> List[Dict[str, Any]]:\n'''
replace_once(log_anchor, log_helper, 'plugin log helper')

# Data schema v6 rechecks old no_new_episode decisions once, because earlier parser versions could have
# permanently marked a resource processed simply because its filename had an unknown episode style.
replace_once('    _data_schema_version = 5\n', '    _data_schema_version = 6\n', 'schema version')
old_schema = '''        if version >= self._data_schema_version:\n            return\n        # v5 延续 v4 媒体事实；新增日报与人工任务状态均为可选数据，无需破坏性迁移。\n        self.save_data("data_meta", {\n'''
new_schema = '''        if version >= self._data_schema_version:\n            return\n        if version < 6:\n            records = self.get_data("processed_entries") or {}\n            before = len(records)\n            records = {key: row for key, row in records.items() if str((row or {}).get("status") or "") != "no_new_episode"}\n            if len(records) != before:\n                self.save_data("processed_entries", records)\n                self._plugin_log("INFO", "【光鸭转存助手】【迁移】重新开放 %s 条旧 no_new_episode 记录，使用新版文件名解析重新检查", before - len(records))\n        # v6 保留既有媒体事实/任务；仅重新评估旧版可能误判的 no_new_episode 消息。\n        self.save_data("data_meta", {\n'''
replace_once(old_schema, new_schema, 'schema migration')

# Planner diagnostics + conservative inference when an entire season has exactly N video files but filenames
# themselves do not expose E01 style numbering.
replace_once(
    '        self, probe: Dict[str, Any], assets: Dict[str, Any], subscribe: Any = None,\n        target_path: str = "", stats: Optional[Dict[str, int]] = None,\n',
    '        self, probe: Dict[str, Any], assets: Dict[str, Any], subscribe: Any = None,\n        target_path: str = "", stats: Optional[Dict[str, Any]] = None,\n',
    'planner stats type',
)
replace_once(
    '        counters = {"total": len(files), "eligible": 0, "inventory": 0, "fact": 0, "episode": 0, "auxiliary": 0}\n',
    '        counters = {"total": len(files), "eligible": 0, "inventory": 0, "fact": 0, "episode": 0, "auxiliary": 0, "video": 0, "subtitle": 0, "unparsed": 0, "inferred": 0}\n        unparsed_paths: List[str] = []\n        unsupported_paths: List[str] = []\n',
    'planner counters',
)
planner_anchor = '''            for value in (getattr(subscribe, "note", None) or []):\n                try:\n                    done_episodes.add(int(value))\n                except (TypeError, ValueError):\n                    continue\n        planned = []\n        for item in files:\n'''
planner_insert = '''            for value in (getattr(subscribe, "note", None) or []):\n                try:\n                    done_episodes.add(int(value))\n                except (TypeError, ValueError):\n                    continue\n\n        inferred_episode_by_id: Dict[str, List[int]] = {}\n        if is_tv and total_episode > 0 and start_episode == 1:\n            video_rows = []\n            for seq_item in files:\n                seq_rel = _safe_relative_path(seq_item.get("relative_path") or seq_item.get("name") or "")\n                seq_effective = seq_rel[len(strip_root) + 1:] if strip_root and seq_rel.startswith(strip_root + "/") else seq_rel\n                seq_effective = _safe_relative_path(seq_effective)\n                if not _is_video(seq_effective):\n                    continue\n                file_season, parsed_eps = _episode_numbers(seq_effective)\n                video_rows.append((seq_item, seq_effective, file_season, parsed_eps))\n            # 只有视频数量与整季总集数完全一致时才按自然顺序推断，避免把更新包/花絮错当集数。\n            if len(video_rows) == total_episode:\n                ordered = sorted(video_rows, key=lambda row: _natural_media_sort_key(row[1]))\n                try:\n                    wanted_season = int(subscribe_season) if subscribe_season not in (None, "") else None\n                except (TypeError, ValueError):\n                    wanted_season = None\n                consistent = True\n                for index, (_, _, file_season, parsed_eps) in enumerate(ordered, 1):\n                    if wanted_season is not None and file_season is not None and file_season != wanted_season:\n                        consistent = False\n                        break\n                    if parsed_eps and index not in parsed_eps:\n                        consistent = False\n                        break\n                if consistent:\n                    for index, (seq_item, _, _, parsed_eps) in enumerate(ordered, 1):\n                        if not parsed_eps:\n                            inferred_episode_by_id[str(seq_item.get("id") or "")] = [index]\n\n        planned = []\n        for item in files:\n'''
replace_once(planner_anchor, planner_insert, 'planner inference')

media_anchor = '''            is_video = _is_video(effective)\n            is_subtitle = _is_subtitle(effective)\n            if self._media_only and not (is_video or is_subtitle):\n                counters["auxiliary"] += 1\n                continue\n            if is_tv and (is_video or is_subtitle):\n                file_season, episodes = _episode_numbers(effective)\n'''
media_replace = '''            is_video = _is_video(effective)\n            is_subtitle = _is_subtitle(effective)\n            if is_video:\n                counters["video"] += 1\n            elif is_subtitle:\n                counters["subtitle"] += 1\n            if self._media_only and not (is_video or is_subtitle):\n                counters["auxiliary"] += 1\n                if len(unsupported_paths) < 12:\n                    unsupported_paths.append(effective)\n                continue\n            if is_tv and (is_video or is_subtitle):\n                file_season, episodes = _episode_numbers(effective)\n                if not episodes:\n                    inferred = inferred_episode_by_id.get(str(item.get("id") or ""))\n                    if inferred:\n                        episodes = list(inferred)\n                        counters["inferred"] += 1\n'''
replace_once(media_anchor, media_replace, 'planner media diagnostics')
replace_once(
    '''                elif done_episodes or start_episode > 1:\n                    # 已有订阅进度时，无法识别集号的 TV 文件不冒险重复转存。\n                    counters["episode"] += 1\n                    continue\n''',
    '''                elif done_episodes or start_episode > 1:\n                    # 已有订阅进度时仍不盲转未知集号，但必须显式暴露诊断且不永久标记消息已处理。\n                    counters["unparsed"] += 1\n                    if len(unparsed_paths) < 12:\n                        unparsed_paths.append(effective)\n                    counters["episode"] += 1\n                    continue\n''',
    'unparsed diagnostics',
)
replace_once(
    '''        if stats is not None:\n            stats.clear()\n            stats.update(counters)\n        return planned\n''',
    '''        if stats is not None:\n            stats.clear()\n            stats.update(counters)\n            stats["unparsed_paths"] = list(unparsed_paths)\n            stats["unsupported_paths"] = list(unsupported_paths)\n        return planned\n''',
    'planner stats output',
)

# Surface exact share/file-level reasons and do not permanently consume entries that were skipped solely due parser limitations.
flow_anchor = '''            planned = self._plan_incremental_files(probe, assets, subscribe=subscribe, target_path=target_path, stats=stats)\n            valid_route_match = True\n            job_key = self._job_key(subscribe, entry)\n'''
flow_replace = '''            planned = self._plan_incremental_files(probe, assets, subscribe=subscribe, target_path=target_path, stats=stats)\n            valid_route_match = True\n            self._plugin_log(\n                "INFO",\n                "【光鸭转存助手】【分享解析】#%s %s share_id=%s 节点=%s 叶子=%s 视频=%s 字幕=%s 可用=%s 未识别集号=%s 推断集号=%s",\n                sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0], probe.get("file_count") or 0, probe.get("leaf_count") or 0,\n                stats.get("video", 0), stats.get("subtitle", 0), stats.get("eligible", 0), stats.get("unparsed", 0), stats.get("inferred", 0),\n            )\n            job_key = self._job_key(subscribe, entry)\n'''
replace_once(flow_anchor, flow_replace, 'share diagnostics log')

no_eligible_old = '''            if stats.get("eligible", 0) <= 0:\n                message = "分享内没有需要的新剧集；已入库/已完成/范围外内容不再重复测试"\n                self._mark_entry_processed(entry, "no_new_episode", message, subscribe)\n                synchronized_match = True\n                self._plugin_log("INFO", "【光鸭转存助手】【消息去重】#%s %s share_id=%s %s", sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0], message)\n                continue\n'''
no_eligible_new = '''            if stats.get("eligible", 0) <= 0:\n                if stats.get("unparsed", 0):\n                    samples = "、".join(str(value) for value in (stats.get("unparsed_paths") or [])[:8])\n                    message = f"分享内有 {stats.get('unparsed', 0)} 个媒体/字幕文件无法解析集号，未标记为已处理；示例：{samples or '-'}"\n                    errors.append(message)\n                    self._plugin_log("WARNING", "【光鸭转存助手】【文件识别】#%s %s share_id=%s %s", sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0], message)\n                    continue\n                if self._media_only and stats.get("total", 0) > 0 and not stats.get("video", 0) and not stats.get("subtitle", 0):\n                    samples = "、".join(str(value) for value in (stats.get("unsupported_paths") or [])[:8])\n                    message = f"分享已读取 {stats.get('total', 0)} 个叶子文件，但没有识别到支持的视频/字幕扩展名；示例：{samples or '-'}"\n                    errors.append(message)\n                    self._plugin_log("WARNING", "【光鸭转存助手】【文件识别】#%s %s share_id=%s %s", sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0], message)\n                    continue\n                message = "分享内没有需要的新剧集；已入库/已完成/范围外内容不再重复测试"\n                self._mark_entry_processed(entry, "no_new_episode", message, subscribe)\n                synchronized_match = True\n                self._plugin_log("INFO", "【光鸭转存助手】【消息去重】#%s %s share_id=%s %s", sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0], message)\n                continue\n'''
replace_once(no_eligible_old, no_eligible_new, 'do not consume unparsed entries')

# Add plugin-only full log card and APIs.
page_anchor = '''        resources = []\n        for entry in list(index.get("items") or [])[:150]:\n'''
page_insert = '''        plugin_log_rows = list(self.get_data("plugin_logs") or [])\n        plugin_log_items = []\n        for row in reversed(plugin_log_rows[-1000:]):\n            plugin_log_items.append({\n                "component": "VListItem",\n                "props": {\n                    "title": f"{row.get('time') or '-'} · {row.get('level') or 'INFO'}",\n                    "subtitle": str(row.get("message") or ""),\n                },\n            })\n        contents.append({\n            "component": "VCard",\n            "props": {"variant": "outlined", "class": "mt-4"},\n            "content": [\n                {"component": "VCardTitle", "text": f"光鸭转存助手插件日志（{len(plugin_log_rows[-1000:])} 条）"},\n                {"component": "VCardText", "text": "这里只显示光鸭转存助手自己的完整日志，不再混入 MoviePilot 全局日志。重点查看【匹配】【分享解析】【文件识别】【增量】【转存】【落盘确认】阶段。"},\n                {"component": "VCardActions", "content": [{\n                    "component": "VBtn",\n                    "props": {"size": "small", "variant": "text", "color": "warning", "prepend-icon": "mdi-delete-sweep-outline"},\n                    "text": "清空插件日志",\n                    "events": {"click": {"api": "plugin/GuangYaTransferAssistant/clear_plugin_logs", "method": "post", "params": {"token": settings.API_TOKEN}}},\n                }]},\n                {"component": "VList", "props": {"density": "compact", "style": "max-height: 680px; overflow-y: auto;"}, "content": plugin_log_items or [{"component": "VListItem", "props": {"title": "暂无插件日志"}}]},\n            ],\n        })\n\n        resources = []\n        for entry in list(index.get("items") or [])[:150]:\n'''
replace_once(page_anchor, page_insert, 'plugin log card')

api_anchor = '''            {"path": "/daily_summary", "endpoint": self.api_daily_summary, "methods": ["POST"], "summary": "立即发送一次光鸭转存摘要"},\n        ]\n'''
api_replace = '''            {"path": "/daily_summary", "endpoint": self.api_daily_summary, "methods": ["POST"], "summary": "立即发送一次光鸭转存摘要"},\n            {"path": "/plugin_logs", "endpoint": self.api_plugin_logs, "methods": ["GET"], "summary": "读取光鸭转存助手完整插件日志"},\n            {"path": "/clear_plugin_logs", "endpoint": self.api_clear_plugin_logs, "methods": ["POST"], "summary": "清空光鸭转存助手插件日志"},\n        ]\n'''
replace_once(api_anchor, api_replace, 'plugin log APIs')

api_method_anchor = '''    def api_refresh(self) -> Dict[str, Any]:\n        self._inspect_cache.clear()\n'''
api_methods = '''    def api_plugin_logs(self, limit: int = 1000) -> Dict[str, Any]:\n        try:\n            limit = max(1, min(int(limit or 1000), 1000))\n        except (TypeError, ValueError):\n            limit = 1000\n        rows = list(self.get_data("plugin_logs") or [])[-limit:]\n        return {"success": True, "count": len(rows), "items": rows}\n\n    def api_clear_plugin_logs(self) -> Dict[str, Any]:\n        self.save_data("plugin_logs", [])\n        return {"success": True, "message": "光鸭转存助手插件日志已清空"}\n\n    def api_refresh(self) -> Dict[str, Any]:\n        self._inspect_cache.clear()\n'''
replace_once(api_method_anchor, api_methods, 'plugin log API methods')

SRC.write_text(text, encoding='utf-8')

package = json.loads(PACKAGE.read_text(encoding='utf-8'))
entry = package['GuangYaTransferAssistant']
entry['version'] = '1.6.3'
entry['description'] = '光鸭订阅固定分流：优先修复“频道有资源但文件级识别后未转存”，增强动漫/弱集号解析与整季安全推断，并加入独立完整插件日志和分享解析诊断。'
entry['history'] = {
    'v1.6.3': '转存识别与诊断修复：支持 Title - 06、06.mkv、[07]、08v2 等弱集号文件名；整季视频数与目标总集数完全一致时允许安全顺序推断；无法解析集号/不支持扩展名时不再静默永久标记消息已处理，而是保留待重试并输出具体文件名；升级时重新开放旧 no_new_episode 记录；增加分享节点/叶子/视频/字幕/未识别统计；详情页加入仅属于本插件的持久完整日志（最多1000条）及日志 API。',
    **entry.get('history', {}),
}
PACKAGE.write_text(json.dumps(package, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

plugin = json.loads(PLUGIN.read_text(encoding='utf-8'))
plugin['version'] = '1.6.3'
plugin['description'] = '固定转存订阅：修复有资源却因文件集号识别失败而不转存，增加弱集号/整季安全推断、文件级诊断和独立完整插件日志。'
PLUGIN.write_text(json.dumps(plugin, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

tests = TEST.read_text(encoding='utf-8').replace('1.6.2', '1.6.3')
addition = r'''


def test_v163_weak_episode_filename_fallbacks():
    episode = ns["_episode_numbers"]
    assert episode("[NC-Raws] Some Show - 06 (B-Global 1920x1080 AVC AAC).mkv")[1] == [6]
    assert episode("06.mkv")[1] == [6]
    assert episode("[07].mp4")[1] == [7]
    assert episode("Some.Show.-.08v2.[1080p].mkv")[1] == [8]
    assert episode("Some.Show.2026.2160p.x265.mkv")[1] == []


def test_v163_unparsed_files_are_not_permanently_consumed_and_logs_are_plugin_scoped():
    assert '_data_schema_version = 6' in text
    assert '重新开放 %s 条旧 no_new_episode 记录' in text
    planner = text.split('    def _plan_incremental_files(', 1)[1].split('    @staticmethod\n    def _remember_assets', 1)[0]
    assert 'inferred_episode_by_id' in planner
    assert 'len(video_rows) == total_episode' in planner
    assert 'unparsed_paths' in planner
    flow = text.split('    def _try_transfer_subscription_inner(', 1)[1].split('    def _target_path(', 1)[0]
    assert '未标记为已处理' in flow
    assert '【光鸭转存助手】【分享解析】' in flow
    assert '【光鸭转存助手】【文件识别】' in flow
    assert 'plugin_logs' in text
    assert '光鸭转存助手插件日志' in text
    assert 'api_plugin_logs' in text and 'api_clear_plugin_logs' in text
    assert '这里只显示光鸭转存助手自己的完整日志' in text
'''
if 'test_v163_weak_episode_filename_fallbacks' not in tests:
    tests += addition
TEST.write_text(tests, encoding='utf-8')

print('GuangYa v1.6.3 transfer diagnostics patch applied')
