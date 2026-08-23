from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "plugins.v3" / "guangyatransferassistant" / "__init__.py"
TEST = ROOT / "tests" / "v3" / "guangyatransferassistant" / "test_plugin_contract.py"
PACKAGE = ROOT / "package.v3.json"
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant" / "plugin.json"

text = SRC.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    if old not in text:
        raise SystemExit(f"missing patch anchor: {label}")
    text = text.replace(old, new, 1)


def replace_section(start: str, end: str, new_block: str, label: str) -> None:
    global text
    start_pos = text.find(start)
    if start_pos < 0:
        raise SystemExit(f"missing section start: {label}")
    end_pos = text.find(end, start_pos)
    if end_pos < 0:
        raise SystemExit(f"missing section end: {label}")
    text = text[:start_pos] + new_block + text[end_pos:]


replace_once('plugin_version = "1.4.0"', 'plugin_version = "1.5.0"', 'version')

# ---- 别名匹配：只做规范化精确候选，不做模糊相似度，避免误转 ----
entry_reason_start = 'def _entry_match_reason(entry: Dict[str, Any], subscribe: Any) -> Tuple[bool, str]:\n'
entry_reason_end = 'def _safe_rule_match(pattern: Any, value: str) -> bool:\n'
new_entry_reason = r'''def _subscription_aliases(subscribe: Any) -> List[str]:
    """收集 MoviePilot 订阅上可用的安全别名；只做规范化标题匹配，不做编辑距离模糊匹配。"""
    values: List[str] = []
    for field in (
        "name", "title", "original_name", "original_title", "en_name", "cn_name",
        "media_name", "aka", "aliases", "alias",
    ):
        raw = getattr(subscribe, field, None)
        if raw in (None, ""):
            continue
        if isinstance(raw, dict):
            candidates = list(raw.values())
        elif isinstance(raw, (list, tuple, set)):
            candidates = list(raw)
        else:
            candidates = [raw]
        for candidate in candidates:
            candidate = str(candidate or "").strip()
            if not candidate:
                continue
            values.append(candidate)
            # 仅拆明确的别名分隔符，避免把标题中的普通 / 误切。
            if "|" in candidate or "／" in candidate:
                values.extend(part.strip() for part in re.split(r"[|／]", candidate) if part.strip())
    result: List[str] = []
    seen = set()
    for value in values:
        normalized = _normalize_media_text(value)
        if len(normalized) < 2 or normalized in seen:
            continue
        seen.add(normalized)
        result.append(value)
    return result


def _entry_match_reason(entry: Dict[str, Any], subscribe: Any) -> Tuple[bool, str]:
    source = str(getattr(subscribe, "media_source", "") or "").lower()
    media_id = str(getattr(subscribe, "media_id", "") or "")
    entry_tmdb = str(entry.get("tmdb_id") or "")
    primary_name = getattr(subscribe, "name", "")
    matched = _entry_matches_subscription(
        entry,
        primary_name,
        getattr(subscribe, "year", None),
        getattr(subscribe, "season", None),
        source,
        media_id,
    )
    if matched:
        if entry_tmdb and media_id and ("tmdb" in source or "themoviedb" in source) and entry_tmdb == media_id:
            return True, "TMDB精确"
        return True, "标题/年份/季匹配"

    # 如果频道和订阅都有可比较 TMDB 且不一致，绝不允许别名绕过身份冲突。
    if entry_tmdb and media_id and ("tmdb" in source or "themoviedb" in source):
        return False, ""

    primary_norm = _normalize_media_text(primary_name)
    for alias in _subscription_aliases(subscribe):
        alias_norm = _normalize_media_text(alias)
        if alias_norm == primary_norm or len(alias_norm) < 3:
            continue
        if _entry_matches_subscription(
            entry,
            alias,
            getattr(subscribe, "year", None),
            getattr(subscribe, "season", None),
            source,
            media_id,
        ):
            return True, "别名匹配"
    return False, ""


'''
replace_section(entry_reason_start, entry_reason_end, new_entry_reason, 'alias match')

