"""v1.9.0 Telegram 多来源消息兼容层。

同一条频道消息是一个 ResourceGroup；光鸭分享、Magnet、ED2K 都只是该组的候选获取方式。
本补丁保持 legacy 光鸭分享索引兼容，同时让“仅含磁力/ED2K”的消息也进入统一频道索引。

v1.12.20 开发阶段补充两个频道完整性修复：
- 兼容当前热更模板“📺 剧集：标题 (年份) SxxExx / 🎬 电影：标题 (年份)”，模板类型前缀和季集号不再污染媒体标题；
- legacy 分页未追到旧游标时绝不提交新游标，单轮有界扩大分页深度，仍未追到则保留旧游标并持久化下一轮追赶预算。
"""

from __future__ import annotations

import functools
import hashlib
import html
import re
from typing import Any, Dict, List
from urllib.parse import urlsplit, urlunsplit, unquote

from .source_types_v180 import normalize_source_uri


_MAGNET_RE = re.compile(r"(?i)magnet:\?[^\s\"'<>]+")
# 允许 HTML 实体解码后的 |，以及 URL 编码残留经 unquote 后的完整 ed2k
_ED2K_RE = re.compile(
    r"(?i)ed2k://\|file\|[^|\r\n<>]+\|\d+\|[0-9a-fA-F]{32}\|/"
)
_ATTR_URL_RE = re.compile(
    r"(?i)\b(?:href|data-href|data-url|data-link|data-button-url|onclick)\s*=\s*([\"'])(.*?)\1",
    re.S,
)
_CHANNEL_CATCHUP_KEY_V11220 = "channel_catchup_v11220"
_CHANNEL_CATCHUP_MAX_PAGES_V11220 = 256
_CHANNEL_CATCHUP_ATTEMPTS_V11220 = 3
_LIVE_CHANNEL_HEADER_V11220 = re.compile(
    r"(?:🎬|📺)\s*(?:(?:电影|剧集|电视剧|动漫|动画)\s*[：:]\s*)?([^\n]{2,360})",
    re.I,
)


def _normalize_channel_source_urls_v11221(values: List[str], legacy_module: Any) -> List[str]:
    """兼容根域名配置：tgm.li668.asia -> 默认频道路径。"""
    defaults = list(getattr(legacy_module, "DEFAULT_CHANNEL_URLS", []) or [])
    default_paths: List[str] = []
    default_hosts = set()
    for item in defaults:
        raw = str(item or "").strip()
        if not raw:
            continue
        try:
            parsed = urlsplit(raw)
        except ValueError:
            continue
        host = (parsed.hostname or "").lower()
        if host:
            default_hosts.add(host)
        path = str(parsed.path or "").strip()
        if path and path != "/" and path not in default_paths:
            default_paths.append(path.rstrip("/"))

    rows: List[str] = []
    seen = set()
    for item in values:
        raw = html.unescape(str(item or "")).replace("\\/", "/").strip()
        if not raw:
            continue
        if not re.match(r"(?i)^https?://", raw):
            raw = "https://" + raw.lstrip("/")
        try:
            parsed = urlsplit(raw)
        except ValueError:
            continue
        host = (parsed.hostname or "").lower()
        if not host:
            continue
        scheme = parsed.scheme or "https"
        netloc = parsed.netloc
        path = str(parsed.path or "").strip()
        query = str(parsed.query or "").strip()
        if path and path != "/":
            normalized = urlunsplit((scheme, netloc, path.rstrip("/"), query, ""))
            if normalized not in seen:
                seen.add(normalized)
                rows.append(normalized)
            continue
        if host in default_hosts and default_paths:
            for default_path in default_paths:
                expanded = urlunsplit((scheme, netloc, default_path, query, ""))
                if expanded in seen:
                    continue
                seen.add(expanded)
                rows.append(expanded)
            continue
        normalized = urlunsplit((scheme, netloc, "", query, ""))
        if normalized not in seen:
            seen.add(normalized)
            rows.append(normalized)
    return rows


def _resource_group_id(source_url: str, message_id: str, text: str) -> str:
    if message_id:
        marker = f"msg:{message_id}"
    else:
        stable = re.sub(r"\s+", " ", str(text or "")).strip()
        marker = "txt:" + hashlib.sha256(stable.encode("utf-8")).hexdigest()[:20]
    return hashlib.sha256(f"{source_url}|{marker}".encode("utf-8")).hexdigest()[:24]


