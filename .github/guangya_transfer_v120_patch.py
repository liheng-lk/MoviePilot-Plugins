from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "plugins.v3" / "guangyatransferassistant" / "__init__.py"
TEST = ROOT / "tests" / "v3" / "guangyatransferassistant" / "test_plugin_contract.py"
text = SRC.read_text(encoding="utf-8")


def replace_block(source: str, start: str, end: str, replacement: str) -> str:
    pattern = re.compile(start + r".*?(?=" + end + r")", re.S)
    source, count = pattern.subn(lambda _m: replacement, source, count=1)
    assert count == 1, f"block not found: {start} -> {end}"
    return source


text = text.replace(
    "from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit",
    "from urllib.parse import parse_qs, urlencode, unquote, urljoin, urlsplit, urlunsplit",
    1,
)

constants = r'''DEFAULT_CHANNEL_URLS = [
    "https://tgm.li668.asia/regengguangya",
    "https://tgm.li668.asia/yunpanguangya",
]
SHARE_PATTERN = re.compile(
    r"(?:(?:https?:)?//)?(?:www\.)?guangyapan\.com/(?:s|share)/[A-Za-z0-9_-]+(?:\?[^\s\"'<>]*)?",
    re.I,
)
CODE_PATTERN = re.compile(r"(?:提取码|密码|code)\s*[：:]?\s*([A-Za-z0-9]{2,16})", re.I)
ATTRIBUTE_URL_PATTERN = re.compile(
    r"(?i)\b(href|data-href|data-url|data-link|data-button-url|onclick)\s*=\s*([\"'])(.*?)\2",
    re.S,
)
TMDB_PATTERN = re.compile(r"(?i)\bTMDB\s*(?:ID)?\s*[：:#]?\s*(\d{2,9})")
PAGINATION_KEYS = {"before", "after", "offset", "page", "cursor", "max_id", "min_id"}
VIDEO_EXTENSIONS = {".mkv", ".mp4", ".ts", ".m2ts", ".avi", ".mov", ".wmv", ".flv", ".webm", ".iso", ".rmvb"}
SUBTITLE_EXTENSIONS = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".sup"}

'''
text = replace_block(text, r"DEFAULT_CHANNEL_URLS\s*=", r"def _normalize_media_text", constants)

helpers = r'''def _canonical_share_url(raw_url: str, context: str = "") -> str:
    """规范化明文、隐藏按钮和包装跳转中的光鸭分享链接。"""
    raw_url = html.unescape(str(raw_url or "").strip()).replace("\\/", "/")
    raw_url = raw_url.strip("\"'<> ").rstrip(".,，。;；)）]】")
    if "guangyapan.com" not in raw_url.lower() and "%" in raw_url:
        raw_url = _decode_url_layers(raw_url)
    if raw_url.startswith("//"):
        raw_url = "https:" + raw_url
    elif re.match(r"(?i)^(?:www\.)?guangyapan\.com/", raw_url):
        raw_url = "https://" + raw_url
    try:
        parsed = urlsplit(raw_url)
    except ValueError:
        return ""
    if not parsed.hostname or not parsed.hostname.lower().endswith("guangyapan.com"):
        return ""
    if not re.search(r"(?i)/(?:s|share)/[A-Za-z0-9_-]+", parsed.path or ""):
        return ""
    query = parse_qs(parsed.query)
    if not any(query.get(key) for key in ("code", "pwd")):
        code_match = CODE_PATTERN.search(html.unescape(context or ""))
        if code_match:
            query["code"] = [code_match.group(1)]
    normalized_query = urlencode(
        [(key, item) for key, values in query.items() for item in values]
    )
    return urlunsplit(("https", "www.guangyapan.com", parsed.path, normalized_query, ""))


def _decode_url_layers(value: Any) -> str:
    """解码 HTML 实体、JSON 斜杠和最多三层 URL 编码。"""
    current = html.unescape(str(value or "")).replace("\\/", "/").strip()
    for _ in range(3):
        decoded = unquote(current)
        if decoded == current:
            break
        current = decoded
    return current


def _html_to_text(fragment: str) -> str:
    """HTML 转文本时保留消息换行，避免相邻字段粘连。"""
    value = re.sub(r"<script\b[^>]*>.*?</script>", " ", str(fragment or ""), flags=re.I | re.S)
    value = re.sub(r"<style\b[^>]*>.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"(?i)<br\s*/?>|</(?:div|p|li|section|article|blockquote)\s*>", "\n", value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    lines = [re.sub(r"\s+", " ", line).strip() for line in value.splitlines()]
    return "\n".join(line for line in lines if line)


def _message_context_html(page_text: str, position: int) -> str:
    """优先按 Telegram data-post 消息边界取上下文，失败才回退固定窗口。"""
    decoded = str(page_text or "")
    markers = list(re.finditer(r"(?i)\bdata-post\s*=\s*[\"'][^\"']+[\"']", decoded))
    if markers:
        previous = None
        next_marker = None
        for marker in markers:
            if marker.start() <= position:
                previous = marker
            elif marker.start() > position:
                next_marker = marker
                break
        if previous:
            start = decoded.rfind("<", 0, previous.start())
            if start < 0:
                start = previous.start()
            if next_marker:
                end = decoded.rfind("<", position, next_marker.start())
                if end <= position:
                    end = next_marker.start()
            else:
                end = min(len(decoded), position + 5000)
            return decoded[start:end]
    # 兼容没有 data-post 的镜像：优先寻找外层 message wrap。
    left = decoded[max(0, position - 5000):position]
    strong = list(re.finditer(
        r"(?i)<(?:div|article)[^>]+class=[\"'][^\"']*(?:message_wrap|widget_message|tme_messages_message)[^\"']*[\"']",
        left,
    ))
    if strong:
        start = max(0, position - 5000) + strong[-1].start()
        right = decoded[position:min(len(decoded), position + 6000)]
        next_strong = re.search(
            r"(?i)<(?:div|article)[^>]+class=[\"'][^\"']*(?:message_wrap|widget_message|tme_messages_message)[^\"']*[\"']",
            right,
        )
        end = position + next_strong.start() if next_strong and next_strong.start() > 0 else min(len(decoded), position + 3500)
        return decoded[start:end]
    return decoded[max(0, position - 1800):min(len(decoded), position + 1800)]


def _entry_metadata(context_text: str, context_html: str = "") -> Dict[str, Any]:
    """提取频道消息中的标题、TMDB、集数提示和消息 ID。"""
    text = str(context_text or "")
    tmdb_match = TMDB_PATTERN.search(text)
    name_match = re.search(r"(?im)(?:^|\n)\s*(?:名称|片名|剧名)\s*[：:]\s*([^\n]{2,180})", text)
    display_title = name_match.group(1).strip() if name_match else ""
    episode_hint = ""
    for pattern in (
        r"第\s*\d{1,3}\s*[-~—至]\s*\d{1,3}\s*集",
        r"第\s*\d{1,3}\s*集",
        r"(?:更新至|更至|更新到)\s*\d{1,3}\s*集",
        r"(?i)S\d{1,2}\s*E\d{1,3}(?:\s*[-~]\s*E?\d{1,3})?",
    ):
        matched = re.search(pattern, text)
        if matched:
            episode_hint = matched.group(0)
            break
    total_match = re.search(r"全\s*(\d{1,4})\s*集", text)
    year_match = re.search(r"\b(19\d{2}|20\d{2})\b", display_title or text)
    post_match = re.search(r"(?i)\bdata-post\s*=\s*[\"'][^\"']+/(\d+)[\"']", context_html or "")
    return {
        "tmdb_id": tmdb_match.group(1) if tmdb_match else "",
        "display_title": display_title,
        "episode_hint": episode_hint,
        "total_episode_hint": int(total_match.group(1)) if total_match else None,
        "year_hint": int(year_match.group(1)) if year_match else None,
        "message_id": post_match.group(1) if post_match else "",
    }


def _extract_share_candidates(page_text: str) -> List[Dict[str, Any]]:
    """同时识别明文链接、隐藏按钮属性和 URL 编码包装链接。"""
    decoded = html.unescape(str(page_text or "")).replace("\\/", "/")
    candidates: List[Dict[str, Any]] = []
    attr_spans: List[Tuple[int, int]] = []
    for attr in ATTRIBUTE_URL_PATTERN.finditer(decoded):
        attr_name = str(attr.group(1) or "").lower()
        attr_value = _decode_url_layers(attr.group(3))
        attr_spans.append((attr.start(), attr.end()))
        tail = decoded[attr.end():min(len(decoded), attr.end() + 320)]
        is_button = bool(re.search(r"(?i)(查看资源|资源链接|光鸭云盘.{0,30}(?:查看|资源))", _html_to_text(tail)))
        matches = list(SHARE_PATTERN.finditer(attr_value))
        for found in matches:
            raw = found.group(0)
            direct_attr = bool(re.match(r"(?i)^(?:(?:https?:)?//)?(?:www\.)?guangyapan\.com/", attr_value.strip()))
            style = "隐藏按钮" if is_button and direct_attr else ("包装按钮" if is_button else ("链接属性" if direct_attr else "包装链接"))
            candidates.append({"raw_url": raw, "position": attr.start(), "link_style": style, "attribute": attr_name})
    for found in SHARE_PATTERN.finditer(decoded):
        if any(start <= found.start() <= end for start, end in attr_spans):
            continue
        candidates.append({"raw_url": found.group(0), "position": found.start(), "link_style": "明文链接", "attribute": ""})
    return candidates


def _extract_pagination_urls(page_text: str, source_url: str) -> List[str]:
    """从镜像页面发现同频道 before/page/offset 等历史翻页链接。"""
    try:
        base = urlsplit(source_url)
    except ValueError:
        return []
    result: List[str] = []
    seen = set()
    for attr in ATTRIBUTE_URL_PATTERN.finditer(html.unescape(str(page_text or ""))):
        if str(attr.group(1) or "").lower() != "href":
            continue
        raw = _decode_url_layers(attr.group(3))
        candidate = urljoin(source_url, raw)
        try:
            parsed = urlsplit(candidate)
        except ValueError:
            continue
        if parsed.hostname != base.hostname or parsed.path.rstrip("/") != base.path.rstrip("/"):
            continue
        query = parse_qs(parsed.query)
        if not PAGINATION_KEYS.intersection(query.keys()):
            continue
        if candidate not in seen and candidate != source_url:
            seen.add(candidate)
            result.append(candidate)
    return result


def _extract_channel_entries(page_text: str, source_url: str, source_label: str) -> List[Dict[str, Any]]:
    """从 Telegram 镜像 HTML 提取分享；按钮文字是否显示 URL 都不影响。"""
    decoded = html.unescape(str(page_text or "")).replace("\\/", "/")
    by_key: Dict[str, Dict[str, Any]] = {}
    for candidate in _extract_share_candidates(decoded):
        position = int(candidate.get("position") or 0)
        context_html = _message_context_html(decoded, position)
        context = _html_to_text(context_html)
        share_url = _canonical_share_url(str(candidate.get("raw_url") or ""), context)
        if not share_url:
            continue
        share_key = _share_identity(share_url)
        if not share_key:
            continue
        metadata = _entry_metadata(context, context_html)
        entry = {
            "share_url": share_url,
            "share_id": share_key.split("|", 1)[0],
            "text": context[:2200],
            "source_url": source_url,
            "source_label": source_label,
            "priority": 0 if "regeng" in source_url.lower() else 1,
            "link_style": candidate.get("link_style") or "未知",
            "stale": False,
            **metadata,
        }
        old = by_key.get(share_key)
        score = len(entry["text"]) + (600 if entry.get("tmdb_id") else 0) + (300 if entry.get("display_title") else 0)
        old_score = len(str((old or {}).get("text") or "")) + (600 if (old or {}).get("tmdb_id") else 0) + (300 if (old or {}).get("display_title") else 0)
        if not old or score > old_score:
            by_key[share_key] = entry
    return list(by_key.values())


'''
text = replace_block(text, r"def _canonical_share_url", r"def _share_identity", helpers)

