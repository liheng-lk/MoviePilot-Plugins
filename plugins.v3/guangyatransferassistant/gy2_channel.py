"""频道适配：链接归一与不可支持类型识别。"""

from __future__ import annotations

import html
import re
from typing import Any, Dict, List
from urllib.parse import unquote, urlsplit


_MAGNET_RE = re.compile(r"(?i)magnet:\?[^\s\"'<>]+")
_ED2K_RE = re.compile(r"(?i)ed2k://\|file\|[^|\r\n<>]+\|\d+\|[0-9a-f]{32}\|/")
_GUANGYA_RE = re.compile(
    r"(?:(?:https?:)?//)?(?:www\.)?guangyapan\.com/(?:s|share)/[A-Za-z0-9_-]+(?:\?[^\s\"'<>]*)?",
    re.I,
)
_XUNLEI_RE = re.compile(r"https?://pan\.xunlei\.com/s/[^\s\"'<>，。；;]+", re.I)
_UNSUPPORTED_RE = re.compile(
    r"https?://(?:[\w.-]+\.)?(?:123865|123684|123pan|115cdn|115|anxia|pan\.baidu|aliyundrive|alipan|pan\.quark)\.[^\s\"'<>]+",
    re.I,
)


def normalize_channel_links(text: str) -> Dict[str, List[str]]:
    decoded = html.unescape(str(text or "")).replace("\\/", "/")
    # 展开简单 URL 编码包装
    for _ in range(2):
        decoded = unquote(decoded)
    return {
        "guangya": _GUANGYA_RE.findall(decoded),
        "xunlei": _XUNLEI_RE.findall(decoded),
        "magnet": _MAGNET_RE.findall(decoded),
        "ed2k": _ED2K_RE.findall(decoded),
        "unsupported": _UNSUPPORTED_RE.findall(decoded),
    }


class ChannelAdapter:
    """薄适配：供 MatchEngine / UI 诊断使用。"""

    def summarize_entry(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        blob = "\n".join(
            [
                str(entry.get("text") or ""),
                str(entry.get("share_url") or ""),
                str(entry.get("display_title") or ""),
            ]
        )
        links = normalize_channel_links(blob)
        return {
            "message_id": str(entry.get("message_id") or ""),
            "display_title": str(entry.get("display_title") or ""),
            "tmdb_id": str(entry.get("tmdb_id") or ""),
            "link_counts": {key: len(values) for key, values in links.items()},
            "has_executable": bool(links["guangya"] or links["xunlei"] or links["magnet"] or links["ed2k"]),
            "unsupported_only": bool(links["unsupported"]) and not (
                links["guangya"] or links["xunlei"] or links["magnet"] or links["ed2k"]
            ),
        }
