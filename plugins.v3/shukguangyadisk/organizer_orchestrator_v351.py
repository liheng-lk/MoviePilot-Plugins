"""v3.5.1：整理任务边界、运行态与 MoviePilot 历史可观测性统一修复。

本层不接管 MoviePilot 的媒体识别/分类/命名规则，只修正调度/观测问题：
1. 分类/电影容器目录必须按单视频资源串行，不能把 /电影、/华语电影、/纪录片 等容器整目录交给 MP；
2. 作品目录/Season 目录继续保持文件夹事务，错误文件名不能反过来否定正确文件夹身份；
3. 没有 MoviePilot ``RMT_MEDIAEXT`` 主视频的目录不会因为 mp3/字幕等旁路文件单独触发影视整理；
4. UI 运行状态展示真实 worker 任务，而不是把状态机缓存数量误当作“正在整理/累计完成”；
5. 最终事件记录 MoviePilot ``transfer_history_id``，明确区分“还在预检”与“已经真实落库”。
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional

from app.schemas.types import MediaType
from app.sdk.logging import logger

from . import organizer_single_flight_v350 as _single
from .organizer_folder_history import GuangYaFolderHistoryMixin
from .organizer_folder_stream import GuangYaFolderStreamMixin
from .organizer_recognition import GuangYaOrganizerMixin as GuangYaRecognitionMixin
from .organizer_worker_guard import _runtime_owner


_GENERIC_MOVIE_CONTAINERS = {
    "movie", "movies", "film", "films", "电影", "電影", "影片",
    "华语电影", "華語電影", "国产电影", "國產電影", "外语电影", "外語電影",
    "欧美电影", "歐美電影", "日韩电影", "日韓電影", "动画电影", "動畫電影",
}

# 这些只表示“结构容器名”，不代表插件自己决定媒体分类。它们的用途仅是避免把
# 分类目录名当作品标题交给 MoviePilot；最终分类仍完全由 MP 当前目录/category 规则决定。
_GENERIC_LIBRARY_CONTAINERS = {
    "纪录片", "紀錄片", "记录片", "記錄片", "documentary", "documentaries",
    "综艺", "綜藝", "variety", "variety show", "variety shows",
    "儿童", "兒童", "少儿", "少兒", "kids", "children",
    "国漫", "國漫", "日番", "韩剧", "韓劇", "港剧", "港劇", "台剧", "台劇",
    "合集", "collection", "collections", "经典电影", "經典電影", "老电影", "老電影",
}


def _norm(value: str) -> str:
    return " ".join(str(value or "").replace("_", " ").replace("-", " ").split()).casefold()


def _probe_path(group_path: str, files: List[Any]) -> Path:
    for item in files:
        path = str(getattr(item, "path", "") or "")
        if path:
            return Path(path)
    return Path(group_path) / "__probe__.mkv"


def _configured_type(plugin: Any, group_path: str, files: List[Any]) -> Optional[MediaType]:
    probe = _probe_path(group_path, files)
    getter = getattr(plugin, "_configured_media_type", None)
    if callable(getter):
        try:
            value = getter(probe)
            if value in {MediaType.TV, MediaType.MOVIE}:
                return value
        except Exception:
            pass
    getter = getattr(plugin, "_root_media_type", None)
    if callable(getter):
        try:
            value = getter(probe)
            if value in {MediaType.TV, MediaType.MOVIE}:
                return value
        except Exception:
            pass
    return None


def _generic_container_names(plugin: Any) -> set[str]:
    names = {_norm(value) for value in _GENERIC_MOVIE_CONTAINERS}
    names.update({_norm(value) for value in _GENERIC_LIBRARY_CONTAINERS})
    names.update({_norm(value) for value in _single._GENERIC_CONTAINER_NAMES})
    names.update({_norm(value) for value in getattr(plugin, "_generic_title_dirs", set())})
    return names


def _is_specific_media_folder(plugin: Any, group_path: str) -> bool:
    """作品目录名称可靠时保留文件夹事务，文件名只负责集号/技术信息。"""
    name = str(PurePosixPath(group_path).name or "").strip()
    if not name:
        return False
    normalized = _norm(name)
    if normalized in _generic_container_names(plugin):
        return False
    useful = getattr(plugin, "_is_useful_title", None)
    if callable(useful):
        try:
            return bool(useful(name))
        except Exception:
            pass
    return any("\u3400" <= ch <= "\u9fff" or ch.isalpha() for ch in name)


def _primary_media_files(files: List[Any]) -> List[Any]:
    """只把 MoviePilot RMT_MEDIAEXT 视频视为影视整理的主资源。"""
    return list(_single._media_files(files))


def _is_loose_container_v351(plugin: Any, group_path: str, files: List[Any]) -> bool:
    """只决定任务粒度，不自行判断影片身份。

    规则：
    - 没有主视频：不在这里决定，外层直接阻止形成影视任务；
    - 监控根/泛化分类容器：哪怕当前只剩 1 个视频，也必须单视频串行，绝不把容器目录递归交给 MP；
    - Season/具体剧集目录：整目录事务；
    - 明确 TV 的具体作品目录：整目录事务；
    - 具体作品目录：即使文件名很乱也保留目录事务。
    """
    media = _primary_media_files(files)
    if not media:
        return False

    normalized_group = plugin._organize_normalize_path(group_path)
    normalized_root = plugin._organize_normalize_path(plugin._organize_monitor_path)
    if normalized_group == normalized_root:
        return True

    # 泛化目录判断必须早于 len(media) 和 configured_type。
    # 否则一个 /电影 目录当前只剩 1 个视频时会再次被当作完整目录任务递归提交。
    name = _norm(PurePosixPath(group_path).name)
    if name in _generic_container_names(plugin):
        return True

    if _single._has_episode_structure(plugin, group_path, files):
        return False

    configured = _configured_type(plugin, group_path, files)
    if configured == MediaType.TV:
        return False

    # 具体作品文件夹优先保护：目录名正确但文件名错误时，仍把文件夹作为作品身份来源。
    if _is_specific_media_folder(plugin, group_path):
        return False

    # 明确 Movie 但目录本身不是可用作品名时，视为电影合集/散放容器。
    return configured == MediaType.MOVIE or len(media) > 1


def _sidecar_only_counters(file_count: int) -> Dict[str, int]:
    counters = _single._empty_counters(file_count)
    counters["ignored"] = file_count
    return counters


def _current_task_members(plugin: Any, current_path: str) -> int:
    if not current_path:
        return 0
    try:
        state = plugin._state().load()
    except Exception:
        return 0
    count = 0
    for path, row in dict(state.get("inflight") or {}).items():
        if not isinstance(row, dict):
            continue
        group_path = str(row.get("group_path") or "")
        if path == current_path or group_path == current_path:
            count += 1
    return count or 1


def _project_runtime_status(plugin: Any, status: Dict[str, Any]) -> Dict[str, Any]:
    isolated_getter = getattr(plugin, "_isolated_queue_snapshot", None)
    isolated = dict(isolated_getter() or {}) if callable(isolated_getter) else {}
    owner = _runtime_owner()
    owner_is_self = owner is plugin
    owner_path = ""
    if owner is not None:
        owner_path = str(getattr(owner, "_isolated_running_path", "") or "")

    own_running = str(isolated.get("running_path") or "")
    queued = int(isolated.get("queued") or 0)
    owner_conflict = bool(isolated.get("owner_conflict")) or (
        owner is not None and not owner_is_self and bool(getattr(owner, "_isolated_worker", None))
    )

    if owner_conflict and owner_path:
        phase = "handoff"
        label = "旧版本任务交接中"
        current_path = owner_path
    elif own_running:
        phase = "transferring"
        label = "正在整理"
        current_path = own_running
    elif queued > 0:
        phase = "queued"
        label = "等待独立 Worker"
        current_path = ""
    elif bool(status.get("scan_in_progress")):
        phase = "scanning"
        label = "正在发现资源"
        current_path = str(status.get("current_group") or "")
    elif not bool(getattr(plugin, "_organize_monitor_enabled", False)):
        phase = "disabled"
        label = "自动监控未启用"
        current_path = ""
    else:
        phase = "idle"
        label = "空闲，等待下一资源"
        current_path = ""

    status.update({
        "runtime_phase": phase,
        "runtime_label": label,
        "current_task_path": current_path,
        "current_task_members": _current_task_members(plugin, current_path),
        "active_resource_tasks": 1 if phase in {"handoff", "transferring", "queued"} else 0,
        "worker_queue_depth": queued,
        "completed_total": int(status.get("mp_completed_total") or 0),
        "failed_total": int(status.get("mp_failed_total") or 0),
        "scan_files_seen": int(status.get("inventory") or 0),
        "scan_is_partial": bool(status.get("truncated") or status.get("single_flight_partial") or status.get("single_flight_busy")),
        "state_inflight_files": int(status.get("state_inflight") or status.get("inflight") or 0),
        "state_completed_cache": int(status.get("state_completed") or status.get("completed") or 0),
        "mp_history_confirmed_total": int(status.get("mp_history_confirmed_total") or 0),
    })
    return status


def _bind_moviepilot_history_to_terminal_event() -> None:
    original_record = GuangYaRecognitionMixin._record_terminal_transfer

    def record(self: Any, event: Any, success: bool) -> None:
        payload_getter = getattr(self, "_event_payload", None)
        payload = payload_getter(event) if callable(payload_getter) else {}
        history_id = payload.get("transfer_history_id") if isinstance(payload, dict) else None
        fileitem = payload.get("fileitem") if isinstance(payload, dict) else None
        source_path = str(getattr(fileitem, "path", "") or "") if fileitem else ""

        original_record(self, event, success)

        status = dict(self.get_data(self._monitor_status_key) or {})
        if history_id:
            history_value = int(history_id)
            status["last_transfer_history_id"] = history_value
            if success and int(status.get("last_counted_transfer_history_id") or 0) != history_value:
                status["mp_history_confirmed_total"] = int(status.get("mp_history_confirmed_total") or 0) + 1
                status["last_counted_transfer_history_id"] = history_value
        status["last_transfer_history_confirmed"] = bool(history_id)
        self._save_monitor_status(**status)

        # 把真实 MP history id 补到刚刚写入的 flat history，供 UI 直接显示。
        if history_id and source_path:
            try:
                rows = list(self.get_data(self._monitor_history_key) or [])
                normalized_source = self._organize_normalize_path(source_path)
                for row in reversed(rows):
                    if not isinstance(row, dict):
                        continue
                    if self._organize_normalize_path(str(row.get("path") or "")) != normalized_source:
                        continue
                    if str(row.get("result") or "") not in {"completed", "failed"}:
                        continue
                    row["transfer_history_id"] = int(history_id)
                    break
                self.save_data(self._monitor_history_key, rows[-self._monitor_history_limit :])
            except Exception:
                pass

        if success and history_id:
            logger.info(
                "【光鸭云盘助手】【MP整理历史】真实整理已落库: history_id=%s；source=%s",
                history_id,
                source_path,
            )
        elif success:
            logger.warning(
                "【光鸭云盘助手】【MP整理历史】收到成功终态但事件未携带 history_id；"
                "请以 MoviePilot 媒体整理记录为准: %s",
                source_path,
            )

    GuangYaRecognitionMixin._record_terminal_transfer = record


def install_orchestrator_v351() -> None:
    if getattr(_single, "_guangya_orchestrator_v351", False):
        return

    # v3.5.0 的 process 闭包运行时从模块全局查找该函数，因此替换后旧闭包也会使用新判断。
    _single._is_loose_container = _is_loose_container_v351

    # 影视整理只能由 RMT_MEDIAEXT 主视频触发。字幕/音频仍可以在 MoviePilot 真正处理
    # 一个视频目录时作为伴随文件参与，但不能单独把“纪录片/电影”等容器目录送去识别。
    original_process = GuangYaFolderStreamMixin._process_folder_group

    def process_group(self: Any, **kwargs: Any) -> Dict[str, int]:
        files = list(kwargs.get("files") or [])
        group_path = str(kwargs.get("group_path") or "")
        if files and not _primary_media_files(files):
            logger.info(
                "【光鸭云盘助手】【主视频门禁】跳过无视频目录，不触发 MoviePilot 影视识别: %s；"
                "当前仅有字幕/音频等旁路文件=%s",
                group_path,
                len(files),
            )
            return _sidecar_only_counters(len(files))
        return original_process(self, **kwargs)

    GuangYaFolderStreamMixin._process_folder_group = process_group

    original_status = GuangYaFolderHistoryMixin.api_organize_monitor_status

    def api_status(self: Any) -> Dict[str, Any]:
        response = original_status(self)
        if not isinstance(response, dict) or not response.get("success"):
            return response
        data = response.setdefault("data", {})
        status = data.setdefault("status", {})
        _project_runtime_status(self, status)
        return response

    GuangYaFolderHistoryMixin.api_organize_monitor_status = api_status
    _bind_moviepilot_history_to_terminal_event()
    _single._guangya_orchestrator_v351 = True
    logger.info("【光鸭云盘助手】【v3.5.1】任务边界、主视频门禁、运行态和 MP 历史确认已启用")


__all__ = [
    "install_orchestrator_v351",
    "_is_loose_container_v351",
    "_primary_media_files",
    "_project_runtime_status",
]