def _clean_external_uri(value: str) -> str:
    value = html.unescape(str(value or "")).replace("\\/", "/").strip()
    return value.rstrip(".,，。;；)）]】")


def _better_episode_hint(text: Any, current: Any = "") -> str:
    """补足 legacy 旧模板对四位绝对集号/“话”格式的覆盖。"""
    current = str(current or "").strip()
    raw = str(text or "")
    patterns = (
        r"(?i)S\d{1,2}\s*[._ -]*E\d{1,4}(?:\s*[-~～—至+]\s*E?\d{1,4})?",
        r"(?i)(?:EP|Episode)[\s._-]*\d{1,4}(?:\s*[-~～—至+]\s*(?:EP|Episode)?\s*\d{1,4})?",
        r"第\s*\d{1,4}\s*[-~～—至]\s*\d{1,4}\s*[集话]",
        r"第\s*\d{1,4}\s*[集话]",
        r"(?:更新至|更新到|更至)\s*(?:第\s*)?\d{1,4}\s*[集话]?",
    )
    for pattern in patterns:
        matched = re.search(pattern, raw)
        if matched:
            candidate = matched.group(0).strip()
            # legacy 已经给出更具体的 SxxExx 时继续保留；否则采用四位/话等增强结果。
            if not current or len(re.findall(r"\d", candidate)) > len(re.findall(r"\d", current)) or "话" in candidate:
                return candidate[:120]
    return current[:120]


def _clean_live_channel_title_v11220(value: Any) -> str:
    """把频道模板字段剥离成作品标题；不做任何模糊标题改写。"""
    title = html.unescape(str(value or "")).strip()
    title = re.sub(r"^[\s🎬🎞🎥📺]+", "", title).strip()
    title = re.sub(r"^(?:电影|剧集|电视剧|动漫|动画)\s*[：:]\s*", "", title, flags=re.I).strip()
    title = re.sub(r"\s+", " ", title)
    title = re.sub(
        r"\s*[（(]\s*(?:19\d{2}|20\d{2})\s*[）)]"
        r"(?:\s*S\d{1,2}(?:\s*[._ -]*E\d{1,4}(?:\s*[-~～—至+]\s*E?\d{1,4})?)?)?"
        r"\s*(?:已?更新|更新中|已?完结|完结|全集|全季)?\s*$",
        "",
        title,
        flags=re.I,
    ).strip()
    title = re.sub(r"\s*(?:已?更新|更新中|已?完结|完结)\s*$", "", title, flags=re.I).strip()
    return title[:300]


def _install_channel_title_compat_v11220(legacy_module: Any) -> None:
    """热重载安全地把当前 tgm 热更模板接入 legacy 标题解析。"""
    current_clean = getattr(legacy_module, "_clean_channel_display_title", None)
    current_extract = getattr(legacy_module, "_extract_channel_display_title", None)
    if not callable(current_clean) or not callable(current_extract):
        return
    if getattr(current_extract, "_guangya_live_channel_title_v11220", False):
        return

    original_clean = current_clean
    original_extract = current_extract

    @functools.wraps(original_clean)
    def patched_clean(value: Any) -> str:
        # 先复用既有清洗，再补当前频道的类型前缀/季集尾巴；如果旧清洗未处理则直接处理原值。
        cleaned = _clean_live_channel_title_v11220(original_clean(value))
        if cleaned:
            return cleaned
        return _clean_live_channel_title_v11220(value)

    legacy_module._clean_channel_display_title = patched_clean

    @functools.wraps(original_extract)
    def patched_extract_title(value: Any) -> str:
        raw = str(value or "")
        matched = _LIVE_CHANNEL_HEADER_V11220.search(raw)
        if matched:
            candidate = str(matched.group(1) or "")
            boundary = getattr(legacy_module, "_CHANNEL_META_BOUNDARY", None)
            if boundary is not None:
                try:
                    candidate = boundary.split(candidate, maxsplit=1)[0]
                except Exception:
                    pass
            cleaned = patched_clean(candidate)
            if cleaned:
                return cleaned
        return patched_clean(original_extract(value))

    patched_extract_title._guangya_live_channel_title_v11220 = True
    patched_extract_title._guangya_original_extract_channel_title = original_extract
    legacy_module._extract_channel_display_title = patched_extract_title


