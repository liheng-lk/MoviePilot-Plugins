"""v1.11.1 多来源媒体身份门禁纯函数。

搜索卡片只负责发现；真正执行转存/秒传前，必须使用频道元数据或已解析的实际资源名、
文件路径重新确认标题、年份与季号。遇到明确冲突或高季资源缺少季号证据时宁可跳过，
不把错误媒体写入光鸭。
"""
from __future__ import annotations

import html
import re
from pathlib import PurePosixPath
from typing import Any, Iterable, List, Sequence, Set

_TECH_TOKEN_RE = re.compile(
    r"(?ix)^(?:2160p|1080p|1080i|720p|576p|480p|4k|8k|web(?:dl|rip)?|web-dl|bluray|blu-ray|bdrip|brrip|remux|hdtv|uhd|x26[45]|h26[45]|hevc|avc|av1|10bit|8bit|hdr10\+?|hdr|dv|dolbyvision|aac\d?(?:\.\d)?|ac3|eac3|ddp?\d?(?:\.\d)?|dts(?:hd)?|truehd|atmos|flac|proper|repack|rerip|internal|extended|uncut|complete|全集|全季|chs|cht|chi|eng|jpn|kor|multi|dual|字幕|中字|简中|繁中)$"
)
_EP_TOKEN_RE = re.compile(r"(?i)^(?:s\d{1,2}(?:e\d{1,4})?|e\d{1,4}|ep\d{1,4}|episode\d{1,4})$")
_SEASON_PATTERNS = (
    re.compile(r"(?i)\bS(?:eason)?[ ._\-]*0*(\d{1,2})\b"),
    re.compile(r"第\s*0*(\d{1,2})\s*季"),
)
_YEAR_RE = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")
_CJK_SEASON_RE = re.compile(r"第\s*([一二三四五六七八九十]{1,3})\s*季")


def _cn_number(value: str) -> int:
    digits = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if value == "十":
        return 10
    if "十" in value:
        left, _, right = value.partition("十")
        return (digits.get(left, 1) * 10) + digits.get(right, 0)
    return digits.get(value, 0)


def explicit_seasons_v1111(values: Iterable[Any]) -> Set[int]:
    seasons: Set[int] = set()
    for raw in values or []:
        text = html.unescape(str(raw or ""))
        for pattern in _SEASON_PATTERNS:
            for match in pattern.findall(text):
                try:
                    number = int(match)
                except (TypeError, ValueError):
                    continue
                if 0 <= number <= 99:
                    seasons.add(number)
        for token in _CJK_SEASON_RE.findall(text):
            number = _cn_number(token)
            if 0 < number <= 99:
                seasons.add(number)
    return seasons


def _title_year_tokens(aliases: Sequence[str]) -> Set[str]:
    result: Set[str] = set()
    for alias in aliases or []:
        result.update(_YEAR_RE.findall(str(alias or "")))
    return result


def explicit_years_v1111(values: Iterable[Any], aliases: Sequence[str] = ()) -> Set[str]:
    title_numbers = _title_year_tokens(aliases)
    years: Set[str] = set()
    for raw in values or []:
        for token in _YEAR_RE.findall(html.unescape(str(raw or ""))):
            if token not in title_numbers:
                years.add(token)
    return years


def _candidate_strings(value: Any) -> List[str]:
    text = html.unescape(str(value or "")).replace("\\", "/").strip()
    if not text:
        return []
    rows = [text]
    rows.extend(part.strip() for part in text.splitlines() if part.strip())
    rows.extend(part.strip() for part in re.split(r"[|／]", text) if part.strip())
    try:
        path = PurePosixPath(text)
        rows.extend(part for part in path.parts if part not in {"/", ".", ".."})
        rows.append(path.name)
    except Exception:
        pass
    result: List[str] = []
    seen = set()
    for row in rows:
        key = row.casefold()
        if row and key not in seen:
            seen.add(key)
            result.append(row)
    return result


