"""Resource candidate filtering helpers.

Rules:
- prefer newer candidates when multiple Magnet/Xunlei candidates match
- prefer largest valid media file for cloud add
- remove anime extras such as NCOP/NCED/OVA/SP/PV
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List


_ANIME_EXTRA_RE = re.compile(
    r"(?:\bNCOP\b|\bNCED\b|\bOVA\b|\bOAD\b|\bSP\b|\bSpecial\b|\bPV\b|\bCM\b|片头|片尾|特典)",
    re.IGNORECASE,
)
_GARBAGE_RE = re.compile(
    r"(?:sample|trailer|preview|poster|cover|folder|readme|nfo|\.jpg$|\.png$|\.txt$)",
    re.IGNORECASE,
)


class ResourceFilterV110:
    """Common resource candidate selector."""

    @staticmethod
    def is_anime_extra(name: str) -> bool:
        return bool(_ANIME_EXTRA_RE.search(str(name or "")))

    @staticmethod
    def is_garbage(name: str) -> bool:
        return bool(_GARBAGE_RE.search(str(name or "")))

    @classmethod
    def select_largest_media(cls, files: Iterable[Dict[str, Any]]) -> Dict[str, Any] | None:
        candidates: List[Dict[str, Any]] = []
        for item in files or []:
            name = str(item.get("name") or item.get("path") or "")
            if cls.is_garbage(name):
                continue
            if cls.is_anime_extra(name):
                continue
            try:
                size = int(item.get("size") or item.get("fileSize") or 0)
            except (TypeError, ValueError):
                size = 0
            if size > 0:
                row = dict(item)
                row["_size"] = size
                candidates.append(row)
        if not candidates:
            return None
        return max(candidates, key=lambda x: x.get("_size", 0))

    @classmethod
    def sort_candidates(cls, resources: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sort resource candidates: newest first, then size."""
        rows = [dict(x) for x in (resources or [])]

        def score(item: Dict[str, Any]):
            text = " ".join(str(item.get(k) or "") for k in ("name", "title", "label"))
            year = 0
            found = re.findall(r"(?:19|20)\d{2}", text)
            if found:
                year = max(int(x) for x in found)
            try:
                size = int(item.get("size") or item.get("fileSize") or 0)
            except (TypeError, ValueError):
                size = 0
            return year, size

        rows.sort(key=score, reverse=True)
        return rows