def _cursor_snapshot_v11220(raw: Any) -> Dict[str, int]:
    result: Dict[str, int] = {}
    if not isinstance(raw, dict):
        return result
    for source, row in raw.items():
        value = row.get("last_message_id") if isinstance(row, dict) else row
        try:
            cursor = int(value or 0)
        except (TypeError, ValueError):
            cursor = 0
        result[str(source or "").strip()] = max(0, cursor)
    return result


def _channel_label_v11220(source_url: str) -> str:
    return "光鸭云盘影视热更频道" if "regeng" in str(source_url or "").lower() else "光鸭云盘资源分享频道"


def _install_channel_cursor_completeness_v11220(legacy_module: Any) -> None:
    """包住 legacy.refresh_channels：没追到旧游标就回滚游标，绝不越过未读消息。"""
    assistant_cls = getattr(legacy_module, "GuangYaTransferAssistant", None)
    current_refresh = getattr(assistant_cls, "refresh_channels", None) if assistant_cls else None
    if not callable(current_refresh) or getattr(current_refresh, "_guangya_channel_complete_v11220", False):
        return
    original_refresh = current_refresh

    @functools.wraps(original_refresh)
    def patched_refresh(self, force: bool = False):
        source_urls = list(self._source_urls() or [])
        before_raw = self.get_data("channel_cursors") or {}
        before_cursors = _cursor_snapshot_v11220(before_raw)
        catchup = self.get_data(_CHANNEL_CATCHUP_KEY_V11220) or {}
        if not isinstance(catchup, dict):
            catchup = {}
        catchup = dict(catchup)
        try:
            configured_pages = max(1, int(getattr(self, "_history_pages", 1) or 1))
        except (TypeError, ValueError):
            configured_pages = 1
        active_budgets = []
        for source_url in source_urls:
            row = catchup.get(source_url) or {}
            try:
                active_budgets.append(int((row or {}).get("page_budget") or 0))
            except (TypeError, ValueError):
                pass
        page_budget = min(
            _CHANNEL_CATCHUP_MAX_PAGES_V11220,
            max([configured_pages, *active_budgets]),
        )
        rows: List[Dict[str, Any]] = []
        incomplete: Dict[str, Dict[str, Any]] = {}
        last_index: Dict[str, Any] = {}

        for attempt in range(_CHANNEL_CATCHUP_ATTEMPTS_V11220):
            previous_limit = getattr(self, "_history_pages", configured_pages)
            self._history_pages = page_budget
            try:
                rows = list(original_refresh(self, force=bool(force or catchup or attempt > 0)) or [])
            finally:
                self._history_pages = previous_limit

            after_raw = self.get_data("channel_cursors") or {}
            after_cursors = _cursor_snapshot_v11220(after_raw)
            last_index = dict(self.get_data("channel_index") or {})
            source_status = dict(last_index.get("source_status") or {})
            incomplete = {}
            for source_url in source_urls:
                old_cursor = int(before_cursors.get(source_url, 0) or 0)
                new_cursor = int(after_cursors.get(source_url, 0) or 0)
                status = dict(source_status.get(_channel_label_v11220(source_url)) or {})
                if (
                    old_cursor > 0
                    and new_cursor > old_cursor
                    and bool(status.get("success"))
                    and not bool(status.get("reached_cursor"))
                ):
                    incomplete[source_url] = {
                        "old_cursor": old_cursor,
                        "high_watermark": new_cursor,
                        "status": status,
                    }

            if not incomplete:
                changed = False
                for source_url in source_urls:
                    status = dict(source_status.get(_channel_label_v11220(source_url)) or {})
                    if bool(status.get("success")) and source_url in catchup:
                        catchup.pop(source_url, None)
                        changed = True
                    if status and status.get("catchup_incomplete"):
                        status["catchup_incomplete"] = False
                        status["page_budget"] = page_budget
                        source_status[_channel_label_v11220(source_url)] = status
                        changed = True
                if changed:
                    catchup = {
                        key: dict(value) for key, value in catchup.items()
                        if key in set(source_urls) and isinstance(value, dict)
                    }
                    last_index["source_status"] = source_status
                    self.save_data("channel_index", last_index)
                    self.save_data(_CHANNEL_CATCHUP_KEY_V11220, catchup)
                return rows

            # legacy 已经把游标推进到当前抓取的最高 ID；在继续翻页前先恢复旧游标。
            restored_cursors = dict(after_raw) if isinstance(after_raw, dict) else {}
            for source_url, detail in incomplete.items():
                old_row = dict((before_raw or {}).get(source_url) or {}) if isinstance((before_raw or {}).get(source_url), dict) else {}
                old_row["last_message_id"] = int(detail["old_cursor"])
                restored_cursors[source_url] = old_row
            self.save_data("channel_cursors", restored_cursors)

            if attempt + 1 < _CHANNEL_CATCHUP_ATTEMPTS_V11220 and page_budget < _CHANNEL_CATCHUP_MAX_PAGES_V11220:
                page_budget = min(
                    _CHANNEL_CATCHUP_MAX_PAGES_V11220,
                    max(configured_pages * 2, page_budget * 2),
                )
                continue
            break

        # 本轮有界追赶仍未触达旧游标：保留旧游标，并为下轮继续扩大预算；这是延迟，不是静默丢失。
        index = dict(self.get_data("channel_index") or last_index or {})
        source_status = dict(index.get("source_status") or {})
        next_budget = min(
            _CHANNEL_CATCHUP_MAX_PAGES_V11220,
            max(configured_pages * 2, page_budget * 2),
        )
        now_text = ""
        now_reader = getattr(self, "_now_text", None)
        if callable(now_reader):
            try:
                now_text = str(now_reader() or "")
            except Exception:
                now_text = ""
        for source_url, detail in incomplete.items():
            old_cursor = int(detail["old_cursor"])
            high_watermark = int(detail["high_watermark"])
            catchup[source_url] = {
                "last_message_id": old_cursor,
                "high_watermark": high_watermark,
                "page_budget": next_budget,
                "updated": now_text,
            }
            label = _channel_label_v11220(source_url)
            status = dict(source_status.get(label) or detail.get("status") or {})
            status.update({
                "cursor": old_cursor,
                "high_watermark": high_watermark,
                "page_budget": page_budget,
                "next_page_budget": next_budget,
                "catchup_incomplete": True,
            })
            source_status[label] = status
            self._plugin_log(
                "WARNING",
                "【光鸭转存助手】【频道完整性v1.12.20】%s 已抓到高水位 %s，但 %s 页预算仍未追到旧游标 %s；"
                "已回退游标，下一轮页预算=%s，不会越过未读取消息",
                label,
                high_watermark,
                page_budget,
                old_cursor,
                next_budget,
            )
        catchup = {
            key: dict(value) for key, value in catchup.items()
            if key in set(source_urls) and isinstance(value, dict)
        }
        index["source_status"] = source_status
        self.save_data("channel_index", index)
        self.save_data(_CHANNEL_CATCHUP_KEY_V11220, catchup)
        return rows

    patched_refresh._guangya_channel_complete_v11220 = True
    patched_refresh._guangya_original_refresh_channels = original_refresh
    assistant_cls.refresh_channels = patched_refresh