# ---- 更健壮的剧集编号解析 ----
episode_start = 'def _episode_numbers(path: Any) -> Tuple[Optional[int], List[int]]:\n'
episode_end = 'def _entry_serial_state(entry: Dict[str, Any]) -> Dict[str, Any]:\n'
new_episode = r'''def _episode_numbers(path: Any) -> Tuple[Optional[int], List[int]]:
    """解析常见季集写法：S01E02、S01.EP.02、1x02、E02-E04、E02E03、第2-4集/话。"""
    value = str(path or "")
    season: Optional[int] = None
    episodes = set()

    # S01E23-E25 / S01.EP.23 / Season 01 EP 23。
    season_block = re.search(
        r"(?i)S(?:eason)?[\s._-]*0*(\d{1,2})[\s._-]*E(?:P)?[\s._-]*0*(\d{1,4})"
        r"(?:[\s._]*(?:-|~|—|至)[\s._]*E?(?:P)?[\s._-]*0*(\d{1,4}))?",
        value,
    )
    if season_block:
        season = int(season_block.group(1))
        start = int(season_block.group(2))
        end = int(season_block.group(3)) if season_block.group(3) else start
        if end >= start and end - start <= 300:
            episodes.update(range(start, end + 1))
    else:
        season_match = re.search(r"(?i)(?:^|[^A-Za-z0-9])S(?:eason)?[\s._-]*0*(\d{1,2})(?=[^0-9]|$)", value)
        if season_match:
            season = int(season_match.group(1))

    # 1x02 / 01x002。
    x_match = re.search(r"(?i)(?:^|[^0-9])0*(\d{1,2})x0*(\d{1,4})(?=[^0-9]|$)", value)
    if x_match:
        if season is None:
            season = int(x_match.group(1))
        episodes.add(int(x_match.group(2)))

    # E02 / EP02 / EP.02 / E02-E04。全局扫描还能覆盖 E01E02 连写。
    range_pattern = re.compile(
        r"(?i)(?:^|[^A-Za-z])E(?:P)?[\s._-]*0*(\d{1,4})"
        r"(?:[\s._]*(?:-|~|—|至)[\s._]*E?(?:P)?[\s._-]*0*(\d{1,4}))?"
    )
    for matched in range_pattern.finditer(value):
        start = int(matched.group(1))
        end = int(matched.group(2)) if matched.group(2) else start
        if end >= start and end - start <= 300:
            episodes.update(range(start, end + 1))
    for ep in re.findall(r"(?i)E(?:P)?[\s._-]*0*(\d{1,4})", value):
        episodes.add(int(ep))

    # 中文 第23-25集 / 第23至25话。
    for matched in re.finditer(r"第\s*(\d{1,4})(?:\s*[-~—至]\s*(\d{1,4}))?\s*[集话]", value):
        start = int(matched.group(1))
        end = int(matched.group(2)) if matched.group(2) else start
        if end >= start and end - start <= 300:
            episodes.update(range(start, end + 1))

    return season, sorted(ep for ep in episodes if ep > 0)


'''
replace_section(episode_start, episode_end, new_episode, 'episode parser')

# ---- 失败通知归一化，避免同类错误只因 share/task ID 不同反复推送 ----
asset_marker = 'def _asset_identity(relative_path: str, size: Any = 0, digest: Any = "") -> str:\n'
asset_pos = text.find(asset_marker)
if asset_pos < 0:
    raise SystemExit('missing asset identity marker')
class_pos = text.find('class GuangYaTransferAssistant(_PluginBase):\n', asset_pos)
if class_pos < 0:
    raise SystemExit('missing class marker')
insert_failure = r'''def _failure_notice_fingerprint(message: Any) -> str:
    """把动态 share/task/token 等噪声归一化，稳定识别同一类失败。"""
    value = str(message or "").lower()
    value = re.sub(r"share[_ -]?id\s*[=:：]\s*[a-z0-9_-]+", "share_id=*", value, flags=re.I)
    value = re.sub(r"task[_ -]?id\s*[=:：]\s*[a-z0-9_-]+", "task_id=*", value, flags=re.I)
    value = re.sub(r"\b[a-z0-9_-]{20,}\b", "*", value, flags=re.I)
    value = re.sub(r"\s+", " ", value).strip()[:1000]
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


'''
text = text[:class_pos] + insert_failure + text[class_pos:]

