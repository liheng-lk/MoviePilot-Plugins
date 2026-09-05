"""v3.4.9：自动整理零损失保护。

目录整理在真正 move/copy 前，先使用 MoviePilot 同一套识别、命名和目标目录规则执行
``preview=True``。插件只做安全审计，不改变 MoviePilot 的业务规则：

- 本轮待整理源文件必须全部出现在预览结果中；
- 每个源文件必须得到成功且非空的目标路径；
- 不同源文件不能规划到同一个目标路径。

任何一项不满足就整文件夹停止，不执行真实整理，避免错误集号/识别导致同名覆盖，进而把
前一集送进回收站。

另外，文件夹级 ``do_transfer`` 返回成功不再作为“所有成员成功”的兜底证据；只有
MoviePilot 的逐文件最终事件才能把成员标记 completed。仍停留在 inflight 的成员会回到
retry，避免漏事件时被静默标记完成。
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from app.chain.transfer import TransferChain
from app.schemas.types import MediaType
from app.sdk.logging import logger

from .organizer_folder_batch_v342 import _FolderBatchEnvelope
from .organizer_mp_folder_context_v346 import (
    _directory_fileitem,
    _is_monitor_root_folder_task,
    _is_tv_media,
    _moviepilot_directory_context,
    _moviepilot_episode_format,
    _moviepilot_tv_context_from_directory_meta,
    _normalize_result,
)


def _normalize_path(plugin: Any, value: Any) -> str:
    return plugin._organize_normalize_path(str(value or ""))


def _preview_result(result: Any) -> Tuple[bool, Optional[dict], str]:
    if isinstance(result, tuple):
        success = bool(result[0])
        payload = result[1] if len(result) > 1 else None
    else:
        success = bool(result)
        payload = None

    if not success:
        if isinstance(payload, dict):
            message = str(payload.get("message") or payload)
        else:
            message = str(payload or "MoviePilot 整理预览失败")
        return False, payload if isinstance(payload, dict) else None, message
    if not isinstance(payload, dict):
        return False, None, "MoviePilot 未返回可审计的整理预览结果"
    return True, payload, ""


def _audit_preview(plugin: Any, item: _FolderBatchEnvelope, result: Any) -> Tuple[bool, str, Dict[str, Any]]:
    """核对本轮成员是否一一映射到唯一目标；这里只审计，不自行计算目标路径。"""
    ok, payload, error = _preview_result(result)
    if not ok or payload is None:
        return False, error, {"preview_total": 0, "expected": len(item.members)}

    preview_items = [row for row in (payload.get("items") or []) if isinstance(row, dict)]
    expected_sources = {
        _normalize_path(plugin, getattr(member, "path", ""))
        for member in item.members
        if getattr(member, "path", None)
    }
    by_source: Dict[str, dict] = {}
    for row in preview_items:
        source = _normalize_path(plugin, row.get("source"))
        if source:
            by_source[source] = row

    missing = sorted(source for source in expected_sources if source not in by_source)
    failed: List[str] = []
    empty_target: List[str] = []
    target_sources: Dict[str, List[str]] = defaultdict(list)

    for source in sorted(expected_sources):
        row = by_source.get(source)
        if not row:
            continue
        if not bool(row.get("success")):
            failed.append(source)
            continue
        target = _normalize_path(plugin, row.get("target"))
        if not target:
            empty_target.append(source)
            continue
        target_sources[target].append(source)

    duplicates = {
        target: sources
        for target, sources in target_sources.items()
        if len(set(sources)) > 1
    }

    details = {
        "expected": len(expected_sources),
        "preview_total": len(preview_items),
        "matched": len(expected_sources - set(missing)),
        "missing": missing[:20],
        "failed": failed[:20],
        "empty_target": empty_target[:20],
        "duplicate_targets": {
            target: sources[:10] for target, sources in list(duplicates.items())[:10]
        },
    }

    problems: List[str] = []
    if missing:
        problems.append(f"{len(missing)} 个源文件未进入 MoviePilot 预览")
    if failed:
        problems.append(f"{len(failed)} 个源文件预览失败")
    if empty_target:
        problems.append(f"{len(empty_target)} 个源文件没有目标路径")
    if duplicates:
        examples = []
        for target, sources in list(duplicates.items())[:3]:
            names = ", ".join(source.rsplit("/", 1)[-1] for source in sources[:4])
            examples.append(f"{names} -> {target}")
        problems.append(f"发现 {len(duplicates)} 组重复目标：" + "；".join(examples))

    if problems:
        return False, "；".join(problems), details
    return True, "", details


def _build_moviepilot_kwargs(plugin: Any, item: _FolderBatchEnvelope) -> Tuple[TransferChain, Any, Dict[str, Any], Optional[str]]:
    """与 v3.4.8 实际目录整理保持同一 MoviePilot 上下文，不引入第二套识别规则。"""
    directory_item = _directory_fileitem(plugin, item)
    transfer_chain = TransferChain()

    context, recognize_error = _moviepilot_directory_context(directory_item.path)
    media = getattr(context, "media_info", None) if context else None
    meta = getattr(context, "meta_info", None) if context else None

    epformat, episode_error = _moviepilot_episode_format(
        transfer_chain=transfer_chain,
        directory_item=directory_item,
    )
    if epformat and not _is_tv_media(media):
        tv_media, tv_error = _moviepilot_tv_context_from_directory_meta(meta)
        if tv_media:
            media = tv_media
            recognize_error = None
        else:
            return (
                transfer_chain,
                directory_item,
                {},
                str(tv_error or "MoviePilot 已检测到集数结构，但电视剧识别未确认"),
            )

    kwargs: Dict[str, Any] = {
        "fileitem": directory_item,
        "background": False,
        "manual": False,
    }
    if media:
        kwargs["mediainfo"] = media
        media_type = getattr(media, "type", None)
        if media_type:
            kwargs["mtype"] = media_type
    elif epformat:
        kwargs["mtype"] = MediaType.TV
    if epformat:
        kwargs["epformat"] = epformat

    if media:
        logger.info(
            "【光鸭云盘助手】【数据安全校验】MoviePilot 目录上下文: %s -> %s；分类=%s",
            item.path,
            getattr(media, "title_year", None) or getattr(media, "title", ""),
            getattr(media, "category", None) or "由 MoviePilot 决定",
        )
    elif recognize_error:
        logger.warning(
            "【光鸭云盘助手】【数据安全校验】%s；继续仅使用 MoviePilot 原生整理预览: %s",
            recognize_error,
            item.path,
        )
    if episode_error and not epformat:
        logger.debug(
            "【光鸭云盘助手】【数据安全校验】MoviePilot 未推荐额外集数模板: %s - %s",
            item.path,
            episode_error,
        )

    return transfer_chain, directory_item, kwargs, None


def _defer_unconfirmed_members(plugin: Any, item: _FolderBatchEnvelope, reason: str) -> List[str]:
    """文件夹整体成功但成员无逐文件终态时，退回重试而不是直接 completed。"""
    state_store = plugin._state()
    raw = state_store.load()
    inflight = dict(raw.get("inflight") or {})
    deferred: List[str] = []
    now = time.time()
    for member in item.members:
        path = _normalize_path(plugin, getattr(member, "path", ""))
        if not path or path not in inflight:
            continue
        fingerprint = plugin._fingerprint(member)
        state_store.mark_deferred(
            path=path,
            fingerprint=fingerprint,
            now=now,
            reason=reason,
        )
        deferred.append(path)
    return deferred



__all__ = [
    "_audit_preview",
    "_build_moviepilot_kwargs",
    "_defer_unconfirmed_members",
    "_preview_result",
]