def _channel_slug_from_url(source_url: str) -> str:
    try:
        path = str(urlsplit(str(source_url or "")).path or "").strip("/")
    except ValueError:
        return str(source_url or "")[-40:]
    return path.split("/")[-1] if path else str(source_url or "")[-40:]


_CHANNEL_DECODE_MAX_CHARS = 2_000_000


def _decode_channel_blob(value: Any) -> str:
    """occurrence discovery 前规范化：HTML 实体 → \\/ / \\u002F → 有限次 unquote。"""
    current = html.unescape(str(value or ""))
    if len(current) > _CHANNEL_DECODE_MAX_CHARS:
        current = current[:_CHANNEL_DECODE_MAX_CHARS]
    current = current.replace("\\/", "/").replace("\\u002F", "/").replace("\\u002f", "/")
    for _ in range(3):
        decoded = unquote(current)
        if decoded == current:
            break
        current = decoded
        if len(current) > _CHANNEL_DECODE_MAX_CHARS:
            current = current[:_CHANNEL_DECODE_MAX_CHARS]
            break
    return current


def _external_sources_from_context(context_html: str) -> List[Dict[str, Any]]:
    # 先整段 decode，再 finditer；属性值同样先 decode
    raw = str(context_html or "")
    decoded = _decode_channel_blob(raw)
    attr_bits = []
    for matched in _ATTR_URL_RE.finditer(raw):
        attr_bits.append(_decode_channel_blob(matched.group(2)))
    if attr_bits:
        decoded = decoded + "\n" + "\n".join(attr_bits)
    rows: List[Dict[str, Any]] = []
    seen = set()
    matches = [(item.start(), item.group(0)) for item in _MAGNET_RE.finditer(decoded)]
    matches.extend((item.start(), item.group(0)) for item in _ED2K_RE.finditer(decoded))
    matches.sort(key=lambda pair: pair[0])
    for _, raw in matches:
        uri = _clean_external_uri(raw)
        try:
            normalized = normalize_source_uri(uri)
        except Exception:
            continue
        key = f"{normalized.get('type')}:{normalized.get('identity')}"
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "type": str(normalized.get("type") or ""),
            "uri": uri,
            "identity": str(normalized.get("identity") or ""),
            "name": str(normalized.get("name") or "")[:300],
            "size": int(normalized.get("size") or 0),
        })
    return rows


