"""v3.5.0 P0：严格单任务流水线。

目标不是“扫描一大批 -> 全部识别 -> 全部排队”，而是：

    发现一个资源单元 -> 识别/预览 -> 整理完成 -> 再发现下一个

电视剧/Season 仍以完整文件夹作为一个资源单元，保证整季上下文与零损失校验；
普通容器目录（如 mp/电影/华语电影）里散放的多部电影则一次只提交一个视频文件，
避免把整个容器目录交给 MoviePilot 后先把几十部电影全部识别、计划后再慢慢执行。

本层只调整调度粒度和背压，不改变 MoviePilot 的识别、分类、命名、目标目录或覆盖规则。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Tuple

from app.sdk.logging import logger

from .organizer_episode_name_adapter_v3411 import _episode_token
from .organizer_folder_stream import GuangYaFolderStreamMixin
from .organizer_queue_recovery import GuangYaQueueRecoveryMixin
from .organizer_state import OrganizerStateStore
from .organizer_empty_folder_guard_v3410 import _runtime_media_exts


_GENERIC_CONTAINER_NAMES = {
    "mp", "media", "medias", "download", "downloads", "incoming", "inbox",
    "movie", "movies", "film", "films", "电影", "電影", "影片",
    "华语电影", "華語電影", "国产电影", "國產電影", "外语电影", "外語電影",
    "欧美电影", "歐美電影", "日韩电影", "日韓電影",
    "tv", "tvshows", "tv shows", "series", "shows", "电视剧", "電視劇",
    "剧", "劇", "剧集", "劇集", "国产剧", "國產劇", "欧美剧", "歐美劇",
    "日韩剧", "日韓劇", "动漫", "動漫", "动画", "動畫", "番剧", "番劇",
}


def _normalized_name(value: str) -> str:
    return " ".join(str(value or "").replace("_", " ").replace("-", " ").split()).casefold()


def _is_season_dir(plugin: Any, group_path: str) -> bool:
    name = PurePosixPath(group_path).name
    season_re = getattr(plugin, "_season_dir_re", None)
    if season_re is not None:
        try:
            if season_re.fullmatch(name):
                return True
        except Exception:
            pass
    normalized = _normalized_name(name).replace(" ", "")
    if normalized.startswith("season") and normalized[6:].isdigit():
        return True
    return normalized.startswith("s") and normalized[1:].isdigit()


def _media_files(files: Iterable[Any]) -> List[Any]:
    media_exts = _runtime_media_exts()
    result: List[Any] = []
    for item in files:
        name = str(getattr(item, "name", "") or Path(str(getattr(item, "path", "") or "")).name)
        if Path(name).suffix.casefold() in media_exts:
            result.append(item)
    return result


def _has_episode_structure(plugin: Any, group_path: str, files: List[Any]) -> bool:
    """只判断任务边界是否像剧集，不决定最终媒体类型。"""
    if _is_season_dir(plugin, group_path):
        return True

    group_name = PurePosixPath(group_path).name
    series_re = getattr(plugin, "_series_folder_re", None)
    if series_re is not None:
        try:
            if series_re.search(group_name):
                return True
        except Exception:
            pass

    media = _media_files(files)
    if len(media) < 2:
        return False
    tokens = []
    for item in media:
        name = str(getattr(item, "name", "") or Path(str(getattr(item, "path", "") or "")).name)
        token = _episode_token(name)
        if token:
            tokens.append(token)
    if len(tokens) < 2:
        return False
    identities = {(token.season, token.start, token.end) for token in tokens}
    return len(identities) == len(tokens) and len(tokens) >= max(2, len(media) - 1)


def _is_loose_container(plugin: Any, group_path: str, files: List[Any]) -> bool:
    """容器目录中的多部独立视频按单文件串行；剧集目录和单作品目录不拆。"""
    media = _media_files(files)
    if len(media) <= 1 or _has_episode_structure(plugin, group_path, files):
        return False
    normalized_group = plugin._organize_normalize_path(group_path)
    normalized_root = plugin._organize_normalize_path(plugin._organize_monitor_path)
    if normalized_group == normalized_root:
        return True
    name = _normalized_name(PurePosixPath(group_path).name)
    return name in {_normalized_name(value) for value in _GENERIC_CONTAINER_NAMES}


def _empty_counters(file_count: int) -> Dict[str, int]:
    return {
        "files": file_count,
        "changed": 0,
        "waiting": 0,
        "inflight": 0,
        "retry_wait": 0,
        "completed": 0,
        "ignored": 0,
        "blocked": 0,
        "ready": 0,
        "submitted": 0,
        "deferred": 0,
        "failed": 0,
        "unsupported": 0,
        "history_completed": 0,
        "newly_blocked": 0,
        "capacity_wait": 0,
        "folder_tasks": 0,
        "resource_tasks": 0,
    }


def _process_one_loose_resource(
    self: Any,
    *,
    group_path: str,
    files: List[Any],
    dispatcher: Any,
    state: OrganizerStateStore,
    submit_budget: Dict[str, int],
    now_text: str,
    scan_started: float,
) -> Dict[str, int]:
    """普通容器目录一次只选择并提交一个主要视频。"""
    counters = _empty_counters(len(files))
    now = time.time()
    media_files = sorted(_media_files(files), key=self._file_sort_key)
    selected: Tuple[Any, str, str] | None = None

    for item in media_files:
        path = self._organize_normalize_path(getattr(item, "path", ""))
        fp = self._fingerprint(item)
        if not dispatcher.is_transfer_candidate_path(Path(path)):
            counters["unsupported"] += 1
            state.mark_ignored(path=path, fingerprint=fp)
            continue

        phase = state.classify(
            path=path,
            fingerprint=fp,
            now=now,
            stability_seconds=self._organize_monitor_stability,
            inflight_lease_seconds=self._monitor_inflight_lease,
        )
        if phase == "completed":
            counters["completed"] += 1
            continue
        if phase == "ignored":
            counters["ignored"] += 1
            continue
        if phase == "blocked":
            counters["blocked"] += 1
            continue
        counters["changed"] += 1
        if phase == "stabilizing":
            counters["waiting"] += 1
            continue
        if phase == "inflight":
            counters["inflight"] += 1
            continue
        if phase == "retry_wait":
            counters["retry_wait"] += 1
            continue
        if phase == "ready":
            counters["ready"] += 1
            if selected is None:
                selected = (item, path, fp)
            else:
                counters["capacity_wait"] += 1

    if selected is None:
        return counters

    item, path, fp = selected
    preflight = self._preflight_history(item, path)
    decision = str(preflight.get("decision") or "unknown")
    message = str(preflight.get("message") or "")
    if decision == "completed":
        counters["history_completed"] += 1
        state.mark_completed(path=path, fingerprint=fp)
        return counters
    if decision == "blocked":
        counters["newly_blocked"] += 1
        state.mark_blocked(path=path, fingerprint=fp, reason=message, now=time.time())
        return counters
    if decision == "unknown":
        counters["deferred"] += 1
        state.mark_deferred(
            path=path,
            fingerprint=fp,
            now=time.time(),
            reason=message or "MoviePilot 整理历史暂不可用",
        )
        return counters

    attempts = state.mark_submitting(
        path=path,
        fingerprint=fp,
        now=time.time(),
        metadata={
            "name": str(getattr(item, "name", "") or Path(path).name),
            "size": int(getattr(item, "size", 0) or 0),
            "history_action": preflight.get("action"),
            "group_path": group_path,
            "group_name": self._group_name(group_path),
            "batch_id": self._new_group_batch_id(path, scan_started),
            "resource_task": True,
            "resource_mode": "loose_single",
        },
    )
    if attempts == 0:
        return counters

    try:
        accepted = self._dispatch_to_moviepilot(item)
    except Exception as err:  # noqa: BLE001
        accepted = False
        message = str(err)
    if not accepted:
        counters["deferred"] += 1
        state.mark_deferred(
            path=path,
            fingerprint=fp,
            now=time.time(),
            reason=message or "私有 worker 当前未接收单任务",
        )
        return counters

    counters["submitted"] = 1
    counters["resource_tasks"] = 1
    submit_budget["remaining"] = 0
    self._append_monitor_history({
        "time": now_text,
        "path": path,
        "name": str(getattr(item, "name", "") or Path(path).name),
        "size": int(getattr(item, "size", 0) or 0),
        "result": "resource_queued",
        "group_path": group_path,
        "group_name": self._group_name(group_path),
        "message": "单任务流水：当前视频已进入私有 worker，完成后才发现下一个资源",
    })
    logger.info(
        "【光鸭云盘助手】【单任务流水】发现一个→识别一个→整理一个: %s",
        path,
    )
    return counters


def _schedule_refill(plugin: Any, delay: float = 0.6) -> None:
    """worker 收尾后异步触发下一次发现；热更新/停用时自然退出。"""
    lock = plugin._isolated_runtime_lock()
    with lock:
        timer = getattr(plugin, "_guangya_single_flight_timer_v350", None)
        if timer is not None and timer.is_alive():
            return

        def run() -> None:
            try:
                if not getattr(plugin, "_organize_monitor_enabled", False):
                    return
                snapshot = plugin._isolated_queue_snapshot()
                if snapshot.get("running_path") or int(snapshot.get("queued") or 0):
                    return
                plugin.run_organize_monitor_scan(manual=False)
            except Exception as err:  # noqa: BLE001
                logger.debug("【光鸭云盘助手】【单任务流水】自动补充扫描失败: %s", err)

        timer = threading.Timer(delay, run)
        timer.daemon = True
        plugin._guangya_single_flight_timer_v350 = timer
        timer.start()


def install_single_flight_v350() -> None:
    if getattr(GuangYaFolderStreamMixin, "_guangya_single_flight_v350", False):
        return

    # 私有队列本身也收紧为 1；更关键的是下面的 admission guard，运行中不允许再排一个。
    GuangYaQueueRecoveryMixin._isolated_queue_capacity = 1

    original_dispatch = GuangYaQueueRecoveryMixin._dispatch_to_moviepilot

    def dispatch(self: Any, item: Any) -> bool:
        self._ensure_isolated_worker()
        snapshot = self._isolated_queue_snapshot()
        if snapshot.get("running_path") or int(snapshot.get("queued") or 0) > 0 or int(snapshot.get("owned") or 0) > 0:
            logger.debug(
                "【光鸭云盘助手】【单任务流水】worker 正忙，不预排后续任务: %s",
                self._isolated_item_path(item),
            )
            return False
        accepted = bool(original_dispatch(self, item))
        if accepted:
            setattr(self, "_guangya_single_flight_claimed_v350", True)
        return accepted

    GuangYaQueueRecoveryMixin._dispatch_to_moviepilot = dispatch

    original_process = GuangYaFolderStreamMixin._process_folder_group

    def process(self: Any, **kwargs: Any) -> Dict[str, int]:
        group_path = str(kwargs.get("group_path") or "")
        files = list(kwargs.get("files") or [])
        if _is_loose_container(self, group_path, files):
            return _process_one_loose_resource(self, **kwargs)
        return original_process(self, **kwargs)

    GuangYaFolderStreamMixin._process_folder_group = process

    original_iter = GuangYaFolderStreamMixin._iter_folder_groups

    def iter_groups(self: Any, root_path: str, scan_meta: Dict[str, Any]):
        setattr(self, "_guangya_single_flight_claimed_v350", False)
        snapshot = self._isolated_queue_snapshot()
        if snapshot.get("running_path") or int(snapshot.get("queued") or 0) > 0 or int(snapshot.get("owned") or 0) > 0:
            scan_meta["truncated"] = True
            scan_meta["single_flight_busy"] = True
            logger.debug(
                "【光鸭云盘助手】【单任务流水】已有任务执行中，本轮不扫描后续资源: %s",
                snapshot.get("running_path") or "queued",
            )
            return
        for group_path, files in original_iter(self, root_path, scan_meta):
            if getattr(self, "_guangya_single_flight_claimed_v350", False):
                scan_meta["truncated"] = True
                scan_meta["single_flight_partial"] = True
                return
            yield group_path, files
            if getattr(self, "_guangya_single_flight_claimed_v350", False):
                # 只完成当前资源的发现；其余目录不进入 backlog，也不能用部分 inventory 清状态。
                scan_meta["truncated"] = True
                scan_meta["single_flight_partial"] = True
                return

    GuangYaFolderStreamMixin._iter_folder_groups = iter_groups

    original_fallback = GuangYaQueueRecoveryMixin._fallback_terminal_state

    def fallback(self: Any, item: Any, success: bool, message: str) -> None:
        try:
            return original_fallback(self, item, success=success, message=message)
        finally:
            _schedule_refill(self)

    GuangYaQueueRecoveryMixin._fallback_terminal_state = fallback
    GuangYaFolderStreamMixin._guangya_single_flight_v350 = True


__all__ = [
    "install_single_flight_v350",
    "_has_episode_structure",
    "_is_loose_container",
]
