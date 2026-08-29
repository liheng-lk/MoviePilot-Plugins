"""v3.5.2：电影/电视剧任务语义收口。

只修正调度与适配边界，不接管 MoviePilot 的业务规则：
1. MoviePilot 已明确识别为电影时，不再调用电视剧集数模板推荐器；
2. 字幕/音频等旁路文件不再作为独立整理状态成员，只由 MoviePilot 在主视频整理时关联处理；
3. 自动清理历史版本错误积累的旁路文件 inflight/retry/blocked/stabilizing 状态。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from app.schemas.types import MediaType
from app.sdk.logging import logger

from . import organizer_episode_name_adapter_v3411 as _episode_adapter
from . import organizer_loss_guard_v349 as _loss_guard
from .organizer_empty_folder_guard_v3410 import _runtime_media_exts
from .organizer_folder_stream import GuangYaFolderStreamMixin
from .organizer_orchestrator_v351 import _primary_media_files


_MEDIA_TYPE_CACHE: Dict[str, Any] = {}
_CACHE_LIMIT = 256


def _cache_key(value: Any) -> str:
    return str(value or "").replace("\\", "/").rstrip("/")


def _remember_type(path: str, media: Any) -> None:
    key = _cache_key(path)
    if not key:
        return
    _MEDIA_TYPE_CACHE[key] = getattr(media, "type", None) if media else None
    if len(_MEDIA_TYPE_CACHE) > _CACHE_LIMIT:
        for old_key in list(_MEDIA_TYPE_CACHE)[: len(_MEDIA_TYPE_CACHE) - _CACHE_LIMIT]:
            _MEDIA_TYPE_CACHE.pop(old_key, None)


def _is_confirmed_movie(path: str) -> bool:
    return _MEDIA_TYPE_CACHE.get(_cache_key(path)) == MediaType.MOVIE


def _is_video_path(path: str) -> bool:
    suffix = Path(str(path or "")).suffix.casefold()
    return bool(suffix and suffix in _runtime_media_exts())


def _prune_sidecar_transient_state(plugin: Any) -> int:
    """移除旧版本误写入状态机的字幕/音频等待项，不碰真实视频状态。"""
    try:
        state = plugin._state()
    except Exception:
        return 0

    def _apply(raw: Dict[str, Any]) -> int:
        removed = 0
        for bucket in ("stabilizing", "inflight", "retry", "blocked"):
            mapping = raw.get(bucket)
            if not isinstance(mapping, dict):
                continue
            for path in list(mapping):
                if _is_video_path(path):
                    continue
                mapping.pop(path, None)
                removed += 1
        return removed

    try:
        removed = int(state.mutate(_apply) or 0)
    except Exception as err:  # noqa: BLE001
        logger.debug("【光鸭云盘助手】【任务语义】旁路状态清理失败: %s", err)
        return 0

    if removed:
        status = dict(plugin.get_data(plugin._monitor_status_key) or {})
        total = int(status.get("sidecar_state_pruned_total") or 0) + removed
        plugin._save_monitor_status(
            sidecar_state_pruned=removed,
            sidecar_state_pruned_total=total,
        )
        logger.info(
            "【光鸭云盘助手】【任务语义】已清理历史旁路文件等待状态 %s 个；字幕/音频不再单独计入整理任务",
            removed,
        )
    return removed


def install_task_semantics_v352() -> None:
    if getattr(GuangYaFolderStreamMixin, "_guangya_task_semantics_v352", False):
        return

    # loss guard 先做目录识别，再调用集数推荐；缓存刚刚得到的 MP 媒体类型，
    # 让后续集数适配明确知道“这是电影”，避免产生无意义 WARNING。
    original_context = _loss_guard._moviepilot_directory_context

    def directory_context(path: str):
        result = original_context(path)
        context = result[0] if isinstance(result, tuple) and result else None
        media = getattr(context, "media_info", None) if context else None
        _remember_type(path, media)
        return result

    _loss_guard._moviepilot_directory_context = directory_context

    original_episode_format = _loss_guard._moviepilot_episode_format

    def moviepilot_episode_format(*, transfer_chain: Any, directory_item: Any):
        path = str(getattr(directory_item, "path", "") or "")
        if _is_confirmed_movie(path):
            return None, "MoviePilot 已确认电影，跳过电视剧集数模板推荐"
        return original_episode_format(
            transfer_chain=transfer_chain,
            directory_item=directory_item,
        )

    _loss_guard._moviepilot_episode_format = moviepilot_episode_format

    original_member_recommend = _episode_adapter._mp_member_recommend

    def member_recommend(plugin: Any, transfer_chain: Any, directory_item: Any, item: Any):
        path = str(getattr(directory_item, "path", "") or getattr(item, "path", "") or "")
        if _is_confirmed_movie(path):
            return None, {}, "confirmed_movie_skip_episode_recommend"
        return original_member_recommend(plugin, transfer_chain, directory_item, item)

    _episode_adapter._mp_member_recommend = member_recommend

    # 从任务状态层彻底剥离 sidecar。目录模式下 MoviePilot 仍会自行扫描同目录并关联字幕；
    # 插件只追踪真正会收到 TransferComplete/TransferFailed 的主视频成员。
    original_process = GuangYaFolderStreamMixin._process_folder_group

    def process_group(self: Any, **kwargs: Any):
        files = list(kwargs.get("files") or [])
        primary = _primary_media_files(files)
        if primary:
            dropped = max(len(files) - len(primary), 0)
            if dropped:
                kwargs = dict(kwargs)
                kwargs["files"] = primary
                logger.debug(
                    "【光鸭云盘助手】【任务语义】旁路文件不作为独立任务成员: %s，主视频=%s，旁路=%s",
                    kwargs.get("group_path") or "",
                    len(primary),
                    dropped,
                )
        return original_process(self, **kwargs)

    GuangYaFolderStreamMixin._process_folder_group = process_group

    # 每轮扫描前清理一次历史遗留 sidecar retry/inflight，解决升级后“重试等待”长期虚高。
    original_scan = GuangYaFolderStreamMixin.run_organize_monitor_scan

    def run_scan(self: Any, manual: bool = False):
        _prune_sidecar_transient_state(self)
        return original_scan(self, manual=manual)

    GuangYaFolderStreamMixin.run_organize_monitor_scan = run_scan
    GuangYaFolderStreamMixin._guangya_task_semantics_v352 = True
    logger.info("【光鸭云盘助手】【v3.5.2】电影集数推荐隔离与主视频任务语义已启用")


__all__ = [
    "install_task_semantics_v352",
    "_prune_sidecar_transient_state",
]
