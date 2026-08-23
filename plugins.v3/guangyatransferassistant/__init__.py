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

from app.chain.subscribe import SubscribeChain, build_subscribe_meta
from app.chain.media import MediaChain
from app.chain.download import DownloadChain
from app.db.oper.subscribe import SubscribeOper
from app.plugins import _PluginBase
from app.schemas import NotificationType
from app.runtime.extensions.plugin_manager import PluginManager
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
VIDEO_EXTENSIONS = {".mkv", ".mp4", ".ts", ".m2ts", ".avi", ".mov", ".wmv", ".flv", ".webm", ".iso", ".rmvb"}
SUBTITLE_EXTENSIONS = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".sup"}
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
    total_match = TOTAL_EPISODE_PATTERN.search(text)
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
    """从 S01E23、S01E23-E25、E23-E25、E23E24、中文第23-25集提取季和集。"""
    value = str(path or "")
    season = None
    episodes = set()

    # S01E23-E25 / S01E23E24 先处理，避免 E 前面是数字时被通用边界规则漏掉。
    season_block = re.search(r"(?i)S(?:eason)?\s*0*(\d{1,2})\s*E(?:P)?\s*0*(\d{1,3})(?:\s*[-~—至]\s*E?(?:P)?\s*0*(\d{1,3}))?", value)
    if season_block:
        season = int(season_block.group(1))
        start = int(season_block.group(2))
        end = int(season_block.group(3)) if season_block.group(3) else start
        if end >= start and end - start <= 200:
            episodes.update(range(start, end + 1))
        # 同一个 season token 后续可能是 E23E24E25。
        suffix = value[season_block.start():]
        for ep in re.findall(r"(?i)E(?:P)?\s*0*(\d{1,3})", suffix):
            episodes.add(int(ep))
    else:
        season_match = re.search(r"(?i)(?:^|[^A-Za-z0-9])S(?:eason)?\s*0*(\d{1,2})(?=[^0-9]|$)", value)
        if season_match:
            season = int(season_match.group(1))

    # 独立 E23 / E23-E25。
    for matched in re.finditer(r"(?i)(?:^|[^A-Za-z0-9])E(?:P)?\s*0*(\d{1,3})(?:\s*[-~—至]\s*E?(?:P)?\s*0*(\d{1,3}))?", value):
        start = int(matched.group(1))
        end = int(matched.group(2)) if matched.group(2) else start
        if end >= start and end - start <= 200:
            episodes.update(range(start, end + 1))

    # 中文 第23-25集 / 第23至25集。
    for matched in re.finditer(r"第\s*(\d{1,3})(?:\s*[-~—至]\s*(\d{1,3}))?\s*集", value):
        start = int(matched.group(1))
        end = int(matched.group(2)) if matched.group(2) else start
        if end >= start and end - start <= 200:
            episodes.update(range(start, end + 1))

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


def _extract_result_list(response: Any) -> List[dict]:
    """兼容光鸭接口多种列表字段。"""
    if not isinstance(response, dict):
        return []
    data = response.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        data = response
    for key in ("list", "files", "items", "records", "fileList", "infoList"):
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


