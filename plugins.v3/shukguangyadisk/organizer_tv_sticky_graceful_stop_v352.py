"""v3.5.2：剧集目录粘性事务 + 手动安全停止。

目标：
- 一个电视剧/Season 资源一旦开始，就保持为当前资源，直到该目录事务完成或进入明确阻断；
  期间其它剧集目录不会插队，避免“这集一会儿、另一部剧一会儿”的来回切换。
- 提供“安全停止并清理待执行”能力：按下后立即停止发现新资源、清理尚未开始的私有/旧全局
  waiting 任务，但绝不强杀当前 move/rename；电影让当前电影收尾，电视剧让当前 Season 事务
  整体收尾，然后 Worker 退出。

媒体识别、分类、重命名、目标目录、覆盖与整理历史仍完全由 MoviePilot 决定。
"""

from __future__ import annotations

import queue
import time
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

from app.schemas.types import MediaType
from app.sdk.logging import logger

from . import organizer_orchestrator_v351 as _orch
from . import organizer_single_flight_v350 as _single
from .models import GuangYaOrganizerResponse
from .organizer import GuangYaOrganizerMixin as _BaseOrganizerMixin
from .organizer_folder_history import GuangYaFolderHistoryMixin
from .organizer_folder_stream import GuangYaFolderStreamMixin
from .organizer_legacy_queue_cleanup_v343 import _cleanup_legacy_global_tasks
from .organizer_queue_recovery import GuangYaQueueRecoveryMixin
from .organizer_worker_guard import GuangYaWorkerGuardMixin


_STICKY_KEY = "sticky_tv_group_path"
_GRACEFUL_FLAG = "_guangya_graceful_stop_requested_v352"


def _normalized(plugin: Any, value: Any) -> str:
    try:
        return plugin._organize_normalize_path(value)
    except Exception:
        return str(value or "")


def _path_under(plugin: Any, path: str, parent: str) -> bool:
    try:
        child = PurePosixPath(_normalized(plugin, path))
        root = PurePosixPath(_normalized(plugin, parent))
        return child == root or child.is_relative_to(root)
    except (TypeError, ValueError):
        return False


def _is_tv_resource(plugin: Any, group_path: str, files: List[Any]) -> bool:
    """只判断任务粒度；泛化 TV 分类容器仍不能被误当成一个剧集事务。"""
    if not files:
        return False
    try:
        if _orch._is_loose_container_v351(plugin, group_path, files):
            return False
    except Exception:
        pass
    try:
        if _single._has_episode_structure(plugin, group_path, files):
            return True
    except Exception:
        pass
    try:
        return _orch._configured_type(plugin, group_path, files) == MediaType.TV
    except Exception:
        return False


def _group_has_pending(plugin: Any, group_path: str) -> bool:
    """inflight/retry/stabilizing 都表示当前 Season 尚未真正收口；blocked 允许释放粘性。"""
    if not group_path:
        return False
    try:
        state = plugin._state().load()
    except Exception:
        return False
    for state_name in ("inflight", "retry", "stabilizing"):
        for path, row in dict(state.get(state_name) or {}).items():
            row = row if isinstance(row, dict) else {}
            row_group = str(row.get("group_path") or "")
            if row_group and _normalized(plugin, row_group) == _normalized(plugin, group_path):
                return True
            if _path_under(plugin, str(path or ""), group_path):
                return True
    return False


def _set_sticky(plugin: Any, group_path: str) -> None:
    normalized = _normalized(plugin, group_path)
    status = dict(plugin.get_data(plugin._monitor_status_key) or {})
    if _normalized(plugin, status.get(_STICKY_KEY) or "") == normalized:
        return
    plugin._save_monitor_status(
        sticky_tv_group_path=normalized,
        sticky_tv_group_since=time.time(),
        sticky_tv_group_active=True,
    )
    logger.info(
        "【光鸭云盘助手】【剧集粘性】锁定当前剧集目录，未完成前不切换其它剧集: %s",
        normalized,
    )


def _clear_sticky(plugin: Any, *, reason: str) -> None:
    status = dict(plugin.get_data(plugin._monitor_status_key) or {})
    old = str(status.get(_STICKY_KEY) or "")
    if not old:
        return
    plugin._save_monitor_status(
        sticky_tv_group_path="",
        sticky_tv_group_since=0,
        sticky_tv_group_active=False,
        sticky_tv_group_release_reason=reason,
        sticky_tv_group_released_at=time.time(),
    )
    logger.info("【光鸭云盘助手】【剧集粘性】当前剧集目录已收口，允许发现下一资源: %s", old)


def _empty_wait_counters(file_count: int) -> Dict[str, int]:
    counters = _single._empty_counters(file_count)
    counters["capacity_wait"] = len(_orch._primary_media_files([])) if not file_count else file_count
    return counters


