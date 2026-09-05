"""v3.4.11：弱命名剧集多形态集数适配。

原则：
1. 仍由 MoviePilot 负责媒体识别、分类、命名、目标目录和真实整理；
2. 先把扫描阶段已经拿到的整目录成员显式传给 MoviePilot 的
   ``recommend_episode_format``，避免远端目录二次取样失败；
3. MoviePilot 仍无法推荐时，只对“集数位置”做兼容推导，不硬编码标题或媒体 ID；
4. 兼容模板必须经过 MoviePilot ``FormatParser`` 对整组视频逐个反向校验；
5. v3.4.9 预览阶段再次核对 MoviePilot 最终解析出的 season/episode，任何不一致都阻止 move。

覆盖常见命名：S01E01、EP01/E01、Episode 01、第01集/话、#01、[01]/【01】、
01~[4K]、01 4K、01-1080p、01_4K、01.mp4，以及带固定标题前后缀的同类变体。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.application.formatting import FormatParser
from app.domain.meta.metabase import MetaBase
from app.schemas.transfer import EpisodeFormat
from app.schemas.types import MediaType
from app.sdk.logging import logger

from .organizer_empty_folder_guard_v3410 import _runtime_media_exts
from .organizer_mp_folder_context_v346 import (
    _is_tv_media,
    _moviepilot_tv_context_from_directory_meta,
)


@dataclass(frozen=True)
class _EpisodeToken:
    start: int
    end: Optional[int]
    season: Optional[int]
    family: str
    strong: bool
    span_start: int
    span_end: int
    marker_start: int
    marker_end: int


_SXE_RANGE = re.compile(
    r"(?i)(?<![A-Za-z0-9])S(?P<season>\d{1,3})[ ._-]*E(?:P)?(?P<ep>\d{1,4})(?:\s*-\s*E(?:P)?(?P<end>\d{1,4}))?(?!\d)"
)
_EP_RANGE = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?P<mark>EP|E|Episode)[ ._-]*(?P<ep>\d{1,4})(?:\s*-\s*(?:EP|E)?(?P<end>\d{1,4}))?(?!\d)"
)
_CN_EP = re.compile(r"第\s*(?P<ep>\d{1,4})\s*(?P<unit>集|话|話)")
_CN_REVERSE = re.compile(r"(?P<unit>集|话|話)\s*(?P<ep>\d{1,4})(?!\d)")
_CN_SUFFIX = re.compile(r"(?<!\d)(?P<ep>\d{1,4})\s*(?P<unit>集|话|話)(?!\d)")
_HASH_EP = re.compile(r"(?<!\d)#\s*(?P<ep>\d{1,4})(?!\d)")
_BRACKET_EP = re.compile(r"(?P<open>[\[【（(])\s*(?P<ep>\d{1,3})\s*(?P<close>[\]】）)])")
_TILDE_EP = re.compile(r"^\s*(?P<ep>\d{1,3})\s*[~～](?=\s|[\[【(（]|$)")
_LEADING_EP = re.compile(r"^\s*(?P<ep>\d{1,3})(?P<sep>\s+|[._~～\-—\[【(（])")
_ONLY_EP = re.compile(r"^\s*(?P<ep>\d{1,3})\s*(?=\.[^.]+$)")
_TRAILING_EP = re.compile(r"(?:^|[\s._\-—])(?P<ep>\d{1,3})\s*(?=\.[^.]+$)")


def _to_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        match = re.search(r"\d{1,4}", str(value))
        return int(match.group(0)) if match else None


def _episode_token(file_name: str) -> Optional[_EpisodeToken]:
    """只抽取集号结构，不参与媒体标题识别。"""
    name = str(file_name or "")

    match = _SXE_RANGE.search(name)
    if match:
        start = int(match.group("ep"))
        end = _to_int(match.group("end"))
        return _EpisodeToken(
            start=start,
            end=end,
            season=int(match.group("season")),
            family="sxe",
            strong=True,
            span_start=match.start("ep"),
            span_end=match.end("end") if match.group("end") else match.end("ep"),
            marker_start=match.start(),
            marker_end=match.end(),
        )

    match = _EP_RANGE.search(name)
    if match:
        start = int(match.group("ep"))
        end = _to_int(match.group("end"))
        return _EpisodeToken(
            start=start,
            end=end,
            season=None,
            family="ep",
            strong=True,
            span_start=match.start("ep"),
            span_end=match.end("end") if match.group("end") else match.end("ep"),
            marker_start=match.start(),
            marker_end=match.end(),
        )

    for pattern, family in (
        (_CN_EP, "cn"),
        (_CN_REVERSE, "cn_reverse"),
        (_CN_SUFFIX, "cn_suffix"),
        (_HASH_EP, "hash"),
    ):
        match = pattern.search(name)
        if match:
            start = int(match.group("ep"))
            return _EpisodeToken(
                start=start,
                end=None,
                season=None,
                family=family,
                strong=True,
                span_start=match.start("ep"),
                span_end=match.end("ep"),
                marker_start=match.start(),
                marker_end=match.end(),
            )

    match = _BRACKET_EP.search(name)
    if match:
        start = int(match.group("ep"))
        if 0 < start <= 999:
            return _EpisodeToken(
                start=start,
                end=None,
                season=None,
                family="bracket",
                strong=False,
                span_start=match.start("ep"),
                span_end=match.end("ep"),
                marker_start=match.start(),
                marker_end=match.end(),
            )

    match = _TILDE_EP.search(name)
    if match:
        start = int(match.group("ep"))
        if 0 < start <= 999:
            return _EpisodeToken(
                start=start,
                end=None,
                season=None,
                family="tilde",
                strong=False,
                span_start=match.start("ep"),
                span_end=match.end("ep"),
                marker_start=match.start("ep"),
                marker_end=match.end(),
            )

    match = _LEADING_EP.search(name)
    if match:
        start = int(match.group("ep"))
        if 0 < start <= 999:
            return _EpisodeToken(
                start=start,
                end=None,
                season=None,
                family="leading",
                strong=False,
                span_start=match.start("ep"),
                span_end=match.end("ep"),
                marker_start=match.start("ep"),
                marker_end=match.end("sep"),
            )

    match = _ONLY_EP.search(name)
    if match:
        start = int(match.group("ep"))
        if 0 < start <= 999:
            return _EpisodeToken(
                start=start,
                end=None,
                season=None,
                family="only",
                strong=False,
                span_start=match.start("ep"),
                span_end=match.end("ep"),
                marker_start=match.start("ep"),
                marker_end=match.end("ep"),
            )

    match = _TRAILING_EP.search(name)
    if match:
        start = int(match.group("ep"))
        if 0 < start <= 999:
            return _EpisodeToken(
                start=start,
                end=None,
                season=None,
                family="trailing",
                strong=False,
                span_start=match.start("ep"),
                span_end=match.end("ep"),
                marker_start=match.start("ep"),
                marker_end=match.end("ep"),
            )

    return None


def _literal(value: str) -> str:
    return str(value or "").replace("{", "{{").replace("}", "}}")


def _next_delimiter(name: str, end: int) -> str:
    if end >= len(name):
        return ""
    char = name[end]
    if char.isspace():
        return " "
    if char in "._-~～—[]【】()（）":
        return char
    return ""


def _candidate_templates(name: str, token: _EpisodeToken) -> List[str]:
    """从一个已定位集号生成由严到宽的定位模板候选。"""
    candidates: List[str] = []
    before = name[: token.span_start]
    after = name[token.span_end :]
    candidates.append(f"{_literal(before)}{{ep}}{_literal(after)}")

    delim = _next_delimiter(name, token.span_end)
    suffix = f"{_literal(delim)}{{b}}" if delim else "{b}"

    if token.family == "sxe":
        marker_prefix = name[token.marker_start : token.span_start]
        candidates.append(f"{{a}}{_literal(marker_prefix)}{{ep}}{suffix}")
    elif token.family == "ep":
        marker_prefix = name[token.marker_start : token.span_start]
        candidates.append(f"{{a}}{_literal(marker_prefix)}{{ep}}{suffix}")
    elif token.family in {"cn", "cn_reverse", "cn_suffix", "hash", "bracket"}:
        marker_before = name[token.marker_start : token.span_start]
        marker_after = name[token.span_end : token.marker_end]
        candidates.append(
            f"{{a}}{_literal(marker_before)}{{ep}}{_literal(marker_after)}{{b}}"
        )
    elif token.family in {"tilde", "leading", "only"}:
        # 弱命名必须把集号放在文件名开头，使用紧邻分隔符约束 {ep} 边界。
        prefix = name[: token.span_start]
        if not prefix.strip():
            boundary = _next_delimiter(name, token.span_end)
            if boundary:
                candidates.append(f"{_literal(prefix)}{{ep}}{_literal(boundary)}{{a}}")
    elif token.family == "trailing":
        boundary_before = name[token.span_start - 1 : token.span_start] if token.span_start else ""
        if boundary_before:
            candidates.append(f"{{a}}{_literal(boundary_before)}{{ep}}{suffix}")

    # 保序去重。
    result: List[str] = []
    seen = set()
    for candidate in candidates:
        if candidate and candidate not in seen:
            seen.add(candidate)
            result.append(candidate)
    return result


def _media_members(item: Any) -> List[Any]:
    media_exts = _runtime_media_exts()
    result: List[Any] = []
    for member in list(getattr(item, "members", None) or []):
        name = str(getattr(member, "name", "") or Path(str(getattr(member, "path", "") or "")).name)
        suffix = Path(name).suffix.casefold()
        if suffix in media_exts:
            result.append(member)
    return result


def _parse_with_template(template: str, file_name: str) -> Tuple[Optional[int], Optional[int]]:
    try:
        parser = FormatParser(eformat=template)
        start, end, _ = parser.split_episode(file_name, MetaBase(title=""))
        return _to_int(start), _to_int(end)
    except Exception:
        return None, None


def _validated_expectations(
    template: str,
    members: Sequence[Any],
    *,
    require_tokens: bool,
) -> Optional[Dict[str, Dict[str, Any]]]:
    expectations: Dict[str, Dict[str, Any]] = {}
    seen_ranges = set()
    for member in members:
        name = str(getattr(member, "name", "") or Path(str(getattr(member, "path", "") or "")).name)
        token = _episode_token(name)
        parsed_start, parsed_end = _parse_with_template(template, name)
        if parsed_start is None:
            return None
        if require_tokens:
            if not token:
                return None
            if parsed_start != token.start:
                return None
            if token.end is not None and parsed_end != token.end:
                return None
        episode_end = parsed_end if parsed_end is not None else (token.end if token else None)
        season = token.season if token else None
        identity = (season, parsed_start, episode_end)
        if identity in seen_ranges:
            # 多个视频被解释为同一季同一集，宁可不启用兼容模板。
            return None
        seen_ranges.add(identity)
        path = str(getattr(member, "path", "") or "")
        expectations[path] = {
            "name": name,
            "season": season,
            "episode": parsed_start,
            "episode_end": episode_end,
        }
    return expectations or None


def _fallback_episode_format(item: Any) -> Tuple[Optional[EpisodeFormat], Dict[str, Dict[str, Any]], str]:
    """MP 推荐失败后的兼容层；只在整组文件可证明一致时返回模板。"""
    members = _media_members(item)
    if not members:
        return None, {}, "no_media"

    tokens: List[_EpisodeToken] = []
    for member in members:
        name = str(getattr(member, "name", "") or Path(str(getattr(member, "path", "") or "")).name)
        token = _episode_token(name)
        if not token:
            return None, {}, f"unrecognized:{name}"
        tokens.append(token)

    # 裸数字、方括号等弱命名至少需要两个不同集号共同证明是剧集，而不是单个电影文件。
    if not all(token.strong for token in tokens):
        if len(tokens) < 2:
            return None, {}, "weak_single_sample"
        if len({(token.start, token.end) for token in tokens}) != len(tokens):
            return None, {}, "weak_duplicate_episode"

    candidate_pool: List[str] = []
    for member, token in zip(members, tokens):
        name = str(getattr(member, "name", "") or Path(str(getattr(member, "path", "") or "")).name)
        candidate_pool.extend(_candidate_templates(name, token))

    # 优先精确模板，再尝试带 MP 通配占位符的模板；每个候选都必须反向解析整组成功。
    seen = set()
    ordered_candidates = []
    for candidate in candidate_pool:
        if candidate not in seen:
            seen.add(candidate)
            ordered_candidates.append(candidate)
    ordered_candidates.sort(key=lambda value: (value.count("{a}") + value.count("{b}"), len(value)))

    for template in ordered_candidates:
        expectations = _validated_expectations(template, members, require_tokens=True)
        if expectations:
            return EpisodeFormat(format=template), expectations, "fallback_validated"

    return None, {}, "no_common_template"


def _ensure_tv_context(
    item: Any,
    kwargs: Dict[str, Any],
    directory_meta: Any,
) -> Tuple[bool, str]:
    media = kwargs.get("mediainfo")
    if _is_tv_media(media):
        kwargs["mtype"] = MediaType.TV
        return True, ""

    # 复用本轮唯一一次 MoviePilot 路径识别得到的 meta；禁止在同一 Preview 构建里二次 recognize_by_path。
    tv_media, tv_error = _moviepilot_tv_context_from_directory_meta(directory_meta)
    if not tv_media:
        return False, str(tv_error or "MoviePilot 电视剧识别未确认")
    kwargs["mediainfo"] = tv_media
    kwargs["mtype"] = MediaType.TV
    return True, ""


def _attach_expectations(plugin: Any, item: Any, expectations: Dict[str, Dict[str, Any]], source: str) -> None:
    normalized: Dict[str, Dict[str, Any]] = {}
    for path, row in expectations.items():
        normalized[plugin._organize_normalize_path(path)] = dict(row)
    setattr(item, "_guangya_episode_expectations_v3411", normalized)
    setattr(item, "_guangya_episode_adapter_source_v3411", source)


def _mp_member_recommend(
    plugin: Any,
    transfer_chain: Any,
    directory_item: Any,
    item: Any,
) -> Tuple[Optional[EpisodeFormat], Dict[str, Dict[str, Any]], str]:
    members = list(getattr(item, "members", None) or [])
    if not members:
        return None, {}, "no_members"
    try:
        state, message, data = transfer_chain.recommend_episode_format(
            fileitem=directory_item,
            fileitems=members,
        )
    except Exception as err:  # noqa: BLE001
        return None, {}, f"MoviePilot 整组样本推荐异常：{err}"
    if not state or not isinstance(data, dict):
        return None, {}, str(message or "MoviePilot 整组样本未推荐模板")
    template = str(data.get("episode_format") or "").strip()
    if not template:
        return None, {}, str(message or "MoviePilot 整组样本未返回模板")
    epformat = EpisodeFormat(format=template)
    expectations = _validated_expectations(template, _media_members(item), require_tokens=False) or {}
    return epformat, expectations, "moviepilot_member_samples"


def apply_episode_name_adapter(
    plugin: Any,
    item: Any,
    transfer_chain: Any,
    directory_item: Any,
    kwargs: Dict[str, Any],
    directory_meta: Any,
) -> Tuple[Dict[str, Any], Optional[str], str]:
    """显式构建 MoviePilot 集数上下文，不改写其它模块函数。"""
    resolved = dict(kwargs or {})

    existing_epformat = resolved.get("epformat")
    if existing_epformat:
        template = str(getattr(existing_epformat, "format", "") or "")
        expectations = _validated_expectations(template, _media_members(item), require_tokens=False) or {}
        if expectations:
            _attach_expectations(plugin, item, expectations, "moviepilot_existing")
        return resolved, None, "moviepilot_existing"

    # 唯一一次 MoviePilot 推荐：直接把当前 folder envelope 的整组成员传入公开 API。
    epformat, expectations, source = _mp_member_recommend(
        plugin,
        transfer_chain,
        directory_item,
        item,
    )
    if epformat:
        ok, error = _ensure_tv_context(item, resolved, directory_meta)
        if not ok:
            return resolved, error, source
        resolved["epformat"] = epformat
        if expectations:
            _attach_expectations(plugin, item, expectations, source)
        logger.info(
            "【光鸭云盘助手】【集数适配】MoviePilot 使用整组文件生成集数模板: %s -> %s",
            item.path,
            epformat.format,
        )
        return resolved, None, source

    # MoviePilot 未推荐时，仅对集号位置做兼容推导；仍必须经 MP FormatParser 整组反向验证。
    fallback, expectations, fallback_reason = _fallback_episode_format(item)
    if not fallback:
        logger.debug(
            "【光鸭云盘助手】【集数适配】未启用弱命名兼容模板: %s - MP=%s；fallback=%s",
            item.path,
            source,
            fallback_reason,
        )
        return resolved, None, f"{source};fallback={fallback_reason}"

    ok, error = _ensure_tv_context(item, resolved, directory_meta)
    if not ok:
        return resolved, error, fallback_reason
    resolved["epformat"] = fallback
    _attach_expectations(plugin, item, expectations, "validated_compatibility")
    logger.info(
        "【光鸭云盘助手】【集数适配】MoviePilot 原推荐未覆盖该命名，已生成并验证兼容模板: %s -> %s；成员=%s",
        item.path,
        fallback.format,
        len(expectations),
    )
    return resolved, None, "validated_compatibility"


def audit_episode_expectations(
    plugin: Any,
    item: Any,
    payload: Dict[str, Any],
    details: Dict[str, Any],
) -> Tuple[bool, str, Dict[str, Any]]:
    """在基础 Preview 唯一性校验之后复核 MoviePilot 最终 season/episode。"""
    expectations = dict(getattr(item, "_guangya_episode_expectations_v3411", {}) or {})
    merged = dict(details or {})
    if not expectations:
        return True, "", merged
    if not isinstance(payload, dict):
        return False, "MoviePilot 预览结果无法执行集号复核", merged

    preview_rows = [row for row in (payload.get("items") or []) if isinstance(row, dict)]
    by_source = {
        plugin._organize_normalize_path(str(row.get("source") or "")): row
        for row in preview_rows
        if row.get("source")
    }
    mismatches: List[str] = []
    for source_path, expected in expectations.items():
        row = by_source.get(source_path)
        if not row:
            mismatches.append(f"{expected.get('name')} 未出现在预览")
            continue
        actual_episode = _to_int(row.get("episode"))
        actual_end = _to_int(row.get("episode_end"))
        actual_season = _to_int(row.get("season"))
        expected_episode = _to_int(expected.get("episode"))
        expected_end = _to_int(expected.get("episode_end"))
        expected_season = _to_int(expected.get("season"))
        if actual_episode != expected_episode:
            mismatches.append(
                f"{expected.get('name')} 期望E{expected_episode}但MoviePilot解析为E{actual_episode}"
            )
            continue
        if expected_end is not None and actual_end != expected_end:
            mismatches.append(
                f"{expected.get('name')} 期望结束集E{expected_end}但MoviePilot解析为E{actual_end}"
            )
            continue
        if expected_season is not None and actual_season not in (None, expected_season):
            mismatches.append(
                f"{expected.get('name')} 期望S{expected_season}但MoviePilot解析为S{actual_season}"
            )

    merged["episode_adapter"] = {
        "source": str(getattr(item, "_guangya_episode_adapter_source_v3411", "") or ""),
        "validated": len(expectations),
        "mismatches": mismatches[:20],
    }
    if mismatches:
        return (
            False,
            f"集号二次校验失败 {len(mismatches)} 个：" + "；".join(mismatches[:6]),
            merged,
        )
    return True, "", merged


__all__ = [
    "apply_episode_name_adapter",
    "audit_episode_expectations",
    "_episode_token",
    "_fallback_episode_format",
]
