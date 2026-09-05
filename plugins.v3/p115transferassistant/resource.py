"""115 转存助手资源规范化。

三种入口最终都转换为稳定 source_key，供去重、任务恢复和跨来源栅栏使用。
"""

from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

from .models import SourceType

_SHARE_RE = re.compile(r"(?:https?://)?(?:115\.com|115cdn\.com)/s/([A-Za-z0-9_-]+)", re.I)
_ED2K_RE = re.compile(r"^ed2k://\|file\|([^|]+)\|(\d+)\|([0-9A-Fa-f]{32})\|/?$", re.I)


@dataclass(slots=True)
class NormalizedResource:
    source_type: SourceType
    source_key: str
    uri: str
    share_code: str = ""
    receive_code: str = ""
    info_hash: str = ""
    filename: str = ""
    size: int = 0
    ed2k_hash: str = ""

    @property
    def task_id(self) -> str:
        digest = hashlib.sha1(f"{self.source_type}:{self.source_key}".encode("utf-8")).hexdigest()
        return f"p115-{digest[:20]}"


def normalize_share(uri: str) -> NormalizedResource:
    raw = (uri or "").strip()
    match = _SHARE_RE.search(raw)
    if not match:
        raise ValueError("不是有效的 115 分享链接")
    share_code = match.group(1)
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    query = parse_qs(parsed.query)
    receive_code = (
        (query.get("password") or query.get("pwd") or query.get("receive_code") or [""])[0]
        or ""
    ).strip()
    return NormalizedResource(
        source_type=SourceType.SHARE115,
        source_key=share_code.lower(),
        uri=raw,
        share_code=share_code,
        receive_code=receive_code,
    )


def _normalize_btih(value: str) -> str:
    token = (value or "").strip()
    if re.fullmatch(r"[0-9A-Fa-f]{40}", token):
        return token.lower()
    if re.fullmatch(r"[A-Z2-7a-z2-7]{32}", token):
        try:
            return base64.b32decode(token.upper()).hex()
        except Exception as err:
            raise ValueError("BTIH Base32 无法解析") from err
    raise ValueError("Magnet 缺少有效 BTIH")


def normalize_magnet(uri: str) -> NormalizedResource:
    raw = (uri or "").strip()
    if not raw.lower().startswith("magnet:?"):
        raise ValueError("不是有效 Magnet")
    query = parse_qs(urlparse(raw).query)
    xt_values = query.get("xt") or []
    btih = ""
    for xt in xt_values:
        if str(xt).lower().startswith("urn:btih:"):
            btih = str(xt).split(":")[-1]
            break
    info_hash = _normalize_btih(btih)
    return NormalizedResource(
        source_type=SourceType.MAGNET,
        source_key=info_hash,
        uri=raw,
        info_hash=info_hash,
    )


def normalize_ed2k(uri: str) -> NormalizedResource:
    raw = (uri or "").strip()
    match = _ED2K_RE.match(raw)
    if not match:
        raise ValueError("不是有效 ED2K 文件链接")
    filename = unquote(match.group(1))
    size = int(match.group(2))
    ed2k_hash = match.group(3).lower()
    source_key = f"{ed2k_hash}:{size}"
    return NormalizedResource(
        source_type=SourceType.ED2K,
        source_key=source_key,
        uri=raw,
        filename=filename,
        size=size,
        ed2k_hash=ed2k_hash,
    )


def normalize_resource(uri: str) -> NormalizedResource:
    raw = (uri or "").strip()
    lowered = raw.lower()
    if lowered.startswith("magnet:?"):
        return normalize_magnet(raw)
    if lowered.startswith("ed2k://"):
        return normalize_ed2k(raw)
    if "115.com/s/" in lowered or "115cdn.com/s/" in lowered:
        return normalize_share(raw)
    raise ValueError("暂不支持该资源类型；仅支持 115 分享、Magnet、ED2K")
