"""统一命名策略：剧集名 + SxxExx。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, List, Optional, Tuple


_FORBIDDEN = re.compile(r"[\\/:*?\"<>|\x00-\x1f]+")


def safe_name(value: Any, limit: int = 120) -> str:
    text = _FORBIDDEN.sub(" ", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip(" .-_")
    return text[: max(1, int(limit or 120))].strip()


def show_name(subscribe: Any) -> str:
    raw = str(getattr(subscribe, "name", "") or "").strip()
    raw = re.sub(r"\s*[（(]\s*(?:19\d{2}|20\d{2})\s*[）)]\s*$", "", raw).strip()
    return safe_name(raw)


def split_name_ext(name: Any) -> Tuple[str, str]:
    text = str(name or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not text:
        return "", ""
    path = Path(text)
    suffix = path.suffix
    if suffix and len(suffix) <= 8:
        return path.stem, suffix
    return text, ""


def episode_numbers(path: Any) -> Tuple[Optional[int], List[int]]:
    """轻量季集解析；完整规则仍可由 legacy._episode_numbers 提供。"""
    value = str(path or "")
    season = None
    episodes = set()
    block = re.search(
        r"(?i)S(?:eason)?[\s._-]*0*(\d{1,2})[\s._-]*E(?:P)?[\s._-]*0*(\d{1,4})"
        r"(?:[\s._]*(?:-|~|—|至)[\s._]*E?(?:P)?[\s._-]*0*(\d{1,4}))?",
        value,
    )
    if block:
        season = int(block.group(1))
        start = int(block.group(2))
        end = int(block.group(3) or start)
        if end >= start and end - start <= 300:
            episodes.update(range(start, end + 1))
    else:
        for matched in re.finditer(r"(?i)(?:^|[^A-Za-z])E(?:P)?[\s._-]*0*(\d{1,4})", value):
            episodes.add(int(matched.group(1)))
        season_match = re.search(r"(?i)(?:^|[^A-Za-z0-9])S(?:eason)?[\s._-]*0*(\d{1,2})(?=[^0-9]|$)", value)
        if season_match:
            season = int(season_match.group(1))
    return season, sorted(episodes)


class NamingPolicy:
    def episode_tag(self, subscribe: Any, path: Any) -> str:
        season, episodes = episode_numbers(path)
        sub_season = getattr(subscribe, "season", None)
        if season is None and sub_season not in (None, ""):
            try:
                season = int(sub_season)
            except (TypeError, ValueError):
                season = None
        if not episodes:
            return f"S{int(season):02d}" if season is not None else ""
        if season is None:
            season = 1
        if len(episodes) == 1:
            return f"S{int(season):02d}E{episodes[0]:02d}"
        return f"S{int(season):02d}E{episodes[0]:02d}-E{episodes[-1]:02d}"

    def canonical_name(self, subscribe: Any, original: Any, *, is_movie: bool = False) -> str:
        show = show_name(subscribe)
        _, ext = split_name_ext(original)
        if not show:
            base = str(original or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
            return safe_name(base, 240)
        if is_movie:
            return f"{show}{ext}"
        tag = self.episode_tag(subscribe, original)
        if tag:
            return f"{show} {tag}{ext}"
        return f"{show}{ext}"