def _log_resource_discovery(legacy_module: Any, source_url: str, entry: Dict[str, Any]) -> None:
    """频道级调试日志；不打印 cookie/token。"""
    logger = getattr(legacy_module, "logger", None)
    if logger is None:
        return
    channel = _channel_slug_from_url(source_url)
    message_id = str(entry.get("message_id") or "") or "-"
    xunlei_n = len(entry.get("xunlei_sources") or [])
    guangya_n = 1 if str(entry.get("share_url") or "").strip() else 0
    magnet_n = sum(1 for item in (entry.get("external_sources") or []) if str(item.get("type") or "") == "magnet")
    ed2k_n = sum(1 for item in (entry.get("external_sources") or []) if str(item.get("type") or "") == "ed2k")
    try:
        logger.info(
            "【光鸭转存助手】【频道】channel=%s message_id=%s",
            channel,
            message_id,
        )
        logger.info(
            "【光鸭转存助手】【资源发现】xunlei=%s guangya=%s magnet=%s ed2k=%s",
            xunlei_n,
            guangya_n,
            magnet_n,
            ed2k_n,
        )
        title = str(entry.get("display_title") or entry.get("title") or "")[:120]
        if title or entry.get("episode_hint"):
            logger.info(
                "【光鸭转存助手】【媒体匹配】title=%s season=%s episodes=%s",
                title or "-",
                entry.get("season_hint") or entry.get("season") or "-",
                entry.get("episode_hint") or "-",
            )
    except Exception:
        return


