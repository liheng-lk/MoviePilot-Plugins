"""v3.5.8：为电视剧弱命名任务补齐 MoviePilot 原生 season 上下文。

问题背景：
``06.2160p...mp4`` 这类文件能由 MoviePilot/既有兼容层稳定识别出集号 E06，
但文件名本身不含 Sxx；当资源目录又是 ``剧名 (年份)`` 而不是 ``Season 01`` 时，
调用 ``TransferChain.do_transfer`` 若只传 ``mediainfo + epformat``，MoviePilot 的文件
Meta 仍可能没有 ``begin_season``，最终用户的 TV 命名模板会渲染出空的 ``Season  ``。

本层不拼接目标路径、不修改命名模板，也不自行决定媒体类型，只把可靠季号通过
MoviePilot 公开的 ``season`` 参数交回宿主：
1. 当前资源路径明确为 Season N / SNN / 第N季；
2. 文件名中存在一致的 SxxExx 季号；
3. MoviePilot 已确认该电视剧只有一个正季（忽略 Specials/Season 0）。

如果多个文件显式给出冲突季号，或 MoviePilot 明确是多季剧但当前目录/文件均没有可靠
季号，则宁可阻止真实整理并保留源文件，也不猜季号。

升级时还会一次性唤醒旧的“Season  目录获取失败” retry，使已失败成员立即重新走
v3.5.8 季号补全；其它 retry 完全不动。
"""

from __future__ import annotations

import re
import time
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from app.schemas.types import MediaType
from app.sdk.logging import logger

from . import organizer_loss_guard_v349 as _loss_guard
from .organizer_episode_name_adapter_v3411 import _episode_token, _media_members
from .organizer_folder_stream import GuangYaFolderStreamMixin
from .organizer_mp_folder_context_v346 import _is_tv_media


_MARKER_KEY = "organize_v358_empty_season_retry_wakeup"
_EMPTY_SEASON_RETRY = re.compile(r"Season\s+目录获取失败", re.IGNORECASE)
_SEASON_DIR = re.compile(
    r"^(?:season[ ._-]*0*(?P<season1>\d{1,3})|"
    r"s0*(?P<season2>\d{1,3})|"
    r"第\s*0*(?P<season3>\d{1,3})\s*季)$",
    re.IGNORECASE,
)


def _positive_int(value: Any) -> Optional[int]:
    try:
        number = int(str(value))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _is_tv_kwargs(kwargs: Dict[str, Any]) -> bool:
    media = kwargs.get("mediainfo")
    if media and _is_tv_media(media):
        return True
    mtype = kwargs.get("mtype")
    if mtype == MediaType.TV:
        return True
    value = getattr(mtype, "value", mtype)
    return str(value or "").casefold() in {
        str(getattr(MediaType.TV, "value", MediaType.TV)).casefold(),
        "tv",
        "电视剧",
    }


def _season_from_path(value: Any) -> Optional[int]:
    """从当前资源路径最后一级明确 Season 目录读取季号。"""
    name = str(PurePosixPath(str(value or "")).name or "").strip()
    match = _SEASON_DIR.fullmatch(name)
    if not match:
        return None
    for key in ("season1", "season2", "season3"):
        season = _positive_int(match.group(key))
        if season is not None:
            return season
    return None


def _member_explicit_seasons(item: Any) -> Set[int]:
    """只接受文件名中明确携带 SxxExx 的季号，不把裸数字集号当季号。"""
    seasons: Set[int] = set()
    for member in _media_members(item):
        name = str(
            getattr(member, "name", "")
            or Path(str(getattr(member, "path", "") or "")).name
        )
        token = _episode_token(name)
        if token and token.season:
            season = _positive_int(token.season)
            if season is not None:
                seasons.add(season)
    return seasons


def _collect_positive_keys(value: Any) -> Set[int]:
    seasons: Set[int] = set()
    if isinstance(value, dict):
        values: Iterable[Any] = value.keys()
    elif isinstance(value, (list, tuple, set)):
        values = value
    else:
        return seasons
    for raw in values:
        if isinstance(raw, dict):
            raw = raw.get("season_number") or raw.get("season")
        season = _positive_int(raw)
        if season is not None:
            seasons.add(season)
    return seasons


def _media_positive_seasons(media: Any) -> Set[int]:
    """读取 MoviePilot 媒体对象已经投影出的季清单；Season 0 不参与单季判断。"""
    seasons: Set[int] = set()
    for attr in ("seasons", "season_years"):
        seasons.update(_collect_positive_keys(getattr(media, attr, None)))
    info = getattr(media, "season_info", None)
    if isinstance(info, (list, tuple)):
        for row in info:
            if not isinstance(row, dict):
                continue
            season = _positive_int(row.get("season_number") or row.get("season"))
            if season is not None:
                seasons.add(season)
    return seasons