replace_once(
    'notice_key = f"{sid}:{hashlib.sha256(final_message.encode(\'utf-8\')).hexdigest()[:12]}"',
    'notice_key = f"{sid}:{_failure_notice_fingerprint(final_message)}"',
    'failure fingerprint',
)

# ---- 状态控制台与安全单订阅操作 ----
page_marker = '    def get_page(self) -> Optional[List[dict]]:\n'
page_pos = text.find(page_marker)
if page_pos < 0:
    raise SystemExit('missing get_page marker')
console_helpers = r'''    def _subscription_console_snapshot(self, subscribe: Any, entries: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """汇总一个固定转存订阅的运行状态，供详情页直接诊断。"""
        sid = int(getattr(subscribe, "id", 0) or 0)
        prefix = self._media_fact_prefix(subscribe)
        state = str(getattr(subscribe, "state", "") or "")
        done, total, lack = self._subscription_episode_progress(subscribe)
        missing = self._subscription_missing_episodes(subscribe)
        channel_state = self._channel_state_for_subscription(subscribe, entries or [])

        jobs = [row for row in (self.get_data("transfer_jobs") or {}).values()
                if isinstance(row, dict) and str(row.get("media") or "") == prefix]
        jobs.sort(key=lambda row: str(row.get("updated") or ""), reverse=True)
        pending_status = {"submitted", "task_confirmed", "verifying"}
        pending_jobs = [row for row in jobs if str(row.get("status") or "") in pending_status]
        failed_jobs = [row for row in jobs if str(row.get("status") or "") == "failed"]

        processed_count = sum(
            1 for row in (self.get_data("processed_entries") or {}).values()
            if isinstance(row, dict) and str(row.get("media") or "") == prefix
        )
        facts = self.get_data("media_facts") or {}
        fact_count = sum(1 for key in facts.keys() if str(key) == prefix or str(key).startswith(prefix + ":e"))

        matched_entries = []
        for entry in entries or []:
            if entry.get("stale"):
                continue
            matched, _ = _entry_match_reason(entry, subscribe)
            if matched:
                matched_entries.append(entry)
        numeric_ids = [int(item.get("message_id")) for item in matched_entries if str(item.get("message_id") or "").isdigit()]
        last_message = str(max(numeric_ids)) if numeric_ids else "-"

        latest_job = jobs[0] if jobs else {}
        latest_status = str(latest_job.get("status") or "")
        latest_event = str(latest_job.get("updated") or "-")
        alert_type = "info"
        label = "等待新消息"
        if state not in ("N", "R"):
            label = f"非活跃订阅（{state or '-'}）"
            alert_type = "warning"
        elif pending_jobs:
            label = f"等待落盘确认（{len(pending_jobs)} 个任务）"
            alert_type = "warning"
        elif latest_status == "failed" and failed_jobs:
            label = "最近转存失败，等待新消息/重试"
            alert_type = "error"
        elif total and lack > 0 and channel_state.get("ongoing"):
            label = f"连载中 · 缺 {lack} 集"
            alert_type = "info"
        elif total and lack > 0:
            label = f"缺集 · 剩余 {lack} 集"
            alert_type = "warning"
        elif total and lack == 0 and channel_state.get("ongoing") and not channel_state.get("complete"):
            label = "当前已齐 · 连载保护中"
            alert_type = "success"
        elif total and lack == 0:
            label = "目标已齐 · 等待完成确认"
            alert_type = "success"
        elif latest_status in ("synced", "verified"):
            label = "已同步 · 等待新消息"
            alert_type = "success"

        return {
            "label": label, "alert_type": alert_type,
            "pending_jobs": len(pending_jobs), "failed_jobs": len(failed_jobs),
            "processed_count": processed_count, "fact_count": fact_count,
            "last_message": last_message, "latest_event": latest_event,
            "done": done, "total": total, "lack": lack, "missing": missing,
            "channel_state": channel_state,
        }

    def _reset_subscription_check_state(self, subscribe: Any) -> Dict[str, Any]:
        """只重置消息检查/失败记录，保留媒体事实、文件库存和已完成集，避免重置导致重复转存。"""
        sid = int(getattr(subscribe, "id", 0) or 0)
        prefix = self._media_fact_prefix(subscribe)
        jobs = self.get_data("transfer_jobs") or {}
        pending = [key for key, row in jobs.items()
                   if isinstance(row, dict) and str(row.get("media") or "") == prefix
                   and str(row.get("status") or "") in {"submitted", "task_confirmed", "verifying"}]
        if pending:
            return {"success": False, "message": f"仍有 {len(pending)} 个待落盘确认任务，请先复查待落盘状态"}

        processed = self.get_data("processed_entries") or {}
        removed_processed = 0
        for key in list(processed.keys()):
            row = processed.get(key) or {}
            if isinstance(row, dict) and str(row.get("media") or "") == prefix:
                processed.pop(key, None)
                removed_processed += 1
        self.save_data("processed_entries", processed)

        removed_jobs = 0
        for key in list(jobs.keys()):
            row = jobs.get(key) or {}
            if isinstance(row, dict) and str(row.get("media") or "") == prefix and str(row.get("status") or "") in {"failed", "synced", "verified"}:
                jobs.pop(key, None)
                removed_jobs += 1
        self.save_data("transfer_jobs", jobs)

        notices = self.get_data("failure_notices") or {}
        removed_notices = 0
        for key in list(notices.keys()):
            if str(key).startswith(f"{sid}:"):
                notices.pop(key, None)
                removed_notices += 1
        self.save_data("failure_notices", notices)
        self._inspect_cache.clear()
        logger.warning(
            "【光鸭转存助手】【状态重置】#%s %s 已重置检查记录：消息=%s，结束任务=%s，失败通知=%s；媒体事实/库存/进度均保留",
            sid, getattr(subscribe, "name", ""), removed_processed, removed_jobs, removed_notices,
        )
        return {
            "success": True,
            "message": f"已重置检查状态：消息 {removed_processed} 条、结束任务 {removed_jobs} 条；媒体事实/库存/订阅进度已保留",
        }

'''
text = text[:page_pos] + console_helpers + text[page_pos:]

