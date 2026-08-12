from __future__ import annotations

import json
from typing import Any, Dict, List

from .torznab import TorznabSource


JACKETT_ALL_DEFAULT = "http://jackett:9117/api/v2.0/indexers/all/results/torznab/api"


def build_sources(config: Dict[str, Any], default_timeout: int = 12) -> List[TorznabSource]:
    """根据内置源配置与高级 JSON 配置生成 Torznab 搜索源列表。"""
    sources: List[TorznabSource] = []

    if bool(config.get("jackett_enabled")):
        url = str(config.get("jackett_url") or JACKETT_ALL_DEFAULT).strip()
        if url:
            sources.append(TorznabSource(
                name="Jackett",
                url=url,
                api_key=str(config.get("jackett_api_key") or "").strip(),
                timeout=_timeout(config.get("jackett_timeout"), default_timeout),
            ))

    if bool(config.get("prowlarr_enabled")):
        url = str(config.get("prowlarr_torznab_url") or "").strip()
        if url:
            sources.append(TorznabSource(
                name="Prowlarr",
                url=url,
                api_key=str(config.get("prowlarr_api_key") or "").strip(),
                timeout=_timeout(config.get("prowlarr_timeout"), default_timeout),
            ))

    if bool(config.get("torznab_enabled")):
        url = str(config.get("torznab_url") or "").strip()
        if url:
            sources.append(TorznabSource(
                name=str(config.get("torznab_name") or "Torznab").strip() or "Torznab",
                url=url,
                api_key=str(config.get("torznab_api_key") or "").strip(),
                timeout=_timeout(config.get("torznab_timeout"), default_timeout),
            ))

    advanced = str(config.get("torznab_sources_json") or "").strip()
    if advanced:
        try:
            raw = json.loads(advanced)
        except Exception as err:
            raise RuntimeError(f"高级 Torznab JSON 配置无效: {err}") from err
        if not isinstance(raw, list):
            raise RuntimeError("高级 Torznab JSON 必须是数组")
        for idx, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            sources.append(TorznabSource(
                name=str(item.get("name") or f"source-{idx + 1}"),
                url=url,
                api_key=str(item.get("api_key") or item.get("apikey") or ""),
                timeout=_timeout(item.get("timeout"), default_timeout),
            ))

    return _dedupe_sources(sources)


def _timeout(value: Any, default_timeout: int) -> int:
    """将搜索源超时限制在 3~30 秒。"""
    try:
        return max(3, min(int(value or default_timeout), 30))
    except Exception:
        return max(3, min(int(default_timeout or 12), 30))


def _dedupe_sources(sources: List[TorznabSource]) -> List[TorznabSource]:
    """按 URL + API Key 去重，保留首次出现的搜索源。"""
    seen = set()
    output: List[TorznabSource] = []
    for source in sources:
        key = (source.url.rstrip("/"), source.api_key)
        if key in seen:
            continue
        seen.add(key)
        output.append(source)
    return output
