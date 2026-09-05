"""v1.12.16 电影双语真实资源身份桥接。

只解决一种可证明为同一媒体的误杀：搜索/订阅使用中文标题，而同一个迅雷分享的
真实顶层名称明确同时给出中文标题与第二语言标题，实际视频文件再使用这个第二语言标题。

安全边界：
- 仅电影；
- 父层已经通过则完全不介入；
- 只救回“实际资源顶层标题与订阅不一致”这一类标题冲突；
- 搜索发现必须命中订阅官方别名；
- 实际资源必须明确包含订阅年份，且不能出现其它年份或季号；
- 同一个真实顶层名称必须同时包含订阅别名段 + 第二语言标题段；
- 至少一个真实视频文件必须精确匹配该第二语言标题段；
- 不使用编辑距离、拼音、包含式模糊匹配，也不允许 discovery 单独覆盖真实资源冲突。
"""
from __future__ import annotations

import html
import re
from pathlib import PurePosixPath
from typing import Any, Dict, Iterable, List, Sequence, Set, Tuple

from .manual_check_v11211 import GuangYaManualCheckV11211Mixin
from .media_identity_v1111 import (
    explicit_seasons_v1111,
    explicit_years_v1111,
    strong_title_match_v1111,
    title_key_v1111,
)

_YEAR_V11216 = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")
_BRACKET_V11216 = re.compile(r"[【\[（(]([^】\]）)]{2,120})[】\]）)]")
_CJK_LATIN_SPLIT_V11216 = re.compile(
    r"(?<=[\u4e00-\u9fff])(?:\s|[·•:：\-—_/])+?(?=[A-Za-z])|"
    r"(?<=[A-Za-z])(?:\s|[·•:：\-—_/])+?(?=[\u4e00-\u9fff])"
)
_DECOR_SPLIT_V11216 = re.compile(r"(?:\|{1,2}|／|---+|={2,}|⭐+|🌈+|🎬+|\n+)")
_GENERIC_SEGMENTS_V11216 = {
    "movie", "film", "video", "resource", "share", "download", "french", "english", "chinese",
    "电影", "影片", "视频", "资源", "分享", "剧情", "传记", "动作", "喜剧", "爱情", "科幻",
}


def _clean_segment_v11216(value: Any) -> str:
    text = html.unescape(str(value or "")).replace("\\", "/").strip()
    if not text:
        return ""
    try:
        text = PurePosixPath(text).name or text
    except Exception:
        pass
    text = re.sub(r"\.(?:mkv|mp4|ts|m2ts|avi|mov|wmv|flv|webm|iso|m4v)$", "", text, flags=re.I)
    text = text.strip(" \t\r\n._-—|/\\[]【】()（）{}<>⭐🌈🎬")
    return text


def _title_segments_v11216(value: Any, expected_year: Any = None) -> List[Tuple[str, str]]:
    """抽取严格可解释的标题段；返回 (规范 key, 原始段)。"""
    raw = _clean_segment_v11216(value)
    if not raw:
        return []

    candidates: List[str] = [raw]
    candidates.extend(match.group(1).strip() for match in _BRACKET_V11216.finditer(raw))
    candidates.extend(part.strip() for part in _DECOR_SPLIT_V11216.split(raw) if part.strip())

    year = str(expected_year or "").strip()
    if year and re.fullmatch(r"(?:19|20)\d{2}", year):
        marker = re.search(rf"(?<!\d){re.escape(year)}(?!\d)", raw)
        if marker and marker.start() > 1:
            candidates.append(raw[:marker.start()].strip(" ._-—|/\\[]【】()（）"))

    expanded = list(candidates)
    for candidate in candidates:
        parts = [part.strip() for part in _CJK_LATIN_SPLIT_V11216.split(candidate) if part.strip()]
        if len(parts) == 2:
            expanded.extend(parts)

    result: List[Tuple[str, str]] = []
    seen: Set[str] = set()
    for candidate in expanded:
        cleaned = _clean_segment_v11216(candidate)
        key = title_key_v1111(cleaned, expected_year=expected_year).casefold()
        if len(key) < 3 or key in _GENERIC_SEGMENTS_V11216 or key in seen:
            continue
        seen.add(key)
        result.append((key, cleaned))
    return result