# get_page 中加入运行状态摘要与安全按钮。
replace_once(
    '            channel_state = self._channel_state_for_subscription(sub, index.get("items") or [])\n            serial_text = ""\n',
    '            channel_state = self._channel_state_for_subscription(sub, index.get("items") or [])\n            runtime = self._subscription_console_snapshot(sub, index.get("items") or [])\n            serial_text = ""\n',
    'page runtime snapshot',
)
replace_once(
    '            actions = [{\n                "component": "VBtn",\n                "props": {"size": "small", "variant": "outlined", "prepend-icon": "mdi-refresh"},\n                "text": "立即检查缺集",\n                "events": {"click": {"api": "plugin/GuangYaTransferAssistant/check_missing", "method": "get", "params": {"subscribe_id": sid, "token": settings.API_TOKEN}}},\n            }]\n',
    '            actions = [{\n                "component": "VBtn",\n                "props": {"size": "small", "variant": "outlined", "prepend-icon": "mdi-refresh"},\n                "text": "立即检查缺集",\n                "events": {"click": {"api": "plugin/GuangYaTransferAssistant/check_missing", "method": "get", "params": {"subscribe_id": sid, "token": settings.API_TOKEN}}},\n            }]\n            if runtime.get("pending_jobs"):\n                actions.append({\n                    "component": "VBtn",\n                    "props": {"size": "small", "variant": "outlined", "color": "warning", "prepend-icon": "mdi-file-sync-outline"},\n                    "text": "复查待落盘",\n                    "events": {"click": {"api": "plugin/GuangYaTransferAssistant/recheck_pending", "method": "get", "params": {"subscribe_id": sid, "token": settings.API_TOKEN}}},\n                })\n            actions.append({\n                "component": "VBtn",\n                "props": {"size": "small", "variant": "text", "prepend-icon": "mdi-restart"},\n                "text": "重置检查状态",\n                "events": {"click": {"api": "plugin/GuangYaTransferAssistant/reset_state", "method": "get", "params": {"subscribe_id": sid, "token": settings.API_TOKEN}}},\n            })\n',
    'page actions',
)
replace_once(
    '                    {"component": "VCardTitle", "text": f"{sub.name} ({getattr(sub, \'year\', \'\') or \'-\'})"},\n                    {"component": "VCardText", "text": f"订阅ID {sid} · 状态 {state}{progress_text}{missing_text}{serial_text} · 去重资源 {asset_count} 个 · {state_text}"},\n                    {"component": "VCardActions", "content": actions},\n',
    '                    {"component": "VCardTitle", "text": f"{sub.name} ({getattr(sub, \'year\', \'\') or \'-\'})"},\n                    {"component": "VAlert", "props": {"type": runtime.get("alert_type") or "info", "variant": "tonal", "density": "compact", "class": "mx-4 mb-2", "text": runtime.get("label") or "等待新消息"}},\n                    {"component": "VCardText", "text": f"订阅ID {sid} · 状态 {state}{progress_text}{missing_text}{serial_text} · 媒体事实 {runtime.get(\'fact_count\') or 0} · 已处理消息 {runtime.get(\'processed_count\') or 0} · 待落盘 {runtime.get(\'pending_jobs\') or 0} · 最近频道消息 {runtime.get(\'last_message\') or \'-\'} · 去重资源 {asset_count} 个 · {state_text}"},\n                    {"component": "VCardActions", "content": actions},\n',
    'page card console',
)

