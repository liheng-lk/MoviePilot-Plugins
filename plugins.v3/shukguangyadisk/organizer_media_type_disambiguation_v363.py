"""v3.6.3：MoviePilot TV 命中但剧集结构不成立时安全复核电影类型。

本层只做媒体类型消歧，不自行识别标题、分类、命名或目标路径：
- 当前 MoviePilot 已识别为电视剧；
- 当前资源不是 Season/Sxx/第N季目录；
- 只有一个主视频；
- 文件名没有任何已知集号结构；
- MoviePilot 最终 kwargs 没有 epformat；
- 再由 MoviePilot 以 ``MediaType.MOVIE`` 对同一目录 meta 做约束识别；
- 电影候选必须与原 TV 候选标题一致，且年份不存在冲突。

仅由 TV 媒体元数据推导出的 ``season`` 不是文件自身的剧集证据，因此不会阻止电影复核；
如果最终确认电影，会移除该 TV season 上下文。任何条件不满足都保持原 TV 结果，不猜测、
不强制改类型。
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple

from app.chain.media import MediaChain
from app.schemas.types import MediaType
from app.sdk.logging import logger

from . import organizer_loss_guard_v349 as _loss_guard
from .organizer_episode_name_adapter_v3411 import _episode_token, _media_members
from .organizer_folder_identity_v350 import _resource_identity_path
from .organizer_mp_folder_context_v346 import _is_tv_media, _moviepilot_directory_context


_TV_SEASON_PLAN_ERROR = "电视剧季号上下文未确认"


def _is_movie_media(media: Any) -> bool:
    media_type = getattr(media, "type", None)
    if media_type == MediaType.MOVIE:
        return True
    value = getattr(media_type, "value", media_type)
    return str(value or "").casefold() in {
        str(getattr(MediaType.MOVIE, "value", MediaType.MOVIE)).casefold(),
        "movie",
        "电影",
    }


def _normalized_title(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(ch for ch in text if ch.isalnum())


def _title_keys(media: Any) -> Set[str]:
    result: Set[str] = set()
    for attr in ("title", "original_title", "en_title", "name"):
        key = _normalized_title(getattr(media, attr, None))
        if key:
            result.add(key)
    return result


def _year(value: Any) -> Optional[int]:
    if value is None:
        return None
    match = re.search(r"(?:19|20)\d{2}", str(value))
    return int(match.group(0)) if match else None


def _media_year(media: Any) -> Optional[int]:
    for attr in ("year", "release_date", "first_air_date"):
        result = _year(getattr(media, attr, None))
        if result is not None:
            return result
    return None


def _moviepilot_movie_from_same_meta(path: str) -> Tuple[Any, str]:
    context, error = _moviepilot_directory_context(path)
    meta = getattr(context, "meta_info", None) if context else None
    if not meta:
        return None, str(error or "MoviePilot 目录上下文缺少 meta_info")
    try:
        movie = MediaChain().recognize_by_meta(
            metainfo=meta,
            mtype=MediaType.MOVIE,
            obtain_images=True,
        )
    except Exception as err:  # noqa: BLE001 - MoviePilot compatibility boundary
        return None, f"MoviePilot 电影约束识别异常：{err}"
    if not movie:
        return None, "MoviePilot 在电影类型下未识别到该目录"
    if not _is_movie_media(movie):
        return None, "MoviePilot 电影约束识别结果类型不是电影"
    return movie, ""


def _same_title_and_year(tv_media: Any, movie_media: Any) -> Tuple[bool, str]:
    tv_titles = _title_keys(tv_media)
    movie_titles = _title_keys(movie_media)
    if not tv_titles or not movie_titles or tv_titles.isdisjoint(movie_titles):
        return False, "电影候选与原电视剧候选标题不一致"

    tv_year = _media_year(tv_media)
    movie_year = _media_year(movie_media)
    if tv_year is not None and movie_year is not None and tv_year != movie_year:
        return False, f"年份冲突：TV={tv_year}，MOVIE={movie_year}"
    return True, ""


def _single_video_without_episode(item: Any) -> Tuple[bool, str]:
    members = list(_media_members(item))
    if len(members) != 1:
        return False, f"主视频数量={len(members)}，仅单主视频允许电影回退"
    member = members[0]
    name = str(
        getattr(member, "name", "")
        or Path(str(getattr(member, "path", "") or "")).name
    )
    if _episode_token(name):
        return False, f"文件名存在集号结构：{name}"
    return True, ""


def _eligible(plugin: Any, item: Any, kwargs: Dict[str, Any]) -> Tuple[bool, str]:
    media = kwargs.get("mediainfo")
    if not media or not _is_tv_media(media):
        return False, "当前 MoviePilot 结果不是电视剧"
    if kwargs.get("epformat"):
        return False, "MoviePilot 已确认集数模板"

    current = plugin._organize_normalize_path(str(getattr(item, "path", "") or ""))
    identity = _resource_identity_path(plugin, current)
    if identity != current:
        return False, "当前是 Season/Sxx/第N季目录"

    return _single_video_without_episode(item)


def _plan_error_allows_movie_recheck(plan_error: Any) -> bool:
    if not plan_error:
        return True
    # 只允许覆盖 v3.5.8 因 TV season 不明确产生的阻断；其它安全错误绝不绕过。
    return _TV_SEASON_PLAN_ERROR in str(plan_error)


def install_media_type_disambiguation_v363() -> None:
    """在 v3.5.8 season 层之后最终收口 TV→MOVIE 类型消歧。"""
    if getattr(_loss_guard, "_guangya_media_type_disambiguation_v363", False):
        return

    previous_build = _loss_guard._build_moviepilot_kwargs

    def build(plugin: Any, item: Any):
        transfer_chain, directory_item, kwargs, plan_error = previous_build(plugin, item)
        if not _plan_error_allows_movie_recheck(plan_error):
            return transfer_chain, directory_item, kwargs, plan_error

        current_kwargs = dict(kwargs or {})
        eligible, reason = _eligible(plugin, item, current_kwargs)
        if not eligible:
            return transfer_chain, directory_item, kwargs, plan_error

        tv_media = current_kwargs.get("mediainfo")
        logger.info(
            "【光鸭云盘助手】【v3.6.3】【媒体类型消歧】TV 已识别但无有效剧集结构，"
            "开始使用 MoviePilot 电影类型复核: %s -> %s%s",
            getattr(item, "path", ""),
            getattr(tv_media, "title_year", None) or getattr(tv_media, "title", ""),
            f"；原 TV 阻断={plan_error}" if plan_error else "",
        )

        movie_media, movie_error = _moviepilot_movie_from_same_meta(str(getattr(item, "path", "") or ""))
        if not movie_media:
            logger.info(
                "【光鸭云盘助手】【v3.6.3】【媒体类型消歧】电影复核未确认，保留 MoviePilot 原 TV 结果: %s - %s",
                getattr(item, "path", ""),
                movie_error,
            )
            return transfer_chain, directory_item, kwargs, plan_error

        consistent, consistency_error = _same_title_and_year(tv_media, movie_media)
        if not consistent:
            logger.warning(
                "【光鸭云盘助手】【v3.6.3】【媒体类型消歧】电影候选一致性未通过，保留 TV，源文件不按电影误整理: %s - %s",
                getattr(item, "path", ""),
                consistency_error,
            )
            return transfer_chain, directory_item, kwargs, plan_error

        current_kwargs.pop("epformat", None)
        current_kwargs.pop("season", None)
        current_kwargs["mediainfo"] = movie_media
        current_kwargs["mtype"] = MediaType.MOVIE
        setattr(item, "_guangya_media_type_disambiguation_v363", {
            "from": "TV",
            "to": "MOVIE",
            "title": str(getattr(movie_media, "title", "") or ""),
            "year": _media_year(movie_media),
            "reason": "single_video_no_episode_moviepilot_movie_confirmed",
        })
        logger.warning(
            "【光鸭云盘助手】【v3.6.3】【媒体类型消歧】电视剧结构未成立，MoviePilot 电影约束识别已确认；"
            "本次按电影继续整理: %s -> %s",
            getattr(item, "path", ""),
            getattr(movie_media, "title_year", None) or getattr(movie_media, "title", ""),
        )
        return transfer_chain, directory_item, current_kwargs, None

    _loss_guard._build_moviepilot_kwargs = build
    _loss_guard._guangya_media_type_disambiguation_v363 = True
    logger.info(
        "【光鸭云盘助手】【v3.6.3】TV→MOVIE 安全消歧已启用：仅单主视频、无集号、非 Season 目录且 MoviePilot 电影复核一致时切换"
    )


__all__ = [
    "install_media_type_disambiguation_v363",
    "_is_movie_media",
    "_same_title_and_year",
]
