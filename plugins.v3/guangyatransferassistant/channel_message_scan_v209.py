"""2.0.9：Raw Channel HTML → Telegram message blocks（独立于 legacy parser）。"""
from __future__ import annotations

import html
import re
from typing import Any, Dict, List
from urllib.parse import urlparse


_RAW_HTML_MAX = 64 * 1024
_DATA_POST_RE = re.compile(
    r'<div[^>]*\bclass=["\'][^"\']*\btgme_widget_message\b[^"\']*["\'][^>]*\bdata-post=["\']([^"\']+)["\']|'
    r'<div[^>]*\bdata-post=["\']([^"\']+)["\'][^>]*\bclass=["\'][^"\']*\btgme_widget_message\b',
    re.I | re.S,
)
_DATA_POST_ATTR_RE = re.compile(r'\bdata-post\s*=\s*["\']([^"\']+)["\']', re.I)
_WRAP_START_RE = re.compile(
    r'<(?:div|article)[^>]+class=["\'][^"\']*'
    r'(?:tgme_widget_message_wrap|js-widget_message_wrap|message_wrap|tme_messages_message|widget_message)'
    r'[^"\']*["\']',
    re.I | re.S,
)


def _html_to_visible_text(fragment: str) -> str:
    value = re.sub(r"<script\b[^>]*>.*?</script>", " ", str(fragment or ""), flags=re.I | re.S)
    value = re.sub(r"<style\b[^>]*>.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"(?i)<br\s*/?>|</(?:div|p|li|section|article|blockquote)\s*>", "\n", value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    lines = [re.sub(r"\s+", " ", line).strip() for line in value.splitlines()]
    return "\n".join(line for line in lines if line)


def _channel_slug(source_url: str, data_post: str = "") -> str:
    if "/" in str(data_post or ""):
        return str(data_post).split("/", 1)[0].strip() or ""
    try:
        path = (urlparse(str(source_url or "")).path or "").strip("/")
    except Exception:
        path = ""
    return path.split("/")[0] if path else str(source_url or "")[-40:]


def _message_id_from_post(data_post: str) -> str:
    text = str(data_post or "").strip()
    if "/" in text:
        return text.rsplit("/", 1)[-1].strip()
    return text


def _slice_message_html(page_html: str, start: int, end: int) -> str:
    chunk = str(page_html or "")[start:end]
    if len(chunk) > _RAW_HTML_MAX:
        chunk = chunk[:_RAW_HTML_MAX]
    return chunk


def extract_channel_message_blocks_v209(page_html: str, source_url: str = "") -> List[Dict[str, Any]]:
    """Split raw TGM HTML into message-local blocks.

    Prefer ``data-post="channel/id"`` boundaries. Never use position±1800 mixing
    when data-post markers exist.
    """
    html_text = str(page_html or "")
    if not html_text.strip():
        return []

    markers = list(_DATA_POST_ATTR_RE.finditer(html_text))
    blocks: List[Dict[str, Any]] = []
    if markers:
        for index, marker in enumerate(markers):
            data_post = marker.group(1)
            # Prefer the opening tag that owns this data-post.
            open_start = html_text.rfind("<", 0, marker.start())
            if open_start < 0:
                open_start = marker.start()
            # Prefer wrap container if immediately before.
            wrap_probe = html_text[max(0, open_start - 220):open_start]
            wrap_hit = list(_WRAP_START_RE.finditer(wrap_probe))
            if wrap_hit:
                open_start = max(0, open_start - 220) + wrap_hit[-1].start()
            if index + 1 < len(markers):
                next_start = markers[index + 1].start()
                end = html_text.rfind("<", open_start + 1, next_start)
                if end <= open_start:
                    end = next_start
            else:
                end = min(len(html_text), open_start + _RAW_HTML_MAX)
            raw_html = _slice_message_html(html_text, open_start, end)
            message_id = _message_id_from_post(data_post)
            channel = _channel_slug(source_url, data_post)
            blocks.append({
                "source_url": str(source_url or ""),
                "channel": channel,
                "message_id": message_id,
                "data_post": data_post,
                "raw_html": raw_html,
                "visible_text": _html_to_visible_text(raw_html),
                "discovered_order": index,
            })
        return blocks

    # Compatibility fallback without data-post: wrap containers only.
    wraps = list(_WRAP_START_RE.finditer(html_text))
    if not wraps:
        return []
    for index, wrap in enumerate(wraps):
        start = wrap.start()
        end = wraps[index + 1].start() if index + 1 < len(wraps) else min(len(html_text), start + _RAW_HTML_MAX)
        raw_html = _slice_message_html(html_text, start, end)
        post = _DATA_POST_ATTR_RE.search(raw_html)
        data_post = post.group(1) if post else ""
        message_id = _message_id_from_post(data_post) or str(index + 1)
        blocks.append({
            "source_url": str(source_url or ""),
            "channel": _channel_slug(source_url, data_post),
            "message_id": message_id,
            "data_post": data_post,
            "raw_html": raw_html,
            "visible_text": _html_to_visible_text(raw_html),
            "discovered_order": index,
        })
    return blocks


def page_has_resource_features_v209(page_html: str) -> bool:
    """Heuristic: page looks like it contains share buttons / URLs."""
    text = str(page_html or "")
    if not text:
        return False
    if re.search(r"(?i)查看资源|资源链接|复制链接|点击保存|光鸭云盘", text):
        return True
    if re.search(r"(?i)guangyapan\.com|guangyunav\.com|pan\.xunlei\.com|magnet:\?|ed2k://", text):
        return True
    if re.search(r"(?i)data-(?:clipboard-text|url|href|link|button-url|share-url)\s*=", text):
        return True
    return False


# Alias required by the round brief (vNext naming).
extract_channel_message_blocks_vNext = extract_channel_message_blocks_v209


__all__ = [
    "extract_channel_message_blocks_v209",
    "extract_channel_message_blocks_vNext",
    "page_has_resource_features_v209",
    "_RAW_HTML_MAX",
]