def title_key_v1111(value: Any, expected_year: Any = None) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\.(?:mkv|mp4|ts|m2ts|avi|mov|wmv|flv|webm|iso|m4v|srt|ass|ssa|vtt|sup)$", " ", text, flags=re.I)
    text = re.sub(r"[\[【（(][^\]】）)]{0,80}[\]】）)]", " ", text)
    text = re.sub(r"(?i)\bS(?:eason)?[ ._\-]*0*\d{1,2}(?:[ ._\-]*E(?:pisode)?[ ._\-]*0*\d{1,4})?\b", " ", text)
    text = re.sub(r"(?i)\b(?:E|EP|Episode)[ ._\-]*0*\d{1,4}\b", " ", text)
    text = re.sub(r"第\s*[0-9一二三四五六七八九十]{1,3}\s*(?:季|集|话)", " ", text)
    year = str(expected_year or "").strip()
    if year and re.fullmatch(r"(?:19|20)\d{2}", year):
        text = re.sub(rf"(?<!\d){re.escape(year)}(?!\d)", " ", text)
    raw_tokens = [token for token in re.split(r"[^0-9A-Za-z\u4e00-\u9fff]+", text) if token]
    kept: List[str] = []
    for token in raw_tokens:
        lowered = token.casefold()
        if _TECH_TOKEN_RE.fullmatch(lowered) or _EP_TOKEN_RE.fullmatch(lowered):
            continue
        if lowered in {"2160", "1080", "720", "576", "480", "264", "265"}:
            continue
        kept.append(lowered)
    return "".join(kept)


def title_variants_v1111(value: Any, expected_year: Any = None) -> Set[str]:
    variants: Set[str] = set()
    for candidate in _candidate_strings(value):
        key = title_key_v1111(candidate, expected_year=expected_year)
        if len(key) >= 2:
            variants.add(key)
    return variants


def strong_title_match_v1111(expected: Any, actual: Any, expected_year: Any = None) -> bool:
    wanted = title_variants_v1111(expected, expected_year=expected_year)
    found = title_variants_v1111(actual, expected_year=expected_year)
    return bool(wanted and found and wanted.intersection(found))


def any_alias_title_match_v1111(aliases: Sequence[str], evidences: Iterable[Any], expected_year: Any = None) -> bool:
    alias_keys: Set[str] = set()
    for alias in aliases or []:
        alias_keys.update(title_variants_v1111(alias, expected_year=expected_year))
    if not alias_keys:
        return False
    for evidence in evidences or []:
        if alias_keys.intersection(title_variants_v1111(evidence, expected_year=expected_year)):
            return True
    return False


def validate_media_evidence_v1111(
    *,
    aliases: Sequence[str],
    expected_year: Any,
    expected_season: Any,
    is_movie: bool,
    evidences: Iterable[Any],
    require_title: bool = True,
    require_explicit_season: bool = False,
) -> tuple[bool, str]:
    rows = [str(value or "").strip() for value in evidences or [] if str(value or "").strip()]
    if not rows:
        return False, "实际资源没有可校验的标题或文件路径"
    year = str(expected_year or "").strip()
    years = explicit_years_v1111(rows, aliases)
    if year and years and year not in years:
        return False, f"实际资源年份冲突：期望={year} 实际={','.join(sorted(years))}"
    seasons = explicit_seasons_v1111(rows)
    try:
        season = int(expected_season or 0)
    except (TypeError, ValueError):
        season = 0
    if is_movie and seasons:
        return False, f"电影资源出现季号：{sorted(seasons)}"
    if not is_movie and season > 0 and seasons and season not in seasons:
        return False, f"实际资源季号冲突：期望=S{season:02d} 实际={sorted(seasons)}"
    if not is_movie and require_explicit_season and season > 1 and not seasons:
        return False, f"S{season:02d} 自动转存要求实际资源包含明确季号，当前资源缺少季号证据"
    if require_title and not any_alias_title_match_v1111(aliases, rows, expected_year=year):
        preview = " | ".join(rows[:4])[:220]
        return False, f"实际资源标题无法确认属于当前媒体：{preview}"
    return True, "实际资源标题/年份/季号校验通过"


__all__ = [
    "explicit_seasons_v1111",
    "explicit_years_v1111",
    "title_key_v1111",
    "title_variants_v1111",
    "strong_title_match_v1111",
    "any_alias_title_match_v1111",
    "validate_media_evidence_v1111",
]
