"""v1.12.14 频道四类来源矩阵补全。

v1.9.0 的频道 ResourceGroup 已支持光鸭分享、Magnet、ED2K，但没有把同一条 Telegram
消息中的迅雷分享纳入索引。此层只扩展“资源发现”，不执行迅雷协议：
- 同一消息中的 光鸭分享 / 迅雷分享 / Magnet / ED2K 保持同一个 resource_group_id；
- 仅含迅雷链接的消息也保留为频道伪条目；
- 迅雷 passcode 只从 URL query 或同一消息上下文提取；
- 后续秒传仍完全复用现有 Xunlei JSON / 媒体身份 / 缺集硬栅栏。
"""
from __future__ import annotations

import functools
import hashlib
import html
import re
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlsplit

from .channel_sources_v190 import _resource_group_id


_XUNLEI_CHANNEL_RE = re.compile(r"https?://pan\.xunlei\.com/s/[^\s\"'<>，。；;]+", re.I)
_XUNLEI_CODE_RE = re.compile(
    r"(?:提取码|访问码|密码|口令|pass\s*code|passcode|pwd)\s*[:：=]?\s*([A-Za-z0-9]{1,16})",
    re.I,
)


def _clean_xunlei_url_v11214(value: Any) -> str:
    return html.unescape(str(value or "")).replace("\\/", "/").strip().rstrip(".,，。;；)）]】}")


def _xunlei_channel_rows_v11214(context_html: str) -> List[Dict[str, str]]:
    """从一个消息上下文提取稳定 Xunlei share_id/passcode，不跨消息借验证码。"""
    decoded = html.unescape(str(context_html or "")).replace("\\/", "/")
    rows: List[Dict[str, str]] = []
    seen = set()
    for matched in _XUNLEI_CHANNEL_RE.finditer(decoded):
        uri = _clean_xunlei_url_v11214(matched.group(0))
        try:
            parsed = urlsplit(uri)
        except ValueError:
            continue
        share = re.search(r"^/s/([^/?#]+)", parsed.path or "", re.I)
        if not share:
            continue
        share_id = str(share.group(1) or "").strip()
        if not share_id:
            continue
        query = parse_qs(parsed.query or "")
        passcode = ""
        for key in ("pwd", "passcode", "pass_code", "code"):
            values = query.get(key) or []
            if values and str(values[0] or "").strip():
                passcode = str(values[0]).strip()
                break
        if not passcode:
            code = _XUNLEI_CODE_RE.search(decoded)
            if code:
                passcode = str(code.group(1) or "").strip()
        key = (share_id, passcode)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "type": "xunlei",
            "uri": uri,
            "identity": share_id,
            "share_id": share_id,
            "passcode": passcode,
        })
    return rows


def _candidate_types_v11214(entry: Dict[str, Any]) -> List[str]:
    ordered: List[str] = []
    if entry.get("xunlei_sources"):
        ordered.append("xunlei")
    if str(entry.get("share_url") or "").strip():
        ordered.append("guangya")
    for item in entry.get("external_sources") or []:
        value = str((item or {}).get("type") or "").strip().lower()
        if value in {"magnet", "ed2k"} and value not in ordered:
            ordered.append(value)
    return ordered


def install_channel_source_matrix_v11214(legacy_module: Any):
    """在 v1.9.0 ResourceGroup 解析器外再补 Xunlei；热重载重复安装是 no-op。"""
    current = getattr(legacy_module, "_extract_channel_entries", None)
    if not callable(current):
        return None
    if getattr(current, "_guangya_channel_source_matrix_v11214", False):
        return current
    original = current

    @functools.wraps(original)
    def patched_extract(page_text: str, source_url: str, source_label: str) -> List[Dict[str, Any]]:
        entries = [dict(row or {}) for row in (original(page_text, source_url, source_label) or [])]
        decoded = html.unescape(str(page_text or "")).replace("\\/", "/")
        occurrences = list(_XUNLEI_CHANNEL_RE.finditer(decoded))
        if not occurrences:
            for row in entries:
                row["candidate_types"] = _candidate_types_v11214(row)
            return entries

        groups: Dict[str, Dict[str, Any]] = {}
        for match in occurrences:
            context_html = legacy_module._message_context_html(decoded, match.start())
            context = legacy_module._html_to_text(context_html)
            xunlei = _xunlei_channel_rows_v11214(context_html)
            if not xunlei:
                continue
            metadata = dict(legacy_module._entry_metadata(context, context_html) or {})
            message_id = str(metadata.get("message_id") or "")
            group_id = _resource_group_id(source_url, message_id, context)
            group = groups.setdefault(group_id, {
                "resource_group_id": group_id,
                "text": context[:4000],
                "source_url": source_url,
                "source_label": source_label,
                "priority": 0 if "regeng" in str(source_url or "").lower() else 1,
                "stale": False,
                "cached_index": False,
                "external_sources": [],
                "xunlei_sources": [],
                **metadata,
            })
            seen = {
                (str(item.get("share_id") or ""), str(item.get("passcode") or ""))
                for item in group.get("xunlei_sources") or []
            }
            for item in xunlei:
                key = (str(item.get("share_id") or ""), str(item.get("passcode") or ""))
                if key not in seen:
                    seen.add(key)
                    group["xunlei_sources"].append(dict(item))

        attached = set()
        for entry in entries:
            entry_message = str(entry.get("message_id") or "")
            entry_text = str(entry.get("text") or "")
            for group_id, group in groups.items():
                same = bool(entry_message and entry_message == str(group.get("message_id") or ""))
                if not same and not entry_message and entry_text == str(group.get("text") or ""):
                    same = True
                if not same and str(entry.get("resource_group_id") or "") == group_id:
                    same = True
                if not same:
                    continue
                existing = list(entry.get("xunlei_sources") or [])
                seen = {(str(v.get("share_id") or ""), str(v.get("passcode") or "")) for v in existing if isinstance(v, dict)}
                for item in group.get("xunlei_sources") or []:
                    key = (str(item.get("share_id") or ""), str(item.get("passcode") or ""))
                    if key not in seen:
                        seen.add(key)
                        existing.append(dict(item))
                entry["xunlei_sources"] = existing
                entry["resource_group_id"] = str(entry.get("resource_group_id") or group_id)
                attached.add(group_id)
                break
            entry["candidate_types"] = _candidate_types_v11214(entry)

        for group_id, group in groups.items():
            if group_id in attached:
                continue
            pseudo = {
                **group,
                "share_url": "",
                "share_id": "",
                "link_style": "迅雷资源",
            }
            pseudo["candidate_types"] = _candidate_types_v11214(pseudo)
            entries.append(pseudo)

        # 同一 ResourceGroup 最多保留一条伪记录，避免重复消息窗口造成二次索引。
        result: List[Dict[str, Any]] = []
        seen_keys = set()
        for entry in entries:
            group_id = str(entry.get("resource_group_id") or "")
            share_url = str(entry.get("share_url") or "")
            marker = (group_id, share_url, str(entry.get("message_id") or ""))
            if marker in seen_keys and not share_url:
                continue
            seen_keys.add(marker)
            result.append(entry)
        return result

    patched_extract._guangya_channel_source_matrix_v11214 = True
    patched_extract._guangya_original_extract_channel_entries = original
    legacy_module._extract_channel_entries = patched_extract
    return patched_extract


__all__ = [
    "install_channel_source_matrix_v11214",
    "_xunlei_channel_rows_v11214",
]