match_helpers = r'''def _entry_matches_subscription(
    entry: Dict[str, Any], name: str, year: Any = None, season: Any = None,
    media_source: Any = None, media_id: Any = None,
) -> bool:
    """优先使用频道 TMDB 精确匹配；没有可比身份时才回退标题/年份/季。"""
    source = str(media_source or "").lower()
    entry_tmdb = str(entry.get("tmdb_id") or "").strip()
    subscribe_id = str(media_id or "").strip()
    comparable_tmdb = bool(entry_tmdb and subscribe_id and ("tmdb" in source or "themoviedb" in source))
    if comparable_tmdb and entry_tmdb != subscribe_id:
        return False

    text_value = str(entry.get("text") or "")
    if season not in (None, "", 0, "0"):
        explicit = re.findall(r"(?i)\bS(?:eason)?\s*0*(\d{1,2})\b", text_value)
        if explicit and int(season) not in {int(value) for value in explicit}:
            return False
    if comparable_tmdb:
        return True

    haystack = _normalize_media_text("\n".join(filter(None, [str(entry.get("display_title") or ""), text_value])))
    if not haystack:
        return False
    raw_name = str(name or "").strip()
    candidates = {
        _normalize_media_text(raw_name),
        _normalize_media_text(re.split(r"[(/（]", raw_name, maxsplit=1)[0]),
    }
    candidates = {value for value in candidates if len(value) >= 2}
    if not candidates or not any(value in haystack for value in candidates):
        return False
    if year:
        years = {int(value) for value in re.findall(r"\b(19\d{2}|20\d{2})\b", str(entry.get("display_title") or "") or text_value)}
        if years and int(year) not in years:
            return False
    return True


def _entry_match_reason(entry: Dict[str, Any], subscribe: Any) -> Tuple[bool, str]:
    source = str(getattr(subscribe, "media_source", "") or "").lower()
    media_id = str(getattr(subscribe, "media_id", "") or "")
    entry_tmdb = str(entry.get("tmdb_id") or "")
    matched = _entry_matches_subscription(
        entry,
        getattr(subscribe, "name", ""),
        getattr(subscribe, "year", None),
        getattr(subscribe, "season", None),
        source,
        media_id,
    )
    if not matched:
        return False, ""
    if entry_tmdb and media_id and ("tmdb" in source or "themoviedb" in source) and entry_tmdb == media_id:
        return True, "TMDB精确"
    return True, "标题/年份/季匹配"


def _safe_rule_match(pattern: Any, value: str) -> bool:
    """订阅字段通常是正则；非法正则时退化为大小写不敏感字面匹配。"""
    rule = str(pattern or "").strip()
    if not rule:
        return True
    try:
        return re.search(rule, value or "", re.I) is not None
    except re.error:
        return rule.lower() in str(value or "").lower()


def _episode_numbers(path: Any) -> Tuple[Optional[int], List[int]]:
    """从常见 S01E02 / E02-E03 / 第2-3集 文件名提取季和集。"""
    value = str(path or "")
    season = None
    season_match = re.search(r"(?i)(?:^|[^A-Za-z0-9])S(?:eason)?\s*0*(\d{1,2})(?=[^0-9]|$)", value)
    if season_match:
        season = int(season_match.group(1))
    episodes = set()
    for matched in re.finditer(r"(?i)(?:^|[^A-Za-z0-9])E(?:P)?\s*0*(\d{1,3})(?:\s*[-~—至]\s*E?(?:P)?\s*0*(\d{1,3}))?", value):
        start = int(matched.group(1))
        end = int(matched.group(2)) if matched.group(2) else start
        if end >= start and end - start <= 200:
            episodes.update(range(start, end + 1))
    for matched in re.finditer(r"第\s*(\d{1,3})(?:\s*[-~—至]\s*(\d{1,3}))?\s*集", value):
        start = int(matched.group(1))
        end = int(matched.group(2)) if matched.group(2) else start
        if end >= start and end - start <= 200:
            episodes.update(range(start, end + 1))
    # S01E02E03 形式补抓后续 E。
    if season is not None:
        for value_ep in re.findall(r"(?i)E\s*0*(\d{1,3})", value):
            episodes.add(int(value_ep))
    return season, sorted(ep for ep in episodes if ep > 0)


def _safe_relative_path(value: Any) -> str:
    """清理分享内相对路径，禁止 . / .. 逃逸目标目录。"""
    raw = str(value or "").replace("\\", "/").replace("\x00", "")
    parts = []
    for part in raw.split("/"):
        part = part.strip()
        if not part or part in (".", ".."):
            continue
        parts.append(part)
    return "/".join(parts)


def _file_extension(value: Any) -> str:
    name = str(value or "").rsplit("/", 1)[-1].lower()
    return "." + name.rsplit(".", 1)[-1] if "." in name else ""


def _is_video(value: Any) -> bool:
    return _file_extension(value) in VIDEO_EXTENSIONS


def _is_subtitle(value: Any) -> bool:
    return _file_extension(value) in SUBTITLE_EXTENSIONS


'''
text = replace_block(text, r"def _entry_matches_subscription", r"def _extract_result_list", match_helpers)

