"""v1.9.0 Telegram 多来源消息兼容层。

同一条频道消息是一个 ResourceGroup；光鸭分享、Magnet、ED2K 都只是该组的候选获取方式。
本补丁保持 legacy 光鸭分享索引兼容，同时让“仅含磁力/ED2K”的消息也进入统一频道索引。
"""

from __future__ import annotations

import functools
import hashlib
import html
import re
from typing import Any, Dict, List

from .source_types_v180 import normalize_source_uri


_MAGNET_RE = re.compile(r"(?i)magnet:\?[^\s\"'<>]+")
_ED2K_RE = re.compile(r"(?i)ed2k://\|file\|[^|\r\n<>]+\|\d+\|[0-9a-f]{32}\|/")


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


def _external_sources_from_context(context_html: str) -> List[Dict[str, Any]]:
    decoded = html.unescape(str(context_html or "")).replace("\\/", "/")
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


def install_channel_multisource_compat(legacy_module: Any):
    """热重载安全地扩展频道解析器和消息稳定键。"""
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
        decoded = html.unescape(str(page_text or "")).replace("\\/", "/")
        occurrence_positions = [item.start() for item in _MAGNET_RE.finditer(decoded)]
        occurrence_positions.extend(item.start() for item in _ED2K_RE.finditer(decoded))

        groups: Dict[str, Dict[str, Any]] = {}
        for position in sorted(set(occurrence_positions)):
            context_html = legacy_module._message_context_html(decoded, position)
            context = legacy_module._html_to_text(context_html)
            external = _external_sources_from_context(context_html)
            if not external:
                continue
            metadata = legacy_module._entry_metadata(context, context_html)
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

        # 同消息已有光鸭分享时，只给原 entry 挂候选，不新增一条重复 UI/匹配记录。
        attached_groups = set()
        for entry in base_entries:
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
                # 光鸭-only 消息也建立 ResourceGroup，便于状态页和后续决策统一展示。
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

        return base_entries

    patched_extract._guangya_channel_multisource = True
    patched_extract._guangya_original_extract_channel_entries = original_extract
    legacy_module._extract_channel_entries = patched_extract
    return patched_extract


__all__ = [
    "install_channel_multisource_compat",
]
