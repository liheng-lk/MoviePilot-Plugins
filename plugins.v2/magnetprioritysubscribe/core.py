from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Set, Tuple
from urllib.parse import parse_qs, urlparse


_CHINESE_POSITIVE = re.compile(
    r"(?:CNSUB|CHS(?:&CHT)?|CHT|简繁|繁中|简中|中字|中文字幕|中文(?:字幕)?|内封(?:中字|中文)|内嵌(?:中字|中文)|Chinese\s*Sub)",
    re.I,
)
_CHINESE_NEGATIVE = re.compile(r"(?:ENG(?:LISH)?\s*ONLY|NO\s*CHINESE|无中字|无中文|无字幕)", re.I)
_EP_SINGLE = re.compile(r"\bS(?P<s>\d{1,2})E(?P<e>\d{1,3})\b", re.I)
_EP_RANGE = re.compile(r"\bS(?P<s>\d{1,2})E(?P<a>\d{1,3})[-~至_ ]E?(?P<b>\d{1,3})\b", re.I)
_EP_RANGE_SHORT = re.compile(r"\bE(?P<a>\d{1,3})[-~至_ ]E?(?P<b>\d{1,3})\b", re.I)
_SEASON = re.compile(r"\bS(?P<s>\d{1,2})\b", re.I)


@dataclass(frozen=True)
class MagnetResult:
    title: str
    magnet: str
    source: str = ""
    size: int = 0
    seeders: int = 0
    description: str = ""
    categories: Tuple[str, ...] = ()
    score: int = 0
    info_hash: str = ""
    season: Optional[int] = None
    episodes: Tuple[int, ...] = ()
    chinese_subtitle: bool = False
    reasons: Tuple[str, ...] = field(default_factory=tuple)


def magnet_info_hash(uri: str) -> Optional[str]:
    """Return canonical uppercase 40-char hex BTIH or None."""
    try:
        parsed = urlparse(str(uri or "").strip())
        if parsed.scheme.lower() != "magnet":
            return None
        values = parse_qs(parsed.query).get("xt", [])
        for value in values:
            prefix = "urn:btih:"
            if not value.lower().startswith(prefix):
                continue
            raw = value[len(prefix):].strip()
            if re.fullmatch(r"[0-9a-fA-F]{40}", raw):
                return raw.upper()
            if re.fullmatch(r"[A-Z2-7a-z2-7]{32}", raw):
                try:
                    return base64.b32decode(raw.upper()).hex().upper()
                except Exception:
                    return None
    except Exception:
        return None
    return None


def has_chinese_subtitle(title: str, description: str = "") -> bool:
    """Strict subtitle gate: explicit negative wins; unknown is rejected."""
    text = f"{title or ''} {description or ''}"
    if _CHINESE_NEGATIVE.search(text):
        return False
    return bool(_CHINESE_POSITIVE.search(text))


def parse_season_episodes(title: str) -> Tuple[Optional[int], Set[int]]:
    """Parse common SxxExx / episode-range forms."""
    text = str(title or "")
    season: Optional[int] = None
    episodes: Set[int] = set()
    for m in _EP_RANGE.finditer(text):
        season = int(m.group("s"))
        a, b = int(m.group("a")), int(m.group("b"))
        episodes.update(range(min(a, b), max(a, b) + 1))
    for m in _EP_SINGLE.finditer(text):
        season = int(m.group("s"))
        episodes.add(int(m.group("e")))
    if season is None:
        m = _SEASON.search(text)
        if m:
            season = int(m.group("s"))
    if season is not None and not episodes:
        for m in _EP_RANGE_SHORT.finditer(text):
            a, b = int(m.group("a")), int(m.group("b"))
            episodes.update(range(min(a, b), max(a, b) + 1))
    return season, episodes


def matches_episode_need(title: str, target_season: Optional[int], missing_episodes: Iterable[int]) -> bool:
    """Require correct season and overlap with missing episodes for TV subscriptions."""
    missing = {int(x) for x in missing_episodes if int(x) > 0}
    season, episodes = parse_season_episodes(title)
    if target_season is not None and season is not None and season != int(target_season):
        return False
    if not missing:
        return True
    if episodes:
        return bool(episodes & missing)
    # Season packs without explicit episodes are acceptable only if season matches/unknown.
    return season is not None


def score_result(title: str, size: int = 0, seeders: int = 0) -> int:
    """Stable deterministic quality score; subtitle is handled as a hard gate."""
    t = str(title or "").lower()
    score = 0
    if "2160p" in t or "4k" in t:
        score += 400
    elif "1080p" in t:
        score += 300
    elif "720p" in t:
        score += 100
    if "web-dl" in t or "webdl" in t:
        score += 80
    elif "webrip" in t:
        score += 60
    if "hevc" in t or "h265" in t or "x265" in t:
        score += 45
    elif "h264" in t or "x264" in t or "avc" in t:
        score += 25
    if "dolby vision" in t or "dovi" in t or " dv " in f" {t} ":
        score += 25
    if "hdr" in t:
        score += 20
    score += min(max(int(seeders or 0), 0), 200)
    if size and size < 100 * 1024 * 1024:
        score -= 500
    return score


def normalize_result(title: str, magnet: str, source: str = "", size: int = 0, seeders: int = 0,
                     description: str = "") -> Optional[MagnetResult]:
    info_hash = magnet_info_hash(magnet)
    if not info_hash:
        return None
    season, episodes = parse_season_episodes(title)
    chinese = has_chinese_subtitle(title, description)
    return MagnetResult(
        title=str(title or "").strip(), magnet=str(magnet or "").strip(), source=source,
        size=int(size or 0), seeders=int(seeders or 0), description=description or "",
        score=score_result(title, size, seeders), info_hash=info_hash, season=season,
        episodes=tuple(sorted(episodes)), chinese_subtitle=chinese,
    )


def select_best(results: Iterable[MagnetResult], target_season: Optional[int] = None,
                missing_episodes: Iterable[int] = ()) -> Optional[MagnetResult]:
    """Deduplicate by infohash, enforce Chinese subtitles and TV episode match."""
    best_by_hash = {}
    for item in results:
        if not item or not item.info_hash or not item.chinese_subtitle:
            continue
        if not matches_episode_need(item.title, target_season, missing_episodes):
            continue
        current = best_by_hash.get(item.info_hash)
        if current is None or (item.score, item.seeders, item.size) > (current.score, current.seeders, current.size):
            best_by_hash[item.info_hash] = item
    if not best_by_hash:
        return None
    return max(best_by_hash.values(), key=lambda x: (x.score, x.seeders, x.size, x.title))