def _disable_monitor_persistently(plugin: Any) -> None:
    """安全停止首先关闭发现入口，防止当前任务结束瞬间 refill 又抢到下一任务。"""
    try:
        config = dict(plugin._load_monitor_config() or {})
    except Exception:
        config = dict(plugin.get_data(plugin._monitor_config_key) or {})
    config["enabled"] = False
    plugin.save_data(plugin._monitor_config_key, config)
    plugin._organize_monitor_enabled = False


def _payload_item_key(payload: Any) -> Tuple[Optional[Any], str]:
    if payload is None:
        return None, ""
    try:
        item, key = payload
        return item, str(key or "")
    except Exception:
        return None, ""


def _drain_private_waiting_after_boundary(plugin: Any, *, preserve_one: bool) -> Tuple[int, str]:
    """清理未开始任务；没有 running 时可保留最接近的一个队列任务自然执行后停止。"""
    lock = plugin._isolated_runtime_lock()
    discarded: List[Any] = []
    keep_payload: Any = None
    keep_path = ""

    with lock:
        stop = getattr(plugin, "_isolated_stop", None)
        q = getattr(plugin, "_isolated_queue", None)
        pending_keys = getattr(plugin, "_isolated_pending_keys", None)
        running_path = str(getattr(plugin, "_isolated_running_path", "") or "")
        if stop is not None:
            stop.set()

        if q is not None:
            while True:
                try:
                    payload = q.get_nowait()
                except queue.Empty:
                    break
                try:
                    item, key = _payload_item_key(payload)
                    if item is None:
                        continue
                    if preserve_one and not running_path and keep_payload is None:
                        keep_payload = payload
                        try:
                            keep_path = plugin._isolated_item_path(item)
                        except Exception:
                            keep_path = str(getattr(item, "path", "") or "")
                        continue
                    discarded.append(item)
                    if pending_keys is not None and key:
                        pending_keys.discard(key)
                finally:
                    q.task_done()

            if keep_payload is not None:
                # 当前没有 running 时，让已经最接近执行的一个资源先完成。
                q.put_nowait(keep_payload)
            try:
                # sentinel 位于保留任务之后：当前资源/最接近资源完成后 Worker 退出。
                q.put_nowait(None)
            except queue.Full:
                # queue_capacity=1 时，保留任务会占满队列；Worker 取走后 stop+empty 也会自然退出。
                pass

    returned = 0
    if discarded:
        try:
            returned = int(plugin._return_items_to_retry_now(
                discarded,
                reason="手动安全停止：未开始任务已退回待处理，重新启用后再发现",
            ) or 0)
        except Exception as err:  # noqa: BLE001
            logger.warning("【光鸭云盘助手】【安全停止】未开始任务退回状态机失败: %s", err)
    return returned, running_path or keep_path


def _legacy_running_path(plugin: Any, snapshot: Dict[str, Any]) -> str:
    for key in ("running_paths", "active_paths", "paths"):
        values = snapshot.get(key)
        if isinstance(values, list) and values:
            return str(values[0] or "")
    cleanup = dict((plugin.get_data(plugin._queue_guard_marker_key) or {}))
    paths = cleanup.get("retained_paths")
    if isinstance(paths, list) and paths:
        return str(paths[0] or "")
    return ""


def _safe_stop(plugin: Any) -> Dict[str, Any]:
    """停止新发现，当前资源自然结束；同时清理未开始的旧全局/私有任务。"""
    plugin.init_organizer_monitor()
    _disable_monitor_persistently(plugin)
    setattr(plugin, _GRACEFUL_FLAG, True)

    legacy_cleanup: Dict[str, Any]
    try:
        legacy_cleanup = dict(_cleanup_legacy_global_tasks(plugin) or {})
    except Exception as err:  # noqa: BLE001
        legacy_cleanup = {"removed": 0, "retained_running": 0, "errors": [str(err)]}

    try:
        legacy_after = dict(plugin._legacy_global_queue_snapshot() or {})
    except Exception:
        legacy_after = {}
    legacy_running = int(legacy_after.get("running") or 0)
    legacy_path = _legacy_running_path(plugin, legacy_after) if legacy_running else ""

    # 如果仍有旧全局 running，它就是唯一允许自然收尾的边界；私有 waiting 全部退回。
    preserve_private_one = legacy_running <= 0
    returned_private, private_path = _drain_private_waiting_after_boundary(
        plugin,
        preserve_one=preserve_private_one,
    )

    current_path = legacy_path or private_path
    try:
        isolated = dict(plugin._isolated_queue_snapshot() or {})
        current_path = current_path or str(isolated.get("running_path") or "")
        private_active = bool(
            isolated.get("running_path")
            or int(isolated.get("queued") or 0) > 0
            or int(isolated.get("owned") or 0) > 0
        )
    except Exception:
        isolated = {}
        private_active = bool(current_path)

    active = legacy_running > 0 or private_active or bool(current_path)
    state = "finishing_current" if active else "stopping"
    returned_legacy = int(legacy_cleanup.get("removed_waiting") or 0)
    plugin._save_monitor_status(
        graceful_stop_requested=True,
        graceful_stop_state=state,
        graceful_stop_current_path=current_path,
        graceful_stop_requested_at=time.time(),
        graceful_stop_returned_private=returned_private,
        graceful_stop_removed_legacy_waiting=returned_legacy,
        graceful_stop_message=(
            "已停止发现新任务；当前资源将自然整理完成后停止，未开始任务已退回待处理"
            if active else
            "已停止发现新任务，正在退出空闲 Worker"
        ),
    )

    logger.warning(
        "【光鸭云盘助手】【安全停止】已停止发现新任务；当前资源%s；"
        "私有未开始退回=%s，旧全局 waiting 清理=%s。不会强制中断 move/rename",
        f"={current_path} 自然收尾后停止" if current_path else "为空",
        returned_private,
        returned_legacy,
    )
    return {
        "state": state,
        "current_path": current_path,
        "returned_private": returned_private,
        "removed_legacy_waiting": returned_legacy,
        "legacy_running": legacy_running,
    }