def install_channel_multisource_compat(legacy_module: Any):
    """热重载安全地扩展频道解析器、消息稳定键和 v1.12.20 完整性补丁。"""
    _install_channel_title_compat_v11220(legacy_module)
    _install_channel_cursor_completeness_v11220(legacy_module)
    assistant_cls = getattr(legacy_module, "GuangYaTransferAssistant", None)
    current_source_urls = getattr(assistant_cls, "_source_urls", None) if assistant_cls else None
    if callable(current_source_urls) and not getattr(current_source_urls, "_guangya_source_urls_v11221", False):
        original_source_urls = current_source_urls

        @functools.wraps(original_source_urls)
        def patched_source_urls(self) -> List[str]:
            original = [str(item or "").strip() for item in (original_source_urls(self) or []) if str(item or "").strip()]
            normalized = _normalize_channel_source_urls_v11221(original, legacy_module)
            if normalized:
                return normalized
            fallbacks = [str(item or "").strip() for item in (getattr(legacy_module, "DEFAULT_CHANNEL_URLS", []) or []) if str(item or "").strip()]
            return fallbacks

        patched_source_urls._guangya_source_urls_v11221 = True
        patched_source_urls._guangya_original_source_urls = original_source_urls
        assistant_cls._source_urls = patched_source_urls

    current_extract = getattr(legacy_module, "_extract_channel_entries", None)
    current_key = getattr(legacy_module, "_entry_process_key", None)
    if not callable(current_extract) or not callable(current_key):
        return None

    if not getattr(current_key, "_guangya_resource_group_key", False):
        original_key = current_key

        @functools.wraps(original_key)
        def patched_key(entry: Dict[str, Any]) -> str:
            existing = original_key(entry)
            if existing:
                return existing
            group_id = str((entry or {}).get("resource_group_id") or "").strip()
            if not group_id:
                return ""
            return hashlib.sha256(f"resource-group|{group_id}".encode("utf-8")).hexdigest()

        patched_key._guangya_resource_group_key = True
        patched_key._guangya_original_entry_process_key = original_key
        legacy_module._entry_process_key = patched_key

    current_extract = getattr(legacy_module, "_extract_channel_entries", None)
    if getattr(current_extract, "_guangya_channel_multisource", False):
        return current_extract
    original_extract = current_extract

    @functools.wraps(original_extract)
    def patched_extract(page_text: str, source_url: str, source_label: str) -> List[Dict[str, Any]]:
        base_entries = list(original_extract(page_text, source_url, source_label) or [])
        # 必须在 Magnet/ED2K occurrence discovery 之前完成 URL decode
        decoded = _decode_channel_blob(page_text)
        occurrence_positions = [item.start() for item in _MAGNET_RE.finditer(decoded)]
        occurrence_positions.extend(item.start() for item in _ED2K_RE.finditer(decoded))

        groups: Dict[str, Dict[str, Any]] = {}
        for position in sorted(set(occurrence_positions)):
            context_html = legacy_module._message_context_html(decoded, position)
            context = legacy_module._html_to_text(context_html)
            external = _external_sources_from_context(context_html)
            if not external:
                continue
            metadata = dict(legacy_module._entry_metadata(context, context_html) or {})
            metadata["episode_hint"] = _better_episode_hint(context, metadata.get("episode_hint"))
            message_id = str(metadata.get("message_id") or "")
            group_id = _resource_group_id(source_url, message_id, context)
            row = groups.get(group_id)
            if row is None:
                row = {
                    "resource_group_id": group_id,
                    "text": context[:4000],
                    "source_url": source_url,
                    "source_label": source_label,
                    "priority": 0 if "regeng" in source_url.lower() else 1,
                    "stale": False,
                    "cached_index": False,
                    "external_sources": [],
                    **metadata,
                }
                groups[group_id] = row
            seen = {f"{item.get('type')}:{item.get('identity')}" for item in row["external_sources"]}
            for item in external:
                key = f"{item.get('type')}:{item.get('identity')}"
                if key not in seen:
                    seen.add(key)
                    row["external_sources"].append(item)

        attached_groups = set()
        for entry in base_entries:
            entry["episode_hint"] = _better_episode_hint(entry.get("text"), entry.get("episode_hint"))
            message_id = str(entry.get("message_id") or "")
            candidates = []
            for group_id, group in groups.items():
                same_message = bool(message_id and message_id == str(group.get("message_id") or ""))
                if not same_message and not message_id and str(entry.get("text") or "") == str(group.get("text") or ""):
                    same_message = True
                if not same_message:
                    continue
                entry["resource_group_id"] = group_id
                entry["external_sources"] = list(group.get("external_sources") or [])
                entry["candidate_types"] = ["guangya", *[str(item.get("type") or "") for item in entry["external_sources"]]]
                attached_groups.add(group_id)
                candidates = entry["external_sources"]
                break
            if not candidates:
                group_id = _resource_group_id(source_url, message_id, str(entry.get("text") or ""))
                entry["resource_group_id"] = group_id
                entry.setdefault("external_sources", [])
                entry["candidate_types"] = ["guangya"]

        for group_id, group in groups.items():
            if group_id in attached_groups:
                continue
            pseudo = {
                **group,
                "share_url": "",
                "share_id": "",
                "link_style": "外部资源",
                "candidate_types": [str(item.get("type") or "") for item in group.get("external_sources") or []],
            }
            base_entries.append(pseudo)

        for entry in base_entries:
            if entry.get("external_sources") or entry.get("share_url") or entry.get("xunlei_sources"):
                _log_resource_discovery(legacy_module, source_url, entry)

        return base_entries

    patched_extract._guangya_channel_multisource = True
    patched_extract._guangya_original_extract_channel_entries = original_extract
    legacy_module._extract_channel_entries = patched_extract
    return patched_extract


__all__ = [
    "install_channel_multisource_compat",
]