class GuangYaTransferAssistant(_PluginBase):
    """对用户勾选的订阅固定走光鸭转存，未勾选固定走 MoviePilot 原生下载。"""

    plugin_name = "光鸭转存助手"
    plugin_desc = "订阅固定分流：手动勾选的订阅只使用光鸭频道转存，未勾选订阅只使用 MoviePilot 原生下载。"
    plugin_icon = "Guangyadisk_A.png"
    plugin_version = "1.3.0"
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
            self._inspect_cache.clear()
            logger.warning("【光鸭转存助手】【去重】已按配置清空转存库存与历史记录")
            config["clear_inventory"] = False
        self._cleanup_selected_ids()
        if path_migrated:
            logger.info("【光鸭转存助手】【路径】目标目录配置已规范化：%s -> %s", raw_save_path, self._save_path)
            self._save_config()
        if self._enabled:
            self._install_takeover()

    def get_state(self) -> bool:
        return self._enabled

    def get_service(self) -> List[Dict[str, Any]]:
        if not self._enabled:
            return []
        return [{
            "id": "GuangYaTransferAssistantTick",
            "name": "光鸭转存助手频道刷新与路由守护",
            "trigger": "interval",
            "func": self._tick,
            "kwargs": {"minutes": self._refresh_minutes},
        }]

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
                "events": {"click": {"api": "plugin/GuangYaTransferAssistant/check_missing", "method": "get", "params": {"subscribe_id": sid, "token": settings.API_TOKEN}}},
            }]
            if lack > 0:
                actions.append({
                    "component": "VBtn",
                    "props": {"size": "small", "variant": "text", "color": "warning", "prepend-icon": "mdi-download"},
                    "text": "切换普通下载",
                    "events": {"click": {"api": "plugin/GuangYaTransferAssistant/release_native", "method": "get", "params": {"subscribe_id": sid, "token": settings.API_TOKEN}}},
                })
            rows.append({
                "component": "VCard",
                "props": {"variant": "tonal", "class": "h-100"},
                "content": [
                    {"component": "VCardTitle", "text": f"{sub.name} ({getattr(sub, 'year', '') or '-'})"},
                    {"component": "VCardText", "text": f"订阅ID {sid} · 状态 {state}{progress_text}{missing_text}{serial_text} · 去重资源 {asset_count} 个 · {state_text}"},
                    {"component": "VCardActions", "content": actions},
                ],
            })
        fresh_count = len([item for item in (index.get("items") or []) if not item.get("stale")])
        stale_count = len(index.get("items") or []) - fresh_count
        contents: List[dict] = [{
            "component": "VAlert",
            "props": {
                "type": "warning" if last.get("stale_index") else ("success" if last.get("success") else "info"),
                "variant": "tonal",
                "text": f"频道索引 {len(index.get('items') or [])} 个（当前抓取 {fresh_count} / 回退缓存 {stale_count}）· 已处理消息/链接 {len(processed_entries)} · 已选择 {len(selected)} 个订阅 · 最近刷新 {index.get('time') or '-'}",
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
                {"component": "VCardText", "text": "显示链接类型、TMDB/集数提示、当前抓取/回退缓存状态及匹配原因；同一链接出现在新消息中会作为新条目处理，最多显示 150 条。"},
                {"component": "VList", "props": {"density": "compact"}, "content": resources or [{"component": "VListItem", "props": {"title": "暂无频道资源"}}]},
            ],
        })
        return contents

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {"path": "/refresh", "endpoint": self.api_refresh, "methods": ["POST"], "summary": "立即刷新频道索引"},
            {"path": "/transfer", "endpoint": self.api_transfer, "methods": ["POST"], "summary": "立即尝试一个订阅的光鸭转存"},
            {"path": "/folders", "endpoint": self.api_folders, "methods": ["GET"], "summary": "读取光鸭根目录文件夹"},
            {"path": "/check_missing", "endpoint": self.api_check_missing, "methods": ["GET"], "summary": "立即刷新并检查指定转存订阅缺集"},
            {"path": "/release_native", "endpoint": self.api_release_native, "methods": ["GET"], "summary": "将指定转存订阅切换回 MoviePilot 普通下载"},
        ]

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
        return self._try_transfer_subscription(subscribe, force=True)

    def api_folders(self) -> Dict[str, Any]:
        return {"success": True, "items": self._root_folder_options(raw=True)}

    def api_check_missing(self, subscribe_id: int = 0) -> Dict[str, Any]:
        """手动强制刷新频道并只检查该转存订阅当前缺失集。"""
        sid = int(subscribe_id or 0)
        subscribe = self._find_subscription(sid)
        if not sid or not subscribe:
            return {"success": False, "message": "订阅不存在"}
        if sid not in set(self._selected_subscriptions):
            return {"success": False, "message": "该订阅当前不是光鸭固定转存路线"}
        self.refresh_channels(force=True)
        self._inspect_cache.clear()
        result = self._try_transfer_subscription(subscribe, force=True)
        missing = self._subscription_missing_episodes(self._find_subscription(sid) or subscribe)
        result["missing_episodes"] = missing
        return result

    def api_release_native(self, subscribe_id: int = 0) -> Dict[str, Any]:
        """由用户明确操作后解除固定转存，后续交还 MoviePilot 原生订阅搜索。"""
        sid = int(subscribe_id or 0)
        subscribe = self._find_subscription(sid)
        if not sid or not subscribe:
            return {"success": False, "message": "订阅不存在"}
        missing = self._subscription_missing_episodes(subscribe)
        self._remove_selected_subscription(sid)
        logger.warning("【光鸭转存助手】【人工分流】#%s %s 已由用户切换为 MoviePilot 普通下载；当前缺失=%s", sid, getattr(subscribe, "name", ""), missing)
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
                logger.warning("【光鸭转存助手】【通知】发送人工切换通知失败：%s", err)
        return {"success": True, "message": "已切换为普通下载，后续由 MoviePilot 原生订阅任务处理缺集", "missing_episodes": missing}

    def _tick(self) -> None:
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

    def refresh_channels(self, force: bool = False) -> List[Dict[str, Any]]:
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
                        key = _entry_process_key(item) or _share_identity(item.get("share_url") or "")
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
                    fresh_keys = {_entry_process_key(item) or _share_identity(item.get("share_url") or "") for item in source_entries}
                    for old in previous_items:
                        if old.get("source_label") != label:
                            continue
                        key = _entry_process_key(old) or _share_identity(old.get("share_url") or "")
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

        # 当前抓取优先、热更频道优先；同一消息+同一分享只保留一条，新消息即使复用旧链接也保留。
        all_entries.sort(key=lambda item: (1 if item.get("stale") else 0, int(item.get("priority") or 0), -len(str(item.get("text") or ""))))
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
        logger.info("【光鸭转存助手】频道刷新完成，识别消息/分享 %s 个（当前抓取 %s / 回退缓存 %s），错误 %s 个", len(entries), fresh_count, stale_count, len(errors))
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
            suffix = f" S{int(season):02d}" if season not in (None, 0) else ""
            state_label = {"N": "新建", "R": "订阅中", "P": "待定", "S": "暂停"}.get(state, state or "-")
            media_type = str(getattr(sub, "type", "") or "").strip() or "媒体"
            done, total, lack = self._subscription_episode_progress(sub)
            progress = f" · 已完成 {done}/{total} · 剩余 {lack}" if total else ""
            options.append({"title": f"{sub.name} ({getattr(sub, 'year', '') or '-'}){suffix} · {media_type} · {state_label}{progress} · #{sid}", "value": sid})
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

    def _save_config(self) -> None:
        self.update_config({
            "enabled": self._enabled,
            "channel_urls": self._channel_urls,
            "selected_subscriptions": self._selected_subscriptions,
            "save_path": self._save_path,
            "create_media_folder": self._create_media_folder,
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
        logger.info(
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
            logger.info(
                "【光鸭转存助手】【连载保护】#%s %s 当前 %s/%s 已齐，但频道仍标记更新中；已稳定 %.1f/%s 天，暂不完成订阅",
                sid, getattr(subscribe, "name", ""), done, total, elapsed_days, self._ongoing_guard_days,
            )
            return False
        logger.info(
            "【光鸭转存助手】【连载保护】#%s %s 当前 %s/%s 已连续稳定 %.1f 天且未发现新集，允许完成订阅",
            sid, getattr(subscribe, "name", ""), done, total, elapsed_days,
        )
        return True

    def _entry_processed(self, entry: Dict[str, Any]) -> bool:
        key = _entry_process_key(entry)
        return bool(key and (self.get_data("processed_entries") or {}).get(key))

    def _mark_entry_processed(self, entry: Dict[str, Any], status: str, message: str = "") -> None:
        key = _entry_process_key(entry)
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
        }
        if len(records) > 5000:
            ordered = sorted(records.items(), key=lambda pair: str((pair[1] or {}).get("time") or ""), reverse=True)[:5000]
            records = dict(ordered)
        self.save_data("processed_entries", records)

    def _sync_media_library_progress(self, subscribe: Any) -> Dict[str, Any]:
        """以 MoviePilot 媒体库为事实源补齐 note/lack_episode，避免重复转存已入库剧集。"""
        sid = int(getattr(subscribe, "id", 0) or 0)
        media_type = str(getattr(subscribe, "type", "") or "").lower()
        season = getattr(subscribe, "season", None)
        if not sid or ("tv" not in media_type and "电视剧" not in str(getattr(subscribe, "type", "") or "") and season in (None, 0)):
            return {"success": True, "existing": [], "missing": []}
        try:
            season = int(season or 0)
            start = max(1, int(getattr(subscribe, "start_episode", 0) or 1))
            total = int(getattr(subscribe, "total_episode", 0) or 0)
        except (TypeError, ValueError):
            return {"success": False, "existing": [], "missing": []}
        if season <= 0 or total < start:
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
                logger.info(
                    "【光鸭转存助手】【媒体库同步】#%s %s 已从媒体库确认 %s 集；订阅进度 %s/%s，剩余 %s",
                    sid, getattr(subscribe, "name", ""), len(library_existing), len(target.intersection(merged)), len(target), lack,
                )
            return {"success": True, "existing": sorted(library_existing), "missing": sorted(target.difference(merged))}
        except Exception as err:
            logger.warning("【光鸭转存助手】【媒体库同步】#%s %s 同步失败：%s", sid, getattr(subscribe, "name", ""), err)
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
            logger.warning("【光鸭转存助手】安装订阅分流失败: %s", err)

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
            logger.warning("【光鸭转存助手】恢复原生订阅搜索失败: %s", err)
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
                    logger.warning("【光鸭转存助手】【分流】已勾选订阅 #%s 不存在；固定转存路线不触发原生下载", sid)
                    return True
                result = self._try_transfer_subscription(subscribe)
                logger.info("【光鸭转存助手】【分流】#%s %s 固定转存处理：%s", sid, getattr(subscribe, "name", ""), result.get("message") or "完成")
                return True

            subscriptions = self._list_subscriptions(state or "N,R")
            for index, subscribe in enumerate(subscriptions):
                subscribe_id = int(getattr(subscribe, "id", 0) or 0)
                if not subscribe_id:
                    continue
                callback = progress_callback if index == 0 else None
                if subscribe_id in selected:
                    result = self._try_transfer_subscription(subscribe)
                    logger.info("【光鸭转存助手】【分流】#%s %s 固定转存处理：%s", subscribe_id, getattr(subscribe, "name", ""), result.get("message") or "完成")
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

    def _try_transfer_subscription(self, subscribe: Any, force: bool = False) -> Dict[str, Any]:
        """对一个活跃订阅执行安全匹配、规则校验、文件级去重和增量转存。"""
        sid = int(getattr(subscribe, "id", 0) or 0)
        allowed, guard_reason = self._subscription_static_guard(subscribe)
        if not allowed:
            logger.info("【光鸭转存助手】【规则】#%s %s 不接管：%s", sid, getattr(subscribe, "name", ""), guard_reason)
            return {"success": False, "handled": True, "message": guard_reason}
        self.refresh_channels(force=False)
        # 每轮先以媒体库为事实源同步当前目标范围，频道没有新链接时也能去掉已入库重复集。
        self._sync_media_library_progress(subscribe)
        entries = list((self.get_data("channel_index") or {}).get("items") or [])
        pre_channel_state = self._channel_state_for_subscription(subscribe, entries)
        if self._finish_subscription_if_complete(subscribe, channel_state=pre_channel_state):
            media_kind = "电影" if self._is_movie_subscription(subscribe) else "剧集"
            return {"success": True, "handled": True, "completed": True, "message": f"{media_kind}目标已完成，订阅已移入历史"}
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
            detail = "仅命中旧缓存，等待频道恢复" if stale_matches else "频道暂未匹配到光鸭分享"
            logger.info("【光鸭转存助手】【匹配】#%s %s %s；固定转存路线不触发原生下载", sid, getattr(subscribe, "name", ""), detail)
            return {"success": False, "handled": True, "message": detail}
        logger.info("【光鸭转存助手】【匹配】#%s %s 命中 %s 个当前频道分享", sid, getattr(subscribe, "name", ""), len(matched_pairs))

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
            if not force and self._entry_processed(entry):
                processed_matches += 1
                continue
            action_pairs.append((entry, reason))
        if not action_pairs:
            done, total, lack = self._subscription_episode_progress(subscribe)
            logger.info(
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
                logger.warning("【光鸭转存助手】【匹配】分享读取失败 share_id=%s：%s", share_key.split("|", 1)[0], error)
                errors.append(error)
                continue
            resource_allowed, resource_reason = self._subscription_resource_allowed(subscribe, entry, probe)
            if not resource_allowed:
                logger.info("【光鸭转存助手】【规则】#%s %s share_id=%s 跳过并记为已处理：%s", sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0], resource_reason)
                self._mark_entry_processed(entry, "filtered", resource_reason)
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
                    logger.info("【光鸭转存助手】【重试】#%s %s share_id=%s 仍在失败退避期", sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0])
                    continue

            stats: Dict[str, int] = {}
            planned = self._plan_incremental_files(probe, assets, subscribe=subscribe, target_path=target_path, stats=stats)
            valid_route_match = True
            if stats.get("eligible", 0) <= 0:
                message = "分享内没有需要的新剧集；已入库/已完成/范围外内容不再重复测试"
                self._mark_entry_processed(entry, "no_new_episode", message)
                synchronized_match = True
                logger.info("【光鸭转存助手】【消息去重】#%s %s share_id=%s %s", sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0], message)
                continue

            # 兼容 1.0.x / 1.1.0：旧版整份分享已成功且内容未变时，仅补建文件库存。
            if not assets and old.get("success") and old.get("fingerprint") in {fingerprint, legacy_fingerprint}:
                migrated_stats: Dict[str, int] = {}
                migrated = self._plan_incremental_files(probe, {}, subscribe=subscribe, target_path=target_path, stats=migrated_stats)
                self._remember_assets(assets, migrated, share_key, target_path)
                inventory[sid_key] = {"assets": assets, "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                self.save_data("transfer_inventory", inventory)
                synchronized_match = True
                self._mark_entry_processed(entry, "legacy_synced", "旧版成功记录已建立文件级索引")
                logger.info("【光鸭转存助手】【去重】#%s %s 从旧版成功记录建立文件级索引 %s 个，不重复转存", sid, getattr(subscribe, "name", ""), len(migrated))
                continue

            if not planned:
                synchronized_match = True
                self._mark_entry_processed(entry, "synced", "库存或订阅进度已覆盖，无新增文件")
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
            if restored.get("success"):
                self._mark_entry_processed(entry, "transferred", restored.get("message") or "增量转存完成")
            else:
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
            partial = bool(errors) and not completed_subscription
            logger.info("【光鸭转存助手】【转存】#%s %s %s：新增 %s 个文件，累计去重 %s 个，剩余待下轮 %s，目标=%s", sid, getattr(subscribe, "name", ""), "订阅完成" if completed_subscription else ("部分完成" if partial else "增量完成"), len(unique_paths), len(assets), remaining_due_to_cap, target_path)
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
                logger.info("【光鸭转存助手】【通知】已发送%s通知：#%s %s", "部分转存" if partial else "增量转存成功", sid, getattr(subscribe, "name", ""))
            if partial:
                return {"success": False, "handled": True, "message": f"部分转存 {len(unique_paths)} 个文件，剩余等待下轮转存", "new_count": len(unique_paths), "target_path": target_path}
            return {"success": True, "handled": True, "completed": completed_subscription, "message": (f"转存成功，本次新增 {len(unique_paths)} 个文件；订阅已完成并移入历史" if completed_subscription else f"增量转存成功，本次新增 {len(unique_paths)} 个文件"), "new_count": len(unique_paths), "target_path": target_path, "remaining": remaining_due_to_cap}

        if valid_route_match and not errors and (synchronized_match or not attempted_new):
            if self._finish_subscription_if_complete(subscribe, channel_state=channel_state):
                return {"success": True, "handled": True, "completed": True, "message": "目标剧集已全部完成，订阅已移入历史"}
            done, total, lack = self._subscription_episode_progress(subscribe)
            logger.info("【光鸭转存助手】【去重】#%s %s 所有有效匹配均无新增；订阅进度 %s/%s，剩余 %s；固定转存路线不触发重复下载", sid, getattr(subscribe, "name", ""), done, total, lack)
            return {"success": True, "handled": True, "already": True, "message": f"已同步，无新增资源；进度 {done}/{total}，剩余 {lack}" if total else "已同步，无新增资源"}

        final_message = "；".join(dict.fromkeys(errors))[:1200] or "匹配分享均不可用"
        logger.warning("【光鸭转存助手】【失败】#%s %s 转存未完成：%s；固定转存路线不触发原生下载", sid, getattr(subscribe, "name", ""), final_message)
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
                            + "后续：保持转存路线，等待频道刷新或下次重试"
                        ),
                    )
                    notices[notice_key] = now.strftime("%Y-%m-%d %H:%M:%S")
                    self.save_data("failure_notices", notices)
                    logger.info("【光鸭转存助手】【通知】已发送转存失败通知：#%s %s（相同错误 6 小时内不重复推送）", sid, getattr(subscribe, "name", ""))
                except Exception as err:
                    logger.warning("【光鸭转存助手】【通知】发送失败通知异常：%s", err)
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
            logger.info(
                "【光鸭转存助手】【进度】#%s %s 本次确认剧集 %s；已完成 %s/%s，剩余 %s",
                getattr(subscribe, "id", 0), getattr(subscribe, "name", ""),
                ",".join(str(v) for v in sorted(episodes)), done, total, lack,
            )
        except Exception as err:
            logger.warning("【光鸭转存助手】【进度】同步 MoviePilot 订阅进度失败：%s", err)

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
                logger.info("【光鸭转存助手】【媒体库同步】#%s %s 电影已存在于媒体库，允许完成订阅", sid, getattr(subscribe, "name", ""))
                return True
        except Exception as err:
            logger.warning("【光鸭转存助手】【媒体库同步】#%s %s 检查电影媒体库状态失败：%s", sid, getattr(subscribe, "name", ""), err)
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
                        logger.warning("【光鸭转存助手】【进度】更新剩余集数失败：%s", err)
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
                logger.warning("【光鸭转存助手】【完成】#%s %s %s，但媒体识别失败，暂不移除订阅", sid, getattr(latest, "name", ""), progress)
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
                logger.warning("【光鸭转存助手】【完成】#%s %s %s，但 MoviePilot 完成流程后订阅仍存在", sid, getattr(latest, "name", ""), progress)
                return False
            self._clear_completion_guard(sid)
            self._remove_selected_subscription(sid)
            if is_movie:
                logger.info("【光鸭转存助手】【完成】#%s %s 电影已确认转存/媒体库存在；已通过 MoviePilot 官方流程移入订阅历史并从活动订阅移除", sid, getattr(latest, "name", ""))
            else:
                logger.info("【光鸭转存助手】【完成】#%s %s 已完成 %s/%s，剩余 0；已通过 MoviePilot 官方流程移入订阅历史并从活动订阅移除", sid, getattr(latest, "name", ""), done, total)
            return True
        except Exception:
            logger.exception("【光鸭转存助手】【完成】#%s %s 执行 MoviePilot 官方完成流程失败", sid, getattr(subscribe, "name", ""))
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
        manager = PluginManager()
        client = manager.get_plugin_attr("ShukGuangYaDisk", "_client")
        api = manager.get_plugin_attr("ShukGuangYaDisk", "_guangya_api")
        return client, api

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

    def _restore_items(self, probe: Dict[str, Any], save_path: str, items: List[Dict[str, Any]]) -> Dict[str, Any]:
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
                    return {"success": False, "message": f"无法创建/定位目标目录 {normalized}", "completed_items": completed, "task_ids": task_ids}
                parent_id = str(getattr(folder, "fileid", "") or "") if folder else ""
                file_ids = [str(item.get("id") or "") for item in group if item.get("id")]
                logger.info("【光鸭转存助手】【增量】提交目录 %s：新增文件 %s 个", normalized, len(file_ids))
                response = client._request(
                    method="POST",
                    url=f"{client.API_BASE_URL}/nd.bizuserres.s/v1/restore_share",
                    data={"accessToken": probe.get("access_token"), "fileIds": file_ids, "parentId": parent_id},
                    need_auth=True,
                )
                if not self._is_success(response):
                    return {"success": False, "message": str(response.get("msg") or response.get("error") or "光鸭增量转存失败"), "completed_items": completed, "task_ids": task_ids}
                data = response.get("data") or {}
                task_id = str(data.get("taskId") or data.get("task_id") or "") if isinstance(data, dict) else ""
                if task_id:
                    task_ids.append(task_id)
                if task_id and hasattr(api, "_wait_task_done"):
                    logger.info("【光鸭转存助手】【转存】等待增量任务完成：task_id=%s", task_id)
                    done = api._wait_task_done(task_id, max_try=120, interval=1, allow_missing=True)
                    if not done:
                        return {"success": False, "message": f"增量转存任务 {task_id} 未确认完成", "completed_items": completed, "task_ids": task_ids}
                completed.extend(group)
            return {
                "success": True, "message": f"增量转存完成，共新增 {len(completed)} 个文件",
                "completed_items": completed, "task_ids": task_ids,
                "confirmation": "所有增量转存任务已确认完成",
            }
        except Exception as err:
            logger.exception("【光鸭转存助手】【转存】执行增量转存异常：target=%s", save_path)
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
        self._restore_takeover()
        self._inspect_cache.clear()