def _graceful_runtime_state(plugin: Any, status: Dict[str, Any]) -> None:
    if not bool(status.get("graceful_stop_requested")) and not bool(getattr(plugin, _GRACEFUL_FLAG, False)):
        return

    try:
        isolated = dict(plugin._isolated_queue_snapshot() or {})
    except Exception:
        isolated = {}
    try:
        legacy = dict(plugin._legacy_global_queue_snapshot() or {})
    except Exception:
        legacy = {}

    current = (
        str(isolated.get("running_path") or "")
        or str(status.get("graceful_stop_current_path") or "")
    )
    active = bool(
        isolated.get("running_path")
        or int(isolated.get("queued") or 0) > 0
        or int(isolated.get("owned") or 0) > 0
        or int(legacy.get("active") or 0) > 0
    )
    if active:
        status.update({
            "runtime_phase": "draining",
            "runtime_label": "安全停止：当前资源收尾中",
            "current_task_path": current,
            "graceful_stop_state": "finishing_current",
        })
        return

    status.update({
        "runtime_phase": "stopped",
        "runtime_label": "已安全停止",
        "current_task_path": "",
        "active_resource_tasks": 0,
        "worker_queue_depth": 0,
        "graceful_stop_state": "stopped",
        "graceful_stop_current_path": "",
        "graceful_stop_finished_at": time.time(),
        "graceful_stop_message": "当前资源已收尾，未开始任务保持待处理；重新启用自动监控后继续",
    })
    plugin._save_monitor_status(**status)