# get_api 新增安全操作。
replace_once(
    '            {"path": "/release_native", "endpoint": self.api_release_native, "methods": ["GET"], "summary": "将指定转存订阅切换回 MoviePilot 普通下载"},\n',
    '            {"path": "/release_native", "endpoint": self.api_release_native, "methods": ["GET"], "summary": "将指定转存订阅切换回 MoviePilot 普通下载"},\n            {"path": "/recheck_pending", "endpoint": self.api_recheck_pending, "methods": ["GET"], "summary": "只复查指定订阅的待落盘任务，不自动重复提交"},\n            {"path": "/reset_state", "endpoint": self.api_reset_state, "methods": ["GET"], "summary": "安全重置指定订阅的频道检查状态，保留媒体事实/库存/进度"},\n',
    'api list',
)

# API 实现插在 api_release_native 前。
release_marker = '    def api_release_native(self, subscribe_id: int = 0) -> Dict[str, Any]:\n'
release_pos = text.find(release_marker)
if release_pos < 0:
    raise SystemExit('missing release api marker')
new_apis = r'''    def api_recheck_pending(self, subscribe_id: int = 0) -> Dict[str, Any]:
        """复查已经提交但尚未落盘确认的任务；force=False 保证不会绕过 v1.4 的防重复提交保护。"""
        sid = int(subscribe_id or 0)
        subscribe = self._find_subscription(sid)
        if not sid or not subscribe:
            return {"success": False, "message": "订阅不存在"}
        if sid not in set(self._selected_subscriptions):
            return {"success": False, "message": "该订阅当前不是光鸭固定转存路线"}
        self._inspect_cache.clear()
        result = self._try_transfer_subscription(subscribe, force=False)
        result["console"] = self._subscription_console_snapshot(
            self._find_subscription(sid) or subscribe,
            (self.get_data("channel_index") or {}).get("items") or [],
        )
        return result

    def api_reset_state(self, subscribe_id: int = 0) -> Dict[str, Any]:
        sid = int(subscribe_id or 0)
        subscribe = self._find_subscription(sid)
        if not sid or not subscribe:
            return {"success": False, "message": "订阅不存在"}
        if sid not in set(self._selected_subscriptions):
            return {"success": False, "message": "该订阅当前不是光鸭固定转存路线"}
        return self._reset_subscription_check_state(subscribe)

'''
text = text[:release_pos] + new_apis + text[release_pos:]

SRC.write_text(text, encoding="utf-8")

# ---- 元数据 ----
package = json.loads(PACKAGE.read_text(encoding="utf-8"))
entry = package["GuangYaTransferAssistant"]
entry["version"] = "1.5.0"
entry["description"] = "光鸭订阅固定分流：状态控制台、单订阅安全复查/重置、别名匹配、增强剧集解析、失败通知去噪，并保留媒体语义幂等/游标/任务恢复/落盘确认。"
history = entry.get("history") or {}
entry["history"] = {
    "v1.5.0": "体验与可观测性版本：详情页加入订阅运行状态控制台，显示等待新消息/缺集/连载保护/待落盘/失败等状态及媒体事实、已处理消息、最近频道消息；新增待落盘安全复查和单订阅检查状态重置（保留媒体事实/库存/进度）；增加 MoviePilot 标题别名匹配但禁止模糊相似度和 TMDB 冲突绕过；增强 EP.08、1x08、E01E02、第N话等剧集命名识别；失败通知指纹归一化，减少仅因 share/task ID 变化造成的重复告警。",
    **history,
}
PACKAGE.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")