def _resolve_reliable_season(item: Any, kwargs: Dict[str, Any]) -> Tuple[Optional[int], str, Optional[str]]:
    """返回 (season, source, error)；error 表示发现明确冲突而不是普通未知。"""
    existing = _positive_int(kwargs.get("season"))
    if existing is not None:
        return existing, "moviepilot_existing", None

    path_season = _season_from_path(getattr(item, "path", ""))
    explicit = _member_explicit_seasons(item)
    if len(explicit) > 1:
        return None, "member_conflict", f"同一资源包含多个明确季号: {sorted(explicit)}"
    member_season = next(iter(explicit), None)
    if path_season is not None and member_season is not None and path_season != member_season:
        return (
            None,
            "path_member_conflict",
            f"目录季号 S{path_season:02d} 与文件明确季号 S{member_season:02d} 冲突",
        )
    if path_season is not None:
        return path_season, "season_directory", None
    if member_season is not None:
        return member_season, "member_sxe", None

    media = kwargs.get("mediainfo") or getattr(item, "_guangya_folder_identity_media_v350", None)
    media_seasons = _media_positive_seasons(media) if media else set()
    if len(media_seasons) == 1:
        return next(iter(media_seasons)), "moviepilot_single_season", None
    if len(media_seasons) > 1:
        return (
            None,
            "moviepilot_multi_season",
            "MoviePilot 已确认该剧存在多个正季，但当前目录和文件名都没有可靠季号",
        )
    return None, "unknown", None


def _wake_empty_season_retries(plugin: Any) -> Dict[str, Any]:
    marker = plugin.get_data(_MARKER_KEY) or {}
    if isinstance(marker, dict) and marker.get("applied"):
        return marker

    state_store = plugin._state()
    now = time.time()

    def apply(state: Dict[str, Any]) -> Dict[str, Any]:
        retry = dict(state.get("retry") or {})
        woken: List[str] = []
        untouched = 0
        for path, raw in list(retry.items()):
            if not isinstance(raw, dict):
                untouched += 1
                continue
            reason = str(raw.get("last_error") or "")
            if not _EMPTY_SEASON_RETRY.search(reason):
                untouched += 1
                continue
            row = dict(raw)
            row["retry_at"] = 0
            row["v358_wakeup_at"] = now
            row["v358_wakeup_reason"] = "升级后立即使用 MoviePilot season 上下文重新整理"
            retry[path] = row
            woken.append(str(path))
        state["retry"] = retry
        return {"woken": len(woken), "paths": woken[:20], "untouched": untouched}

    result = dict(state_store.mutate(apply) or {})
    marker = {
        "applied": True,
        "applied_at": now,
        "woken": int(result.get("woken") or 0),
        "paths": list(result.get("paths") or []),
        "untouched": int(result.get("untouched") or 0),
    }
    plugin.save_data(_MARKER_KEY, marker)
    if marker["woken"]:
        logger.warning(
            "【光鸭云盘助手】【v3.5.8】【升级自愈】发现空 Season 目标失败 retry=%s，"
            "已取消旧退避并立即重新交给 MoviePilot season 上下文；其它 retry 保持原样",
            marker["woken"],
        )
    return marker


def install_season_context_v358() -> None:
    if getattr(_loss_guard, "_guangya_season_context_v358", False):
        return

    previous_build = _loss_guard._build_moviepilot_kwargs

    def build(plugin: Any, item: Any):
        transfer_chain, directory_item, kwargs, plan_error = previous_build(plugin, item)
        if plan_error or not _is_tv_kwargs(dict(kwargs or {})):
            return transfer_chain, directory_item, kwargs, plan_error

        kwargs = dict(kwargs or {})
        season, source, season_error = _resolve_reliable_season(item, kwargs)
        if season_error:
            message = f"电视剧季号上下文未确认：{season_error}"
            logger.error(
                "【光鸭云盘助手】【v3.5.8】【季号上下文】阻止真实整理，源文件保持原位: %s - %s",
                getattr(item, "path", ""),
                message,
            )
            return transfer_chain, directory_item, kwargs, message
        if season is not None:
            kwargs["season"] = season
            setattr(item, "_guangya_season_context_v358", {"season": season, "source": source})
            logger.info(
                "【光鸭云盘助手】【v3.5.8】【季号上下文】MoviePilot season=%s，来源=%s: %s",
                season,
                source,
                getattr(item, "path", ""),
            )
        return transfer_chain, directory_item, kwargs, None

    _loss_guard._build_moviepilot_kwargs = build
    _loss_guard._guangya_season_context_v358 = True

    previous_scan = GuangYaFolderStreamMixin.run_organize_monitor_scan

    def run_scan(self: Any, manual: bool = False):
        try:
            _wake_empty_season_retries(self)
        except Exception as err:  # noqa: BLE001
            logger.exception("【光鸭云盘助手】【v3.5.8】【升级自愈】空 Season retry 唤醒失败: %s", err)
        return previous_scan(self, manual=manual)

    GuangYaFolderStreamMixin.run_organize_monitor_scan = run_scan
    logger.info("【光鸭云盘助手】【v3.5.8】电视剧季号上下文补全与空季重试自愈已启用")


__all__ = [
    "install_season_context_v358",
    "_resolve_reliable_season",
    "_wake_empty_season_retries",
]