cloud_item = r'''def _cloud_item(raw: dict) -> Optional[Dict[str, Any]]:
    """规范化光鸭分享文件，并尽可能保留服务端内容摘要。"""
    if not isinstance(raw, dict):
        return None
    file_id = raw.get("fileId") or raw.get("id") or raw.get("fid") or raw.get("resId")
    name = str(raw.get("fileName") or raw.get("name") or raw.get("filename") or "").strip()
    if file_id in (None, "") or not name:
        return None
    raw_type = raw.get("type", raw.get("resType", raw.get("fileType", raw.get("dirType"))))
    is_dir = bool(raw.get("isDir") or raw.get("is_dir") or raw.get("dir") or raw_type in (2, "2", "dir", "folder"))
    if raw_type in (0, 1, "0", "1", "file"):
        is_dir = False
    digest = str(raw.get("sha1") or raw.get("md5") or raw.get("hash") or raw.get("etag") or "").strip()
    return {
        "id": str(file_id),
        "name": name,
        "is_dir": is_dir,
        "size": int(raw.get("fileSize") or raw.get("size") or 0),
        "digest": digest,
    }


def _asset_identity(relative_path: str, size: Any = 0, digest: Any = "") -> str:
    """目标相对路径+大小+可用摘要生成稳定资源键；无摘要时兼容 1.1.0。"""
    normalized = re.sub(r"/+", "/", _safe_relative_path(relative_path)).lower()
    suffix = str(digest or "").strip().lower()
    base = f"{normalized}|{int(size or 0)}"
    if suffix:
        base += f"|{suffix}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


'''
text = replace_block(text, r"def _cloud_item", r"class GuangYaTransferAssistant", cloud_item)

text = text.replace('plugin_version = "1.1.0"', 'plugin_version = "1.2.0"', 1)
text = text.replace(
    '    _auto_transfer_on_refresh = True\n    _refresh_minutes = 5\n    _proxy = False\n    _max_share_files = 5000',
    '    _auto_transfer_on_refresh = True\n    _strict_subscription_rules = True\n    _media_only = True\n    _sync_subscription_progress = True\n    _history_pages = 3\n    _retry_minutes = 30\n    _max_files_per_run = 50\n    _refresh_minutes = 5\n    _proxy = False\n    _max_share_files = 5000',
    1,
)
text = text.replace(
    '        self._auto_transfer_on_refresh = bool(config.get("auto_transfer_on_refresh", True))\n        self._proxy = bool(config.get("proxy", False))\n        self._refresh_minutes = self._to_int(config.get("refresh_minutes"), 5, 1, 120)\n        self._max_share_files = self._to_int(config.get("max_share_files"), 5000, 100, 20000)\n        self._cleanup_selected_ids()',
    '        self._auto_transfer_on_refresh = bool(config.get("auto_transfer_on_refresh", True))\n        self._strict_subscription_rules = bool(config.get("strict_subscription_rules", True))\n        self._media_only = bool(config.get("media_only", True))\n        self._sync_subscription_progress = bool(config.get("sync_subscription_progress", True))\n        self._history_pages = self._to_int(config.get("history_pages"), 3, 1, 10)\n        self._retry_minutes = self._to_int(config.get("retry_minutes"), 30, 5, 720)\n        self._max_files_per_run = self._to_int(config.get("max_files_per_run"), 50, 1, 500)\n        self._proxy = bool(config.get("proxy", False))\n        self._refresh_minutes = self._to_int(config.get("refresh_minutes"), 5, 1, 120)\n        self._max_share_files = self._to_int(config.get("max_share_files"), 5000, 100, 20000)\n        if bool(config.get("clear_inventory", False)):\n            self.save_data("transfer_inventory", {})\n            self.save_data("transfer_history", {})\n            self.save_data("failure_notices", {})\n            self._inspect_cache.clear()\n            logger.warning("【光鸭转存助手】【去重】已按配置清空转存库存与历史记录")\n            config["clear_inventory"] = False\n        self._cleanup_selected_ids()',
    1,
)

form = r'''    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        subscriptions = self._subscription_options()
        folders = self._root_folder_options()
        return [{
            "component": "VForm",
            "content": [
                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "enabled", "label": "启用转存优先路由"}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "fallback_native", "label": "未命中/失败回退原生下载"}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "notify", "label": "转存结果通知"}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "proxy", "label": "频道读取使用代理"}}]},
                ]},
                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 7}, "content": [{"component": "VSelect", "props": {"model": "selected_subscriptions", "label": "选择走光鸭优先的订阅", "items": subscriptions, "multiple": True, "chips": True, "clearable": True}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 2}, "content": [{"component": "VTextField", "props": {"model": "refresh_minutes", "label": "刷新间隔(分钟)", "type": "number"}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "auto_transfer_on_refresh", "label": "刷新后自动检查转存"}}]},
                ]},
                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 7}, "content": [{"component": "VCombobox", "props": {"model": "save_path", "label": "光鸭目标文件夹", "items": folders, "clearable": False, "hint": "可选择已有文件夹，也可直接输入完整路径", "persistent-hint": True}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 2}, "content": [{"component": "VSwitch", "props": {"model": "create_media_folder", "label": "媒体名子文件夹"}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "media_only", "label": "仅媒体/字幕文件"}}]},
                ]},
                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 6, "md": 2}, "content": [{"component": "VTextField", "props": {"model": "history_pages", "label": "每频道历史页数", "type": "number"}}]},
                    {"component": "VCol", "props": {"cols": 6, "md": 2}, "content": [{"component": "VTextField", "props": {"model": "max_files_per_run", "label": "单次最多文件", "type": "number"}}]},
                    {"component": "VCol", "props": {"cols": 6, "md": 2}, "content": [{"component": "VTextField", "props": {"model": "retry_minutes", "label": "失败重试(分钟)", "type": "number"}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "strict_subscription_rules", "label": "严格遵循订阅规则"}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "sync_subscription_progress", "label": "同步已转存剧集进度"}}]},
                ]},
                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 9}, "content": [{"component": "VTextarea", "props": {"model": "channel_urls", "label": "资源频道地址（每行一个）", "rows": 3}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "clear_inventory", "label": "保存时清空去重记录", "hint": "仅故障恢复时使用，执行一次后自动关闭", "persistent-hint": True}}]},
                ]},
                {"component": "VAlert", "props": {"type": "info", "variant": "tonal", "text": "支持明文链接、查看资源隐藏按钮、URL编码/包装链接。仅接管手动勾选且状态为新建/订阅中的项目；暂停/待定、洗版订阅、严格模式下的复杂规则订阅继续走 MoviePilot 原路线。电视剧会跳过 note 已记录剧集，确认转存后再同步订阅进度。"}},
            ],
        }], {
            "enabled": self._enabled,
            "channel_urls": self._channel_urls or "\n".join(DEFAULT_CHANNEL_URLS),
            "selected_subscriptions": self._selected_subscriptions,
            "save_path": self._save_path or "/光鸭转存",
            "create_media_folder": self._create_media_folder,
            "fallback_native": self._fallback_native,
            "notify": self._notify,
            "auto_transfer_on_refresh": self._auto_transfer_on_refresh,
            "strict_subscription_rules": self._strict_subscription_rules,
            "media_only": self._media_only,
            "sync_subscription_progress": self._sync_subscription_progress,
            "history_pages": self._history_pages or 3,
            "retry_minutes": self._retry_minutes or 30,
            "max_files_per_run": self._max_files_per_run or 50,
            "refresh_minutes": self._refresh_minutes or 5,
            "proxy": self._proxy,
            "max_share_files": self._max_share_files or 5000,
            "clear_inventory": False,
        }

'''
text = replace_block(text, r"    def get_form\(self\)", r"    def get_page\(self\)", form)

