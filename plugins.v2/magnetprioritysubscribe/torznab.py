from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urlencode

import requests

from .core import MagnetResult, normalize_result


@dataclass(frozen=True)
class TorznabSource:
    name: str
    url: str
    api_key: str = ""
    timeout: int = 12


class TorznabError(RuntimeError):
    pass


def _attr(item: ET.Element, name: str) -> str:
    for child in item:
        if child.tag.endswith("attr") and child.attrib.get("name") == name:
            return child.attrib.get("value") or ""
    return ""


def parse_torznab_xml(xml_text: str, source_name: str = "") -> List[MagnetResult]:
    try:
        root = ET.fromstring(xml_text)
    except Exception as err:
        raise TorznabError(f"Torznab XML 解析失败: {err}") from err
    results: List[MagnetResult] = []
    for item in root.iter():
        if not item.tag.endswith("item"):
            continue
        title = (item.findtext("title") or "").strip()
        description = (item.findtext("description") or "").strip()
        link = (item.findtext("link") or "").strip()
        magnet = _attr(item, "magneturl") or link
        size_text = item.findtext("size") or _attr(item, "size") or "0"
        seeders_text = _attr(item, "seeders") or "0"
        try:
            size = int(size_text)
        except Exception:
            size = 0
        try:
            seeders = int(seeders_text)
        except Exception:
            seeders = 0
        normalized = normalize_result(title, magnet, source=source_name, size=size,
                                      seeders=seeders, description=description)
        if normalized:
            results.append(normalized)
    return results


def search_torznab(source: TorznabSource, query: str, season: Optional[int] = None,
                   episode: Optional[int] = None, tmdb_id: Optional[int] = None,
                   session: Optional[requests.Session] = None) -> List[MagnetResult]:
    base = source.url.rstrip("/")
    params = {"t": "search", "q": query, "apikey": source.api_key}
    if tmdb_id:
        params["tmdbid"] = str(tmdb_id)
    if season is not None:
        params["season"] = str(season)
    if episode is not None:
        params["ep"] = str(episode)
    client = session or requests.Session()
    try:
        response = client.get(f"{base}/api?{urlencode(params)}", timeout=max(3, min(int(source.timeout), 30)))
    except requests.RequestException as err:
        raise TorznabError(f"{source.name} 请求失败: {err}") from err
    if response.status_code >= 400:
        raise TorznabError(f"{source.name} HTTP {response.status_code}")
    return parse_torznab_xml(response.text, source.name)
