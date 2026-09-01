"""Magnet/ED2K 来源规范化与稳定身份。"""

from __future__ import annotations

import base64
import hashlib
import re
from typing import Any, Dict
from urllib.parse import parse_qs, unquote, urlsplit


SOURCE_TYPES = ("guangya", "magnet", "ed2k")
SOURCE_SCHEMA_VERSION = 2
# queued 已经对应服务端 taskId，必须继续轮询而不是再次 create_task。
SOURCE_PENDING_STATES = {"new", "retry"}
SOURCE_INFLIGHT_STATES = {"dispatching", "submitted", "queued", "waiting"}
# needs_review 表示已解析资源，但集号置信度不足；必须人工确认或换候选，不能自动重试整包。
SOURCE_TERMINAL_STATES = {"completed", "failed", "disabled", "needs_review"}

_BTih_RE = re.compile(r"^(?:[0-9a-fA-F]{40}|[A-Z2-7a-z2-7]{32})$")
_ED2K_HASH_RE = re.compile(r"^[0-9a-fA-F]{32}$")


def safe_int(value: Any, default: int = 0, minimum: int = 0) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, result)


def source_identity(source_type: str, identity: str, subscribe_id: int = 0) -> str:
    raw = f"{int(subscribe_id or 0)}|{source_type}|{identity}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def normalize_magnet(uri: str) -> Dict[str, Any]:
    text = str(uri or "").strip()
    if not text.lower().startswith("magnet:?"):
        raise ValueError("不是有效的 Magnet 链接")
    query = parse_qs(urlsplit(text).query, keep_blank_values=True)
    btih = ""
    for value in query.get("xt") or []:
        match = re.match(r"(?i)^urn:btih:([0-9a-z]+)$", str(value or "").strip())
        if match and _BTih_RE.fullmatch(match.group(1)):
            btih = match.group(1)
            break
    if not btih:
        raise ValueError("Magnet 缺少合法的 xt=urn:btih")
    if len(btih) == 32:
        try:
            identity = base64.b32decode(btih.upper()).hex()
        except Exception as err:
            raise ValueError("Magnet BTIH Base32 无法解码") from err
    else:
        identity = btih.lower()
    name = unquote(str((query.get("dn") or [""])[0] or "")).strip()[:300]
    size = safe_int((query.get("xl") or [0])[0], 0, 0)
    return {
        "type": "magnet",
        "uri": text,
        "identity": identity,
        "name": name,
        "size": size,
    }


def normalize_ed2k(uri: str) -> Dict[str, Any]:
    text = str(uri or "").strip()
    if not text.lower().startswith("ed2k://|file|"):
        raise ValueError("不是有效的 ED2K 文件链接")
    # ED2K 文件链接固定为 ed2k://|file|NAME|SIZE|HASH|/
    parts = text.split("|")
    if len(parts) < 6 or parts[1].lower() != "file":
        raise ValueError("ED2K 文件链接结构无效")
    name = unquote(parts[2]).strip()
    if not name:
        raise ValueError("ED2K 文件名为空")
    try:
        size = int(parts[3])
    except (TypeError, ValueError) as err:
        raise ValueError("ED2K 文件大小无效") from err
    if size <= 0:
        raise ValueError("ED2K 文件大小无效")
    digest = str(parts[4] or "").strip().lower()
    if not _ED2K_HASH_RE.fullmatch(digest):
        raise ValueError("ED2K 文件哈希无效")
    return {
        "type": "ed2k",
        "uri": text,
        "identity": digest,
        "name": name[:300],
        "size": size,
    }


def normalize_source_uri(uri: str) -> Dict[str, Any]:
    text = str(uri or "").strip()
    if text.lower().startswith("magnet:?"):
        return normalize_magnet(text)
    if text.lower().startswith("ed2k://|file|"):
        return normalize_ed2k(text)
    raise ValueError("当前仅支持 magnet:? 与 ed2k://|file| 来源")


__all__ = [
    "SOURCE_TYPES", "SOURCE_SCHEMA_VERSION", "SOURCE_PENDING_STATES",
    "SOURCE_INFLIGHT_STATES", "SOURCE_TERMINAL_STATES",
    "safe_int", "source_identity", "normalize_magnet", "normalize_ed2k",
    "normalize_source_uri",
]
