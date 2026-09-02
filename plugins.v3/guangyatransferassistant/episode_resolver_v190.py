"""v1.9.0 统一剧集识别器。

目标不是“从文件名抓一个数字”，而是把文件名、父目录、整包序列与频道提示一起判断，
给出可解释的 season / episodes / confidence。只有高置信结果才允许自动拆包。
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


AUTO_SELECT_CONFIDENCE = 0.90
MAX_EXPLICIT_EPISODE = 9999
_COMMON_NOISE_NUMBERS = {264, 265, 266, 360, 480, 720, 1080, 2160, 4320}
_VIDEO_SUFFIX_RE = re.compile(r"\.[A-Za-z0-9]{2,5}$")
_SEASON_RE = re.compile(r"(?i)(?:^|[^A-Za-z0-9])S(?:eason)?[\s._-]*0*(\d{1,2})(?=[^0-9]|$)")
_X_RE = re.compile(r"(?i)(?:^|[^0-9])0*(\d{1,2})x0*(\d{1,4})(?=[^0-9]|$)")
_EP_RANGE_RE = re.compile(
    r"(?i)(?:^|[^A-Za-z])E(?:P(?:ISODE)?)?[\s._-]*0*(\d{1,4})"
    r"(?:[\s._]*(?:-|~|～|—|至|\+)[\s._]*E?(?:P(?:ISODE)?)?[\s._-]*0*(\d{1,4}))?"
)
_CHINESE_RE = re.compile(r"第\s*0*(\d{1,4})(?:\s*[-~～—至]\s*0*(\d{1,4}))?\s*[集话]")
_SPECIAL_RE = re.compile(
    r"(?i)(?:^|[^A-Za-z0-9])(?:SP|SPECIAL|OVA|OAD)[\s._-]*0*(\d{1,4})(?=[^0-9]|$)"
)
_CHINESE_SPECIAL_RE = re.compile(r"(?:特别篇|番外|特典)\s*0*(\d{1,4})(?=[^0-9]|$)")
_QUALITY_TOKEN = (
    r"(?:4K|8K|2160P?|1080P?|720P?|480P?|UHD|FHD|HD|HDR(?:10\+?)?|DV|DOVI|"
    r"WEB(?:-?DL)?|BLU-?RAY|BDREMUX|REMUX|HEVC|AVC|AV1|H\.?26[45]|X26[45])"
)
_QUALITY_SUFFIX_RE = re.compile(
    rf"(?ix)^\s*0*(\d{{1,4}})\s*[~～丨|｜]\s*[\[【(（]?\s*{_QUALITY_TOKEN}"
    r"(?=$|[\s._\-\[\]【】()（）])"
)
_RELEASE_EP_BEFORE_QUALITY_RE = re.compile(
    rf"(?ix)(?:^|[\s._\-])0*(\d{{1,4}})(?:v\d+)?(?=[\s._\-]+{_QUALITY_TOKEN}(?:$|[\s._\-\[\]【】()（）]))"
)


def _clean_path(value: Any) -> str:
    return str(value or "").replace("\\", "/").strip()


def _basename(value: Any) -> str:
    return _clean_path(value).rsplit("/", 1)[-1]


def _stem(value: Any) -> str:
    return _VIDEO_SUFFIX_RE.sub("", _basename(value)).strip()


def _expand_range(start: int, end: int) -> List[int]:
    if start <= 0 or end < start or end > MAX_EXPLICIT_EPISODE or end - start > 500:
        return []
    return list(range(start, end + 1))


def _season_from_path(path: Any, explicit_hint: Optional[int] = None) -> Optional[int]:
    if explicit_hint is not None:
        try:
            return max(0, int(explicit_hint))
        except (TypeError, ValueError):
            pass
    value = _clean_path(path)
    matches = list(_SEASON_RE.finditer(value))
    if matches:
        return int(matches[-1].group(1))
    return None


def _strict_parse(value: Any, season_hint: Optional[int] = None) -> Optional[Dict[str, Any]]:
    text = _clean_path(value)
    season = _season_from_path(text, season_hint)
    episodes = set()
    reasons: List[str] = []

    x_match = _X_RE.search(text)
    if x_match:
        if season is None:
            season = int(x_match.group(1))
        episodes.add(int(x_match.group(2)))
        reasons.append("1x02")

    for matched in _EP_RANGE_RE.finditer(text):
        start = int(matched.group(1))
        end = int(matched.group(2)) if matched.group(2) else start
        values = _expand_range(start, end)
        if values:
            episodes.update(values)
            reasons.append("E/EP")

    for raw in re.findall(r"(?i)E(?:P(?:ISODE)?)?[\s._-]*0*(\d{1,4})", text):
        value_int = int(raw)
        if 0 < value_int <= MAX_EXPLICIT_EPISODE:
            episodes.add(value_int)
            reasons.append("multi-E")

    for matched in _CHINESE_RE.finditer(text):
        start = int(matched.group(1))
        end = int(matched.group(2)) if matched.group(2) else start
        values = _expand_range(start, end)
        if values:
            episodes.update(values)
            reasons.append("第N集/话")

    if episodes:
        values = sorted(episode for episode in episodes if 0 < episode <= MAX_EXPLICIT_EPISODE)
        absolute = values[0] if season is None and len(values) == 1 and values[0] > 500 else None
        return {
            "season": season,
            "episodes": values,
            "absolute_episode": absolute,
            "confidence": 1.0,
            "reason": "+".join(dict.fromkeys(reasons)) or "explicit",
            "explicit": True,
        }

    special = _SPECIAL_RE.search(text) or _CHINESE_SPECIAL_RE.search(text)
    if special:
        value_int = int(special.group(1))
        if 0 < value_int <= MAX_EXPLICIT_EPISODE:
            return {
                "season": 0,
                "episodes": [value_int],
                "absolute_episode": None,
                "confidence": 1.0,
                "reason": "special",
                "explicit": True,
            }
    return None


def _looks_like_year(value: int) -> bool:
    return 1900 <= int(value) <= 2099


def _valid_weak_number(candidate: int) -> bool:
    return bool(
        0 < int(candidate) <= MAX_EXPLICIT_EPISODE
        and int(candidate) not in _COMMON_NOISE_NUMBERS
        and not _looks_like_year(int(candidate))
    )


def _weak_numeric_candidate(value: Any) -> Optional[Tuple[int, str]]:
    """只返回位置语义明确的弱数字；不会从 1080p/H265/2026 中间硬抓数字。"""
    stem = _stem(value)
    quality = _QUALITY_SUFFIX_RE.search(stem)
    if quality:
        candidate = int(quality.group(1))
        if _valid_weak_number(candidate):
            return candidate, "quality-suffix"

    release_quality = list(_RELEASE_EP_BEFORE_QUALITY_RE.finditer(stem))
    if release_quality:
        candidate = int(release_quality[-1].group(1))
        if _valid_weak_number(candidate):
            return candidate, "release-before-quality"

    patterns: Sequence[Tuple[str, str]] = (
        (r"[\[【(（]\s*0*(\d{1,4})(?:v\d+)?\s*[\]】)）]", "bracket-number"),
        (r"(?:^|[\s._])[-–—][\s._-]*0*(\d{1,4})(?:v\d+)?(?=\s|[._\[(（]|$)", "dash-number"),
        (r"^\s*0*(\d{1,4})(?:v\d+)?$", "bare-number"),
        (r"^\s*0*(\d{1,4})(?:v\d+)?(?=[\s._\-\[(（])", "leading-number"),
        (r"(?:^|[\s._-])0*(\d{1,4})(?:v\d+)?$", "trailing-number"),
    )
    for pattern, reason in patterns:
        matched = re.search(pattern, stem, re.I)
        if not matched:
            continue
        candidate = int(matched.group(1))
        if not _valid_weak_number(candidate):
            continue
        return candidate, reason
    return None


def _package_sequence_numbers(paths: Iterable[Any]) -> List[int]:
    values = []
    seen = set()
    for path in paths or []:
        strict = _strict_parse(path)
        if strict and strict.get("episodes"):
            continue
        weak = _weak_numeric_candidate(path)
        if not weak:
            continue
        candidate = int(weak[0])
        if candidate not in seen:
            seen.add(candidate)
            values.append(candidate)
    return sorted(values)


def _is_coherent_sequence(values: Sequence[int]) -> bool:
    if len(values) < 3:
        return False
    ordered = sorted(set(int(v) for v in values))
    span = ordered[-1] - ordered[0] + 1
    return span <= len(ordered) + 1 and span <= 500


def resolve_episode(
    path: Any,
    *,
    package_paths: Optional[Iterable[Any]] = None,
    season_hint: Optional[int] = None,
    episode_hint: Any = "",
) -> Dict[str, Any]:
    """返回可解释的剧集识别结果；低于阈值只诊断，不自动拆包。"""
    strict = _strict_parse(path, season_hint=season_hint)
    if strict:
        return strict

    weak = _weak_numeric_candidate(path)
    if not weak:
        return {
            "season": _season_from_path(path, season_hint),
            "episodes": [],
            "absolute_episode": None,
            "confidence": 0.0,
            "reason": "unparsed",
            "explicit": False,
        }

    candidate, weak_reason = weak
    season = _season_from_path(path, season_hint)
    confidence = 0.65
    reason = weak_reason

    hinted = _strict_parse(episode_hint, season_hint=season) if episode_hint else None
    if hinted and candidate in set(hinted.get("episodes") or []):
        confidence = max(confidence, 0.96)
        reason += "+episode-hint"
        if season is None:
            season = hinted.get("season")

    package_numbers = _package_sequence_numbers(package_paths or [])
    if candidate in package_numbers and _is_coherent_sequence(package_numbers):
        confidence = max(confidence, 0.92)
        reason += "+package-sequence"

    if season is not None and weak_reason in {
        "bare-number", "leading-number", "trailing-number", "bracket-number", "dash-number",
        "quality-suffix", "release-before-quality",
    }:
        confidence = max(confidence, 0.90)
        reason += "+season-context"

    absolute = candidate if season is None and candidate > 500 else None
    return {
        "season": season,
        "episodes": [candidate],
        "absolute_episode": absolute,
        "confidence": round(confidence, 3),
        "reason": reason,
        "explicit": False,
    }


def reliable_episode_set(result: Dict[str, Any], threshold: float = AUTO_SELECT_CONFIDENCE) -> set[int]:
    try:
        confidence = float(result.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < float(threshold):
        return set()
    values = set()
    for raw in result.get("episodes") or []:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if 0 < value <= MAX_EXPLICIT_EPISODE:
            values.add(value)
    return values


__all__ = [
    "AUTO_SELECT_CONFIDENCE",
    "MAX_EXPLICIT_EPISODE",
    "resolve_episode",
    "reliable_episode_set",
]