page = r'''    def get_page(self) -> Optional[List[dict]]:
        index = self.get_data("channel_index") or {}
        history = self.get_data("transfer_history") or {}
        inventory = self.get_data("transfer_inventory") or {}
        last = self.get_data("last_run") or {}
        selected = set(self._selected_subscriptions)
        all_subs = self._list_subscriptions(None)
        selected_subs = [sub for sub in all_subs if int(getattr(sub, "id", 0) or 0) in selected]
        rows = []
        for sub in selected_subs:
            sid = int(sub.id)
            recent = [value for key, value in history.items() if str(key).startswith(f"{sid}:")]
            recent.sort(key=lambda value: str(value.get("time") or ""), reverse=True)
            asset_count = len(((inventory.get(str(sid)) or {}).get("assets") or {}))
            state_text = (f"{recent[0].get('time') or '-'} · {recent[0].get('message') or '-'}" if recent else "等待频道匹配")
            state = str(getattr(sub, "state", "") or "-")
            rows.append({
                "component": "VCard",
                "props": {"variant": "tonal", "class": "h-100"},
                "content": [
                    {"component": "VCardTitle", "text": f"{sub.name} ({getattr(sub, 'year', '') or '-'})"},
                    {"component": "VCardText", "text": f"订阅ID {sid} · 状态 {state} · 去重资源 {asset_count} 个 · {state_text}"},
                ],
            })
        fresh_count = len([item for item in (index.get("items") or []) if not item.get("stale")])
        stale_count = len(index.get("items") or []) - fresh_count
        contents: List[dict] = [{
            "component": "VAlert",
            "props": {
                "type": "warning" if last.get("stale_index") else ("success" if last.get("success") else "info"),
                "variant": "tonal",
                "text": f"频道索引 {len(index.get('items') or [])} 个（新鲜 {fresh_count} / 旧缓存 {stale_count}）· 已选择 {len(selected)} 个订阅 · 最近刷新 {index.get('time') or '-'}",
            },
        }]
        source_status = index.get("source_status") or {}
        if source_status:
            status_items = []
            for label, status in source_status.items():
                status_items.append({
                    "component": "VListItem",
                    "props": {
                        "title": label,
                        "subtitle": (
                            f"{'正常' if status.get('success') else '使用旧缓存'} · 页面 {status.get('pages') or 0} · "
                            f"分享 {status.get('count') or 0} · 隐藏/包装按钮 {status.get('button_links') or 0} · "
                            f"明文 {status.get('visible_links') or 0} · 未解析按钮 {status.get('unresolved_buttons') or 0}"
                        ),
                    },
                })
            contents.append({"component": "VCard", "props": {"variant": "outlined", "class": "mt-3"}, "content": [
                {"component": "VCardTitle", "text": "频道解析状态"},
                {"component": "VList", "props": {"density": "compact"}, "content": status_items},
            ]})
        if rows:
            contents.append({"component": "div", "props": {"class": "grid gap-3 grid-info-card mt-3"}, "content": rows})

        resources = []
        for entry in list(index.get("items") or [])[:150]:
            matched = []
            for sub in selected_subs:
                ok, reason = _entry_match_reason(entry, sub)
                if ok:
                    matched.append(f"{getattr(sub, 'name', '')}#{int(getattr(sub, 'id', 0) or 0)}({reason})")
            display = str(entry.get("display_title") or "").strip() or str(entry.get("source_label") or "频道资源")
            snippet = re.sub(r"https?://\S+", "", str(entry.get("text") or ""))
            snippet = re.sub(r"\s+", " ", snippet).strip()[:160]
            meta = [str(entry.get("link_style") or "未知链接")]
            if entry.get("tmdb_id"):
                meta.append(f"TMDB {entry.get('tmdb_id')}")
            if entry.get("episode_hint"):
                meta.append(str(entry.get("episode_hint")))
            if entry.get("stale"):
                meta.append("旧缓存")
            status = "匹配：" + "、".join(matched) if matched else "未匹配已勾选订阅"
            resources.append({
                "component": "VListItem",
                "props": {
                    "title": f"{display} · {entry.get('share_id') or '-'}",
                    "subtitle": f"{entry.get('source_label') or '-'} · {' · '.join(meta)} · {status} · {snippet}",
                },
            })
        contents.append({
            "component": "VCard",
            "props": {"variant": "outlined", "class": "mt-4"},
            "content": [
                {"component": "VCardTitle", "text": f"频道资源（{len(index.get('items') or [])}）"},
                {"component": "VCardText", "text": "显示链接类型、TMDB/集数提示、缓存新鲜度及匹配原因；最多显示 150 条。"},
                {"component": "VList", "props": {"density": "compact"}, "content": resources or [{"component": "VListItem", "props": {"title": "暂无频道资源"}}]},
            ],
        })
        return contents

'''
text = replace_block(text, r"    def get_page\(self\)", r"    def get_api\(self\)", page)

text = text.replace(
    '    def api_refresh(self) -> Dict[str, Any]:\n        items = self.refresh_channels(force=True)\n        routed = self._process_selected_subscriptions(trigger="手动刷新") if self._auto_transfer_on_refresh else []',
    '    def api_refresh(self) -> Dict[str, Any]:\n        self._inspect_cache.clear()\n        items = self.refresh_channels(force=True)\n        routed = self._process_selected_subscriptions(trigger="手动刷新") if self._auto_transfer_on_refresh and any(not item.get("stale") for item in items) else []',
    1,
)

runtime = r'''    def _tick(self) -> None:
        self._install_takeover()
        items = self.refresh_channels(force=True)
        # 分享内容可能在同一个 URL 内热更，每轮正式检查前清掉 API 文件缓存。
        self._inspect_cache.clear()
        if self._auto_transfer_on_refresh and any(not item.get("stale") for item in items):
            self._process_selected_subscriptions(trigger="频道定时刷新")

    def _process_selected_subscriptions(self, trigger: str = "后台检查") -> List[Dict[str, Any]]:
        """频道刷新后只检查活跃订阅；不会在后台刷新任务里主动触发原生下载。"""
        results: List[Dict[str, Any]] = []
        with self._route_lock:
            for sid in list(self._selected_subscriptions):
                subscribe = self._find_subscription(int(sid))
                if not subscribe:
                    continue
                if str(getattr(subscribe, "state", "") or "") not in ("N", "R"):
                    logger.info("【光鸭转存助手】【规则】%s #%s %s 当前状态=%s，后台不接管", trigger, sid, getattr(subscribe, "name", ""), getattr(subscribe, "state", ""))
                    results.append({"subscribe_id": int(sid), "success": False, "handled": False, "message": "非活跃订阅，已跳过"})
                    continue
                try:
                    result = self._try_transfer_subscription(subscribe)
                    results.append({"subscribe_id": int(sid), **result})
                    logger.info("【光鸭转存助手】【自动】%s #%s %s：%s", trigger, sid, getattr(subscribe, "name", ""), result.get("message") or "完成")
                except Exception as err:
                    logger.exception("【光鸭转存助手】【自动】%s #%s 执行异常", trigger, sid)
                    results.append({"subscribe_id": int(sid), "success": False, "handled": False, "message": str(err)})
        return results

'''
text = replace_block(text, r"    def _tick\(self\)", r"    def refresh_channels\(self", runtime)

refresh = r'''    def refresh_channels(self, force: bool = False) -> List[Dict[str, Any]]:
        """逐频道抓取并按源保留旧缓存；支持镜像页面自带历史翻页入口。"""
        current = self.get_data("channel_index") or {}
        current_time = self._parse_datetime(current.get("time"))
        if not force and current_time and (datetime.datetime.now() - current_time).total_seconds() < self._refresh_minutes * 60:
            return list(current.get("items") or [])
        previous_items = list(current.get("items") or [])
        all_entries: List[Dict[str, Any]] = []
        errors: List[str] = []
        source_status: Dict[str, Any] = {}
        source_successes = 0
        urls = self._source_urls()
        for source_url in urls:
            label = "光鸭云盘影视热更频道" if "regeng" in source_url.lower() else "光鸭云盘资源分享频道"
            queue = [source_url]
            visited = set()
            source_entries: List[Dict[str, Any]] = []
            source_seen = set()
            page_errors: List[str] = []
            pages = 0
            button_count = 0
            button_links = 0
            visible_links = 0
            while queue and pages < self._history_pages:
                page_url = queue.pop(0)
                if page_url in visited:
                    continue
                visited.add(page_url)
                try:
                    request = RequestUtils(proxies=settings.PROXY) if self._proxy else RequestUtils()
                    response = request.get_res(page_url)
                    if not response or getattr(response, "status_code", 200) >= 400:
                        page_errors.append(f"HTTP {getattr(response, 'status_code', '无响应')} {page_url}")
                        continue
                    pages += 1
                    page_html = response.text or ""
                    button_count += len(re.findall(r"查看资源", page_html, re.I))
                    found = _extract_channel_entries(page_html, source_url, label)
                    for item in found:
                        key = _share_identity(item.get("share_url") or "")
                        if not key or key in source_seen:
                            continue
                        source_seen.add(key)
                        item["stale"] = False
                        source_entries.append(item)
                        style = str(item.get("link_style") or "")
                        if "按钮" in style or "包装" in style:
                            button_links += 1
                        if style == "明文链接":
                            visible_links += 1
                    for next_url in _extract_pagination_urls(page_html, source_url):
                        if next_url not in visited and next_url not in queue and len(queue) < self._history_pages * 4:
                            queue.append(next_url)
                except Exception as err:
                    page_errors.append(f"{page_url}: {err}")
            unresolved = max(0, button_count - button_links)
            parse_suspect = bool(pages and button_count and not source_entries and unresolved)
            if pages > 0 and not parse_suspect:
                source_successes += 1
                all_entries.extend(source_entries)
                # 某个历史页失败时保留该源以前未被新结果覆盖的条目，但标为 stale，不能阻断原生下载。
                if page_errors:
                    fresh_keys = {_share_identity(item.get("share_url") or "") for item in source_entries}
                    for old in previous_items:
                        if old.get("source_label") != label:
                            continue
                        key = _share_identity(old.get("share_url") or "")
                        if key and key not in fresh_keys:
                            stale = dict(old)
                            stale["stale"] = True
                            all_entries.append(stale)
                source_status[label] = {
                    "success": True, "pages": pages, "count": len(source_entries),
                    "button_links": button_links, "visible_links": visible_links,
                    "unresolved_buttons": unresolved, "errors": page_errors,
                }
            else:
                preserved = 0
                for old in previous_items:
                    if old.get("source_label") != label:
                        continue
                    stale = dict(old)
                    stale["stale"] = True
                    all_entries.append(stale)
                    preserved += 1
                reason = "页面存在查看资源按钮但未解析出分享链接" if parse_suspect else ("；".join(page_errors[:3]) or "频道未返回有效页面")
                errors.append(f"{label}: {reason}")
                source_status[label] = {
                    "success": False, "pages": pages, "count": preserved,
                    "button_links": button_links, "visible_links": visible_links,
                    "unresolved_buttons": unresolved, "errors": page_errors or [reason],
                }
                if parse_suspect:
                    logger.warning("【光鸭转存助手】【频道】%s 检测到 %s 个查看资源按钮但未解析到光鸭 URL，已保留旧索引", label, unresolved)

        # 新鲜条目优先，热更频道优先；同一分享跨频道只保留最佳条目。
        all_entries.sort(key=lambda item: (1 if item.get("stale") else 0, int(item.get("priority") or 0), -len(str(item.get("text") or ""))))
        entries: List[Dict[str, Any]] = []
        seen = set()
        for item in all_entries:
            key = _share_identity(item.get("share_url") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            entries.append(item)
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        all_failed = source_successes == 0
        partial_stale = source_successes < len(urls)
        payload = {
            "time": now,
            "items": entries[:2000],
            "errors": errors,
            "source_status": source_status,
        }
        self.save_data("channel_index", payload)
        self.save_data("last_run", {
            "success": bool(source_successes), "time": now, "count": len(entries), "errors": errors,
            "stale_index": all_failed, "partial_stale": partial_stale,
        })
        fresh_count = len([item for item in entries if not item.get("stale")])
        stale_count = len(entries) - fresh_count
        logger.info("【光鸭转存助手】频道刷新完成，识别分享 %s 个（新鲜 %s / 旧缓存 %s），错误 %s 个", len(entries), fresh_count, stale_count, len(errors))
        return entries

'''
text = replace_block(text, r"    def refresh_channels\(self", r"    def _source_urls\(self\)", refresh)

