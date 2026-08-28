"""v3.5.0 P0：把“作品身份”和“单文件集号”彻底分开。

自动整理遇到 ``作品名 (年份)/Season 1/01 4K.mp4`` 这类目录时，文件名可能完全不包含
作品标题，但作品目录本身是可靠的。旧链路直接对当前文件目录（例如 ``Season 1``）识别，
再叠加文件级集号解析，容易把“某个文件无法识别集号”误报成“作品识别失败”。

本层只做两件事：
1. Season/Sxx/第N季目录向上取一级作为“作品身份目录”，由 MoviePilot 原生
   ``MediaChain.recognize_by_path`` 识别作品；
2. 将该 MoviePilot 识别结果重新注入同一 ``TransferChain`` 预览/真实整理。

集号仍由 MoviePilot 推荐器和既有 v3.4.11 兼容层处理；分类仍按 MoviePilot 当前
``category.yaml`` 复核；本层不写死标题、TMDB ID、分类或命名规则。
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any, Optional, Tuple

from app.sdk.logging import logger

from . import organizer_loss_guard_v349 as _loss_guard
from .organizer_category_consistency_v3412 import _reconcile_moviepilot_category
from .organizer_mp_folder_context_v346 import (
    _is_tv_media,
    _moviepilot_directory_context,
    _moviepilot_tv_context_from_directory_meta,
)


_SEASON_DIR = re.compile(
    r"^(?:season[ ._-]*0*\d{1,3}|s0*\d{1,3}|第\s*0*\d{1,3}\s*季)$",
    re.IGNORECASE,
)


def _resource_identity_path(plugin: Any, group_path: str) -> str:
    """返回作品身份目录；Season 目录只承载季信息，不作为作品标题。"""
    normalized = plugin._organize_normalize_path(group_path)
    path = PurePosixPath(normalized)
    name = str(path.name or "").strip()

    season_re = getattr(plugin, "_season_dir_re", None)
    is_season = bool(_SEASON_DIR.fullmatch(name))
    if season_re is not None:
        try:
            is_season = is_season or bool(season_re.fullmatch(name))
        except Exception:
            pass

    if is_season and path.parent != path:
        return plugin._organize_normalize_path(str(path.parent))
    return normalized


def _identity_media(
    plugin: Any,
    item: Any,
    *,
    tv_required: bool,
) -> Tuple[Any, Any, str, Optional[str]]:
    """仅由 MoviePilot 识别作品目录，必要时仍用 MoviePilot 约束 TV 重识别。"""
    identity_path = _resource_identity_path(plugin, str(getattr(item, "path", "") or ""))
    context, error = _moviepilot_directory_context(identity_path)
    media = getattr(context, "media_info", None) if context else None
    meta = getattr(context, "meta_info", None) if context else None

    if media and tv_required and not _is_tv_media(media):
        tv_media, tv_error = _moviepilot_tv_context_from_directory_meta(meta)
        if tv_media:
            media = tv_media
            error = None
        else:
            return None, meta, identity_path, str(tv_error or error or "MoviePilot 电视剧识别未确认")

    if not media:
        return None, meta, identity_path, str(error or "MoviePilot 未从作品目录识别到媒体信息")

    reconciled, diagnostics, category_error = _reconcile_moviepilot_category(media)
    if category_error:
        return None, meta, identity_path, category_error

    setattr(item, "_guangya_folder_identity_v350", {
        "path": identity_path,
        "title": str(getattr(reconciled, "title", "") or ""),
        "title_year": str(getattr(reconciled, "title_year", "") or getattr(reconciled, "title", "") or ""),
        "year": getattr(reconciled, "year", None),
        "type": str(getattr(getattr(reconciled, "type", None), "value", getattr(reconciled, "type", None)) or ""),
        "category": str(getattr(reconciled, "category", "") or ""),
        "tmdb_id": getattr(reconciled, "tmdb_id", None),
        "media_id": getattr(reconciled, "media_id", None),
        "category_diagnostics": diagnostics,
    })
    setattr(item, "_guangya_folder_identity_media_v350", reconciled)
    setattr(item, "_guangya_folder_identity_meta_v350", meta)
    return reconciled, meta, identity_path, None


def install_folder_identity_v350() -> None:
    """最后包裹 v3.4.x 的 MP kwargs 构造，使作品目录身份优先于单文件标题。"""
    if getattr(_loss_guard, "_guangya_folder_identity_v350", False):
        return

    original_build = _loss_guard._build_moviepilot_kwargs

    def build(plugin: Any, item: Any):
        transfer_chain, directory_item, kwargs, plan_error = original_build(plugin, item)

        identity_path = _resource_identity_path(plugin, str(getattr(item, "path", "") or ""))
        current_path = plugin._organize_normalize_path(str(getattr(item, "path", "") or ""))
        season_parent_mode = identity_path != current_path
        tv_required = bool(kwargs.get("epformat")) or season_parent_mode

        media, _meta, resolved_path, identity_error = _identity_media(
            plugin,
            item,
            tv_required=tv_required,
        )
        if media:
            kwargs = dict(kwargs or {})
            kwargs["mediainfo"] = media
            media_type = getattr(media, "type", None)
            if media_type:
                kwargs["mtype"] = media_type
            logger.info(
                "【光鸭云盘助手】【文件夹身份】作品目录=%s -> %s；当前文件目录=%s；"
                "作品识别与单文件集号解析已分离",
                resolved_path,
                getattr(media, "title_year", None) or getattr(media, "title", ""),
                current_path,
            )
            # Season 目录以前可能因为用 Season 1/文件名识别而产生 plan_error；
            # 作品目录已经由 MP 明确认出后，允许进入后续独立集号校验。
            return transfer_chain, directory_item, kwargs, None

        setattr(item, "_guangya_folder_identity_v350", {
            "path": resolved_path,
            "state": "failed",
            "error": identity_error or "",
        })

        # 当前目录本身就是作品目录时，保留既有 MP 原生结果；这里不制造第二套判定。
        if not season_parent_mode and not plan_error:
            return transfer_chain, directory_item, kwargs, None

        # Season 子目录明确存在上级作品目录时，作品身份必须由该目录确认；
        # 不允许退回到 01.mp4/S01E05.xxx 等文件名去猜另一个作品。
        if season_parent_mode:
            message = f"作品目录识别未确认：{resolved_path} - {identity_error or '未知原因'}"
            logger.warning(
                "【光鸭云盘助手】【文件夹身份】%s；文件名不作为作品身份兜底，源文件保持原位",
                message,
            )
            return transfer_chain, directory_item, kwargs, message

        return transfer_chain, directory_item, kwargs, plan_error

    _loss_guard._build_moviepilot_kwargs = build
    _loss_guard._guangya_folder_identity_v350 = True


__all__ = [
    "install_folder_identity_v350",
    "_resource_identity_path",
]