plugin = json.loads(PLUGIN.read_text(encoding="utf-8"))
plugin["version"] = "1.5.0"
plugin["description"] = "固定转存订阅：状态控制台、安全复查/重置、别名匹配、增强剧集解析、失败通知去噪及 v1.4 可靠性闭环。"
PLUGIN.write_text(json.dumps(plugin, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# ---- 回归测试 ----
tests = TEST.read_text(encoding="utf-8")
addition = r'''


def test_v150_version_and_console_contracts():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    local = json.loads((ROOT / "plugins.v3" / "guangyatransferassistant" / "plugin.json").read_text(encoding="utf-8"))
    assert package["version"] == "1.5.0" and local["version"] == "1.5.0"
    assert 'plugin_version = "1.5.0"' in text
    assert '_subscription_console_snapshot' in text
    assert '等待落盘确认' in text and '当前已齐 · 连载保护中' in text
    assert '复查待落盘' in text and '重置检查状态' in text
    assert '/recheck_pending' in text and '/reset_state' in text
    assert '媒体事实' in text and '已处理消息' in text and '最近频道消息' in text


def test_alias_matching_never_overrides_tmdb_conflict():
    class Sub:
        name = '中文主标题'
        original_title = 'Library Sheep'
        year = 2026
        season = 1
        media_source = 'themoviedb'
        media_id = '12345'
    sub = Sub()
    alias_entry = {
        'text': '名称：Library Sheep (2026) S01',
        'display_title': 'Library Sheep (2026)',
        'tmdb_id': '',
    }
    assert ns['_entry_match_reason'](alias_entry, sub) == (True, '别名匹配')
    conflict = dict(alias_entry, tmdb_id='99999')
    assert ns['_entry_match_reason'](conflict, sub) == (False, '')
    assert '模糊匹配' not in text


def test_extended_episode_parser_contracts():
    parser = ns['_episode_numbers']
    assert parser('Show.S01.EP.08.2160p.mkv') == (1, [8])
    assert parser('Show.1x09.WEB-DL.mkv') == (1, [9])
    assert parser('Show.S01E10E11E12.mkv') == (1, [10, 11, 12])
    assert parser('动画 第13-15话.mp4')[1] == [13, 14, 15]


def test_single_subscription_reset_is_safe():
    block = text.split('    def _reset_subscription_check_state(', 1)[1].split('    def get_page(', 1)[0]
    assert 'submitted' in block and 'task_confirmed' in block and 'verifying' in block
    assert '请先复查待落盘状态' in block
    assert 'processed_entries' in block and 'failure_notices' in block
    assert 'media_facts' not in block.replace('媒体事实/库存/进度均保留', '')
    assert 'transfer_inventory' not in block
    assert '媒体事实/库存/进度均保留' in block


def test_pending_recheck_does_not_force_replay():
    block = text.split('    def api_recheck_pending(', 1)[1].split('    def api_reset_state(', 1)[0]
    assert '_try_transfer_subscription(subscribe, force=False)' in block
    assert 'force=True' not in block


def test_failure_notice_fingerprint_ignores_dynamic_ids():
    fp = ns['_failure_notice_fingerprint']
    left = fp('share_id=AbCdEf123 task_id=ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890 网络错误')
    right = fp('share_id=Other999 task_id=ZZZZZZZZZZZZZZZZZZZZZZZZZZZZ 网络错误')
    assert left == right
'''
if 'test_v150_version_and_console_contracts' not in tests:
    tests += addition
# 旧版本断言升级。
tests = tests.replace('assert package["version"] == "1.4.0" and local["version"] == "1.4.0"', 'assert package["version"] == "1.5.0" and local["version"] == "1.5.0"')
tests = tests.replace("assert 'plugin_version = \"1.4.0\"' in text", "assert 'plugin_version = \"1.5.0\"' in text")
TEST.write_text(tests, encoding="utf-8")

print('GuangYa v1.5.0 experience patch applied')
