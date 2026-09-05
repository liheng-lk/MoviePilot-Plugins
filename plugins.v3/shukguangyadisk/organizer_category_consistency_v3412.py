"""v3.4.12：MoviePilot 分类一致性校验。

目录识别得到的 MediaInfo 可能来自缓存或第三方识别源合并，里面的 ``category`` 不一定
与当前 MoviePilot ``category.yaml`` 一致。本层不维护任何“国产/欧美/日韩”等分类规则，
只使用 MoviePilot 自己的 ``CategoryHelper`` 和 MediaInfo 中的原始 TMDB 详情重新计算一次
当前分类，再把结果交回同一套 ``TransferChain`` 预览/真实整理。

目标：
- 修复识别缓存或外部识别插件残留旧 category 导致的错误目录选择；
- 日志明确输出 TMDB 的 origin_country/original_language 和 MP 当前分类结果；
- CategoryHelper 无法核验时宁可阻止本次真实整理，不带着不可验证的分类继续 move；
- 不写死任何分类名称，也不改变 MoviePilot 的 category.yaml。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Optional, Tuple

from app.modules.themoviedb.category import CategoryHelper
from app.schemas.types import MediaType
from app.sdk.logging import logger

from .organizer_mp_folder_context_v346 import _is_tv_media


def _media_type_value(media: Any) -> str:
    value = getattr(media, "type", None)
    return str(getattr(value, "value", value) or "").casefold()


def _tmdb_category_facts(media: Any) -> Dict[str, Any]:
    info = dict(getattr(media, "tmdb_info", None) or {})
    origin_country = info.get("origin_country") or []
    production_countries = info.get("production_countries") or []
    if isinstance(origin_country, str):
        origin_country = [origin_country]
    if isinstance(production_countries, dict):
        production_countries = [production_countries]
    production_codes = []
    for value in production_countries or []:
        if isinstance(value, dict):
            code = value.get("iso_3166_1")
        else:
            code = value
        if code:
            production_codes.append(str(code).upper())
    return {
        "tmdb_info": info,
        "original_language": str(info.get("original_language") or "").lower(),
        "origin_country": [str(value).upper() for value in origin_country if value],
        "production_countries": production_codes,
    }


def _moviepilot_current_category(media: Any) -> Tuple[Optional[str], Dict[str, Any], Optional[str]]:
    """严格按 MoviePilot 当前 CategoryHelper 重新计算分类。"""
    facts = _tmdb_category_facts(media)
    info = facts["tmdb_info"]
    if not info:
        return None, facts, "识别结果缺少 TMDB 原始详情，无法核对 MoviePilot 分类规则"

    try:
        helper = CategoryHelper()
        if _is_tv_media(media):
            category = helper.get_tv_category(info)
        elif _media_type_value(media) in {
            str(getattr(MediaType.MOVIE, "value", MediaType.MOVIE)).casefold(),
            "movie",
            "电影",
        }:
            category = helper.get_movie_category(info)
        else:
            return None, facts, None
    except Exception as err:  # noqa: BLE001 - MoviePilot runtime boundary
        return None, facts, f"MoviePilot CategoryHelper 分类核验异常：{err}"

    return str(category or "").strip(), facts, None


def _reconcile_moviepilot_category(media: Any) -> Tuple[Any, Dict[str, Any], Optional[str]]:
    """只纠正为 MP 当前 category.yaml 的计算结果，不做插件自定义分类。"""
    expected, facts, error = _moviepilot_current_category(media)
    current = str(getattr(media, "category", None) or "").strip()
    diagnostics = {
        "current_category": current,
        "moviepilot_category": expected,
        "original_language": facts.get("original_language") or "",
        "origin_country": list(facts.get("origin_country") or []),
        "production_countries": list(facts.get("production_countries") or []),
    }
    if error:
        return media, diagnostics, error
    if expected is None:
        return media, diagnostics, None

    # 有 TMDB 详情时，以当前 MoviePilot category.yaml 的实时计算结果为唯一分类事实。
    # 即使结果为空，也清掉缓存/外部识别源带来的旧 category，避免错误命中分类目录。
    if current == expected:
        return media, diagnostics, None

    corrected = deepcopy(media)
    corrected.category = expected
    diagnostics["corrected"] = True
    return corrected, diagnostics, None


def apply_category_consistency(
    item: Any,
    kwargs: Dict[str, Any],
) -> Tuple[Dict[str, Any], Optional[str]]:
    """按 MoviePilot 当前 CategoryHelper 收口 mediainfo.category；失败时 fail closed。"""
    resolved = dict(kwargs or {})
    media = resolved.get("mediainfo")
    if not media:
        return resolved, None

    reconciled, diagnostics, category_error = _reconcile_moviepilot_category(media)
    if category_error:
        logger.error(
            "【光鸭云盘助手】【分类一致性】已阻止真实整理，无法使用 MoviePilot 当前分类规则核验: %s - %s",
            getattr(item, "path", ""),
            category_error,
        )
        return resolved, category_error

    resolved["mediainfo"] = reconciled
    media_type = getattr(reconciled, "type", None)
    if media_type:
        resolved["mtype"] = media_type

    current = diagnostics.get("current_category") or "未分类"
    expected = diagnostics.get("moviepilot_category")
    expected_text = expected if expected else "未分类"
    origin = ",".join(diagnostics.get("origin_country") or []) or "-"
    production = ",".join(diagnostics.get("production_countries") or []) or "-"
    language = diagnostics.get("original_language") or "-"

    if diagnostics.get("corrected"):
        logger.warning(
            "【光鸭云盘助手】【分类一致性】识别上下文分类与 MoviePilot 当前 category.yaml 不一致，"
            "已使用 MP 当前结果: %s -> %s；origin_country=%s；production_countries=%s；original_language=%s",
            current,
            expected_text,
            origin,
            production,
            language,
        )
    else:
        logger.info(
            "【光鸭云盘助手】【分类一致性】MoviePilot 当前分类=%s；origin_country=%s；"
            "production_countries=%s；original_language=%s",
            expected_text,
            origin,
            production,
            language,
        )
    return resolved, None


__all__ = [
    "apply_category_consistency",
    "_moviepilot_current_category",
    "_reconcile_moviepilot_category",
]