subs = r'''    def _subscription_options(self) -> List[Dict[str, Any]]:
        options = []
        selected = set(self._selected_subscriptions)
        for sub in self._list_subscriptions(None):
            sid = int(getattr(sub, "id", 0) or 0)
            state = str(getattr(sub, "state", "") or "")
            if not sid or (state not in ("N", "R") and sid not in selected):
                continue
            season = getattr(sub, "season", None)
            suffix = f" S{int(season):02d}" if season not in (None, 0) else ""
            state_label = {"N": "新建", "R": "订阅中", "P": "待定", "S": "暂停"}.get(state, state or "-")
            options.append({"title": f"{sub.name} ({getattr(sub, 'year', '') or '-'}){suffix} · {state_label} · #{sid}", "value": sid})
        return options

    @staticmethod
    def _list_subscriptions(state: Optional[str] = "N,R") -> List[Any]:
        try:
            return list(SubscribeOper().list(state) or [])
        except Exception as err:
            logger.warning("【光鸭转存助手】读取 MoviePilot 订阅失败: %s", err)
            return []

    def _find_subscription(self, sid: int) -> Optional[Any]:
        try:
            return SubscribeOper().get(int(sid))
        except Exception as err:
            logger.warning("【光鸭转存助手】读取订阅 #%s 失败: %s", sid, err)
            return None

    def _cleanup_selected_ids(self) -> None:
        # 所有状态都视为有效，暂停/待定只是不自动接管；恢复状态后无需重新勾选。
        valid = {int(getattr(item, "id", 0) or 0) for item in self._list_subscriptions(None)}
        if not valid:
            return
        selected = [sid for sid in self._selected_subscriptions if sid in valid]
        if selected == self._selected_subscriptions:
            return
        self._selected_subscriptions = selected
        self._save_config()

'''
text = replace_block(text, r"    def _subscription_options\(self\)", r"    def _save_config\(self\)", subs)

save_config = r'''    def _save_config(self) -> None:
        self.update_config({
            "enabled": self._enabled,
            "channel_urls": self._channel_urls,
            "selected_subscriptions": self._selected_subscriptions,
            "save_path": self._save_path,
            "create_media_folder": self._create_media_folder,
            "fallback_native": self._fallback_native,
            "notify": self._notify,
            "auto_transfer_on_refresh": self._auto_transfer_on_refresh,
            "strict_subscription_rules": self._strict_subscription_rules,
            "media_only": self._media_only,
            "sync_subscription_progress": self._sync_subscription_progress,
            "history_pages": self._history_pages,
            "retry_minutes": self._retry_minutes,
            "max_files_per_run": self._max_files_per_run,
            "refresh_minutes": self._refresh_minutes,
            "proxy": self._proxy,
            "max_share_files": self._max_share_files,
            "clear_inventory": False,
        })

'''
text = replace_block(text, r"    def _save_config\(self\)", r"    def _install_takeover\(self\)", save_config)

