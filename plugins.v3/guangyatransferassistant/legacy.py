"""光鸭转存助手：Telegram 频道分享索引 + MoviePilot 订阅精确分流。"""

from __future__ import annotations

import datetime
import hashlib
import html
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, unquote, urljoin, urlsplit, urlunsplit

from apscheduler.triggers.cron import CronTrigger

from app.chain.subscribe import SubscribeChain, build_subscribe_meta
from app.chain.media import MediaChain
from app.chain.download import DownloadChain
from app.db.oper.subscribe import SubscribeOper
from app.plugins import _PluginBase
from app.schemas import NotificationType
from app.sdk.plugins import PluginManager
from app.sdk.config import settings
from app.sdk.logging import logger
from app.sdk.network import RequestUtils


DEFAULT_CHANNEL_URLS = [
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
VIDEO_EXTENSIONS = {".mkv", ".mp4", ".ts", ".m2ts", ".mts", ".avi", ".mov", ".wmv", ".flv", ".webm", ".iso", ".rmvb", ".m4v", ".mpg", ".mpeg", ".vob"}
SUBTITLE_EXTENSIONS = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".sup", ".smi", ".idx"}
TOTAL_EPISODE_PATTERN = re.compile(r"(?:全|共|总共|共计)\s*(\d{1,4})\s*(?:集|话)", re.I)
COMPLETE_HINT_PATTERN = re.compile(r"(?:已?完结|全集|全季|大结局|\bcomplete\b|\bend\b)", re.I)
ONGOING_HINT_PATTERN = re.compile(r"(?:更新至|更新到|更至|连载中?|持续更新|热更中?)", re.I)

def _normalize_media_text(value: Any) -> str:
    """标题匹配使用的宽松归一化。"""
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[\[【（(].{0,28}?[\]】）)]", " ", text)
    text = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", text).lower()
    return text


def _canonical_share_url(raw_url: str, context: str = "") -> str:
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


_CHANNEL_META_BOUNDARY = re.compile(
    r"(?=\s*(?:🎭|⭐|🖥|📺|📼|📦|👤|🔗|📝|类型\s*[：:]|TMDB(?:\s*ID)?\s*[：:#]|"
    r"TMDB评分\s*[：:]|画质\s*[：:]|质量\s*[：:]|集数\s*[：:]|大小\s*[：:]|分享\s*[：:]|简介\s*[：:]|$))",
    re.I,
)


def _clean_channel_display_title(value: Any) -> str:
    """清理频道标题末尾年份/更新状态，但保留完整中英日韩标题。"""
    title = html.unescape(str(value or "")).strip()
    title = re.sub(r"^[\s🎬🎞🎥📺]+", "", title).strip()
    title = re.sub(r"\s+", " ", title)
    # 新热更模板常见：标题 (2026) 已更新 / 标题（2026）完结。
    title = re.sub(
        r"\s*[（(]\s*(?:19\d{2}|20\d{2})\s*[）)]\s*(?:已?更新|更新中|已?完结|完结|全集|全季)?\s*$",
        "",
        title,
        flags=re.I,
    ).strip()
    title = re.sub(r"\s*(?:已?更新|更新中|已?完结|完结)\s*$", "", title, flags=re.I).strip()
    return title[:300]


def _extract_channel_display_title(text: Any) -> str:
    """兼容“名称：xxx”和“🎬 xxx (2026) 已更新”两类频道标题模板。"""
    raw = str(text or "")
    # 传统字段格式。允许标题后同一行继续跟元数据 emoji。
    labelled = re.search(r"(?im)(?:^|\n)\s*(?:名称|片名|剧名|标题)\s*[：:]\s*([^\n]{2,320})", raw)
    if labelled:
        candidate = _CHANNEL_META_BOUNDARY.split(labelled.group(1), maxsplit=1)[0]
        cleaned = _clean_channel_display_title(candidate)
        if cleaned:
            return cleaned

    # 新版影视热更频道：频道名可能与 🎬 标题处于同一文本行。
    emoji = re.search(r"🎬\s*([^\n]{2,360})", raw)
    if emoji:
        candidate = _CHANNEL_META_BOUNDARY.split(emoji.group(1), maxsplit=1)[0]
        cleaned = _clean_channel_display_title(candidate)
        if cleaned:
            return cleaned

    # 保守兜底：只接受带年份、且不是明显元数据字段的独立行，避免把分享文件名误当标题。
    for line in raw.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if not line or re.match(r"^(?:类型|TMDB|画质|质量|集数|大小|分享|简介)\s*[：:]", line, re.I):
            continue
        if not re.search(r"[（(](?:19\d{2}|20\d{2})[）)]", line):
            continue
        candidate = _CHANNEL_META_BOUNDARY.split(line, maxsplit=1)[0]
        cleaned = _clean_channel_display_title(candidate)
        if cleaned and "光鸭云盘影视热更频道" not in cleaned:
            return cleaned
    return ""


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
    display_title = _extract_channel_display_title(text)
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
    total_match = TOTAL_EPISODE_PATTERN.search(text)
    year_match = re.search(r"\b(19\d{2}|20\d{2})\b", text)
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
        entry_key = _entry_process_key(entry) or share_key
        old = by_key.get(entry_key)
        score = len(entry["text"]) + (600 if entry.get("tmdb_id") else 0) + (300 if entry.get("display_title") else 0)
        old_score = len(str((old or {}).get("text") or "")) + (600 if (old or {}).get("tmdb_id") else 0) + (300 if (old or {}).get("display_title") else 0)
        if not old or score > old_score:
            by_key[entry_key] = entry
    return list(by_key.values())


def _share_identity(share_url: str) -> str:
    """返回 shareId + code 的稳定键。"""
    try:
        parsed = urlsplit(str(share_url or ""))
    except ValueError:
        return ""
    combined_path = "/".join(
        value.strip("/") for value in (parsed.path, parsed.fragment) if value
    )
    matched = re.search(r"(?:^|/)(?:s|share)/([A-Za-z0-9_-]+)", combined_path, re.I)
    query = parse_qs(parsed.query)
    share_id = (query.get("shareId") or query.get("share_id") or query.get("id") or [""])[0]
    if not share_id and matched:
        share_id = matched.group(1)
    code = (query.get("code") or query.get("pwd") or [""])[0]
    return f"{share_id}|{code}" if share_id else ""



def _entry_process_key(entry: Dict[str, Any]) -> str:
    """同一频道消息+同一分享只处理一次；新消息或新链接会生成新键。"""
    share_key = _share_identity(str(entry.get("share_url") or ""))
    if not share_key:
        return ""
    source = str(entry.get("source_url") or entry.get("source_label") or "").strip()
    message_id = str(entry.get("message_id") or "").strip()
    if message_id:
        message_marker = f"msg:{message_id}"
    else:
        stable_text = re.sub(r"\s+", " ", str(entry.get("text") or "")).strip()
        message_marker = "txt:" + hashlib.sha256(stable_text.encode("utf-8")).hexdigest()[:20]
    return hashlib.sha256(f"{source}|{message_marker}|{share_key}".encode("utf-8")).hexdigest()