def install_tv_sticky_graceful_stop_v352() -> None:
    if getattr(GuangYaFolderStreamMixin, "_guangya_tv_sticky_graceful_stop_v352", False):
        return

    # 1) 剧集事务粘性：当前 Season 未收口时，其它资源只观察、不提交。
    previous_process = GuangYaFolderStreamMixin._process_folder_group

    def process_group(self: Any, **kwargs: Any) -> Dict[str, int]:
        group_path = _normalized(self, kwargs.get("group_path") or "")
        files = list(kwargs.get("files") or [])
        status = dict(self.get_data(self._monitor_status_key) or {})
        sticky = _normalized(self, status.get(_STICKY_KEY) or "") if status.get(_STICKY_KEY) else ""

        if sticky and not _group_has_pending(self, sticky):
            _clear_sticky(self, reason="当前剧集已无 inflight/retry/stabilizing 成员")
            sticky = ""

        if sticky and group_path != sticky:
            counters = _single._empty_counters(len(files))
            counters["capacity_wait"] = len(_orch._primary_media_files(files))
            logger.debug(
                "【光鸭云盘助手】【剧集粘性】当前剧集未完成，暂不切换其它资源: current=%s skip=%s",
                sticky,
                group_path,
            )
            return counters

        result = previous_process(self, **kwargs)
        if (
            not sticky
            and _is_tv_resource(self, group_path, files)
            and int((result or {}).get("submitted") or 0) > 0
        ):
            _set_sticky(self, group_path)
        return result

    GuangYaFolderStreamMixin._process_folder_group = process_group

    previous_fallback = GuangYaQueueRecoveryMixin._fallback_terminal_state

    def fallback(self: Any, item: Any, success: bool, message: str) -> None:
        try:
            return previous_fallback(self, item, success=success, message=message)
        finally:
            status = dict(self.get_data(self._monitor_status_key) or {})
            sticky = str(status.get(_STICKY_KEY) or "")
            item_path = _normalized(self, getattr(item, "path", ""))
            if sticky and _normalized(self, sticky) == item_path and not _group_has_pending(self, sticky):
                _clear_sticky(self, reason="当前剧集事务已完成或进入明确阻断")

    GuangYaQueueRecoveryMixin._fallback_terminal_state = fallback

    # 2) 安全停止期间禁止正在进行的扫描再抢到新任务。
    previous_dispatch = GuangYaWorkerGuardMixin._dispatch_to_moviepilot

    def dispatch(self: Any, item: Any) -> bool:
        if bool(getattr(self, _GRACEFUL_FLAG, False)) and not bool(getattr(self, "_organize_monitor_enabled", False)):
            logger.debug(
                "【光鸭云盘助手】【安全停止】已请求停止，不接收新资源: %s",
                getattr(item, "path", ""),
            )
            return False
        return bool(previous_dispatch(self, item))

    GuangYaWorkerGuardMixin._dispatch_to_moviepilot = dispatch

    # 3) Worker 真正退出后写入明确 stopped 状态；不调用 stop_service，不释放账号/存储对象。
    previous_worker_loop = GuangYaWorkerGuardMixin._isolated_worker_loop

    def worker_loop(self: Any) -> None:
        try:
            return previous_worker_loop(self)
        finally:
            if bool(getattr(self, _GRACEFUL_FLAG, False)):
                self._save_monitor_status(
                    graceful_stop_state="stopped",
                    graceful_stop_current_path="",
                    graceful_stop_finished_at=time.time(),
                    graceful_stop_message="当前资源已收尾，Worker 已停止；重新启用自动监控后继续",
                )
                logger.info("【光鸭云盘助手】【安全停止】当前资源已收尾，私有 Worker 已停止")

    GuangYaWorkerGuardMixin._isolated_worker_loop = worker_loop

    # 4) 显式重新启用时解除安全停止锁。
    previous_save = _BaseOrganizerMixin.api_organize_monitor_save

    def save_config(self: Any, payload: dict) -> Dict[str, Any]:
        response = previous_save(self, payload)
        if isinstance(response, dict) and response.get("success") and bool((payload or {}).get("enabled")):
            setattr(self, _GRACEFUL_FLAG, False)
            self._save_monitor_status(
                graceful_stop_requested=False,
                graceful_stop_state="",
                graceful_stop_current_path="",
                graceful_stop_message="",
            )
            logger.info("【光鸭云盘助手】【安全停止】已重新启用自动监控，允许继续发现资源")
        return response

    _BaseOrganizerMixin.api_organize_monitor_save = save_config

    # 5) API + 状态投影。
    def api_graceful_stop(self: Any, payload: dict = None) -> Dict[str, Any]:
        data = _safe_stop(self)
        return {
            "success": True,
            "message": (
                "已停止发现新任务；当前资源会完整收尾后停止，未开始任务已安全清理"
                if data.get("state") == "finishing_current"
                else "没有正在执行的资源，已安全停止并清理未开始任务"
            ),
            "data": data,
        }

    GuangYaWorkerGuardMixin.api_organize_monitor_graceful_stop = api_graceful_stop

    previous_get_api = _BaseOrganizerMixin.get_organizer_api

    def get_api(self: Any) -> List[Dict[str, Any]]:
        apis = list(previous_get_api(self) or [])
        if not any(str(api.get("path") or "") == "/organize/monitor/graceful-stop" for api in apis):
            apis.append({
                "path": "/organize/monitor/graceful-stop",
                "endpoint": self.api_organize_monitor_graceful_stop,
                "auth": "bear",
                "methods": ["POST"],
                "summary": "安全停止自动整理并清理未开始任务",
                "response_model": GuangYaOrganizerResponse,
            })
        return apis

    _BaseOrganizerMixin.get_organizer_api = get_api

    previous_status = GuangYaFolderHistoryMixin.api_organize_monitor_status

    def api_status(self: Any) -> Dict[str, Any]:
        response = previous_status(self)
        if not isinstance(response, dict) or not response.get("success"):
            return response
        data = response.setdefault("data", {})
        status = data.setdefault("status", {})
        _graceful_runtime_state(self, status)
        return response

    GuangYaFolderHistoryMixin.api_organize_monitor_status = api_status

    GuangYaFolderStreamMixin._guangya_tv_sticky_graceful_stop_v352 = True
    logger.info("【光鸭云盘助手】【v3.5.2】剧集目录粘性事务与手动安全停止已启用")


__all__ = [
    "install_tv_sticky_graceful_stop_v352",
    "_is_tv_resource",
    "_group_has_pending",
]