try_transfer = r'''    def _subscription_static_guard(self, subscribe: Any) -> Tuple[bool, str]:
        state = str(getattr(subscribe, "state", "") or "")
        if state not in ("N", "R"):
            return False, f"订阅状态 {state or '-'} 非活跃"
        if bool(getattr(subscribe, "best_version", 0)):
            return False, "洗版订阅保留 MoviePilot 原生质量优先级逻辑"
        mtype = str(getattr(subscribe, "type", "") or "").lower()
        if mtype and not any(token in mtype for token in ("tv", "movie", "电视剧", "电影")):
            return False, f"媒体类型 {getattr(subscribe, 'type', '')} 不适合网盘影视转存"
        if self._strict_subscription_rules:
            if getattr(subscribe, "filter_groups", None):
                return False, "存在复杂过滤规则组，严格模式下交回原生下载"
            if str(getattr(subscribe, "filter", "") or "").strip():
                return False, "存在复杂过滤规则，严格模式下交回原生下载"
        return True, ""

    def _subscription_resource_allowed(self, subscribe: Any, entry: Dict[str, Any], probe: Dict[str, Any]) -> Tuple[bool, str]:
        descriptor = "\n".join([
            str(entry.get("text") or ""),
            "\n".join(str(item.get("relative_path") or item.get("name") or "") for item in (probe.get("files") or [])[:300]),
        ])
        exclude = str(getattr(subscribe, "exclude", "") or "").strip()
        if exclude and _safe_rule_match(exclude, descriptor):
            return False, "命中订阅排除规则"
        include = str(getattr(subscribe, "include", "") or "").strip()
        if include and not _safe_rule_match(include, descriptor):
            return False, "未命中订阅包含规则"
        for field, label in (("resolution", "分辨率"), ("quality", "质量"), ("effect", "特效")):
            rule = str(getattr(subscribe, field, "") or "").strip()
            if rule and not _safe_rule_match(rule, descriptor):
                return False, f"资源未满足订阅{label}规则"
        return True, ""

    def _try_transfer_subscription(self, subscribe: Any, force: bool = False) -> Dict[str, Any]:
        """对一个活跃订阅执行安全匹配、规则校验、文件级去重和增量转存。"""
        sid = int(getattr(subscribe, "id", 0) or 0)
        allowed, guard_reason = self._subscription_static_guard(subscribe)
        if not allowed:
            logger.info("【光鸭转存助手】【规则】#%s %s 不接管：%s", sid, getattr(subscribe, "name", ""), guard_reason)
            return {"success": False, "handled": False, "message": guard_reason}
        self.refresh_channels(force=False)
        entries = list((self.get_data("channel_index") or {}).get("items") or [])
        matched_pairs = []
        stale_matches = 0
        for item in entries:
            matched, reason = _entry_match_reason(item, subscribe)
            if not matched:
                continue
            if item.get("stale"):
                stale_matches += 1
                continue
            matched_pairs.append((item, reason))
        if not matched_pairs:
            detail = "仅命中旧缓存，不能阻断原生下载" if stale_matches else "频道未匹配到光鸭分享"
            logger.info("【光鸭转存助手】【匹配】#%s %s %s；%s", sid, getattr(subscribe, "name", ""), detail, "将由 MoviePilot 原订阅任务继续下载" if self._fallback_native else "原生下载回退已关闭")
            return {"success": False, "handled": False, "message": detail}
        logger.info("【光鸭转存助手】【匹配】#%s %s 命中 %s 个新鲜频道分享", sid, getattr(subscribe, "name", ""), len(matched_pairs))

        history = self.get_data("transfer_history") or {}
        inventory = self.get_data("transfer_inventory") or {}
        sid_key = str(sid)
        inv_row = inventory.get(sid_key) or {"assets": {}}
        assets = inv_row.get("assets") or {}
        errors: List[str] = []
        transferred_assets: List[Dict[str, Any]] = []
        task_ids: List[str] = []
        sources = set()
        valid_route_match = False
        synchronized_match = False
        attempted_new = False
        remaining_due_to_cap = 0
        match_reasons = set()
        target_path = self._target_path(subscribe)

        for entry, match_reason in matched_pairs[:20]:
            share_url = entry.get("share_url") or ""
            share_key = _share_identity(share_url)
            if not share_key:
                continue
            probe = self._inspect_share(share_url)
            if not probe.get("success"):
                error = str(probe.get("message") or "分享读取失败")
                logger.warning("【光鸭转存助手】【匹配】分享读取失败 share_id=%s：%s", share_key.split("|", 1)[0], error)
                errors.append(error)
                continue
            resource_allowed, resource_reason = self._subscription_resource_allowed(subscribe, entry, probe)
            if not resource_allowed:
                logger.info("【光鸭转存助手】【规则】#%s %s share_id=%s 跳过：%s", sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0], resource_reason)
                errors.append(resource_reason)
                continue
            match_reasons.add(match_reason)
            source = str(entry.get("source_label") or "频道资源")
            sources.add(source)
            fingerprint = str(probe.get("fingerprint") or "")
            legacy_fingerprint = str(probe.get("legacy_fingerprint") or "")
            history_key = f"{sid}:{share_key}"
            old = history.get(history_key) or {}
            if not force and old and not old.get("success") and old.get("fingerprint") in {fingerprint, legacy_fingerprint}:
                failed_at = self._parse_datetime(old.get("time"))
                if failed_at and (datetime.datetime.now() - failed_at).total_seconds() < self._retry_minutes * 60:
                    wait = self._retry_minutes - int((datetime.datetime.now() - failed_at).total_seconds() // 60)
                    errors.append(f"share_id={share_key.split('|', 1)[0]} 失败退避中，约 {max(wait, 1)} 分钟后重试")
                    logger.info("【光鸭转存助手】【重试】#%s %s share_id=%s 仍在失败退避期", sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0])
                    continue

            stats: Dict[str, int] = {}
            planned = self._plan_incremental_files(probe, assets, subscribe=subscribe, target_path=target_path, stats=stats)
            if stats.get("eligible", 0) <= 0:
                errors.append("分享内没有符合订阅范围的媒体/字幕文件")
                logger.info("【光鸭转存助手】【规则】#%s %s share_id=%s 没有符合订阅范围的可转存文件", sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0])
                continue
            valid_route_match = True

            # 兼容 1.0.x / 1.1.0：旧版整份分享已成功且内容未变时，仅补建文件库存。
            if not assets and old.get("success") and old.get("fingerprint") in {fingerprint, legacy_fingerprint}:
                migrated_stats: Dict[str, int] = {}
                migrated = self._plan_incremental_files(probe, {}, subscribe=subscribe, target_path=target_path, stats=migrated_stats)
                self._remember_assets(assets, migrated, share_key, target_path)
                inventory[sid_key] = {"assets": assets, "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                self.save_data("transfer_inventory", inventory)
                synchronized_match = True
                logger.info("【光鸭转存助手】【去重】#%s %s 从旧版成功记录建立文件级索引 %s 个，不重复转存", sid, getattr(subscribe, "name", ""), len(migrated))
                continue

            if not planned:
                synchronized_match = True
                logger.info(
                    "【光鸭转存助手】【去重】#%s %s share_id=%s 无新增文件（库存=%s，已完成剧集/范围过滤=%s），跳过",
                    sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0], stats.get("inventory", 0), stats.get("episode", 0),
                )
                continue

            attempted_new = True
            pending_count = len(planned)
            if pending_count > self._max_files_per_run:
                remaining_due_to_cap += pending_count - self._max_files_per_run
                planned = planned[:self._max_files_per_run]
            logger.info(
                "【光鸭转存助手】【增量】#%s %s share_id=%s 叶子文件=%s，符合范围=%s，新增待转=%s，本轮=%s，库存=%s，剧集过滤=%s",
                sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0], probe.get("leaf_count") or len(probe.get("files") or []),
                stats.get("eligible", 0), pending_count, len(planned), stats.get("inventory", 0), stats.get("episode", 0),
            )
            restored = self._restore_items(probe, target_path, planned)
            completed = list(restored.get("completed_items") or [])
            if completed:
                self._remember_assets(assets, completed, share_key, target_path)
                inventory[sid_key] = {"assets": assets, "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                self.save_data("transfer_inventory", inventory)
                transferred_assets.extend(completed)
                task_ids.extend([value for value in (restored.get("task_ids") or []) if value])
                self._sync_progress(subscribe, completed)
            record = {
                "success": bool(restored.get("success")), "fingerprint": fingerprint,
                "legacy_fingerprint": legacy_fingerprint,
                "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "share_url": share_url, "source": source, "target_path": target_path,
                "message": restored.get("message") or "", "task_id": ",".join(restored.get("task_ids") or []),
                "confirmed": bool(restored.get("success")), "confirmation": restored.get("confirmation") or "",
                "file_count": probe.get("leaf_count") or len(probe.get("files") or []), "new_count": len(completed),
            }
            history[history_key] = record
            self._trim_history(history)
            self.save_data("transfer_history", history)
            if not restored.get("success"):
                errors.append(str(restored.get("message") or "增量转存失败"))

        unique_paths = []
        seen_paths = set()
        for item in transferred_assets:
            rel = str(item.get("effective_path") or item.get("relative_path") or item.get("name") or "")
            if rel and rel not in seen_paths:
                seen_paths.add(rel)
                unique_paths.append(rel)
        if unique_paths:
            partial = bool(errors)
            logger.info("【光鸭转存助手】【转存】#%s %s %s：新增 %s 个文件，累计去重 %s 个，剩余待下轮 %s，目标=%s", sid, getattr(subscribe, "name", ""), "部分完成" if partial else "增量完成", len(unique_paths), len(assets), remaining_due_to_cap, target_path)
            if self._notify:
                season = getattr(subscribe, "season", None)
                media_text = f"{getattr(subscribe, 'name', '')} ({getattr(subscribe, 'year', '') or '-'})"
                if season not in (None, "", 0, "0"):
                    media_text += f" S{int(season):02d}"
                preview = "、".join(unique_paths[:8])
                if len(unique_paths) > 8:
                    preview += f" 等 {len(unique_paths)} 个"
                lines = [
                    f"媒体：{media_text}",
                    "状态：部分转存完成，剩余将回原订阅处理" if partial else "状态：增量转存已确认完成",
                    f"匹配：{'、'.join(sorted(match_reasons)) or '-'}",
                    f"本次新增：{len(unique_paths)} 个文件",
                    f"累计去重：{len(assets)} 个文件",
                    f"来源：{'、'.join(sorted(sources))}",
                    f"目标：{target_path}",
                    f"新增内容：{preview or '-'}",
                ]
                if remaining_due_to_cap:
                    lines.append(f"待下轮：至少 {remaining_due_to_cap} 个文件")
                if task_ids:
                    lines.append(f"任务ID：{','.join(task_ids[:6])}")
                self.post_message(mtype=NotificationType.Plugin, title="⚠️ 光鸭部分转存" if partial else "✅ 光鸭转存成功", text="\n".join(lines))
                logger.info("【光鸭转存助手】【通知】已发送%s通知：#%s %s", "部分转存" if partial else "增量转存成功", sid, getattr(subscribe, "name", ""))
            if partial:
                return {"success": False, "handled": False, "message": f"部分转存 {len(unique_paths)} 个文件，剩余回退原订阅", "new_count": len(unique_paths), "target_path": target_path}
            return {"success": True, "handled": True, "message": f"增量转存成功，本次新增 {len(unique_paths)} 个文件", "new_count": len(unique_paths), "target_path": target_path, "remaining": remaining_due_to_cap}

        if valid_route_match and (synchronized_match or not attempted_new):
            logger.info("【光鸭转存助手】【去重】#%s %s 所有有效匹配均无新增，保持光鸭优先，不触发重复下载", sid, getattr(subscribe, "name", ""))
            return {"success": True, "handled": True, "already": True, "message": "已同步，无新增资源"}

        final_message = "；".join(dict.fromkeys(errors))[:1200] or "匹配分享均不可用"
        logger.warning("【光鸭转存助手】【回退】#%s %s 转存未完成：%s；%s", sid, getattr(subscribe, "name", ""), final_message, "将回退 MoviePilot 原生下载" if self._fallback_native else "原生下载回退已关闭")
        if self._notify and matched_pairs:
            notices = self.get_data("failure_notices") or {}
            notice_key = f"{sid}:{hashlib.sha256(final_message.encode('utf-8')).hexdigest()[:12]}"
            last_notice = self._parse_datetime(notices.get(notice_key))
            now = datetime.datetime.now()
            if not last_notice or (now - last_notice).total_seconds() >= 6 * 3600:
                try:
                    self.post_message(
                        mtype=NotificationType.Plugin,
                        title="⚠️ 光鸭转存失败",
                        text=(
                            f"媒体：{getattr(subscribe, 'name', '')} ({getattr(subscribe, 'year', '') or '-'})\n"
                            f"状态：转存未完成\n原因：{final_message}\n"
                            + ("后续：将回退 MoviePilot 原生下载" if self._fallback_native else "后续：原生下载回退已关闭")
                        ),
                    )
                    notices[notice_key] = now.strftime("%Y-%m-%d %H:%M:%S")
                    self.save_data("failure_notices", notices)
                    logger.info("【光鸭转存助手】【通知】已发送转存失败通知：#%s %s（相同错误 6 小时内不重复推送）", sid, getattr(subscribe, "name", ""))
                except Exception as err:
                    logger.warning("【光鸭转存助手】【通知】发送失败通知异常：%s", err)
        return {"success": False, "handled": False, "message": final_message}

'''
text = replace_block(text, r"    def _try_transfer_subscription\(self", r"    def _target_path\(self", try_transfer)