class GuangYaMovieBilingualIdentityV11216Mixin(GuangYaManualCheckV11211Mixin):
    """用同一真实分享内的双语标题关系救回电影标题误杀。"""

    plugin_version = "1.12.16"
    build_id = "20260906-r63"

    @staticmethod
    def _known_alias_keys_v11216(aliases: Sequence[str], expected_year: Any) -> Set[str]:
        result: Set[str] = set()
        for alias in aliases or []:
            key = title_key_v1111(alias, expected_year=expected_year).casefold()
            if len(key) >= 3:
                result.add(key)
        return result

    @staticmethod
    def _discovery_matches_alias_v11216(
        aliases: Sequence[str],
        values: Iterable[Any],
        expected_year: Any,
    ) -> bool:
        for value in values or []:
            if not str(value or "").strip():
                continue
            for alias in aliases or []:
                if strong_title_match_v1111(alias, value, expected_year=expected_year):
                    return True
            segment_keys = {key for key, _ in _title_segments_v11216(value, expected_year)}
            if segment_keys.intersection(
                GuangYaMovieBilingualIdentityV11216Mixin._known_alias_keys_v11216(aliases, expected_year)
            ):
                return True
        return False

    def _bilingual_bridge_v11216(
        self,
        subscribe: Any,
        candidate: Dict[str, Any],
        info: Dict[str, Any],
        template: Dict[str, Any],
    ) -> Tuple[bool, str]:
        is_movie = getattr(self, "_identity_is_movie_v1111", None)
        if not callable(is_movie) or not bool(is_movie(subscribe)):
            return False, "非电影"

        aliases = list(self._identity_aliases_v1111(subscribe) or [])
        year = str(getattr(subscribe, "year", "") or "").strip()
        if not aliases or not year:
            return False, "缺少订阅别名或年份"

        search_title = str(candidate.get("search_title") or "").strip()
        if not self._discovery_matches_alias_v11216(
            aliases,
            [search_title, candidate.get("label")],
            year,
        ):
            return False, "搜索发现未命中订阅别名"

        resource_name = str(candidate.get("name") or "").strip()
        if resource_name and search_title and resource_name.casefold() == search_title.casefold():
            resource_name = ""
        primary = [
            str(info.get("title") or "").strip(),
            resource_name,
        ]
        files = [
            str(row.get("path") or row.get("name") or "").strip()
            for row in (template.get("files") or [])
            if isinstance(row, dict) and str(row.get("path") or row.get("name") or "").strip()
        ]
        actual = [value for value in [*primary, *files[:300]] if value]
        years = explicit_years_v1111(actual, aliases)
        if not years or years != {year}:
            return False, f"实际年份不足或冲突：期望={year} 实际={sorted(years)}"
        if explicit_seasons_v1111(actual):
            return False, "电影实际资源出现季号"

        known = self._known_alias_keys_v11216(aliases, year)
        if not known:
            return False, "订阅别名无法规范化"

        file_keys: Set[str] = set()
        for value in files:
            file_keys.update(key for key, _ in _title_segments_v11216(value, year))

        bridges: List[str] = []
        for value in primary:
            if not value:
                continue
            segments = _title_segments_v11216(value, year)
            keys = {key for key, _ in segments}
            if not keys.intersection(known):
                continue
            foreign = {key for key in keys if key not in known and len(key) >= 4}
            matched_foreign = sorted(foreign.intersection(file_keys))
            if not matched_foreign:
                continue
            bridge_key = matched_foreign[0]
            bridge_text = next((text for key, text in segments if key == bridge_key), bridge_key)
            bridges.append(bridge_text)

        if not bridges:
            return False, "同一分享未形成“订阅标题 + 第二语言标题 → 实际文件”闭环"

        return True, f"同一分享双语闭环：订阅标题 + {bridges[0]}；年份={year}；真实文件精确命中第二语言标题"

    def _xunlei_json_identity_matches_v1123(
        self,
        subscribe: Any,
        candidate: Dict[str, Any],
        info: Dict[str, Any],
        template: Dict[str, Any],
    ):
        accepted, reason = super()._xunlei_json_identity_matches_v1123(subscribe, candidate, info, template)
        if accepted:
            return accepted, reason
        text = str(reason or "")
        if "实际资源顶层标题与订阅不一致" not in text:
            return accepted, reason

        rescued, bridge_reason = self._bilingual_bridge_v11216(subscribe, candidate, info, template)
        if not rescued:
            return accepted, reason

        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【电影双语身份v1.12.16】#%s %s 原硬冲突已由真实分享双语闭环救回：%s",
            int(getattr(subscribe, "id", 0) or 0),
            str(getattr(subscribe, "name", "") or ""),
            bridge_reason,
        )
        return True, f"迅雷媒体身份通过：电影双语真实资源桥接；{bridge_reason}"


__all__ = ["GuangYaMovieBilingualIdentityV11216Mixin"]
