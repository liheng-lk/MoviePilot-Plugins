"""高置信季集号解析。

只接受明确的 SxxEyy / Exx / EPxx / 第N集(话) 语义，不把普通年份、分辨率、
文件序号直接当成集号，避免整包资源误选。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(slots=True)
class EpisodeMatch:
    episodes: tuple[int, ...]
    explicit_season: int | None = None
    confidence: str = "high"


_SEASON_EP_RE = re.compile(
    r"(?i)(?:^|[^A-Z0-9])S(?P<season>\d{1,2})[ ._\-]*E(?P<start>\d{1,3})(?:[ ._\-]*(?:E)?(?P<end>\d{1,3}))?"
)
_EP_RE = re.compile(
    r"(?i)(?:^|[^A-Z0-9])(?:EP?|E)[ ._\-]*(?P<start>\d{1,3})(?:[ ._\-]*(?:EP?|E)?(?P<end>\d{1,3}))?(?=$|[^A-Z0-9])"
)
_CN_RE = re.compile(r"第\s*(?P<start>\d{1,3})\s*(?:[-~至到]\s*(?P<end>\d{1,3})\s*)?[集话話]")


def _expand(start: int, end: int | None) -> tuple[int, ...]:
    if start <= 0 or start > 999:
        return ()
    if end is None:
        return (start,)
    if end < start or end - start > 100 or end > 999:
        return ()
    return tuple(range(start, end + 1))


def match_episodes(name: str, *, expected_season: int | None = None) -> EpisodeMatch:
    stem = Path(str(name or "")).stem

    match = _SEASON_EP_RE.search(stem)
    if match:
        season = int(match.group("season"))
        if expected_season is not None and season != int(expected_season):
            return EpisodeMatch((), explicit_season=season)
        episodes = _expand(int(match.group("start")), int(match.group("end")) if match.group("end") else None)
        return EpisodeMatch(episodes, explicit_season=season)

    match = _EP_RE.search(stem)
    if match:
        episodes = _expand(int(match.group("start")), int(match.group("end")) if match.group("end") else None)
        return EpisodeMatch(episodes)

    match = _CN_RE.search(stem)
    if match:
        episodes = _expand(int(match.group("start")), int(match.group("end")) if match.group("end") else None)
        return EpisodeMatch(episodes)

    return EpisodeMatch(())


def episode_intersection(name: str, targets: Iterable[int], *, expected_season: int | None = None) -> tuple[int, ...]:
    target_set = {int(value) for value in targets if int(value) > 0}
    if not target_set:
        return ()
    matched = match_episodes(name, expected_season=expected_season)
    return tuple(ep for ep in matched.episodes if ep in target_set)