planning = r'''    def _target_path(self, subscribe: Any) -> str:
        base = "/" + _safe_relative_path(self._save_path) if _safe_relative_path(self._save_path) else "/"
        if not self._create_media_folder:
            return base
        name = re.sub(r"[\\/:*?\"<>|]+", " ", str(getattr(subscribe, "name", "") or "")).strip()
        year = str(getattr(subscribe, "year", "") or "").strip()
        folder = f"{name} ({year})" if year else name
        return (base.rstrip("/") + "/" + _safe_relative_path(folder)).replace("//", "/")

    def _plan_incremental_files(
        self, probe: Dict[str, Any], assets: Dict[str, Any], subscribe: Any = None,
        target_path: str = "", stats: Optional[Dict[str, int]] = None,
    ) -> List[Dict[str, Any]]:
        files = [dict(item) for item in (probe.get("files") or []) if item.get("id")]
        counters = {"total": len(files), "eligible": 0, "inventory": 0, "episode": 0, "auxiliary": 0}
        top_parts = {_safe_relative_path(item.get("relative_path")).split("/", 1)[0] for item in files if "/" in _safe_relative_path(item.get("relative_path"))}
        strip_root = next(iter(top_parts)) if self._create_media_folder and len(top_parts) == 1 else ""
        done_episodes = set()
        start_episode = 1
        total_episode = 0
        subscribe_season = None
        is_tv = False
        if subscribe is not None:
            is_tv = "tv" in str(getattr(subscribe, "type", "") or "").lower() or "电视剧" in str(getattr(subscribe, "type", "") or "") or getattr(subscribe, "season", None) not in (None, 0)
            subscribe_season = getattr(subscribe, "season", None)
            try:
                start_episode = max(1, int(getattr(subscribe, "start_episode", 0) or 1))
            except (TypeError, ValueError):
                start_episode = 1
            try:
                total_episode = max(0, int(getattr(subscribe, "total_episode", 0) or 0))
            except (TypeError, ValueError):
                total_episode = 0
            for value in (getattr(subscribe, "note", None) or []):
                try:
                    done_episodes.add(int(value))
                except (TypeError, ValueError):
                    continue
        planned = []
        for item in files:
            rel = _safe_relative_path(item.get("relative_path") or item.get("name") or "")
            effective = rel
            if strip_root and rel.startswith(strip_root + "/"):
                effective = rel[len(strip_root) + 1:]
            effective = _safe_relative_path(effective)
            if not effective:
                counters["auxiliary"] += 1
                continue
            is_video = _is_video(effective)
            is_subtitle = _is_subtitle(effective)
            if self._media_only and not (is_video or is_subtitle):
                counters["auxiliary"] += 1
                continue
            if is_tv and (is_video or is_subtitle):
                file_season, episodes = _episode_numbers(effective)
                if subscribe_season not in (None, 0) and file_season not in (None, int(subscribe_season)):
                    counters["episode"] += 1
                    continue
                if episodes:
                    wanted = [ep for ep in episodes if ep >= start_episode and (not total_episode or ep <= total_episode) and ep not in done_episodes]
                    if not wanted:
                        counters["episode"] += 1
                        continue
                elif done_episodes or start_episode > 1:
                    # 已有订阅进度时，无法识别集号的 TV 文件不冒险重复转存。
                    counters["episode"] += 1
                    continue
            counters["eligible"] += 1
            parent = effective.rsplit("/", 1)[0] if "/" in effective else ""
            digest = item.get("digest") or ""
            asset_key = _asset_identity(effective, item.get("size") or 0, digest)
            legacy_key = _asset_identity(effective, item.get("size") or 0)
            existing = assets.get(asset_key) or assets.get(legacy_key)
            if existing and str((existing or {}).get("target") or "") == str(target_path or ""):
                counters["inventory"] += 1
                continue
            item["effective_path"] = effective
            item["target_parent"] = parent
            item["asset_key"] = asset_key
            item["legacy_asset_key"] = legacy_key
            planned.append(item)
        planned.sort(key=lambda item: ((_episode_numbers(item.get("effective_path"))[1] or [999999])[0], str(item.get("effective_path") or "")))
        if stats is not None:
            stats.clear()
            stats.update(counters)
        return planned

    @staticmethod
    def _remember_assets(assets: Dict[str, Any], items: List[Dict[str, Any]], share_key: str, target_path: str) -> None:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for item in items:
            effective = item.get("effective_path") or item.get("relative_path") or item.get("name") or ""
            key = str(item.get("asset_key") or _asset_identity(effective, item.get("size") or 0, item.get("digest") or ""))
            assets[key] = {
                "path": effective, "size": int(item.get("size") or 0), "digest": str(item.get("digest") or ""),
                "share_id": str(share_key or "").split("|", 1)[0], "target": target_path, "time": now,
            }
        if len(assets) > 20000:
            ordered = sorted(assets.items(), key=lambda pair: str((pair[1] or {}).get("time") or ""), reverse=True)[:20000]
            assets.clear()
            assets.update(dict(ordered))

    def _sync_progress(self, subscribe: Any, completed: List[Dict[str, Any]]) -> None:
        """确认转存成功后把剧集写入 MoviePilot note，避免后续原生搜索重复下载。"""
        if not self._sync_subscription_progress or bool(getattr(subscribe, "best_version", 0)):
            return
        mtype = str(getattr(subscribe, "type", "") or "").lower()
        if "tv" not in mtype and "电视剧" not in str(getattr(subscribe, "type", "") or "") and getattr(subscribe, "season", None) in (None, 0):
            return
        episodes = set()
        wanted_season = getattr(subscribe, "season", None)
        for item in completed:
            path = item.get("effective_path") or item.get("relative_path") or item.get("name") or ""
            if not _is_video(path):
                continue
            file_season, values = _episode_numbers(path)
            if wanted_season not in (None, 0) and file_season not in (None, int(wanted_season)):
                continue
            episodes.update(values)
        if not episodes:
            return
        current = set()
        for value in (getattr(subscribe, "note", None) or []):
            try:
                current.add(int(value))
            except (TypeError, ValueError):
                continue
        merged = current | episodes
        if merged == current:
            return
        payload: Dict[str, Any] = {"note": sorted(merged)}
        try:
            start = max(1, int(getattr(subscribe, "start_episode", 0) or 1))
            total = int(getattr(subscribe, "total_episode", 0) or 0)
            if total >= start:
                payload["lack_episode"] = len(set(range(start, total + 1)) - merged)
        except (TypeError, ValueError):
            pass
        try:
            SubscribeOper().update(int(getattr(subscribe, "id", 0) or 0), payload)
            setattr(subscribe, "note", sorted(merged))
            if "lack_episode" in payload:
                setattr(subscribe, "lack_episode", payload["lack_episode"])
            logger.info("【光鸭转存助手】【进度】#%s %s 已同步剧集 %s 到 MoviePilot note", getattr(subscribe, "id", 0), getattr(subscribe, "name", ""), ",".join(str(v) for v in sorted(episodes)))
        except Exception as err:
            logger.warning("【光鸭转存助手】【进度】同步 MoviePilot 订阅进度失败：%s", err)

'''
text = replace_block(text, r"    def _target_path\(self", r"    def _get_guangya_runtime\(self", planning)