def _entry_matches_subscription(
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
    if season not in (None, ""):
        explicit = re.findall(r"(?i)\bS(?:eason)?\s*0*(\d{1,2})\b", text_value)
        if explicit and int(season) not in {int(value) for value in explicit}:
            return False
    if comparable_tmdb:
        return True

    parsed_title = str(entry.get("display_title") or "").strip()
    # 已成功解析频道标题时，只用标题做标题匹配；避免字幕/文件列表中的其它片名造成误命中。
    haystack = _normalize_media_text(parsed_title if parsed_title else text_value)
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
        hinted_year = entry.get("year_hint")
        years = {int(hinted_year)} if hinted_year else {int(value) for value in re.findall(r"\b(19\d{2}|20\d{2})\b", text_value)}
        if years and int(year) not in years:
            return False
    return True


def _subscription_aliases(subscribe: Any) -> List[str]:
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

    # 特别篇 / SP / OVA / OAD 属于 Season 0。只有没有普通季集标记时才启用，
    # 防止 Show.S01E08.SP1 把 SP1 误并入第一季完成集。
    if not episodes:
        special = re.search(
            r"(?i)(?:^|[^A-Za-z0-9])(?:SP|SPECIAL|OVA|OAD)[\s._-]*0*(\d{1,4})(?=[^0-9]|$)",
            value,
        )
        if not special:
            special = re.search(r"(?:特别篇|番外|特典)\s*0*(\d{1,4})(?=[^0-9]|$)", value)
        if special:
            season = 0
            episodes.add(int(special.group(1)))

    # 动漫/压制组常用弱格式："Title - 06"、"06.mkv"、"[07]"、"08v2"。
    # 只在所有严格规则都失败时启用；4 位年份/2160p 不会命中，并排除常见编码号。
    if not episodes:
        basename = str(value or "").replace("\\", "/").rsplit("/", 1)[-1]
        stem = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", basename).strip()
        fallback_patterns = (
            r"[\[【(（]\s*0*(\d{1,3})(?:v\d+)?\s*[\]】)）]",
            r"(?:^|[\s._])[-–—][\s._-]*0*(\d{1,3})(?:v\d+)?(?=\s|[._\[(（]|$)",
            r"^\s*0*(\d{1,3})(?:v\d+)?(?=\s|[._\-\[(（]|$)",
            r"(?:^|[\s._-])0*(\d{1,3})(?:v\d+)?$",
        )
        for pattern in fallback_patterns:
            matched = re.search(pattern, stem, re.I)
            if not matched:
                continue
            candidate = int(matched.group(1))
            if 0 < candidate <= 500 and candidate not in {264, 265, 266}:
                episodes.add(candidate)
                break

    return season, sorted(ep for ep in episodes if ep > 0)


def _entry_serial_state(entry: Dict[str, Any]) -> Dict[str, Any]:
    """从频道消息判断当前更新集、明确总集数以及连载/完结提示。"""
    value = str(entry.get("text") or "")
    explicit_total = 0
    try:
        explicit_total = int(entry.get("total_episode_hint") or 0)
    except (TypeError, ValueError):
        explicit_total = 0
    if not explicit_total:
        total_match = TOTAL_EPISODE_PATTERN.search(value)
        if total_match:
            explicit_total = int(total_match.group(1))

    current_episode = 0
    _, episode_values = _episode_numbers(entry.get("episode_hint") or value)
    if episode_values:
        current_episode = max(episode_values)
    if not current_episode:
        current_match = re.search(r"(?:更新至|更新到|更至)\s*0*(\d{1,4})\s*(?:集|话)", value, re.I)
        if current_match:
            current_episode = int(current_match.group(1))

    complete = bool(COMPLETE_HINT_PATTERN.search(value))
    ongoing = bool(ONGOING_HINT_PATTERN.search(value)) and not complete
    return {
        "explicit_total": explicit_total,
        "current_episode": current_episode,
        "complete": complete,
        "ongoing": ongoing,
    }

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



def _normalize_config_path(value: Any, default: str = "/光鸭转存") -> str:
    """把 VCombobox 的字符串/对象/旧对象字符串统一成绝对云盘路径。"""
    candidate = value
    if isinstance(candidate, dict):
        candidate = candidate.get("value") or candidate.get("title") or default
    elif isinstance(candidate, (list, tuple)) and candidate:
        candidate = candidate[0]
        if isinstance(candidate, dict):
            candidate = candidate.get("value") or candidate.get("title") or default

    raw = str(candidate if candidate not in (None, "") else default).strip()
    # 兼容 1.2.0 错误持久化的：{'title': '/光鸭媒体库', 'value': '/光鸭媒体库'}
    if raw.startswith("{") and ("value" in raw or "title" in raw):
        matched = re.search(r"[\"'](?:value|title)[\"']\s*:\s*[\"']([^\"']+)[\"']", raw)
        if matched:
            raw = matched.group(1).strip()
    normalized = _safe_relative_path(raw)
    return f"/{normalized}" if normalized else "/"

def _file_extension(value: Any) -> str:
    name = str(value or "").rsplit("/", 1)[-1].lower()
    return "." + name.rsplit(".", 1)[-1] if "." in name else ""


def _is_video(value: Any) -> bool:
    return _file_extension(value) in VIDEO_EXTENSIONS


def _is_subtitle(value: Any) -> bool:
    return _file_extension(value) in SUBTITLE_EXTENSIONS


def _natural_media_sort_key(value: Any) -> tuple:
    parts = re.split(r"(\d+)", str(value or "").lower())
    return tuple((0, int(part)) if part.isdigit() else (1, part) for part in parts if part != "")


def _extract_result_list(response: Any) -> List[dict]:
    """兼容光鸭接口多种列表字段。"""
    if not isinstance(response, dict):
        return []
    data = response.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        data = response
    for key in ("list", "files", "items", "records", "fileList", "infoList", "rows", "dataList", "resList", "resources"):
        value = data.get(key) if isinstance(data, dict) else None
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _cloud_item(raw: dict) -> Optional[Dict[str, Any]]:
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


def _failure_notice_fingerprint(message: Any) -> str:
    """把动态 share/task/token 等噪声归一化，稳定识别同一类失败。"""
    value = str(message or "").lower()
    value = re.sub(r"share[_ -]?id\s*[=:：]\s*[a-z0-9_-]+", "share_id=*", value, flags=re.I)
    value = re.sub(r"task[_ -]?id\s*[=:：]\s*[a-z0-9_-]+", "task_id=*", value, flags=re.I)
    value = re.sub(r"\b[a-z0-9_-]{20,}\b", "*", value, flags=re.I)
    value = re.sub(r"\s+", " ", value).strip()[:1000]
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


class GuangYaTransferAssistant(_PluginBase):
    """对用户勾选的订阅固定走光鸭转存，未勾选固定走 MoviePilot 原生下载。"""

    plugin_name = "光鸭转存助手"
    plugin_desc = "订阅固定分流：手动勾选的订阅只使用光鸭频道转存，未勾选订阅只使用 MoviePilot 原生下载。"
    plugin_icon = "Guangyadisk_A.png"
    plugin_version = "1.6.5"
    plugin_author = "liheng-lk"
    plugin_label = "光鸭云盘,转存,订阅,Telegram,网盘,固定分流"
    author_url = "https://github.com/liheng-lk/MoviePilot-Plugins"
    plugin_config_prefix = "guangyatransferassistant_"
    plugin_order = 24
    auth_level = 1

    _enabled = False
    _channel_urls = "\n".join(DEFAULT_CHANNEL_URLS)
    _selected_subscriptions: List[int] = []
    _save_path = "/光鸭转存"
    _create_media_folder = False
    _notify = True
    _daily_summary = False
    _summary_cron = "30 22 * * *"
    _auto_transfer_on_refresh = True
    _strict_subscription_rules = True
    _media_only = True
    _sync_subscription_progress = True
    _protect_ongoing = True
    _ongoing_guard_days = 10
    _history_pages = 3
    _retry_minutes = 30
    _max_files_per_run = 50
    _refresh_minutes = 5
    _proxy = False
    _max_share_files = 5000
    _takeover_originals: Dict[str, Any] = {}
    _route_lock = threading.RLock()
    _inspect_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
    _state_lock = threading.RLock()
    _run_lock_minutes = 15
    _data_schema_version = 6
    _runtime_generation = 0
    _runtime_generation_lock = threading.Lock()

    def init_plugin(self, config: dict = None) -> None:
        """读取配置并安装订阅搜索分流。"""
        self._restore_takeover()
        config = config or {}
        self._enabled = bool(config.get("enabled", False))
        self._channel_urls = str(config.get("channel_urls") or "\n".join(DEFAULT_CHANNEL_URLS)).strip()
        self._selected_subscriptions = sorted({int(value) for value in (config.get("selected_subscriptions") or []) if str(value).isdigit()})
        raw_save_path = config.get("save_path")
        self._save_path = _normalize_config_path(raw_save_path, "/光鸭转存")
        path_migrated = raw_save_path not in (None, "") and raw_save_path != self._save_path
        self._create_media_folder = bool(config.get("create_media_folder", False))
        self._notify = bool(config.get("notify", True))
        self._daily_summary = bool(config.get("daily_summary", False))
        self._summary_cron = str(config.get("summary_cron") or "30 22 * * *").strip()
        self._auto_transfer_on_refresh = bool(config.get("auto_transfer_on_refresh", True))
        self._strict_subscription_rules = bool(config.get("strict_subscription_rules", True))
        self._media_only = bool(config.get("media_only", True))
        self._sync_subscription_progress = bool(config.get("sync_subscription_progress", True))
        self._protect_ongoing = bool(config.get("protect_ongoing", True))
        self._ongoing_guard_days = self._to_int(config.get("ongoing_guard_days"), 10, 1, 60)
        self._history_pages = self._to_int(config.get("history_pages"), 3, 1, 10)
        self._retry_minutes = self._to_int(config.get("retry_minutes"), 30, 5, 720)
        self._max_files_per_run = self._to_int(config.get("max_files_per_run"), 50, 1, 500)
        self._proxy = bool(config.get("proxy", False))
        self._refresh_minutes = self._to_int(config.get("refresh_minutes"), 5, 1, 120)
        self._max_share_files = self._to_int(config.get("max_share_files"), 5000, 100, 20000)
        if bool(config.get("clear_inventory", False)):
            self.save_data("transfer_inventory", {})
            self.save_data("transfer_history", {})
            self.save_data("failure_notices", {})
            self.save_data("completion_guard", {})
            self.save_data("processed_entries", {})
            self.save_data("media_facts", {})
            self.save_data("transfer_jobs", {})
            self.save_data("active_runs", {})
            self.save_data("channel_cursors", {})
            self._inspect_cache.clear()
            self._plugin_log("WARNING", "【光鸭转存助手】【去重】已按配置清空转存库存与历史记录")
            config["clear_inventory"] = False
        self._ensure_data_schema()
        self._cleanup_selected_ids()
        if path_migrated:
            self._plugin_log("INFO", "【光鸭转存助手】【路径】目标目录配置已规范化：%s -> %s", raw_save_path, self._save_path)
            self._save_config()
        cached_count = len(((self.get_data("channel_index") or {}).get("items") or []))
        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【启动】v%s 启用=%s 自动转存=%s 刷新周期=%s分钟 固定转存订阅=%s 缓存索引=%s",
            self.plugin_version, self._enabled, self._auto_transfer_on_refresh, self._refresh_minutes,
            len(self._selected_subscriptions), cached_count,
        )
        if self._enabled:
            self._install_takeover()
            self._start_runtime_worker()

    def get_state(self) -> bool:
        return self._enabled

    def _plugin_log(self, level: str, message: Any, *args: Any) -> None:
        """同时写 MoviePilot 日志和插件自己的持久日志，页面只展示本插件记录。"""
        level_name = str(level or "INFO").upper()
        try:
            rendered = str(message) % args if args else str(message)
        except Exception:
            rendered = " ".join([str(message), *(str(arg) for arg in args)])
        method_name = "exception" if level_name == "EXCEPTION" else level_name.lower()
        log_method = getattr(logger, method_name, logger.info)
        try:
            log_method(message, *args)
        except Exception:
            pass
        try:
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with self._state_lock:
                rows = list(self.get_data("plugin_logs") or [])
                rows.append({"time": now, "level": level_name, "message": rendered})
                if len(rows) > 1000:
                    rows = rows[-1000:]
                self.save_data("plugin_logs", rows)
        except Exception:
            # 日志持久化失败不能影响转存主流程。
            pass

    def get_service(self) -> List[Dict[str, Any]]:
        if not self._enabled:
            return []
        services: List[Dict[str, Any]] = [{
            "id": "GuangYaTransferAssistantTick",
            "name": "光鸭转存助手频道增量刷新与路由守护",
            "trigger": "interval",
            "func": self._tick,
            "kwargs": {"minutes": self._refresh_minutes},
        }]
        if self._daily_summary:
            try:
                summary_trigger = CronTrigger.from_crontab(self._summary_cron)
            except Exception:
                self._plugin_log("WARNING", "【光鸭转存助手】【日报】Cron 配置无效，回退到每天 22:30")
                summary_trigger = CronTrigger.from_crontab("30 22 * * *")
            services.append({
                "id": "GuangYaTransferAssistantDailySummary",
                "name": "光鸭转存助手每日摘要",
                "trigger": summary_trigger,
                "func": self._send_daily_summary,
                "kwargs": {},
            })
        return services

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        subscriptions = self._subscription_options()
        folders = self._root_folder_options()
        return [{
            "component": "VForm",
            "content": [
                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VSwitch", "props": {"model": "enabled", "label": "启用订阅固定分流"}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VSwitch", "props": {"model": "notify", "label": "转存结果通知"}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VSwitch", "props": {"model": "proxy", "label": "频道读取使用代理"}}]},
                ]},
                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "daily_summary", "label": "每日转存摘要"}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VTextField", "props": {"model": "summary_cron", "label": "摘要 Cron", "hint": "默认每天 22:30；关闭摘要时不会注册任务", "persistent-hint": True}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [{"component": "VAlert", "props": {"type": "info", "variant": "tonal", "text": "日报只汇总当天新增文件、失败/待落盘任务和缺集/连载状态，不改变任何订阅或转存路线。"}}]},
                ]},
                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 7}, "content": [{"component": "VAutocomplete", "props": {"model": "selected_subscriptions", "label": "搜索并选择仅使用光鸭转存的订阅", "items": subscriptions, "multiple": True, "chips": True, "closable-chips": True, "clearable": True, "hide-selected": False, "hint": "可按剧名、年份、季、类型或订阅ID搜索", "persistent-hint": True, "prepend-inner-icon": "mdi-magnify"}}]},
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
                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "protect_ongoing", "label": "连载保护", "hint": "更新至/连载中的剧即使当前集数齐全，也不会立即判定订阅完成", "persistent-hint": True}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VTextField", "props": {"model": "ongoing_guard_days", "label": "无完结标记等待(天)", "type": "number", "hint": "频道仅写更新至N集且没有全N集/完结时，稳定达到当前总集数后至少等待该天数", "persistent-hint": True}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [{"component": "VAlert", "props": {"type": "info", "variant": "tonal", "text": "频道若写明全N集/共N集，会自动把 MoviePilot 总集数向上校正；更新至N集只作为当前进度下限，不会误当完结。"}}]},
                ]},
                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 9}, "content": [{"component": "VTextarea", "props": {"model": "channel_urls", "label": "资源频道地址（每行一个）", "rows": 3}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "clear_inventory", "label": "保存时清空去重记录", "hint": "仅故障恢复时使用，执行一次后自动关闭", "persistent-hint": True}}]},
                ]},
                {"component": "VAlert", "props": {"type": "info", "variant": "tonal", "text": "固定分流模式：已勾选订阅只走光鸭转存，即使暂时无资源或转存失败也不会启动原生下载；未勾选订阅完全走 MoviePilot 原生下载。暂停/待定不会执行转存；洗版或复杂规则如需原生处理，请取消勾选。"}},
            ],
        }], {
            "enabled": self._enabled,
            "channel_urls": self._channel_urls or "\n".join(DEFAULT_CHANNEL_URLS),
            "selected_subscriptions": self._selected_subscriptions,
            "save_path": self._save_path or "/光鸭转存",
            "create_media_folder": self._create_media_folder,
            "notify": self._notify,
            "daily_summary": self._daily_summary,
            "summary_cron": self._summary_cron or "30 22 * * *",
            "auto_transfer_on_refresh": self._auto_transfer_on_refresh,
            "strict_subscription_rules": self._strict_subscription_rules,
            "media_only": self._media_only,
            "sync_subscription_progress": self._sync_subscription_progress,
            "protect_ongoing": self._protect_ongoing,
            "ongoing_guard_days": self._ongoing_guard_days or 10,
            "history_pages": self._history_pages or 3,
            "retry_minutes": self._retry_minutes or 30,
            "max_files_per_run": self._max_files_per_run or 50,
            "refresh_minutes": self._refresh_minutes or 5,
            "proxy": self._proxy,
            "max_share_files": self._max_share_files or 5000,
            "clear_inventory": False,
        }

    def _subscription_console_snapshot(self, subscribe: Any, entries: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
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
        cancelled_jobs = [row for row in jobs if str(row.get("status") or "") == "cancelled"]

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
        elif latest_status == "cancelled" and cancelled_jobs:
            label = "旧卡住任务已忽略 · 等待新消息"
            alert_type = "warning"
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
            "pending_jobs": len(pending_jobs), "failed_jobs": len(failed_jobs), "cancelled_jobs": len(cancelled_jobs),
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
            if isinstance(row, dict) and str(row.get("media") or "") == prefix and str(row.get("status") or "") in {"failed", "synced", "verified", "cancelled"}:
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
        self._plugin_log("WARNING", 
            "【光鸭转存助手】【状态重置】#%s %s 已重置检查记录：消息=%s，结束任务=%s，失败通知=%s；媒体事实/库存/进度均保留",
            sid, getattr(subscribe, "name", ""), removed_processed, removed_jobs, removed_notices,
        )
        return {
            "success": True,
            "message": f"已重置检查状态：消息 {removed_processed} 条、结束任务 {removed_jobs} 条；媒体事实/库存/订阅进度已保留",
        }

    def _pending_jobs_for_subscription(self, subscribe: Any) -> List[Tuple[str, Dict[str, Any]]]:
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

    def _pending_reservations(self, subscribe: Any, exclude_job_key: str = "") -> Dict[str, Any]:
        """收集同媒体其它在途任务已占用的路径/剧集，避免新频道消息重复提交相同内容。"""
        prefix = self._media_fact_prefix(subscribe)
        pending_status = {"submitted", "task_confirmed", "verifying"}
        paths = set()
        episodes = set()
        movie_pending = False
        for key, row in (self.get_data("transfer_jobs") or {}).items():
            if str(key) == str(exclude_job_key or "") or not isinstance(row, dict):
                continue
            if str(row.get("media") or "") != prefix or str(row.get("status") or "") not in pending_status:
                continue
            for raw_path in (row.get("paths") or []):
                path = _safe_relative_path(raw_path)
                if not path:
                    continue
                paths.add(path.lower())
                if _is_video(path) or _is_subtitle(path):
                    _, values = _episode_numbers(path)
                    episodes.update(int(value) for value in values)
                if self._is_movie_subscription(subscribe) and _is_video(path):
                    movie_pending = True
        return {"paths": paths, "episodes": episodes, "movie": movie_pending}

    def _filter_inflight_planned_items(
        self, subscribe: Any, planned: List[Dict[str, Any]], exclude_job_key: str = "",
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        reservations = self._pending_reservations(subscribe, exclude_job_key=exclude_job_key)
        if not reservations["paths"] and not reservations["episodes"] and not reservations["movie"]:
            return list(planned), []
        ready: List[Dict[str, Any]] = []
        held: List[Dict[str, Any]] = []
        for item in planned:
            path = _safe_relative_path(item.get("effective_path") or item.get("relative_path") or item.get("name") or "")
            lowered = path.lower()
            blocked = bool(lowered and lowered in reservations["paths"])
            if not blocked and reservations["movie"] and self._is_movie_subscription(subscribe):
                blocked = bool(_is_video(path) or _is_subtitle(path))
            if not blocked and reservations["episodes"]:
                _, values = _episode_numbers(path)
                blocked = bool(set(values).intersection(reservations["episodes"]))
            (held if blocked else ready).append(item)
        return ready, held

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
        self._plugin_log("WARNING", 
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
            self._plugin_log("INFO", "【光鸭转存助手】【日报】已发送：新增文件=%s，失败=%s，待落盘=%s，订阅=%s", new_files, failed, pending, len(subs))
            return {"success": True, "message": "每日摘要已发送", "new_files": new_files, "failed": failed, "pending": pending}
        except Exception as err:
            self._plugin_log("WARNING", "【光鸭转存助手】【日报】发送失败：%s", err)
            return {"success": False, "message": f"摘要发送失败：{err}"}

    def get_page(self) -> Optional[List[dict]]:
        index = self.get_data("channel_index") or {}
        history = self.get_data("transfer_history") or {}
        inventory = self.get_data("transfer_inventory") or {}
        last = self.get_data("last_run") or {}
        processed_entries = self.get_data("processed_entries") or {}
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
            done, total, lack = self._subscription_episode_progress(sub)
            missing = self._subscription_missing_episodes(sub)
            progress_text = f" · 已完成 {done}/{total} 集 · 剩余 {lack} 集" if total else ""
            missing_text = ""
            if missing:
                shown = ",".join(f"E{value:02d}" for value in missing[:20])
                missing_text = f" · 缺失 {shown}" + (f" 等{len(missing)}集" if len(missing) > 20 else "")
            channel_state = self._channel_state_for_subscription(sub, index.get("items") or [])
            runtime = self._subscription_console_snapshot(sub, index.get("items") or [])
            serial_text = ""
            if channel_state.get("explicit_total"):
                serial_text += f" · 频道总集 {channel_state.get('explicit_total')}"
            if channel_state.get("ongoing") and not channel_state.get("complete"):
                serial_text += " · 连载中"
            elif channel_state.get("complete"):
                serial_text += " · 频道标记完结"
            actions = [{
                "component": "VBtn",
                "props": {"size": "small", "variant": "outlined", "prepend-icon": "mdi-refresh"},
                "text": "立即检查缺集",
                "events": {"click": {"api": "plugin/GuangYaTransferAssistant/check_missing", "method": "post", "params": {"subscribe_id": sid, "token": settings.API_TOKEN}}},
            }]
            if runtime.get("pending_jobs"):
                actions.append({
                    "component": "VBtn",
                    "props": {"size": "small", "variant": "outlined", "color": "warning", "prepend-icon": "mdi-file-sync-outline"},
                    "text": "复查待落盘",
                    "events": {"click": {"api": "plugin/GuangYaTransferAssistant/recheck_pending", "method": "post", "params": {"subscribe_id": sid, "token": settings.API_TOKEN}}},
                })
                actions.append({
                    "component": "VBtn",
                    "props": {"size": "small", "variant": "text", "color": "error", "prepend-icon": "mdi-cancel"},
                    "text": "忽略卡住任务",
                    "events": {"click": {"api": "plugin/GuangYaTransferAssistant/cancel_pending", "method": "post", "params": {"subscribe_id": sid, "token": settings.API_TOKEN}}},
                })
            actions.append({
                "component": "VBtn",
                "props": {"size": "small", "variant": "text", "prepend-icon": "mdi-restart"},
                "text": "重置检查状态",
                "events": {"click": {"api": "plugin/GuangYaTransferAssistant/reset_state", "method": "post", "params": {"subscribe_id": sid, "token": settings.API_TOKEN}}},
            })
            if lack > 0:
                actions.append({
                    "component": "VBtn",
                    "props": {"size": "small", "variant": "text", "color": "warning", "prepend-icon": "mdi-download"},
                    "text": "切换普通下载",
                    "events": {"click": {"api": "plugin/GuangYaTransferAssistant/release_native", "method": "post", "params": {"subscribe_id": sid, "token": settings.API_TOKEN}}},
                })
            rows.append({
                "component": "VCard",
                "props": {"variant": "tonal", "class": "h-100"},
                "content": [
                    {"component": "VCardTitle", "text": f"{sub.name} ({getattr(sub, 'year', '') or '-'})"},
                    {"component": "VAlert", "props": {"type": runtime.get("alert_type") or "info", "variant": "tonal", "density": "compact", "class": "mx-4 mb-2", "text": runtime.get("label") or "等待新消息"}},
                    {"component": "VCardText", "text": f"订阅ID {sid} · 状态 {state}{progress_text}{missing_text}{serial_text} · 媒体事实 {runtime.get('fact_count') or 0} · 已处理消息 {runtime.get('processed_count') or 0} · 待落盘 {runtime.get('pending_jobs') or 0} · 最近频道消息 {runtime.get('last_message') or '-'} · 去重资源 {asset_count} 个 · {state_text}"},
                    {"component": "VCardActions", "content": actions},
                ],
            })
        fresh_count = len([item for item in (index.get("items") or []) if not item.get("stale") and not item.get("cached_index")])
        retained_count = len([item for item in (index.get("items") or []) if not item.get("stale") and item.get("cached_index")])
        stale_count = len(index.get("items") or []) - fresh_count - retained_count
        contents: List[dict] = [{
            "component": "VAlert",
            "props": {
                "type": "warning" if last.get("stale_index") else ("success" if last.get("success") else "info"),
                "variant": "tonal",
                "text": f"频道索引 {len(index.get('items') or [])} 个（本轮新增 {index.get('new_count') or 0} / 当前抓取 {fresh_count} / 保留索引 {retained_count} / 故障回退 {stale_count}）· 已处理媒体消息 {len(processed_entries)} · 媒体事实 {len(self.get_data('media_facts') or {})} · 最近刷新 {index.get('time') or '-'}",
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
                            f"索引 {status.get('count') or 0} · 本轮新增 {status.get('new_count') or 0} · 游标 {status.get('cursor') or '-'} · 隐藏/包装按钮 {status.get('button_links') or 0} · "
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

        audit = []
        for row in self._task_audit_rows(40):
            paths = [str(value) for value in (row.get("paths") or []) if value]
            detail = str(row.get("error") or row.get("verification_message") or row.get("cancel_reason") or row.get("message") or "").strip()
            if paths:
                detail = (detail + (" · " if detail else "") + "文件：" + "、".join(paths[:4]) + (f" 等{len(paths)}个" if len(paths) > 4 else ""))
            audit.append({
                "component": "VListItem",
                "props": {
                    "title": f"{row.get('updated') or '-'} · {row.get('status') or '-'} · {row.get('media') or '-'}",
                    "subtitle": f"消息 {row.get('message_id') or '-'} · 分享 {row.get('share_id') or '-'} · {detail[:500] or '无附加错误'}",
                },
            })
        contents.append({
            "component": "VCard",
            "props": {"variant": "outlined", "class": "mt-4"},
            "content": [
                {"component": "VCardTitle", "text": f"转存任务审计（最近 {len(audit)} 条）"},
                {"component": "VCardText", "text": "submitted/task_confirmed/verifying 表示任务已经提交，不能用‘立即检查缺集’强制重放；如确需忽略卡住任务，请使用订阅卡片上的人工操作。"},
                {"component": "VList", "props": {"density": "compact"}, "content": audit or [{"component": "VListItem", "props": {"title": "暂无转存任务记录"}}]},
            ],
        })

        plugin_log_rows = list(self.get_data("plugin_logs") or [])
        plugin_log_items = []
        for row in reversed(plugin_log_rows[-1000:]):
            plugin_log_items.append({
                "component": "VListItem",
                "props": {
                    "title": f"{row.get('time') or '-'} · {row.get('level') or 'INFO'}",
                    "subtitle": str(row.get("message") or ""),
                },
            })
        contents.append({
            "component": "VCard",
            "props": {"variant": "outlined", "class": "mt-4"},
            "content": [
                {"component": "VCardTitle", "text": f"光鸭转存助手插件日志（{len(plugin_log_rows[-1000:])} 条）"},
                {"component": "VCardText", "text": "这里只显示光鸭转存助手自己的完整日志，不再混入 MoviePilot 全局日志。重点查看【匹配】【分享解析】【文件识别】【增量】【转存】【落盘确认】阶段。"},
                {"component": "VCardActions", "content": [{
                    "component": "VBtn",
                    "props": {"size": "small", "variant": "text", "color": "warning", "prepend-icon": "mdi-delete-sweep-outline"},
                    "text": "清空插件日志",
                    "events": {"click": {"api": "plugin/GuangYaTransferAssistant/clear_plugin_logs", "method": "post", "params": {"token": settings.API_TOKEN}}},
                }]},
                {"component": "VList", "props": {"density": "compact", "style": "max-height: 680px; overflow-y: auto;"}, "content": plugin_log_items or [{"component": "VListItem", "props": {"title": "暂无插件日志"}}]},
            ],
        })

        resources = []
        for entry in list(index.get("items") or [])[:150]:
            matched = []
            for sub in selected_subs:
                ok, reason = _entry_match_reason(entry, sub)
                if ok:
                    matched.append(f"{getattr(sub, 'name', '')}#{int(getattr(sub, 'id', 0) or 0)}({reason})")
            display = str(entry.get("display_title") or "").strip() or str(entry.get("source_label") or "频道资源")
            snippet = re.sub(r"https?://\S+", "", str(entry.get("text") or ""))
            snippet = re.sub(r"\s+", " ", snippet).strip()[:420]
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
                {"component": "VCardText", "text": "显示链接类型、TMDB/集数提示、当前抓取/保留索引/故障回退及匹配原因；频道使用消息游标增量读取，同一链接出现在新消息中仍作为新条目处理。"},
                {"component": "VList", "props": {"density": "compact"}, "content": resources or [{"component": "VListItem", "props": {"title": "暂无频道资源"}}]},
            ],
        })
        return contents

    def _manual_transfer_guard(self, subscribe: Any) -> Optional[Dict[str, Any]]:
        """所有会触发转存提交的人工入口共用同一门禁，避免绕过固定分流和待落盘保护。"""
        sid = int(getattr(subscribe, "id", 0) or 0)
        if not sid:
            return {"success": False, "message": "订阅不存在"}
        if sid not in set(self._selected_subscriptions):
            return {"success": False, "message": "该订阅当前不是光鸭固定转存路线"}
        state = str(getattr(subscribe, "state", "") or "")
        if state not in ("N", "R"):
            return {"success": False, "message": f"订阅当前状态 {state or '-'}，不允许人工触发转存"}
        pending = self._pending_jobs_for_subscription(subscribe)
        if pending:
            return {
                "success": False, "pending": True,
                "message": f"仍有 {len(pending)} 个已提交任务等待落盘确认；请先使用‘复查待落盘’，不会强制重复提交",
            }
        return None

    def _cached_matches_for_subscription(self, subscribe: Any) -> List[Tuple[Dict[str, Any], str]]:
        """从本地频道索引直接取该订阅的已知分享；stale 只代表频道抓取失败，不代表光鸭分享失效。"""
        entries = list(((self.get_data("channel_index") or {}).get("items") or []))
        pairs: List[Tuple[Dict[str, Any], str]] = []
        for entry in entries:
            matched, reason = _entry_match_reason(entry, subscribe)
            if matched and entry.get("share_url"):
                pairs.append((entry, reason))
        return pairs

    def _prepare_cache_first_manual_check(self, subscribe: Any, action: str) -> List[Tuple[Dict[str, Any], str]]:
        sid = int(getattr(subscribe, "id", 0) or 0)
        pairs = self._cached_matches_for_subscription(subscribe)
        if pairs:
            fallback = sum(1 for entry, _ in pairs if entry.get("stale"))
            self._plugin_log(
                "INFO", "【光鸭转存助手】【缓存命中】%s #%s %s 命中本地索引 %s 个分享（故障缓存 %s）；不访问 Telegram，直接检查光鸭分享",
                action, sid, getattr(subscribe, "name", ""), len(pairs), fallback,
            )
            return pairs
        self._plugin_log(
            "INFO", "【光鸭转存助手】【缓存未命中】%s #%s %s 本地索引没有可匹配分享，执行一次频道增量刷新",
            action, sid, getattr(subscribe, "name", ""),
        )
        self.refresh_channels(force=True)
        pairs = self._cached_matches_for_subscription(subscribe)
        self._plugin_log(
            "INFO", "【光鸭转存助手】【频道增量刷新】%s #%s %s 刷新后匹配分享=%s",
            action, sid, getattr(subscribe, "name", ""), len(pairs),
        )
        return pairs

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {"path": "/refresh", "endpoint": self.api_refresh, "methods": ["POST"], "summary": "立即刷新频道索引"},
            {"path": "/transfer", "endpoint": self.api_transfer, "methods": ["POST"], "summary": "立即尝试一个订阅的光鸭转存"},
            {"path": "/folders", "endpoint": self.api_folders, "methods": ["GET"], "summary": "读取光鸭根目录文件夹"},
            {"path": "/check_missing", "endpoint": self.api_check_missing, "methods": ["POST"], "summary": "缓存优先检查指定转存订阅缺集"},
            {"path": "/release_native", "endpoint": self.api_release_native, "methods": ["POST"], "summary": "将指定转存订阅切换回 MoviePilot 普通下载"},
            {"path": "/recheck_pending", "endpoint": self.api_recheck_pending, "methods": ["POST"], "summary": "只复查指定订阅的待落盘任务，不自动重复提交"},
            {"path": "/reset_state", "endpoint": self.api_reset_state, "methods": ["POST"], "summary": "安全重置指定订阅的频道检查状态，保留媒体事实/库存/进度"},
            {"path": "/cancel_pending", "endpoint": self.api_cancel_pending, "methods": ["POST"], "summary": "人工忽略指定订阅待落盘任务，旧消息不自动重放"},
            {"path": "/daily_summary", "endpoint": self.api_daily_summary, "methods": ["POST"], "summary": "立即发送一次光鸭转存摘要"},
            {"path": "/plugin_logs", "endpoint": self.api_plugin_logs, "methods": ["GET"], "summary": "读取光鸭转存助手完整插件日志"},
            {"path": "/clear_plugin_logs", "endpoint": self.api_clear_plugin_logs, "methods": ["POST"], "summary": "清空光鸭转存助手插件日志"},
        ]

    def api_plugin_logs(self, limit: int = 1000) -> Dict[str, Any]:
        try:
            limit = max(1, min(int(limit or 1000), 1000))
        except (TypeError, ValueError):
            limit = 1000
        rows = list(self.get_data("plugin_logs") or [])[-limit:]
        return {"success": True, "count": len(rows), "items": rows}

    def api_clear_plugin_logs(self) -> Dict[str, Any]:
        self.save_data("plugin_logs", [])
        return {"success": True, "message": "光鸭转存助手插件日志已清空"}

    def api_refresh(self) -> Dict[str, Any]:
        self._inspect_cache.clear()
        items = self.refresh_channels(force=True)
        routed = self._process_selected_subscriptions(trigger="手动刷新") if self._auto_transfer_on_refresh and any(not item.get("stale") for item in items) else []
        return {"success": True, "count": len(items), "items": items, "routes": routed}

    def api_transfer(self, payload: dict) -> Dict[str, Any]:
        payload = payload or {}
        sid = int(payload.get("subscribe_id") or 0)
        if not sid:
            return {"success": False, "message": "subscribe_id 不能为空"}
        subscribe = self._find_subscription(sid)
        if not subscribe:
            return {"success": False, "message": "订阅不存在"}
        self._plugin_log("INFO", "【光鸭转存助手】【人工检查】立即转存 #%s %s 开始", sid, getattr(subscribe, "name", ""))
        guard = self._manual_transfer_guard(subscribe)
        if guard:
            self._plugin_log("WARNING", "【光鸭转存助手】【门禁】立即转存 #%s %s 拒绝：%s", sid, getattr(subscribe, "name", ""), guard.get("message") or "未知原因")
            return guard
        self._prepare_cache_first_manual_check(subscribe, "立即转存")
        self._inspect_cache.clear()
        return self._try_transfer_subscription(subscribe, force=True, refresh_channel=False)

    def api_folders(self) -> Dict[str, Any]:
        return {"success": True, "items": self._root_folder_options(raw=True)}

    def api_check_missing(self, subscribe_id: int = 0) -> Dict[str, Any]:
        """缓存优先检查缺集：已知分享直接访问光鸭；只有缓存未命中才刷新 Telegram 频道。"""
        sid = int(subscribe_id or 0)
        subscribe = self._find_subscription(sid)
        if not sid or not subscribe:
            return {"success": False, "message": "订阅不存在"}
        self._plugin_log("INFO", "【光鸭转存助手】【人工检查】立即检查缺集 #%s %s 开始", sid, getattr(subscribe, "name", ""))
        guard = self._manual_transfer_guard(subscribe)
        if guard:
            self._plugin_log("WARNING", "【光鸭转存助手】【门禁】立即检查缺集 #%s %s 拒绝：%s", sid, getattr(subscribe, "name", ""), guard.get("message") or "未知原因")
            return guard
        self._prepare_cache_first_manual_check(subscribe, "立即检查缺集")
        self._inspect_cache.clear()
        result = self._try_transfer_subscription(subscribe, force=True, refresh_channel=False)
        missing = self._subscription_missing_episodes(self._find_subscription(sid) or subscribe)
        result["missing_episodes"] = missing
        return result

    def api_recheck_pending(self, subscribe_id: int = 0) -> Dict[str, Any]:
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

    def api_cancel_pending(self, subscribe_id: int = 0) -> Dict[str, Any]:
        sid = int(subscribe_id or 0)
        subscribe = self._find_subscription(sid)
        if not sid or not subscribe:
            return {"success": False, "message": "订阅不存在"}
        if sid not in set(self._selected_subscriptions):
            return {"success": False, "message": "该订阅当前不是光鸭固定转存路线"}
        return self._cancel_pending_jobs(subscribe)

    def api_daily_summary(self) -> Dict[str, Any]:
        return self._send_daily_summary(force=True)

    def api_release_native(self, subscribe_id: int = 0) -> Dict[str, Any]:
        """由用户明确操作后解除固定转存，后续交还 MoviePilot 原生订阅搜索。"""
        sid = int(subscribe_id or 0)
        subscribe = self._find_subscription(sid)
        if not sid or not subscribe:
            return {"success": False, "message": "订阅不存在"}
        missing = self._subscription_missing_episodes(subscribe)
        self._remove_selected_subscription(sid)
        self._plugin_log("WARNING", "【光鸭转存助手】【人工分流】#%s %s 已由用户切换为 MoviePilot 普通下载；当前缺失=%s", sid, getattr(subscribe, "name", ""), missing)
        if self._notify:
            try:
                self.post_message(
                    mtype=NotificationType.Plugin,
                    title="↪️ 光鸭订阅已切换普通下载",
                    text=(f"媒体：{getattr(subscribe, 'name', '')} ({getattr(subscribe, 'year', '') or '-'})\n"
                          f"缺失：{','.join(f'E{value:02d}' for value in missing) or '-'}\n"
                          "后续：已解除光鸭固定转存，交还 MoviePilot 原生订阅路线；不会立即强制搜索。"),
                )
            except Exception as err:
                self._plugin_log("WARNING", "【光鸭转存助手】【通知】发送人工切换通知失败：%s", err)
        return {"success": True, "message": "已切换为普通下载，后续由 MoviePilot 原生订阅任务处理缺集", "missing_episodes": missing}

    def _start_runtime_worker(self) -> None:
        """启动内置守护线程。宿主未重新注册 get_service 时仍能立即/周期执行；宿主定时器恢复后自动退居备用。"""
        try:
            old_stop = getattr(self, "_runtime_stop", None)
            if old_stop is not None:
                old_stop.set()
        except Exception:
            pass
        with type(self)._runtime_generation_lock:
            type(self)._runtime_generation += 1
            generation = type(self)._runtime_generation
        self._runtime_stop = threading.Event()
        self._host_tick_heartbeat = 0.0
        self._runtime_thread = threading.Thread(
            target=self._runtime_worker_loop,
            args=(generation,),
            name="GuangYaTransferAssistantRuntime",
            daemon=True,
        )
        self._runtime_thread.start()
        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【服务】内置运行时守护已启动；无需进入设置页再次保存，宿主服务未注册时自动接管",
        )

    def _runtime_worker_loop(self, generation: int) -> None:
        """热升级兜底：init_plugin 已执行但 MoviePilot 尚未重建公共服务时，自行维持检查链。"""
        stop = getattr(self, "_runtime_stop", None)
        if stop is None:
            return
        if stop.wait(1.5):
            return
        if generation != type(self)._runtime_generation or not self._enabled:
            return
        try:
            self._plugin_log("INFO", "【光鸭转存助手】【启动检查】内置守护开始首轮缓存检查")
            self._startup_check()
        except Exception as err:
            self._plugin_log("EXCEPTION", "【光鸭转存助手】【启动检查】内置守护首轮执行异常：%s", err)

        while self._enabled and generation == type(self)._runtime_generation:
            interval = max(60, int(self._refresh_minutes or 5) * 60)
            if stop.wait(interval):
                return
            if generation != type(self)._runtime_generation or not self._enabled:
                return
            heartbeat = float(getattr(self, "_host_tick_heartbeat", 0.0) or 0.0)
            if heartbeat and (time.monotonic() - heartbeat) < interval * 1.5:
                continue
            try:
                self._plugin_log(
                    "WARNING",
                    "【光鸭转存助手】【服务回退】未检测到宿主定时服务心跳，内置守护执行本轮检查；无需手动保存配置",
                )
                self._tick(host_service=False)
            except Exception as err:
                self._plugin_log("EXCEPTION", "【光鸭转存助手】【服务回退】内置守护执行异常：%s", err)

    def _startup_check(self) -> None:
        """启动后先消费本地索引，不等待首个 interval；随后再按游标做一次到期增量发现。"""
        cached = list(((self.get_data("channel_index") or {}).get("items") or []))
        self._plugin_log("INFO", "【光鸭转存助手】【启动检查】缓存索引=%s，固定转存订阅=%s", len(cached), len(self._selected_subscriptions))
        if self._auto_transfer_on_refresh and cached:
            self._inspect_cache.clear()
            self._process_selected_subscriptions(trigger="启动缓存检查", refresh_channel=False)
        before_new = int((self.get_data("channel_index") or {}).get("new_count") or 0)
        refreshed = self.refresh_channels(force=False)
        after_new = int((self.get_data("channel_index") or {}).get("new_count") or 0)
        if self._auto_transfer_on_refresh and refreshed and after_new > 0 and (not cached or after_new != before_new):
            self._inspect_cache.clear()
            self._process_selected_subscriptions(trigger="启动频道增量刷新", refresh_channel=False)

    def _tick(self, host_service: bool = True) -> None:
        if host_service:
            self._host_tick_heartbeat = time.monotonic()
            self._plugin_log("INFO", "【光鸭转存助手】【服务】宿主定时服务心跳已确认")
        self._install_takeover()
        items = self.refresh_channels(force=False)
        # 频道负责发现，缓存负责执行；Telegram 故障时已有分享仍可直接访问光鸭。
        self._inspect_cache.clear()
        if self._auto_transfer_on_refresh and items:
            self._process_selected_subscriptions(trigger="频道定时增量刷新", refresh_channel=False)

    def _process_selected_subscriptions(self, trigger: str = "后台检查", refresh_channel: bool = False) -> List[Dict[str, Any]]:
        """频道刷新后只检查活跃订阅；不会在后台刷新任务里主动触发原生下载。"""
        results: List[Dict[str, Any]] = []
        with self._route_lock:
            for sid in list(self._selected_subscriptions):
                subscribe = self._find_subscription(int(sid))
                if not subscribe:
                    continue
                if str(getattr(subscribe, "state", "") or "") not in ("N", "R"):
                    self._plugin_log("INFO", "【光鸭转存助手】【规则】%s #%s %s 当前状态=%s，后台不接管", trigger, sid, getattr(subscribe, "name", ""), getattr(subscribe, "state", ""))
                    results.append({"subscribe_id": int(sid), "success": False, "handled": False, "message": "非活跃订阅，已跳过"})
                    continue
                try:
                    result = self._try_transfer_subscription(subscribe, refresh_channel=refresh_channel)
                    results.append({"subscribe_id": int(sid), **result})
                    self._plugin_log("INFO", "【光鸭转存助手】【自动】%s #%s %s：%s", trigger, sid, getattr(subscribe, "name", ""), result.get("message") or "完成")
                except Exception as err:
                    self._plugin_log("EXCEPTION", "【光鸭转存助手】【自动】%s #%s 执行异常", trigger, sid)
                    results.append({"subscribe_id": int(sid), "success": False, "handled": False, "message": str(err)})
        return results

    def refresh_channels(self, force: bool = False) -> List[Dict[str, Any]]:
        """按频道消息游标增量抓取；首次建立历史索引，后续只读取游标之后的新消息。"""
        current = self.get_data("channel_index") or {}
        current_time = self._parse_datetime(current.get("time"))
        if not force and current_time and (datetime.datetime.now() - current_time).total_seconds() < self._refresh_minutes * 60:
            return list(current.get("items") or [])
        previous_items = list(current.get("items") or [])
        cursors = self.get_data("channel_cursors") or {}
        all_entries: List[Dict[str, Any]] = []
        errors: List[str] = []
        source_status: Dict[str, Any] = {}
        source_successes = 0
        total_new = 0
        urls = self._source_urls()
        for source_url in urls:
            label = "光鸭云盘影视热更频道" if "regeng" in source_url.lower() else "光鸭云盘资源分享频道"
            cursor_row = cursors.get(source_url) or {}
            try:
                last_message_id = int(cursor_row.get("last_message_id") or 0)
            except (TypeError, ValueError):
                last_message_id = 0
            queue = [source_url]
            visited = set()
            fetched_entries: List[Dict[str, Any]] = []
            new_entries: List[Dict[str, Any]] = []
            source_seen = set()
            page_errors: List[str] = []
            pages = 0
            button_count = 0
            button_links = 0
            visible_links = 0
            source_max_id = last_message_id
            reached_cursor = False
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
                    page_ids: List[int] = []
                    for item in found:
                        key = _entry_process_key(item) or _share_identity(item.get("share_url") or "")
                        if not key or key in source_seen:
                            continue
                        source_seen.add(key)
                        item["stale"] = False
                        item["cached_index"] = False
                        fetched_entries.append(item)
                        message_id = str(item.get("message_id") or "")
                        numeric_id = int(message_id) if message_id.isdigit() else 0
                        if numeric_id:
                            page_ids.append(numeric_id)
                            source_max_id = max(source_max_id, numeric_id)
                        if not last_message_id or not numeric_id or numeric_id > last_message_id:
                            new_entries.append(item)
                        style = str(item.get("link_style") or "")
                        if "按钮" in style or "包装" in style:
                            button_links += 1
                        if style == "明文链接":
                            visible_links += 1
                    # 一旦当前历史页已经全部落在旧游标以内，就不再继续请求更老页面。
                    if last_message_id and page_ids and max(page_ids) <= last_message_id:
                        reached_cursor = True
                    if not reached_cursor:
                        for next_url in _extract_pagination_urls(page_html, source_url):
                            if next_url not in visited and next_url not in queue and len(queue) < self._history_pages * 4:
                                queue.append(next_url)
                except Exception as err:
                    page_errors.append(f"{page_url}: {err}")
            unresolved = max(0, button_count - button_links)
            parse_suspect = bool(pages and button_count and not fetched_entries and unresolved)
            old_source = [dict(old) for old in previous_items if old.get("source_label") == label]
            if pages > 0 and not parse_suspect:
                source_successes += 1
                fetched_keys = {_entry_process_key(item) or _share_identity(item.get("share_url") or "") for item in fetched_entries}
                retained = 0
                all_entries.extend(fetched_entries)
                for old in old_source:
                    key = _entry_process_key(old) or _share_identity(old.get("share_url") or "")
                    if not key or key in fetched_keys:
                        continue
                    old["stale"] = False
                    old["cached_index"] = True
                    all_entries.append(old)
                    retained += 1
                if source_max_id > last_message_id:
                    cursors[source_url] = {
                        "last_message_id": source_max_id,
                        "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                total_new += len(new_entries)
                source_status[label] = {
                    "success": True, "pages": pages, "count": len(fetched_entries) + retained,
                    "new_count": len(new_entries), "retained_count": retained,
                    "cursor": source_max_id or last_message_id, "reached_cursor": reached_cursor,
                    "button_links": button_links, "visible_links": visible_links,
                    "unresolved_buttons": unresolved, "errors": page_errors,
                }
            else:
                preserved = 0
                for old in old_source:
                    old["stale"] = True
                    old["cached_index"] = True
                    all_entries.append(old)
                    preserved += 1
                reason = "页面存在查看资源按钮但未解析出分享链接" if parse_suspect else ("；".join(page_errors[:3]) or "频道未返回有效页面")
                errors.append(f"{label}: {reason}")
                source_status[label] = {
                    "success": False, "pages": pages, "count": preserved,
                    "new_count": 0, "retained_count": preserved, "cursor": last_message_id,
                    "button_links": button_links, "visible_links": visible_links,
                    "unresolved_buttons": unresolved, "errors": page_errors or [reason],
                }
                if parse_suspect:
                    self._plugin_log("WARNING", "【光鸭转存助手】【频道】%s 检测到 %s 个查看资源按钮但未解析到光鸭 URL，使用故障回退索引", label, unresolved)

        self.save_data("channel_cursors", cursors)
        # 当前抓取优先，其次保留索引，故障回退最后；新消息即使复用旧链接仍保留。
        all_entries.sort(key=lambda item: (
            1 if item.get("stale") else 0,
            1 if item.get("cached_index") else 0,
            int(item.get("priority") or 0),
            -int(item.get("message_id") or 0) if str(item.get("message_id") or "").isdigit() else 0,
        ))
        entries: List[Dict[str, Any]] = []
        seen = set()
        for item in all_entries:
            key = _entry_process_key(item) or _share_identity(item.get("share_url") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            entries.append(item)
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        all_failed = source_successes == 0
        partial_stale = source_successes < len(urls)
        payload = {
            "time": now, "items": entries[:2000], "errors": errors,
            "source_status": source_status, "new_count": total_new,
        }
        self.save_data("channel_index", payload)
        self.save_data("last_run", {
            "success": bool(source_successes), "time": now, "count": len(entries), "new_count": total_new, "errors": errors,
            "stale_index": all_failed, "partial_stale": partial_stale,
        })
        fetched_count = len([item for item in entries if not item.get("stale") and not item.get("cached_index")])
        retained_count = len([item for item in entries if not item.get("stale") and item.get("cached_index")])
        stale_count = len(entries) - fetched_count - retained_count
        self._plugin_log("INFO", "【光鸭转存助手】频道增量刷新完成，索引 %s 个（本轮新增 %s / 当前抓取 %s / 保留索引 %s / 故障回退 %s），错误 %s 个", len(entries), total_new, fetched_count, retained_count, stale_count, len(errors))
        return entries

    def _source_urls(self) -> List[str]:
        values = [line.strip() for line in re.split(r"[\r\n]+", self._channel_urls or "") if line.strip()]
        return values or list(DEFAULT_CHANNEL_URLS)

    @staticmethod
    def _subscription_episode_progress(subscribe: Any) -> Tuple[int, int, int]:
        """按 MoviePilot note 与目标集范围计算已完成、目标和剩余集数。"""
        media_type = str(getattr(subscribe, "type", "") or "").lower()
        if "tv" not in media_type and "电视剧" not in str(getattr(subscribe, "type", "") or "") and getattr(subscribe, "season", None) in (None, 0):
            return 0, 0, 0
        try:
            start = max(1, int(getattr(subscribe, "start_episode", 0) or 1))
            total = int(getattr(subscribe, "total_episode", 0) or 0)
        except (TypeError, ValueError):
            return 0, 0, 0
        if total < start:
            return 0, 0, 0
        target = set(range(start, total + 1))
        done = set()
        for value in (getattr(subscribe, "note", None) or []):
            try:
                episode = int(value)
            except (TypeError, ValueError):
                continue
            if episode in target:
                done.add(episode)
        return len(done), len(target), len(target - done)

    def _subscription_options(self) -> List[Dict[str, Any]]:
        options = []
        selected = set(self._selected_subscriptions)
        for sub in self._list_subscriptions(None):
            sid = int(getattr(sub, "id", 0) or 0)
            state = str(getattr(sub, "state", "") or "")
            if not sid or (state not in ("N", "R") and sid not in selected):
                continue
            season = getattr(sub, "season", None)
            suffix = f" S{int(season):02d}" if season not in (None, "") else ""
            state_label = {"N": "新建", "R": "订阅中", "P": "待定", "S": "暂停"}.get(state, state or "-")
            media_type = str(getattr(sub, "type", "") or "").strip() or "媒体"
            done, total, lack = self._subscription_episode_progress(sub)
            progress = f" · 已完成 {done}/{total} · 剩余 {lack}" if total else ""
            options.append({"title": f"{sub.name} ({getattr(sub, 'year', '') or '-'}){suffix} · {media_type} · {state_label}{progress} · #{sid}", "value": sid})
        return options

    def _list_subscriptions(self, state: Optional[str] = "N,R") -> List[Any]:
        try:
            return list(SubscribeOper().list(state) or [])
        except Exception as err:
            self._plugin_log("WARNING", "【光鸭转存助手】读取 MoviePilot 订阅失败: %s", err)
            return []

    def _find_subscription(self, sid: int) -> Optional[Any]:
        try:
            return SubscribeOper().get(int(sid))
        except Exception as err:
            self._plugin_log("WARNING", "【光鸭转存助手】读取订阅 #%s 失败: %s", sid, err)
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

    def _save_config(self) -> None:
        self.update_config({
            "enabled": self._enabled,
            "channel_urls": self._channel_urls,
            "selected_subscriptions": self._selected_subscriptions,
            "save_path": self._save_path,
            "create_media_folder": self._create_media_folder,
            "notify": self._notify,
            "daily_summary": self._daily_summary,
            "summary_cron": self._summary_cron,
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
            "protect_ongoing": self._protect_ongoing,
            "ongoing_guard_days": self._ongoing_guard_days,
            "clear_inventory": False,
        })

    @staticmethod
    def _subscription_missing_episodes(subscribe: Any) -> List[int]:
        """返回 MoviePilot 当前目标范围中尚未完成的真实集号。"""
        try:
            start = max(1, int(getattr(subscribe, "start_episode", 0) or 1))
            total = int(getattr(subscribe, "total_episode", 0) or 0)
        except (TypeError, ValueError):
            return []
        if total < start:
            return []
        done = set()
        for value in (getattr(subscribe, "note", None) or []):
            try:
                done.add(int(value))
            except (TypeError, ValueError):
                continue
        return sorted(set(range(start, total + 1)) - done)

    def _channel_state_for_subscription(self, subscribe: Any, entries: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """汇总该订阅所有新鲜频道消息的连载/总集/完结状态。"""
        entries = list(entries if entries is not None else ((self.get_data("channel_index") or {}).get("items") or []))
        states = []
        for entry in entries:
            if entry.get("stale"):
                continue
            matched, _ = _entry_match_reason(entry, subscribe)
            if matched:
                states.append(_entry_serial_state(entry))
        return {
            "explicit_total": max([int(item.get("explicit_total") or 0) for item in states] or [0]),
            "current_episode": max([int(item.get("current_episode") or 0) for item in states] or [0]),
            "complete": any(bool(item.get("complete")) for item in states),
            "ongoing": any(bool(item.get("ongoing")) for item in states),
            "matched": len(states),
        }

    def _sync_channel_episode_floor(self, subscribe: Any, channel_state: Dict[str, Any]) -> bool:
        """频道明确的全N集或更新至N集只向上扩展 MoviePilot 目标，绝不向下缩减。"""
        sid = int(getattr(subscribe, "id", 0) or 0)
        try:
            current_total = int(getattr(subscribe, "total_episode", 0) or 0)
        except (TypeError, ValueError):
            current_total = 0
        floor = max(int(channel_state.get("explicit_total") or 0), int(channel_state.get("current_episode") or 0))
        if not sid or floor <= current_total:
            return False
        done = set()
        for value in (getattr(subscribe, "note", None) or []):
            try:
                done.add(int(value))
            except (TypeError, ValueError):
                continue
        try:
            start = max(1, int(getattr(subscribe, "start_episode", 0) or 1))
        except (TypeError, ValueError):
            start = 1
        lack = len(set(range(start, floor + 1)) - done)
        SubscribeOper().update(sid, {"total_episode": floor, "lack_episode": lack})
        setattr(subscribe, "total_episode", floor)
        setattr(subscribe, "lack_episode", lack)
        self._plugin_log("INFO", 
            "【光鸭转存助手】【追更】#%s %s 频道进度把目标总集数由 %s 向上校正为 %s，剩余 %s 集",
            sid, getattr(subscribe, "name", ""), current_total, floor, lack,
        )
        return True

    def _clear_completion_guard(self, sid: int) -> None:
        guards = self.get_data("completion_guard") or {}
        if str(sid) in guards:
            guards.pop(str(sid), None)
            self.save_data("completion_guard", guards)

    def _completion_guard_allows(self, subscribe: Any, channel_state: Optional[Dict[str, Any]] = None) -> bool:
        """当前集齐但仍标记连载时延迟完成，防止总集数后续继续增长。"""
        if not self._protect_ongoing:
            return True
        sid = int(getattr(subscribe, "id", 0) or 0)
        if not sid:
            return False
        if bool(getattr(subscribe, "manual_total_episode", False)):
            self._clear_completion_guard(sid)
            return True
        state = channel_state or self._channel_state_for_subscription(subscribe)
        explicit_total = int(state.get("explicit_total") or 0)
        if bool(state.get("complete")) or explicit_total > 0:
            self._clear_completion_guard(sid)
            return True
        if not bool(state.get("ongoing")):
            self._clear_completion_guard(sid)
            return True

        done, total, lack = self._subscription_episode_progress(subscribe)
        if not total or lack > 0:
            self._clear_completion_guard(sid)
            return False
        guards = self.get_data("completion_guard") or {}
        key = str(sid)
        now = datetime.datetime.now()
        row = guards.get(key) or {}
        if int(row.get("total") or 0) != total or int(row.get("done") or 0) != done:
            row = {"total": total, "done": done, "since": now.strftime("%Y-%m-%d %H:%M:%S")}
            guards[key] = row
            self.save_data("completion_guard", guards)
        since = self._parse_datetime(row.get("since")) or now
        elapsed_days = max(0.0, (now - since).total_seconds() / 86400)
        if elapsed_days < self._ongoing_guard_days:
            self._plugin_log("INFO", 
                "【光鸭转存助手】【连载保护】#%s %s 当前 %s/%s 已齐，但频道仍标记更新中；已稳定 %.1f/%s 天，暂不完成订阅",
                sid, getattr(subscribe, "name", ""), done, total, elapsed_days, self._ongoing_guard_days,
            )
            return False
        self._plugin_log("INFO", 
            "【光鸭转存助手】【连载保护】#%s %s 当前 %s/%s 已连续稳定 %.1f 天且未发现新集，允许完成订阅",
            sid, getattr(subscribe, "name", ""), done, total, elapsed_days,
        )
        return True

    def _ensure_data_schema(self) -> None:
        meta = self.get_data("data_meta") or {}
        try:
            version = int(meta.get("schema_version") or 0)
        except (TypeError, ValueError):
            version = 0
        if version >= self._data_schema_version:
            return
        if version < 6:
            records = self.get_data("processed_entries") or {}
            before = len(records)
            records = {key: row for key, row in records.items() if str((row or {}).get("status") or "") != "no_new_episode"}
            if len(records) != before:
                self.save_data("processed_entries", records)
                self._plugin_log("INFO", "【光鸭转存助手】【迁移】重新开放 %s 条旧 no_new_episode 记录，使用新版文件名解析重新检查", before - len(records))
        # v6 保留既有媒体事实/任务；仅重新评估旧版可能误判的 no_new_episode 消息。
        self.save_data("data_meta", {
            "schema_version": self._data_schema_version,
            "migrated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        # 进程异常退出留下的执行锁不跨版本继承。
        self.save_data("active_runs", {})
        self._plugin_log("INFO", "【光鸭转存助手】【迁移】持久数据结构升级到 v%s", self._data_schema_version)

    def _media_fact_prefix(self, subscribe: Any) -> str:
        source_value = getattr(subscribe, "media_source", None)
        source_value = getattr(source_value, "value", source_value)
        source = re.sub(r"[^0-9A-Za-z_-]+", "", str(source_value or "").lower()) or "title"
        media_id = str(getattr(subscribe, "media_id", None) or "").strip()
        if not media_id:
            title = _normalize_media_text(getattr(subscribe, "name", "") or "unknown") or "unknown"
            year = str(getattr(subscribe, "year", "") or "-")
            media_id = f"{title}:{year}"
            source = "title"
        raw_type = str(getattr(subscribe, "type", "") or "")
        is_movie = "movie" in raw_type.lower() or "电影" in raw_type
        if is_movie:
            return f"{source}:{media_id}:movie"
        try:
            raw_season = getattr(subscribe, "season", None)
            season = 1 if raw_season in (None, "") else max(0, int(raw_season))
        except (TypeError, ValueError):
            season = 1
        return f"{source}:{media_id}:s{season:02d}"

    def _media_fact_keys_for_item(self, subscribe: Any, item: Dict[str, Any]) -> List[str]:
        path = str(item.get("effective_path") or item.get("relative_path") or item.get("path") or item.get("name") or "")
        if not _is_video(path):
            return []
        prefix = self._media_fact_prefix(subscribe)
        if self._is_movie_subscription(subscribe):
            return [prefix]
        wanted_season = getattr(subscribe, "season", None)
        file_season, episodes = _episode_numbers(path)
        if wanted_season not in (None, ""):
            try:
                wanted_value = int(wanted_season)
            except (TypeError, ValueError):
                wanted_value = None
            if wanted_value is not None:
                if file_season is not None and file_season != wanted_value:
                    return []
                if wanted_value == 0 and file_season is None:
                    return []
        return [f"{prefix}:e{int(ep):04d}" for ep in episodes]

    def _remember_media_facts(self, subscribe: Any, items: List[Dict[str, Any]], origin: str = "transfer") -> int:
        facts = self.get_data("media_facts") or {}
        changed = 0
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for item in items:
            path = str(item.get("effective_path") or item.get("relative_path") or item.get("path") or item.get("name") or "")
            for key in self._media_fact_keys_for_item(subscribe, item):
                if key in facts:
                    continue
                facts[key] = {
                    "time": now, "origin": origin, "path": path,
                    "size": int(item.get("size") or 0), "digest": str(item.get("digest") or ""),
                }
                changed += 1
        if changed:
            if len(facts) > 50000:
                ordered = sorted(facts.items(), key=lambda pair: str((pair[1] or {}).get("time") or ""), reverse=True)[:50000]
                facts = dict(ordered)
            self.save_data("media_facts", facts)
        return changed

    def _remember_episode_facts(self, subscribe: Any, episodes: Iterable[int], origin: str = "library") -> int:
        prefix = self._media_fact_prefix(subscribe)
        facts = self.get_data("media_facts") or {}
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        changed = 0
        for episode in episodes:
            try:
                episode = int(episode)
            except (TypeError, ValueError):
                continue
            key = f"{prefix}:e{episode:04d}"
            if key in facts:
                continue
            facts[key] = {"time": now, "origin": origin, "path": f"E{episode:04d}"}
            changed += 1
        if changed:
            self.save_data("media_facts", facts)
        return changed

    def _semantic_fact_exists(self, subscribe: Any, item: Dict[str, Any]) -> bool:
        keys = self._media_fact_keys_for_item(subscribe, item)
        if not keys:
            return False
        facts = self.get_data("media_facts") or {}
        return all(key in facts for key in keys)

    def _sync_media_facts_from_inventory(self, subscribe: Any) -> None:
        sid = str(int(getattr(subscribe, "id", 0) or 0))
        assets = (((self.get_data("transfer_inventory") or {}).get(sid) or {}).get("assets") or {})
        items = []
        for row in assets.values():
            if not isinstance(row, dict):
                continue
            path = str(row.get("path") or "")
            if path:
                items.append({"path": path, "size": row.get("size") or 0, "digest": row.get("digest") or ""})
        if items:
            self._remember_media_facts(subscribe, items, origin="inventory_migration")

    def _sync_media_facts_progress(self, subscribe: Any) -> int:
        if self._is_movie_subscription(subscribe):
            return 0
        sid = int(getattr(subscribe, "id", 0) or 0)
        if not sid:
            return 0
        prefix = self._media_fact_prefix(subscribe) + ":e"
        facts = self.get_data("media_facts") or {}
        episodes = set()
        for key in facts.keys():
            if not str(key).startswith(prefix):
                continue
            suffix = str(key)[len(prefix):]
            if suffix.isdigit():
                episodes.add(int(suffix))
        if not episodes:
            return 0
        current = set()
        for value in (getattr(subscribe, "note", None) or []):
            try:
                current.add(int(value))
            except (TypeError, ValueError):
                continue
        merged = current | episodes
        try:
            start = max(1, int(getattr(subscribe, "start_episode", 0) or 1))
            total = int(getattr(subscribe, "total_episode", 0) or 0)
        except (TypeError, ValueError):
            total = 0
            start = 1
        if total >= start:
            target = set(range(start, total + 1))
            episodes = episodes.intersection(target)
            merged = current | episodes
        payload: Dict[str, Any] = {"note": sorted(merged)}
        if total >= start:
            payload["lack_episode"] = len(target - merged)
        if merged != current or ("lack_episode" in payload and int(getattr(subscribe, "lack_episode", payload["lack_episode"]) or 0) != payload["lack_episode"]):
            SubscribeOper().update(sid, payload)
            setattr(subscribe, "note", sorted(merged))
            if "lack_episode" in payload:
                setattr(subscribe, "lack_episode", payload["lack_episode"] )
            self._plugin_log("INFO", "【光鸭转存助手】【事实同步】#%s %s 从跨订阅媒体事实恢复 %s 个已完成集", sid, getattr(subscribe, "name", ""), len(episodes))
        return len(episodes)

    def _processed_entry_key(self, entry: Dict[str, Any], subscribe: Any = None) -> str:
        entry_key = _entry_process_key(entry)
        if not entry_key:
            return ""
        if subscribe is None:
            return entry_key
        raw = f"{self._media_fact_prefix(subscribe)}|{entry_key}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _entry_processed(self, entry: Dict[str, Any], subscribe: Any = None) -> bool:
        key = self._processed_entry_key(entry, subscribe)
        return bool(key and (self.get_data("processed_entries") or {}).get(key))

    def _mark_entry_processed(self, entry: Dict[str, Any], status: str, message: str = "", subscribe: Any = None) -> None:
        key = self._processed_entry_key(entry, subscribe)
        if not key:
            return
        records = self.get_data("processed_entries") or {}
        records[key] = {
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": str(status or "processed"),
            "message": str(message or "")[:300],
            "share_id": str(entry.get("share_id") or ""),
            "message_id": str(entry.get("message_id") or ""),
            "source": str(entry.get("source_label") or entry.get("source_url") or ""),
            "media": self._media_fact_prefix(subscribe) if subscribe is not None else "",
        }
        if len(records) > 10000:
            ordered = sorted(records.items(), key=lambda pair: str((pair[1] or {}).get("time") or ""), reverse=True)[:10000]
            records = dict(ordered)
        self.save_data("processed_entries", records)

    def _job_key(self, subscribe: Any, entry: Dict[str, Any]) -> str:
        raw = f"{self._media_fact_prefix(subscribe)}|{_entry_process_key(entry)}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _set_job_state(self, job_key: str, status: str, **fields: Any) -> None:
        if not job_key:
            return
        jobs = self.get_data("transfer_jobs") or {}
        row = dict(jobs.get(job_key) or {})
        row.update(fields)
        row["status"] = status
        row["updated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        jobs[job_key] = row
        if len(jobs) > 2000:
            ordered = sorted(jobs.items(), key=lambda pair: str((pair[1] or {}).get("updated") or ""), reverse=True)[:2000]
            jobs = dict(ordered)
        self.save_data("transfer_jobs", jobs)

    def _get_job_state(self, job_key: str) -> Dict[str, Any]:
        return dict((self.get_data("transfer_jobs") or {}).get(job_key) or {})

    def _acquire_subscription_run(self, subscribe: Any) -> Tuple[str, str]:
        lock_key = self._media_fact_prefix(subscribe)
        sid = int(getattr(subscribe, "id", 0) or 0)
        now = datetime.datetime.now()
        token = hashlib.sha256(f"{lock_key}|{sid}|{threading.get_ident()}|{time.time_ns()}".encode("utf-8")).hexdigest()[:24]
        with self._state_lock:
            runs = self.get_data("active_runs") or {}
            row = runs.get(lock_key) or {}
            updated = self._parse_datetime(row.get("updated"))
            if updated and (now - updated).total_seconds() < self._run_lock_minutes * 60:
                return "", lock_key
            if row:
                self._plugin_log("WARNING", "【光鸭转存助手】【恢复】%s 检测到过期执行锁，已自动接管恢复", lock_key)
            runs[lock_key] = {
                "token": token, "subscribe_id": sid, "updated": now.strftime("%Y-%m-%d %H:%M:%S")
            }
            self.save_data("active_runs", runs)
        return token, lock_key

    def _release_subscription_run(self, lock_key: str, token: str) -> None:
        if not lock_key or not token:
            return
        with self._state_lock:
            runs = self.get_data("active_runs") or {}
            row = runs.get(lock_key) or {}
            if row.get("token") != token:
                return
            runs.pop(lock_key, None)
            self.save_data("active_runs", runs)

    def _sync_media_library_progress(self, subscribe: Any) -> Dict[str, Any]:
        """以 MoviePilot 媒体库为事实源补齐 note/lack_episode，避免重复转存已入库剧集。"""
        sid = int(getattr(subscribe, "id", 0) or 0)
        raw_type = str(getattr(subscribe, "type", "") or "")
        media_type = raw_type.lower()
        raw_season = getattr(subscribe, "season", None)
        is_tv = "tv" in media_type or "电视剧" in raw_type or raw_season not in (None, "")
        if not sid or not is_tv:
            return {"success": True, "existing": [], "missing": []}
        if raw_season in (None, ""):
            return {"success": False, "existing": [], "missing": []}
        try:
            season = int(raw_season)
            start = max(1, int(getattr(subscribe, "start_episode", 0) or 1))
            total = int(getattr(subscribe, "total_episode", 0) or 0)
        except (TypeError, ValueError):
            return {"success": False, "existing": [], "missing": []}
        # Season 0 是 MoviePilot 合法的特别篇季；只有负季号或无有效目标集时拒绝同步。
        if season < 0 or total < start:
            return {"success": False, "existing": [], "missing": []}
        target = set(range(start, total + 1))
        try:
            meta = build_subscribe_meta(subscribe)
            mediainfo = MediaChain().recognize_media(
                meta=meta,
                mtype=meta.type,
                media_source=getattr(subscribe, "media_source", None),
                media_id=getattr(subscribe, "media_id", None),
                episode_group=getattr(subscribe, "episode_group", None),
                cache=False,
            )
            if not mediainfo:
                return {"success": False, "existing": [], "missing": sorted(target)}
            complete, no_exists = DownloadChain().get_no_exists_info(
                meta=meta,
                mediainfo=mediainfo,
                totals={season: total},
            )
            library_existing = set()
            if complete:
                library_existing = set(target)
            elif no_exists:
                season_detail = None
                for season_map in no_exists.values():
                    if not isinstance(season_map, dict):
                        continue
                    season_detail = season_map.get(season)
                    if season_detail is None:
                        season_detail = season_map.get(str(season))
                    if season_detail is not None:
                        break
                if season_detail is None:
                    library_existing = set(target)
                else:
                    missing_values = getattr(season_detail, "episodes", None)
                    if missing_values is None and isinstance(season_detail, dict):
                        missing_values = season_detail.get("episodes")
                    if missing_values:
                        missing_set = {int(value) for value in missing_values if str(value).isdigit()}
                        library_existing = target.difference(missing_set)
                    else:
                        library_existing = set()
            self._remember_episode_facts(subscribe, library_existing, origin="library")
            current = set()
            for value in (getattr(subscribe, "note", None) or []):
                try:
                    current.add(int(value))
                except (TypeError, ValueError):
                    continue
            merged = current | library_existing
            lack = len(target.difference(merged))
            current_lack = int(getattr(subscribe, "lack_episode", lack) or 0)
            if merged != current or current_lack != lack:
                SubscribeOper().update(sid, {"note": sorted(merged), "lack_episode": lack})
                setattr(subscribe, "note", sorted(merged))
                setattr(subscribe, "lack_episode", lack)
                self._plugin_log("INFO", 
                    "【光鸭转存助手】【媒体库同步】#%s %s 已从媒体库确认 %s 集；订阅进度 %s/%s，剩余 %s",
                    sid, getattr(subscribe, "name", ""), len(library_existing), len(target.intersection(merged)), len(target), lack,
                )
            return {"success": True, "existing": sorted(library_existing), "missing": sorted(target.difference(merged))}
        except Exception as err:
            self._plugin_log("WARNING", "【光鸭转存助手】【媒体库同步】#%s %s 同步失败：%s", sid, getattr(subscribe, "name", ""), err)
            return {"success": False, "existing": [], "missing": sorted(target)}

    def _install_takeover(self) -> None:
        """只接管订阅搜索任务；未选择的订阅仍调用原生 SubscribeChain.search。"""
        if not self._enabled:
            return
        try:
            from app.scheduler import Scheduler
            scheduler = Scheduler.get_existing_instance()
            jobs = getattr(scheduler, "_jobs", None) if scheduler else None
            jobs = jobs or {}
            for job_id in ("subscribe_search", "new_subscribe_search"):
                job = jobs.get(job_id)
                if not job:
                    continue
                current = job.get("func")
                if getattr(current, "__self__", None) is self:
                    continue
                self._takeover_originals.setdefault(job_id, current)
                job["func"] = self._dispatch_subscribe_search
        except Exception as err:
            self._plugin_log("WARNING", "【光鸭转存助手】安装订阅分流失败: %s", err)

    def _restore_takeover(self) -> None:
        originals = dict(self._takeover_originals or {})
        if not originals:
            return
        try:
            from app.scheduler import Scheduler
            scheduler = Scheduler.get_existing_instance()
            jobs = getattr(scheduler, "_jobs", None) if scheduler else None
            jobs = jobs or {}
            for job_id, original in originals.items():
                job = jobs.get(job_id)
                current = job.get("func") if job else None
                if job and getattr(current, "__self__", None) is self:
                    job["func"] = original
        except Exception as err:
            self._plugin_log("WARNING", "【光鸭转存助手】恢复原生订阅搜索失败: %s", err)
        finally:
            self._takeover_originals = {}

    def _dispatch_subscribe_search(self, sid: Optional[int] = None, state: Optional[str] = "R", manual: Optional[bool] = False, progress_callback=None):
        """固定分流：已勾选只转存，未勾选只走 MoviePilot 原生下载。"""
        with self._route_lock:
            selected = set(self._selected_subscriptions)
            if sid:
                if int(sid) not in selected:
                    return SubscribeChain().search(sid=sid, state=state, manual=manual, progress_callback=progress_callback)
                subscribe = self._find_subscription(int(sid))
                if not subscribe:
                    self._plugin_log("WARNING", "【光鸭转存助手】【分流】已勾选订阅 #%s 不存在；固定转存路线不触发原生下载", sid)
                    return True
                result = self._try_transfer_subscription(subscribe)
                self._plugin_log("INFO", "【光鸭转存助手】【分流】#%s %s 固定转存处理：%s", sid, getattr(subscribe, "name", ""), result.get("message") or "完成")
                return True

            subscriptions = self._list_subscriptions(state or "N,R")
            for index, subscribe in enumerate(subscriptions):
                subscribe_id = int(getattr(subscribe, "id", 0) or 0)
                if not subscribe_id:
                    continue
                callback = progress_callback if index == 0 else None
                if subscribe_id in selected:
                    result = self._try_transfer_subscription(subscribe)
                    self._plugin_log("INFO", "【光鸭转存助手】【分流】#%s %s 固定转存处理：%s", subscribe_id, getattr(subscribe, "name", ""), result.get("message") or "完成")
                    continue
                SubscribeChain().search(sid=subscribe_id, state=None, manual=manual, progress_callback=callback)
            return True

    def _subscription_static_guard(self, subscribe: Any) -> Tuple[bool, str]:
        state = str(getattr(subscribe, "state", "") or "")
        if state not in ("N", "R"):
            return False, f"订阅状态 {state or '-'} 非活跃"
        if bool(getattr(subscribe, "best_version", 0)):
            return False, "洗版订阅不支持固定转存；如需原生处理请取消勾选"
        mtype = str(getattr(subscribe, "type", "") or "").lower()
        if mtype and not any(token in mtype for token in ("tv", "movie", "电视剧", "电影")):
            return False, f"媒体类型 {getattr(subscribe, 'type', '')} 不适合网盘影视转存"
        if self._strict_subscription_rules:
            if getattr(subscribe, "filter_groups", None):
                return False, "存在复杂过滤规则组；如需原生处理请取消勾选"
            if str(getattr(subscribe, "filter", "") or "").strip():
                return False, "存在复杂过滤规则；如需原生处理请取消勾选"
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

    def _try_transfer_subscription(self, subscribe: Any, force: bool = False, refresh_channel: bool = True) -> Dict[str, Any]:
        token, lock_key = self._acquire_subscription_run(subscribe)
        if not token:
            self._plugin_log("INFO", "【光鸭转存助手】【并发】#%s %s 已有同媒体转存任务执行中，本次跳过", getattr(subscribe, "id", 0), getattr(subscribe, "name", ""))
            return {"success": True, "handled": True, "busy": True, "message": "已有同媒体转存任务执行中"}
        try:
            return self._try_transfer_subscription_inner(subscribe, force=force, refresh_channel=refresh_channel)
        finally:
            self._release_subscription_run(lock_key, token)

    def _try_transfer_subscription_inner(self, subscribe: Any, force: bool = False, refresh_channel: bool = True) -> Dict[str, Any]:
        """对一个活跃订阅执行安全匹配、规则校验、文件级去重和增量转存。"""
        sid = int(getattr(subscribe, "id", 0) or 0)
        allowed, guard_reason = self._subscription_static_guard(subscribe)
        if not allowed:
            self._plugin_log("INFO", "【光鸭转存助手】【规则】#%s %s 不接管：%s", sid, getattr(subscribe, "name", ""), guard_reason)
            return {"success": False, "handled": True, "message": guard_reason}
        if refresh_channel:
            self.refresh_channels(force=False)
        # 先把旧版库存迁移成媒体语义事实，再同步事实和 MoviePilot 媒体库。
        self._sync_media_facts_from_inventory(subscribe)
        self._sync_media_facts_progress(subscribe)
        # 每轮先以媒体库为事实源同步当前目标范围，频道没有新链接时也能去掉已入库重复集。
        self._sync_media_library_progress(subscribe)
        entries = list((self.get_data("channel_index") or {}).get("items") or [])
        pre_channel_state = self._channel_state_for_subscription(subscribe, entries)
        if self._finish_subscription_if_complete(subscribe, channel_state=pre_channel_state):
            media_kind = "电影" if self._is_movie_subscription(subscribe) else "剧集"
            return {"success": True, "handled": True, "completed": True, "message": f"{media_kind}目标已完成，订阅已移入历史"}
        matched_pairs = []
        fallback_cache_matches = 0
        for item in entries:
            matched, reason = _entry_match_reason(item, subscribe)
            if not matched:
                continue
            if item.get("stale"):
                fallback_cache_matches += 1
            matched_pairs.append((item, reason))
        if not matched_pairs:
            detail = "本地频道索引暂未匹配到光鸭分享"
            self._plugin_log("INFO", "【光鸭转存助手】【匹配】#%s %s %s；固定转存路线不触发原生下载", sid, getattr(subscribe, "name", ""), detail)
            return {"success": False, "handled": True, "message": detail}
        self._plugin_log("INFO", "【光鸭转存助手】【匹配】#%s %s 命中 %s 个缓存/当前分享", sid, getattr(subscribe, "name", ""), len(matched_pairs))
        if fallback_cache_matches:
            self._plugin_log(
                "WARNING", "【光鸭转存助手】【缓存回退】#%s %s 有 %s 个分享来自 Telegram 故障缓存；频道不可用不阻断已知光鸭链接转存",
                sid, getattr(subscribe, "name", ""), fallback_cache_matches,
            )

        channel_state = self._channel_state_for_subscription(subscribe, [item for item, _ in matched_pairs])
        if self._sync_channel_episode_floor(subscribe, channel_state):
            # 频道把目标集数向上扩展后，再同步一次媒体库新扩展区间。
            self._sync_media_library_progress(subscribe)
        # 兼容旧版本已经 N/N、剩余0 但尚未完成的记录；连载保护在这里统一判断。
        if self._finish_subscription_if_complete(subscribe, channel_state=channel_state):
            return {"success": True, "handled": True, "completed": True, "message": "目标剧集已全部完成，订阅已移入历史"}

        action_pairs = []
        processed_matches = 0
        for entry, reason in matched_pairs:
            if not force and self._entry_processed(entry, subscribe):
                processed_matches += 1
                continue
            action_pairs.append((entry, reason))
        if not action_pairs:
            done, total, lack = self._subscription_episode_progress(subscribe)
            self._plugin_log("INFO", 
                "【光鸭转存助手】【消息去重】#%s %s 当前没有新链接/新消息，跳过已处理 %s 条；进度 %s/%s，剩余 %s",
                sid, getattr(subscribe, "name", ""), processed_matches, done, total, lack,
            )
            return {"success": True, "handled": True, "already": True, "message": f"没有新链接/新消息；已处理记录不重复测试，进度 {done}/{total}，剩余 {lack}" if total else "没有新链接/新消息；已处理记录不重复测试"}

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
        pending_verification = False
        match_reasons = set()
        target_path = self._target_path(subscribe)

        for entry, match_reason in action_pairs[:20]:
            share_url = entry.get("share_url") or ""
            share_key = _share_identity(share_url)
            if not share_key:
                continue
            probe = self._inspect_share(share_url)
            if not probe.get("success"):
                error = str(probe.get("message") or "分享读取失败")
                self._plugin_log("WARNING", "【光鸭转存助手】【匹配】分享读取失败 share_id=%s：%s", share_key.split("|", 1)[0], error)
                errors.append(error)
                continue
            resource_allowed, resource_reason = self._subscription_resource_allowed(subscribe, entry, probe)
            if not resource_allowed:
                self._plugin_log("INFO", "【光鸭转存助手】【规则】#%s %s share_id=%s 跳过并记为已处理：%s", sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0], resource_reason)
                self._mark_entry_processed(entry, "filtered", resource_reason, subscribe)
                synchronized_match = True
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
                    self._plugin_log("INFO", "【光鸭转存助手】【重试】#%s %s share_id=%s 仍在失败退避期", sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0])
                    continue

            stats: Dict[str, int] = {}
            planned = self._plan_incremental_files(probe, assets, subscribe=subscribe, target_path=target_path, stats=stats)
            valid_route_match = True
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【分享解析】#%s %s share_id=%s 节点=%s 叶子=%s 视频=%s 字幕=%s 可用=%s 未识别集号=%s 推断集号=%s",
                sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0], probe.get("file_count") or 0, probe.get("leaf_count") or 0,
                stats.get("video", 0), stats.get("subtitle", 0), stats.get("eligible", 0), stats.get("unparsed", 0), stats.get("inferred", 0),
            )
            job_key = self._job_key(subscribe, entry)
            planned, inflight_held = self._filter_inflight_planned_items(subscribe, planned, exclude_job_key=job_key)
            if inflight_held:
                pending_verification = True
                self._plugin_log("INFO", 
                    "【光鸭转存助手】【在途去重】#%s %s share_id=%s 新消息中 %s 个文件/剧集已被其它待落盘任务占用，本轮不重复提交",
                    sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0], len(inflight_held),
                )
            if stats.get("eligible", 0) <= 0:
                if stats.get("unparsed", 0):
                    samples = "、".join(str(value) for value in (stats.get("unparsed_paths") or [])[:8])
                    message = f"分享内有 {stats.get('unparsed', 0)} 个媒体/字幕文件无法解析集号，未标记为已处理；示例：{samples or '-'}"
                    errors.append(message)
                    self._plugin_log("WARNING", "【光鸭转存助手】【文件识别】#%s %s share_id=%s %s", sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0], message)
                    continue
                if self._media_only and stats.get("total", 0) > 0 and not stats.get("video", 0) and not stats.get("subtitle", 0):
                    samples = "、".join(str(value) for value in (stats.get("unsupported_paths") or [])[:8])
                    message = f"分享已读取 {stats.get('total', 0)} 个叶子文件，但没有识别到支持的视频/字幕扩展名；示例：{samples or '-'}"
                    errors.append(message)
                    self._plugin_log("WARNING", "【光鸭转存助手】【文件识别】#%s %s share_id=%s %s", sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0], message)
                    continue
                message = "分享内没有需要的新剧集；已入库/已完成/范围外内容不再重复测试"
                self._mark_entry_processed(entry, "no_new_episode", message, subscribe)
                synchronized_match = True
                self._plugin_log("INFO", "【光鸭转存助手】【消息去重】#%s %s share_id=%s %s", sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0], message)
                continue

            # 兼容 1.0.x / 1.1.0：旧版整份分享已成功且内容未变时，仅补建文件库存。
            if not assets and old.get("success") and old.get("fingerprint") in {fingerprint, legacy_fingerprint}:
                migrated_stats: Dict[str, int] = {}
                migrated = self._plan_incremental_files(probe, {}, subscribe=subscribe, target_path=target_path, stats=migrated_stats)
                self._remember_assets(assets, migrated, share_key, target_path)
                inventory[sid_key] = {"assets": assets, "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                self.save_data("transfer_inventory", inventory)
                synchronized_match = True
                self._mark_entry_processed(entry, "legacy_synced", "旧版成功记录已建立文件级索引", subscribe)
                self._plugin_log("INFO", "【光鸭转存助手】【去重】#%s %s 从旧版成功记录建立文件级索引 %s 个，不重复转存", sid, getattr(subscribe, "name", ""), len(migrated))
                continue

            if not planned:
                synchronized_match = True
                if inflight_held:
                    self._plugin_log("INFO", 
                        "【光鸭转存助手】【在途去重】#%s %s share_id=%s 本条新消息可转内容全部已在其它任务中，保留消息为待检查，不标记永久处理",
                        sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0],
                    )
                    continue
                self._mark_entry_processed(entry, "synced", "库存或订阅进度已覆盖，无新增文件", subscribe)
                self._plugin_log("INFO", 
                    "【光鸭转存助手】【去重】#%s %s share_id=%s 无新增文件（库存=%s，已完成剧集/范围过滤=%s），跳过",
                    sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0], stats.get("inventory", 0), stats.get("episode", 0),
                )
                continue

            attempted_new = True
            pending_count = len(planned)
            deferred_for_entry = max(0, pending_count - self._max_files_per_run)
            if deferred_for_entry:
                remaining_due_to_cap += deferred_for_entry
                planned = planned[:self._max_files_per_run]
            job_paths = [str(item.get("effective_path") or item.get("relative_path") or item.get("name") or "") for item in planned]
            pending_job = self._get_job_state(job_key)
            restored = None
            if pending_job.get("status") == "cancelled" and set(pending_job.get("paths") or []) == set(job_paths):
                synchronized_match = True
                self._plugin_log("INFO", 
                    "【光鸭转存助手】【人工任务】#%s %s share_id=%s 该旧消息任务已人工忽略，本轮不重复提交；等待新消息/新链接",
                    sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0],
                )
                continue
            self._plugin_log("INFO", 
                "【光鸭转存助手】【增量】#%s %s share_id=%s 叶子文件=%s，符合范围=%s，新增待转=%s，本轮=%s，库存=%s，剧集过滤=%s",
                sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0], probe.get("leaf_count") or len(probe.get("files") or []),
                stats.get("eligible", 0), pending_count, len(planned), stats.get("inventory", 0) + stats.get("fact", 0), stats.get("episode", 0),
            )
            if not force and pending_job.get("status") in ("submitted", "task_confirmed", "verifying") and set(pending_job.get("paths") or []) == set(job_paths):
                updated = self._parse_datetime(pending_job.get("updated"))
                age = (datetime.datetime.now() - updated).total_seconds() if updated else self._retry_minutes * 60 + 1
                recovered = self._verify_restored_items(target_path, planned, max_try=1)
                if recovered.get("success"):
                    restored = {
                        "success": True, "message": "恢复上次任务：目标文件已确认可见",
                        "completed_items": list(recovered.get("verified_items") or planned),
                        "task_ids": list(pending_job.get("task_ids") or []),
                        "confirmation": "重启恢复后通过目标文件可见性确认",
                    }
                    self._set_job_state(job_key, "verified", recovered=True)
                else:
                    pending_verification = True
                    wait_text = "等待落盘确认" if age < self._retry_minutes * 60 else "落盘确认已超等待窗口，保持待确认以避免重复提交"
                    self._set_job_state(job_key, "verifying", verification_message=wait_text)
                    self._plugin_log("WARNING", 
                        "【光鸭转存助手】【恢复】#%s %s share_id=%s %s；已提交任务不会自动重复提交",
                        sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0], wait_text,
                    )
                    continue
            if restored is None:
                self._set_job_state(
                    job_key, "planned", subscribe_id=sid, media=self._media_fact_prefix(subscribe),
                    share_id=share_key.split("|", 1)[0], message_id=str(entry.get("message_id") or ""),
                    paths=job_paths, target=target_path, fingerprint=fingerprint,
                )
                restored = self._restore_items(probe, target_path, planned, job_key=job_key)
            completed = list(restored.get("completed_items") or [])
            if completed:
                self._remember_assets(assets, completed, share_key, target_path)
                inventory[sid_key] = {"assets": assets, "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                self.save_data("transfer_inventory", inventory)
                self._remember_media_facts(subscribe, completed, origin="transfer")
                transferred_assets.extend(completed)
                task_ids.extend([value for value in (restored.get("task_ids") or []) if value])
                self._sync_progress(subscribe, completed)
                self._set_job_state(job_key, "synced" if restored.get("success") else "partial", completed_paths=[str(item.get("effective_path") or item.get("relative_path") or item.get("name") or "") for item in completed])
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
            if restored.get("success"):
                if deferred_for_entry <= 0:
                    self._mark_entry_processed(entry, "transferred", restored.get("message") or "增量转存完成", subscribe)
                else:
                    # 本条消息还有被单次上限截断的文件，保留为未处理，下一轮继续增量。
                    self._set_job_state(job_key, "partial", deferred=deferred_for_entry)
                    self._plugin_log("INFO", "【光鸭转存助手】【分批】#%s %s share_id=%s 本轮完成后仍有 %s 个文件待下轮，不标记消息完成", sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0], deferred_for_entry)
            else:
                if restored.get("pending_verification"):
                    pending_verification = True
                    self._set_job_state(job_key, "verifying", verification_message=str(restored.get("message") or "等待落盘确认"))
                    self._plugin_log("WARNING", 
                        "【光鸭转存助手】【落盘确认】#%s %s share_id=%s 任务已提交但文件尚未全部确认；保持待确认，不自动重复提交",
                        sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0],
                    )
                else:
                    self._set_job_state(job_key, "failed", error=str(restored.get("message") or "增量转存失败"))
                    errors.append(str(restored.get("message") or "增量转存失败"))

        unique_paths = []
        seen_paths = set()
        for item in transferred_assets:
            rel = str(item.get("effective_path") or item.get("relative_path") or item.get("name") or "")
            if rel and rel not in seen_paths:
                seen_paths.add(rel)
                unique_paths.append(rel)
        if unique_paths:
            completed_subscription = self._finish_subscription_if_complete(subscribe, channel_state=channel_state)
            partial = (bool(errors) or remaining_due_to_cap > 0 or pending_verification) and not completed_subscription
            self._plugin_log("INFO", "【光鸭转存助手】【转存】#%s %s %s：新增 %s 个文件，累计去重 %s 个，剩余待下轮 %s，目标=%s", sid, getattr(subscribe, "name", ""), "订阅完成" if completed_subscription else ("部分完成" if partial else "增量完成"), len(unique_paths), len(assets), remaining_due_to_cap, target_path)
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
                    ("状态：电影/剧集目标已完成，订阅已移入历史" if completed_subscription else ("状态：部分转存完成，剩余保持转存路线等待下轮" if partial else "状态：增量转存已确认完成")),
                    f"匹配：{'、'.join(sorted(match_reasons)) or '-'}",
                    f"本次新增：{len(unique_paths)} 个文件",
                    f"累计去重：{len(assets)} 个文件",
                    (lambda p: f"订阅进度：{p[0]}/{p[1]}，剩余 {p[2]} 集" if p[1] else "订阅进度：非剧集订阅")(self._subscription_episode_progress(subscribe)),
                    f"来源：{'、'.join(sorted(sources))}",
                    f"目标：{target_path}",
                    f"新增内容：{preview or '-'}",
                ]
                missing_now = self._subscription_missing_episodes(subscribe)
                if missing_now:
                    shown_missing = ",".join(f"E{value:02d}" for value in missing_now[:30])
                    lines.append(f"缺失：{shown_missing}" + (f" 等{len(missing_now)}集" if len(missing_now) > 30 else ""))
                if channel_state.get("ongoing") and not channel_state.get("complete") and not channel_state.get("explicit_total"):
                    lines.append("追更状态：频道仍标记更新中，即使当前集数齐全也受连载保护，不会提前完成订阅")
                if remaining_due_to_cap:
                    lines.append(f"待下轮：至少 {remaining_due_to_cap} 个文件")
                if task_ids:
                    lines.append(f"任务ID：{','.join(task_ids[:6])}")
                self.post_message(mtype=NotificationType.Plugin, title="✅ 光鸭订阅完成" if completed_subscription else ("⚠️ 光鸭部分转存" if partial else "✅ 光鸭转存成功"), text="\n".join(lines))
                self._plugin_log("INFO", "【光鸭转存助手】【通知】已发送%s通知：#%s %s", "部分转存" if partial else "增量转存成功", sid, getattr(subscribe, "name", ""))
            if partial:
                return {"success": False, "handled": True, "message": f"部分转存 {len(unique_paths)} 个文件，剩余等待下轮转存", "new_count": len(unique_paths), "target_path": target_path}
            return {"success": True, "handled": True, "completed": completed_subscription, "message": (f"转存成功，本次新增 {len(unique_paths)} 个文件；订阅已完成并移入历史" if completed_subscription else f"增量转存成功，本次新增 {len(unique_paths)} 个文件"), "new_count": len(unique_paths), "target_path": target_path, "remaining": remaining_due_to_cap}

        if valid_route_match and not errors and (synchronized_match or not attempted_new):
            if self._finish_subscription_if_complete(subscribe, channel_state=channel_state):
                return {"success": True, "handled": True, "completed": True, "message": "目标剧集已全部完成，订阅已移入历史"}
            done, total, lack = self._subscription_episode_progress(subscribe)
            self._plugin_log("INFO", "【光鸭转存助手】【去重】#%s %s 所有有效匹配均无新增；订阅进度 %s/%s，剩余 %s；固定转存路线不触发重复下载", sid, getattr(subscribe, "name", ""), done, total, lack)
            return {"success": True, "handled": True, "already": True, "message": f"已同步，无新增资源；进度 {done}/{total}，剩余 {lack}" if total else "已同步，无新增资源"}

        if pending_verification and not errors:
            self._plugin_log("INFO", 
                "【光鸭转存助手】【落盘确认】#%s %s 已有转存任务等待目标文件确认；本轮不重复提交、不触发失败通知",
                sid, getattr(subscribe, "name", ""),
            )
            return {
                "success": True, "handled": True, "pending": True,
                "message": "转存任务已提交，等待目标文件落盘确认；不会重复提交",
            }

        final_message = "；".join(dict.fromkeys(errors))[:1200] or "匹配分享均不可用"
        self._plugin_log("WARNING", "【光鸭转存助手】【失败】#%s %s 转存未完成：%s；固定转存路线不触发原生下载", sid, getattr(subscribe, "name", ""), final_message)
        if self._notify and matched_pairs:
            notices = self.get_data("failure_notices") or {}
            notice_key = f"{sid}:{_failure_notice_fingerprint(final_message)}"
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
                            + "后续：保持转存路线，等待频道刷新或下次重试"
                        ),
                    )
                    notices[notice_key] = now.strftime("%Y-%m-%d %H:%M:%S")
                    self.save_data("failure_notices", notices)
                    self._plugin_log("INFO", "【光鸭转存助手】【通知】已发送转存失败通知：#%s %s（相同错误 6 小时内不重复推送）", sid, getattr(subscribe, "name", ""))
                except Exception as err:
                    self._plugin_log("WARNING", "【光鸭转存助手】【通知】发送失败通知异常：%s", err)
        return {"success": False, "handled": True, "message": final_message}

    def _target_path(self, subscribe: Any) -> str:
        base = _normalize_config_path(self._save_path, "/")
        if not self._create_media_folder:
            return base
        name = re.sub(r"[\\/:*?\"<>|]+", " ", str(getattr(subscribe, "name", "") or "")).strip()
        year = str(getattr(subscribe, "year", "") or "").strip()
        folder = f"{name} ({year})" if year else name
        return (base.rstrip("/") + "/" + _safe_relative_path(folder)).replace("//", "/")

    def _plan_incremental_files(
        self, probe: Dict[str, Any], assets: Dict[str, Any], subscribe: Any = None,
        target_path: str = "", stats: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        files = [dict(item) for item in (probe.get("files") or []) if item.get("id")]
        counters = {"total": len(files), "eligible": 0, "inventory": 0, "fact": 0, "episode": 0, "auxiliary": 0, "video": 0, "subtitle": 0, "unparsed": 0, "inferred": 0}
        unparsed_paths: List[str] = []
        unsupported_paths: List[str] = []
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

        inferred_episode_by_id: Dict[str, List[int]] = {}
        if is_tv and total_episode > 0 and start_episode == 1:
            video_rows = []
            for seq_item in files:
                seq_rel = _safe_relative_path(seq_item.get("relative_path") or seq_item.get("name") or "")
                seq_effective = seq_rel[len(strip_root) + 1:] if strip_root and seq_rel.startswith(strip_root + "/") else seq_rel
                seq_effective = _safe_relative_path(seq_effective)
                if not _is_video(seq_effective):
                    continue
                file_season, parsed_eps = _episode_numbers(seq_effective)
                video_rows.append((seq_item, seq_effective, file_season, parsed_eps))
            # 只有视频数量与整季总集数完全一致时才按自然顺序推断，避免把更新包/花絮错当集数。
            if len(video_rows) == total_episode:
                ordered = sorted(video_rows, key=lambda row: _natural_media_sort_key(row[1]))
                try:
                    wanted_season = int(subscribe_season) if subscribe_season not in (None, "") else None
                except (TypeError, ValueError):
                    wanted_season = None
                consistent = True
                for index, (_, _, file_season, parsed_eps) in enumerate(ordered, 1):
                    if wanted_season is not None and file_season is not None and file_season != wanted_season:
                        consistent = False
                        break
                    if parsed_eps and index not in parsed_eps:
                        consistent = False
                        break
                if consistent:
                    for index, (seq_item, _, _, parsed_eps) in enumerate(ordered, 1):
                        if not parsed_eps:
                            inferred_episode_by_id[str(seq_item.get("id") or "")] = [index]

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
            if is_video:
                counters["video"] += 1
            elif is_subtitle:
                counters["subtitle"] += 1
            if self._media_only and not (is_video or is_subtitle):
                counters["auxiliary"] += 1
                if len(unsupported_paths) < 12:
                    unsupported_paths.append(effective)
                continue
            if is_tv and (is_video or is_subtitle):
                file_season, episodes = _episode_numbers(effective)
                if not episodes:
                    inferred = inferred_episode_by_id.get(str(item.get("id") or ""))
                    if inferred:
                        episodes = list(inferred)
                        counters["inferred"] += 1
                if subscribe_season not in (None, ""):
                    try:
                        wanted_season = int(subscribe_season)
                    except (TypeError, ValueError):
                        wanted_season = None
                    if wanted_season is not None:
                        if file_season is not None and file_season != wanted_season:
                            counters["episode"] += 1
                            continue
                        if wanted_season == 0 and file_season is None:
                            counters["episode"] += 1
                            continue
                if episodes:
                    wanted = [ep for ep in episodes if ep >= start_episode and (not total_episode or ep <= total_episode) and ep not in done_episodes]
                    if not wanted:
                        counters["episode"] += 1
                        continue
                elif done_episodes or start_episode > 1:
                    # 已有订阅进度时仍不盲转未知集号，但必须显式暴露诊断且不永久标记消息已处理。
                    counters["unparsed"] += 1
                    if len(unparsed_paths) < 12:
                        unparsed_paths.append(effective)
                    counters["episode"] += 1
                    continue
            counters["eligible"] += 1
            semantic_probe = dict(item)
            semantic_probe["effective_path"] = effective
            if subscribe is not None and is_video and self._semantic_fact_exists(subscribe, semantic_probe):
                counters["fact"] += 1
                continue
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
            stats["unparsed_paths"] = list(unparsed_paths)
            stats["unsupported_paths"] = list(unsupported_paths)
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
        """确认转存成功后同步 MoviePilot note 和 lack_episode。"""
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
        payload: Dict[str, Any] = {"note": sorted(merged)}
        try:
            start = max(1, int(getattr(subscribe, "start_episode", 0) or 1))
            total = int(getattr(subscribe, "total_episode", 0) or 0)
            if total >= start:
                target = set(range(start, total + 1))
                payload["lack_episode"] = len(target - merged)
        except (TypeError, ValueError):
            pass
        try:
            SubscribeOper().update(int(getattr(subscribe, "id", 0) or 0), payload)
            setattr(subscribe, "note", sorted(merged))
            if "lack_episode" in payload:
                setattr(subscribe, "lack_episode", payload["lack_episode"])
            done, total, lack = self._subscription_episode_progress(subscribe)
            self._plugin_log("INFO", 
                "【光鸭转存助手】【进度】#%s %s 本次确认剧集 %s；已完成 %s/%s，剩余 %s",
                getattr(subscribe, "id", 0), getattr(subscribe, "name", ""),
                ",".join(str(v) for v in sorted(episodes)), done, total, lack,
            )
        except Exception as err:
            self._plugin_log("WARNING", "【光鸭转存助手】【进度】同步 MoviePilot 订阅进度失败：%s", err)

    @staticmethod
    def _is_movie_subscription(subscribe: Any) -> bool:
        raw_type = str(getattr(subscribe, "type", "") or "")
        mtype = raw_type.lower()
        return "movie" in mtype or "电影" in raw_type

    def _movie_transfer_confirmed(self, subscribe: Any) -> bool:
        """电影只在媒体库已存在或已确认至少一个视频文件成功转存后允许完成。"""
        sid = int(getattr(subscribe, "id", 0) or 0)
        if not sid:
            return False
        facts = self.get_data("media_facts") or {}
        if self._media_fact_prefix(subscribe) in facts:
            return True
        inventory = self.get_data("transfer_inventory") or {}
        assets = ((inventory.get(str(sid)) or {}).get("assets") or {})
        for row in assets.values():
            if not isinstance(row, dict):
                continue
            path = str(row.get("path") or "")
            if path and _is_video(path):
                return True
        try:
            meta = build_subscribe_meta(subscribe)
            mediainfo = MediaChain().recognize_media(
                meta=meta,
                mtype=meta.type,
                media_source=getattr(subscribe, "media_source", None),
                media_id=getattr(subscribe, "media_id", None),
                episode_group=getattr(subscribe, "episode_group", None),
                cache=False,
            )
            if not mediainfo:
                return False
            exists, _ = DownloadChain().get_no_exists_info(meta=meta, mediainfo=mediainfo)
            if exists:
                self._plugin_log("INFO", "【光鸭转存助手】【媒体库同步】#%s %s 电影已存在于媒体库，允许完成订阅", sid, getattr(subscribe, "name", ""))
                return True
        except Exception as err:
            self._plugin_log("WARNING", "【光鸭转存助手】【媒体库同步】#%s %s 检查电影媒体库状态失败：%s", sid, getattr(subscribe, "name", ""), err)
        return False

    def _finish_subscription_if_complete(self, subscribe: Any, channel_state: Optional[Dict[str, Any]] = None) -> bool:
        """电影按确认转存/媒体库存在完成；剧集按目标集进度并通过连载保护后完成。"""
        if bool(getattr(subscribe, "best_version", 0)):
            return False
        sid = int(getattr(subscribe, "id", 0) or 0)
        if not sid:
            return False
        is_movie = self._is_movie_subscription(subscribe)
        done = total = lack = 0
        if is_movie:
            if not self._movie_transfer_confirmed(subscribe):
                return False
            self._clear_completion_guard(sid)
        else:
            if not self._sync_subscription_progress:
                return False
            done, total, lack = self._subscription_episode_progress(subscribe)
            if not total or lack > 0:
                self._clear_completion_guard(sid)
                if total:
                    try:
                        if int(getattr(subscribe, "lack_episode", lack) or 0) != lack:
                            SubscribeOper().update(sid, {"lack_episode": lack})
                            setattr(subscribe, "lack_episode", lack)
                    except Exception as err:
                        self._plugin_log("WARNING", "【光鸭转存助手】【进度】更新剩余集数失败：%s", err)
                return False
            if not self._completion_guard_allows(subscribe, channel_state=channel_state):
                return False
        latest = self._find_subscription(sid)
        if not latest:
            self._remove_selected_subscription(sid)
            return True
        try:
            meta = build_subscribe_meta(latest)
            mediainfo = MediaChain().recognize_media(
                meta=meta,
                mtype=meta.type,
                media_source=getattr(latest, "media_source", None),
                media_id=getattr(latest, "media_id", None),
                episode_group=getattr(latest, "episode_group", None),
                cache=False,
            )
            if not mediainfo:
                progress = "电影已确认转存" if is_movie else f"已完成 {done}/{total}"
                self._plugin_log("WARNING", "【光鸭转存助手】【完成】#%s %s %s，但媒体识别失败，暂不移除订阅", sid, getattr(latest, "name", ""), progress)
                return False
            SubscribeChain().finish_subscribe_or_not(
                subscribe=latest,
                meta=meta,
                mediainfo=mediainfo,
                lefts={},
                force=True,
            )
            if self._find_subscription(sid):
                progress = "电影已确认转存" if is_movie else f"已完成 {done}/{total}"
                self._plugin_log("WARNING", "【光鸭转存助手】【完成】#%s %s %s，但 MoviePilot 完成流程后订阅仍存在", sid, getattr(latest, "name", ""), progress)
                return False
            self._clear_completion_guard(sid)
            self._remove_selected_subscription(sid)
            if is_movie:
                self._plugin_log("INFO", "【光鸭转存助手】【完成】#%s %s 电影已确认转存/媒体库存在；已通过 MoviePilot 官方流程移入订阅历史并从活动订阅移除", sid, getattr(latest, "name", ""))
            else:
                self._plugin_log("INFO", "【光鸭转存助手】【完成】#%s %s 已完成 %s/%s，剩余 0；已通过 MoviePilot 官方流程移入订阅历史并从活动订阅移除", sid, getattr(latest, "name", ""), done, total)
            return True
        except Exception:
            self._plugin_log("EXCEPTION", "【光鸭转存助手】【完成】#%s %s 执行 MoviePilot 官方完成流程失败", sid, getattr(subscribe, "name", ""))
            return False

    def _remove_selected_subscription(self, sid: int) -> None:
        """订阅完成后同步移除插件固定转存名单中的订阅 ID。"""
        selected = [value for value in self._selected_subscriptions if int(value) != int(sid)]
        if selected == self._selected_subscriptions:
            return
        self._selected_subscriptions = selected
        self._clear_completion_guard(int(sid))
        self._save_config()

    def _get_guangya_runtime(self) -> Tuple[Any, Any]:
        """通过 V3 SDK 读取光鸭云盘助手运行实例，不依赖已迁移的 Runtime 内部模块。"""
        manager = PluginManager()
        running = getattr(manager, "running_plugins", None) or {}
        plugin = running.get("ShukGuangYaDisk") if isinstance(running, dict) else None
        if plugin is not None:
            return getattr(plugin, "_client", None), getattr(plugin, "_guangya_api", None)

        # 兼容 SDK 包装器仍暴露旧 helper 的 MoviePilot V3 小版本；这里只调用方法，
        # 不再导入 app.runtime.extensions.plugin_manager。
        getter = getattr(manager, "get_plugin_attr", None)
        if callable(getter):
            try:
                return (
                    getter("ShukGuangYaDisk", "_client"),
                    getter("ShukGuangYaDisk", "_guangya_api"),
                )
            except Exception:
                pass
        return None, None

    @staticmethod
    def _is_success(response: Any) -> bool:
        if not isinstance(response, dict):
            return False
        code = response.get("code")
        return code in (None, 0, "0") and str(response.get("msg") or response.get("message") or "success").lower() not in ("error", "failed", "fail")

    def _share_access(self, client: Any, share_url: str) -> Tuple[Optional[str], str]:
        identity = _share_identity(share_url)
        if not identity:
            return None, "无效光鸭分享链接"
        share_id, code = identity.split("|", 1)
        response = client._request(
            method="POST",
            url=f"{client.API_BASE_URL}/nd.bizuserres.s/v1/get_share_access_token",
            data={"shareId": share_id, "code": code},
            need_auth=False,
        )
        data = response.get("data") or {} if isinstance(response, dict) else {}
        token = str(data.get("accessToken") or data.get("access_token") or data.get("token") or "") if isinstance(data, dict) else ""
        if not self._is_success(response) or not token:
            return None, str(response.get("msg") or response.get("error") or "获取分享令牌失败")
        return token, ""

    def _inspect_share(self, share_url: str) -> Dict[str, Any]:
        cached = self._inspect_cache.get(_share_identity(share_url))
        if cached and time.time() - cached[0] < min(self._refresh_minutes * 60, 900):
            return dict(cached[1])
        client, _ = self._get_guangya_runtime()
        if not client:
            return {"success": False, "message": "光鸭云盘助手未运行或未登录"}
        token, error = self._share_access(client, share_url)
        if not token:
            return {"success": False, "message": error}
        stack: List[Tuple[str, str]] = [("", "")]
        root_ids: List[str] = []
        fingerprint_rows: List[str] = []
        legacy_fingerprint_rows: List[str] = []
        files: List[Dict[str, Any]] = []
        count = 0
        while stack and count < self._max_share_files:
            parent_id, parent_path = stack.pop()
            page = 1
            while count < self._max_share_files:
                response = client._request(
                    method="POST",
                    url=f"{client.API_BASE_URL}/nd.bizuserres.s/v1/get_share_page_files_list",
                    data={"accessToken": token, "parentId": parent_id, "page": page, "pageSize": 100, "orderBy": 0, "sortType": 0},
                    need_auth=False,
                )
                if not self._is_success(response):
                    return {"success": False, "message": str(response.get("msg") or response.get("error") or "读取分享文件失败")}
                raw_items = _extract_result_list(response)
                if parent_id == "":
                    root_ids.extend(str(item.get("fileId") or item.get("id") or item.get("fid") or item.get("resId") or "") for item in raw_items)
                for raw in raw_items:
                    item = _cloud_item(raw)
                    if not item:
                        continue
                    count += 1
                    rel = _safe_relative_path("/".join(value for value in (parent_path.strip("/"), item["name"].strip("/")) if value))
                    fingerprint_rows.append(f"{item['id']}|{rel}|{item['size']}|{int(item['is_dir'])}|{item.get('digest') or ''}")
                    legacy_fingerprint_rows.append(f"{item['id']}|{item['name']}|{item['size']}|{int(item['is_dir'])}")
                    if item["is_dir"]:
                        stack.append((item["id"], rel))
                    else:
                        files.append({**item, "relative_path": rel, "parent_path": parent_path})
                    if count >= self._max_share_files:
                        break
                if len(raw_items) < 100:
                    break
                page += 1
        fingerprint = hashlib.sha256("\n".join(sorted(fingerprint_rows)).encode("utf-8")).hexdigest()
        legacy_fingerprint = hashlib.sha256("\n".join(sorted(legacy_fingerprint_rows)).encode("utf-8")).hexdigest()
        result = {
            "success": True, "access_token": token,
            "root_ids": [value for value in root_ids if value],
            "fingerprint": fingerprint, "legacy_fingerprint": legacy_fingerprint, "file_count": count,
            "leaf_count": len(files), "files": files,
        }
        self._inspect_cache[_share_identity(share_url)] = (time.time(), result)
        return dict(result)

    def _verify_restored_group(
        self, api: Any, parent_id: str, parent_path: str, items: List[Dict[str, Any]],
        max_try: int = 20, interval: float = 1.0,
    ) -> Dict[str, Any]:
        """按目标目录中的同名/同大小文件进行二次落盘确认。"""
        if not items:
            return {"success": True, "verified_items": []}
        expected = {}
        for item in items:
            effective = str(item.get("effective_path") or item.get("relative_path") or item.get("name") or "")
            name = Path(effective).name
            if name:
                expected[name] = int(item.get("size") or 0)
        if not expected:
            return {"success": False, "message": "无法生成目标文件校验清单", "verified_items": []}
        for attempt in range(max(1, max_try)):
            try:
                remote_items = []
                if hasattr(api, "_iter_parent_items"):
                    remote_items = list(api._iter_parent_items(parent_id=parent_id, parent_path=parent_path) or [])
                else:
                    for name in expected:
                        if hasattr(api, "_wait_item_visible"):
                            item = api._wait_item_visible(parent_path=parent_path, name=name, expected_type="file", max_try=1, interval=0)
                            if item:
                                remote_items.append(item)
                remote = {str(getattr(item, "name", "") or ""): item for item in remote_items}
                missing = []
                mismatch = []
                for name, size in expected.items():
                    found = remote.get(name)
                    if not found:
                        missing.append(name)
                        continue
                    remote_size = getattr(found, "size", None)
                    if size and remote_size not in (None, 0, size):
                        mismatch.append(f"{name}({remote_size}!={size})")
                if not missing and not mismatch:
                    return {"success": True, "verified_items": list(items)}
                last_message = ""
                if missing:
                    last_message += "未出现:" + ",".join(missing[:8])
                if mismatch:
                    last_message += ("；" if last_message else "") + "大小不符:" + ",".join(mismatch[:8])
            except Exception as err:
                last_message = str(err)
            if attempt < max_try - 1:
                time.sleep(interval)
        return {"success": False, "message": last_message or "目标文件未确认可见", "verified_items": []}

    def _verify_restored_items(self, save_path: str, items: List[Dict[str, Any]], max_try: int = 1) -> Dict[str, Any]:
        """恢复进程重启后的任务：按目标相对目录分组做可见性校验。"""
        _, api = self._get_guangya_runtime()
        if not api:
            return {"success": False, "message": "光鸭云盘助手不可用", "verified_items": []}
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for item in items:
            groups.setdefault(str(item.get("target_parent") or ""), []).append(item)
        verified: List[Dict[str, Any]] = []
        for relative_parent, group in groups.items():
            base = _normalize_config_path(save_path, "/")
            relative_parent = _safe_relative_path(relative_parent)
            normalized = (base.rstrip("/") + ("/" + relative_parent if relative_parent else "")) or "/"
            try:
                folder = api.get_folder(Path(normalized))
                parent_id = str(getattr(folder, "fileid", "") or "") if folder else ""
            except Exception as err:
                return {"success": False, "message": str(err), "verified_items": verified}
            result = self._verify_restored_group(api, parent_id, normalized, group, max_try=max_try, interval=0 if max_try <= 1 else 1.0)
            if not result.get("success"):
                return {"success": False, "message": result.get("message") or "目标文件未确认可见", "verified_items": verified}
            verified.extend(result.get("verified_items") or group)
        return {"success": True, "verified_items": verified}

    def _restore_items(self, probe: Dict[str, Any], save_path: str, items: List[Dict[str, Any]], job_key: str = "") -> Dict[str, Any]:
        save_path = _normalize_config_path(save_path, "/")
        client, api = self._get_guangya_runtime()
        if not client or not api:
            return {"success": False, "message": "请先安装、启用并登录光鸭云盘助手", "completed_items": []}
        if not items:
            return {"success": True, "message": "无新增文件", "completed_items": [], "task_ids": []}
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for item in items:
            groups.setdefault(str(item.get("target_parent") or ""), []).append(item)
        completed: List[Dict[str, Any]] = []
        task_ids: List[str] = []
        try:
            for relative_parent, group in groups.items():
                base = _normalize_config_path(save_path, "/")
                relative_parent = _safe_relative_path(relative_parent)
                normalized = (base.rstrip("/") + ("/" + relative_parent if relative_parent else "")) or "/"
                folder = api.get_folder(Path(normalized))
                if not folder and normalized != "/":
                    self._set_job_state(job_key, "failed", error=f"无法创建/定位目标目录 {normalized}")
                    return {"success": False, "message": f"无法创建/定位目标目录 {normalized}", "completed_items": completed, "task_ids": task_ids}
                parent_id = str(getattr(folder, "fileid", "") or "") if folder else ""
                file_ids = [str(item.get("id") or "") for item in group if item.get("id")]
                group_paths = [str(item.get("effective_path") or item.get("relative_path") or item.get("name") or "") for item in group]
                self._set_job_state(job_key, "submitting", group_paths=group_paths, task_ids=task_ids)
                self._plugin_log("INFO", "【光鸭转存助手】【增量】提交目录 %s：新增文件 %s 个", normalized, len(file_ids))
                response = client._request(
                    method="POST",
                    url=f"{client.API_BASE_URL}/nd.bizuserres.s/v1/restore_share",
                    data={"accessToken": probe.get("access_token"), "fileIds": file_ids, "parentId": parent_id},
                    need_auth=True,
                )
                if not self._is_success(response):
                    message = str(response.get("msg") or response.get("error") or "光鸭增量转存失败")
                    self._set_job_state(job_key, "failed", error=message, task_ids=task_ids)
                    return {"success": False, "message": message, "completed_items": completed, "task_ids": task_ids}
                data = response.get("data") or {}
                task_id = str(data.get("taskId") or data.get("task_id") or "") if isinstance(data, dict) else ""
                if task_id:
                    task_ids.append(task_id)
                self._set_job_state(job_key, "submitted", task_ids=task_ids, group_paths=group_paths)
                if task_id and hasattr(api, "_wait_task_done"):
                    self._plugin_log("INFO", "【光鸭转存助手】【转存】等待增量任务完成：task_id=%s", task_id)
                    done = api._wait_task_done(task_id, max_try=120, interval=1, allow_missing=True)
                    if not done:
                        self._set_job_state(job_key, "failed", error=f"任务 {task_id} 未确认完成", task_ids=task_ids)
                        return {"success": False, "message": f"增量转存任务 {task_id} 未确认完成", "completed_items": completed, "task_ids": task_ids}
                self._set_job_state(job_key, "task_confirmed", task_ids=task_ids, group_paths=group_paths)
                self._plugin_log("INFO", "【光鸭转存助手】【落盘确认】开始校验目录 %s 的 %s 个文件", normalized, len(group))
                verified = self._verify_restored_group(api, parent_id, normalized, group, max_try=30, interval=1.0)
                if not verified.get("success"):
                    message = f"转存任务已完成但目标文件未全部确认：{verified.get('message') or '-'}"
                    self._set_job_state(job_key, "verifying", error=message, task_ids=task_ids, group_paths=group_paths)
                    return {
                        "success": False, "pending_verification": True, "message": message,
                        "completed_items": completed, "task_ids": task_ids,
                    }
                completed.extend(verified.get("verified_items") or group)
                self._set_job_state(job_key, "verified", task_ids=task_ids, verified_paths=[str(item.get("effective_path") or item.get("relative_path") or item.get("name") or "") for item in completed])
                self._plugin_log("INFO", "【光鸭转存助手】【落盘确认】目录 %s 已确认 %s 个文件可见且大小匹配", normalized, len(group))
            return {
                "success": True, "message": f"增量转存并落盘确认完成，共新增 {len(completed)} 个文件",
                "completed_items": completed, "task_ids": task_ids,
                "confirmation": "所有转存任务完成且目标文件可见性/大小已确认",
            }
        except Exception as err:
            self._plugin_log("EXCEPTION", "【光鸭转存助手】【转存】执行增量转存异常：target=%s", save_path)
            self._set_job_state(job_key, "failed", error=str(err), task_ids=task_ids)
            return {"success": False, "message": f"光鸭增量转存异常: {err}", "completed_items": completed, "task_ids": task_ids}

    def _restore_share(self, share_url: str, save_path: str, probe: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """兼容入口：仍使用文件级恢复，避免整份分享重复转存。"""
        probe = probe or self._inspect_share(share_url)
        if not probe.get("success"):
            return probe
        items = self._plan_incremental_files(probe, {})
        return self._restore_items(probe, save_path, items)

    def _root_folder_options(self, raw: bool = False) -> List[Any]:
        client, _ = self._get_guangya_runtime()
        if not client:
            return []
        try:
            response = client._request(
                method="POST",
                url=f"{client.API_BASE_URL}/nd.bizuserres.s/v1/file/get_file_list",
                data={"parentId": "", "page": 0, "pageSize": 100, "orderBy": 0, "sortType": 0, "fileTypes": []},
                need_auth=True,
            )
            result = []
            for value in _extract_result_list(response):
                item = _cloud_item(value)
                if item and item["is_dir"]:
                    row = {"title": "/" + item["name"], "value": "/" + item["name"], "file_id": item["id"]}
                    result.append(row if raw else row["value"])
            return result
        except Exception:
            return []

    @staticmethod
    def _trim_history(history: Dict[str, Any]) -> None:
        if len(history) <= 500:
            return
        ordered = sorted(history.items(), key=lambda pair: str((pair[1] or {}).get("time") or ""), reverse=True)
        history.clear()
        history.update(dict(ordered[:500]))

    @staticmethod
    def _parse_datetime(value: Any) -> Optional[datetime.datetime]:
        try:
            return datetime.datetime.strptime(str(value or ""), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None

    @staticmethod
    def _to_int(value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(parsed, maximum))

    def stop_service(self) -> None:
        try:
            stop = getattr(self, "_runtime_stop", None)
            if stop is not None:
                stop.set()
            with type(self)._runtime_generation_lock:
                type(self)._runtime_generation += 1
            thread = getattr(self, "_runtime_thread", None)
            if thread and thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout=1.0)
        except Exception:
            pass
        self._restore_takeover()
        self._inspect_cache.clear()