# Inspect-share: sanitize paths and carry digest into file fingerprints while preserving legacy 1.0.x hash.
text = text.replace(
    '                    rel = "/".join(value for value in (parent_path.strip("/"), item["name"].strip("/")) if value)\n                    fingerprint_rows.append(f"{item[\'id\']}|{rel}|{item[\'size\']}|{int(item[\'is_dir\'])}")',
    '                    rel = _safe_relative_path("/".join(value for value in (parent_path.strip("/"), item["name"].strip("/")) if value))\n                    fingerprint_rows.append(f"{item[\'id\']}|{rel}|{item[\'size\']}|{int(item[\'is_dir\'])}|{item.get(\'digest\') or \'\'}")',
    1,
)
# Keep legacy hash exactly compatible with v1.0.1 (name only, no relative path/digest).
assert 'legacy_fingerprint_rows' in text, 'legacy fingerprint migration missing from 1.1.0 base'

# Ensure nested target paths remain under configured root.
text = text.replace(
    '                normalized = (base.rstrip("/") + ("/" + relative_parent.strip("/") if relative_parent else "")) or "/"',
    '                relative_parent = _safe_relative_path(relative_parent)\n                normalized = (base.rstrip("/") + ("/" + relative_parent if relative_parent else "")) or "/"',
    1,
)

# Package/plugin metadata.
plugin_json = ROOT / "plugins.v3" / "guangyatransferassistant" / "plugin.json"
local = json.loads(plugin_json.read_text(encoding="utf-8"))
local["version"] = "1.2.0"
local["description"] = "光鸭频道转存优先路由：兼容明文/隐藏/包装分享链接，TMDB精确匹配，遵循订阅状态与规则，文件级增量去重并同步剧集进度。"
plugin_json.write_text(json.dumps(local, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

package_path = ROOT / "package.v3.json"
package = json.loads(package_path.read_text(encoding="utf-8"))
item = package["GuangYaTransferAssistant"]
item["version"] = "1.2.0"
item["description"] = "光鸭频道转存优先路由：兼容明文/隐藏/包装分享链接，TMDB精确匹配，遵循订阅状态与规则，文件级增量去重并同步剧集进度。"
history = item.setdefault("history", {})
new_history = {
    "v1.2.0": "完整体验增强：支持查看资源隐藏按钮、明文及URL编码/包装链接；TMDB优先精确匹配；历史翻页与单源故障缓存；严格保护暂停/待定、洗版和复杂规则订阅；按MoviePilot note跳过已有剧集，转存确认后同步订阅进度；加入失败退避、单次文件上限、路径安全和解析诊断。"
}
new_history.update(history)
item["history"] = new_history
package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# Update source after all transforms.
SRC.write_text(text, encoding="utf-8")

# Replace contract tests with focused parser + routing-safety regression coverage.
test = r'''import ast
import hashlib
import html
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, unquote, urljoin, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "plugins.v3" / "guangyatransferassistant" / "__init__.py"
text = SRC.read_text(encoding="utf-8")
tree = ast.parse(text)

# 执行 class 之前的常量与纯函数，不依赖 MoviePilot 运行时。
nodes = []
for node in tree.body:
    if isinstance(node, ast.ClassDef):
        break
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.FunctionDef)):
        if isinstance(node, ast.FunctionDef):
            node.returns = None
            for arg in node.args.args:
                arg.annotation = None
        nodes.append(node)
mod = ast.Module(body=nodes, type_ignores=[])
ast.fix_missing_locations(mod)
ns = {
    "ast": ast, "hashlib": hashlib, "html": html, "re": re,
    "parse_qs": parse_qs, "urlencode": urlencode, "unquote": unquote,
    "urljoin": urljoin, "urlsplit": urlsplit, "urlunsplit": urlunsplit,
    "Any": Any, "Dict": Dict, "Iterable": Iterable, "List": List,
    "Optional": Optional, "Tuple": Tuple,
}
exec(compile(mod, str(SRC), "exec"), ns)


def test_hidden_visible_and_wrapped_links():
    hidden = '''<div class="tgme_widget_message_wrap" data-post="regengguangya/100">
    <div>名称：花开锦绣 (2026) [2160P]<br>集数：第23-25集 / 全36集<br>TMDB：287496</div>
    <a class="tgme_widget_message_inline_button" href="https://www.guangyapan.com/s/hiddenABC">🔗 光鸭云盘：查看资源</a>
    </div>'''
    items = ns["_extract_channel_entries"](hidden, "https://tgm.li668.asia/regengguangya", "影视热更")
    assert len(items) == 1
    assert items[0]["share_id"] == "hiddenABC"
    assert items[0]["tmdb_id"] == "287496"
    assert "23-25" in items[0]["episode_hint"]
    assert "按钮" in items[0]["link_style"]

    visible = '''<div data-post="yunpanguangya/101">名称：杀手妈咪 유부녀 킬러 (2026) [1080P] [更至8集]
    链接：www.guangyapan.com/s/plainXYZ</div>'''
    items = ns["_extract_channel_entries"](visible, "https://tgm.li668.asia/yunpanguangya", "资源分享")
    assert len(items) == 1 and items[0]["share_id"] == "plainXYZ"
    assert items[0]["link_style"] == "明文链接"

    wrapped = '''<div data-post="regengguangya/102">名称：包装测试 (2026)
    <a href="/redirect?url=https%3A%2F%2Fwww.guangyapan.com%2Fs%2Fwrap123%3Fcode%3DAb12">查看资源</a></div>'''
    items = ns["_extract_channel_entries"](wrapped, "https://tgm.li668.asia/regengguangya", "影视热更")
    assert len(items) == 1 and items[0]["share_id"] == "wrap123"
    assert "code=Ab12" in items[0]["share_url"]
    assert "按钮" in items[0]["link_style"] or "包装" in items[0]["link_style"]


def test_message_boundary_and_tmdb_exact_match():
    page = '''<div data-post="regengguangya/201">名称：花开锦绣 (2026)<br>TMDB: 287496
    <a href="https://www.guangyapan.com/s/a201">查看资源</a></div>
    <div data-post="regengguangya/202">名称：完全不同 (2025)<br>TMDB: 999999
    <a href="https://www.guangyapan.com/s/a202">查看资源</a></div>'''
    items = ns["_extract_channel_entries"](page, "https://tgm.li668.asia/regengguangya", "影视热更")
    first = next(item for item in items if item["share_id"] == "a201")
    assert "999999" not in first["text"]
    assert ns["_entry_matches_subscription"](first, "标题甚至不同也可由ID确认", 2026, 1, "themoviedb", "287496") is True
    assert ns["_entry_matches_subscription"](first, "花开锦绣", 2026, 1, "themoviedb", "999999") is False


def test_pagination_episode_and_path_safety():
    html_page = '''<a href="/regengguangya?before=123">Older</a>
    <a href="/other?before=1">Other</a><a href="/regengguangya">Same</a>'''
    pages = ns["_extract_pagination_urls"](html_page, "https://tgm.li668.asia/regengguangya")
    assert pages == ["https://tgm.li668.asia/regengguangya?before=123"]
    season, eps = ns["_episode_numbers"]("Show.S01E23-E25.2160p.WEB-DL.mkv")
    assert season == 1 and eps == [23, 24, 25]
    _, eps = ns["_episode_numbers"]("第8-10集.mp4")
    assert eps == [8, 9, 10]
    assert ns["_safe_relative_path"]("../../Season 1/../E01.mkv") == "Season 1/E01.mkv"


def test_version_and_safety_contracts():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    local = json.loads((ROOT / "plugins.v3" / "guangyatransferassistant" / "plugin.json").read_text(encoding="utf-8"))
    assert package["version"] == "1.2.0" and local["version"] == "1.2.0"
    assert 'plugin_version = "1.2.0"' in text
    for token in (
        "隐藏按钮", "包装按钮", "_extract_pagination_urls", "tmdb_id", "TMDB精确",
        "strict_subscription_rules", "best_version", "filter_groups", "state not in (\"N\", \"R\")",
        "sync_subscription_progress", "SubscribeOper().update", "_episode_numbers",
        "max_files_per_run", "retry_minutes", "旧缓存", "stale", "clear_inventory",
        "【光鸭转存助手】【进度】", "【光鸭转存助手】【规则】", "【光鸭转存助手】【重试】",
    ):
        assert token in text, token
    assert "subscribe_search" in text and "new_subscribe_search" in text
    assert "SubscribeChain().search" in text
    assert "/nd.bizuserres.s/v1/restore_share" in text
    assert "transfer_inventory" in text and "legacy_fingerprint" in text
    assert "✅ 光鸭转存成功" in text and "⚠️ 光鸭转存失败" in text


def test_asset_identity_keeps_v11_compatibility_when_digest_absent():
    old_style = hashlib.sha256("season 1/e01.mkv|100".encode("utf-8")).hexdigest()
    assert ns["_asset_identity"]("Season 1/E01.mkv", 100) == old_style
    assert ns["_asset_identity"]("Season 1/E01.mkv", 100, "abc") != old_style
'''
TEST.write_text(test, encoding="utf-8")
print("patched GuangYaTransferAssistant v1.2.0")
