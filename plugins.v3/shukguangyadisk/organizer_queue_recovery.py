"""光鸭自动整理 v3.4 独立执行器与旧全局队列恢复边界。

v3.3.0/v3.3.1 曾把自动整理文件直接提交到 MoviePilot 全局
``TransferChain`` 后台队列。MoviePilot 的本地硬盘监控、下载器整理和插件整理共享
该队列，因此大量远端任务会把原生自动整理一起堵住。

v3.4 固定边界：光鸭扫描 -> 插件私有 Queue -> 插件私有 Worker ->
TransferChain.do_transfer(background=False)。
"""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from app.application.chain.data import get_chain_transfer_pending_port
from app.chain.transfer import TransferChain
from app.runtime.config import global_vars
from app.sdk.logging import logger


class GuangYaQueueRecoveryMixin:
    """旧队列隔离 + 插件私有串行 worker。"""

    _queue_guard_marker_key = "organize_v332_queue_guard"
    _isolated_recovery_marker_key = "organize_v340_isolated_recovery"
    _isolated_queue_capacity = 256
    _monitor_inflight_lease = 7 * 24 * 3600

    _isolated_queue: Optional[queue.Queue] = None
    _isolated_worker: Optional[threading.Thread] = None
    _isolated_stop: Optional[threading.Event] = None
    _isolated_lock: Optional[threading.RLock] = None
    _isolated_pending_keys: Optional[Set[Tuple[str, str]]] = None
    _isolated_running_path: str = ""
    _isolated_last_result: str = ""
    _isolated_last_message: str = ""
    _isolated_last_finished_at: float = 0.0

    @staticmethod
    def _isolated_item_path(item: Any) -> str:
        return str(getattr(item, "path", "") or "")

    def _queue_guard_storage_names(self) -> set[str]:
        getter = getattr(self, "_storage_names", None)
        if callable(getter):
            try:
                return {str(value) for value in getter() if value}
            except Exception:
                pass
        return {
            str(getattr(self, "_disk_name", "光鸭云盘助手") or "光鸭云盘助手"),
            str(getattr(self, "_legacy_disk_name", "Shuk-光鸭云盘") or "Shuk-光鸭云盘"),
        }

    def _queue_guard_path_matches(self, src_path: Any) -> bool:
        checker = getattr(self, "_is_monitored_path", None)
        if callable(checker):
            try:
                return bool(checker(src_path))
            except Exception:
                return False
        return False

    def _quarantine_legacy_pending(self) -> Dict[str, Any]:
        """只清理旧光鸭自动监控留下的 TransferPending 登记。"""
        pending_oper = get_chain_transfer_pending_port()
        storage_names = self._queue_guard_storage_names()
        quarantined: List[str] = []
        errors: List[str] = []
        try:
            pendings = list(pending_oper.list_all() or [])
        except Exception as err:  # noqa: BLE001
            return {"quarantined": 0, "paths": [], "errors": [str(err)]}

        for row in pendings:
            try:
                storage, src_path = row
            except Exception:
                continue
            if str(storage or "") not in storage_names:
                continue
            if not self._queue_guard_path_matches(src_path):
                continue
            try:
                pending_oper.discard(storage=storage, src_path=src_path)
                global_vars.stop_transfer(str(src_path))
                quarantined.append(str(src_path))
            except Exception as err:  # noqa: BLE001
                errors.append(f"{storage}:{src_path}: {err}")

        return {"quarantined": len(quarantined), "paths": quarantined, "errors": errors[:20]}

    @staticmethod
    def _queue_obj_get(obj: Any, name: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    def _legacy_global_queue_snapshot(self) -> Dict[str, Any]:
        """只读 MoviePilot 公开队列视图，确认旧光鸭后台任务是否已经排空。"""
        storage_names = self._queue_guard_storage_names()
        waiting = running = other = 0
        sample: List[Dict[str, str]] = []
        try:
            jobs = TransferChain().get_queue_tasks() or []
        except Exception as err:  # noqa: BLE001
            return {
                "available": False, "active": 0, "waiting": 0, "running": 0,
                "other": 0, "sample": [], "error": str(err),
            }

        for job in jobs:
            for task in self._queue_obj_get(job, "tasks", []) or []:
                fileitem = self._queue_obj_get(task, "fileitem")
                if not fileitem:
                    continue
                storage = str(self._queue_obj_get(fileitem, "storage", "") or "")
                path = str(self._queue_obj_get(fileitem, "path", "") or "")
                if storage not in storage_names or not self._queue_guard_path_matches(path):
                    continue
                state = str(self._queue_obj_get(task, "state", "waiting") or "waiting")
                if state == "waiting":
                    waiting += 1
                elif state == "running":
                    running += 1
                else:
                    other += 1
                if len(sample) < 10:
                    sample.append({"path": path, "state": state})
        return {
            "available": True,
            "active": waiting + running,
            "waiting": waiting,
            "running": running,
            "other": other,
            "sample": sample,
            "error": "",
        }

    def _apply_legacy_queue_migration_once(self) -> Dict[str, Any]:
        marker = self.get_data(self._queue_guard_marker_key) or {}
        if isinstance(marker, dict) and marker.get("applied"):
            return marker
        result = self._quarantine_legacy_pending()
        marker = {
            "applied": True,
            "applied_at": time.time(),
            "was_enabled": bool(getattr(self, "_organize_monitor_enabled", False)),
            "quarantined": int(result.get("quarantined") or 0),
            "state_moved_to_retry": 0,
            "errors": list(result.get("errors") or []),
            "restart_required": bool(result.get("quarantined")),
        }
        self.save_data(self._queue_guard_marker_key, marker)
        logger.warning(
            "【光鸭云盘助手】【v3.4迁移】隔离旧 MoviePilot pending=%s；自动整理后续改由插件私有 worker 执行",
            marker["quarantined"],
        )
        return marker

    def _recover_isolated_inflight_once(self) -> int:
        marker = self.get_data(self._isolated_recovery_marker_key) or {}
        if isinstance(marker, dict) and marker.get("process_token") == id(self):
            return int(marker.get("recovered") or 0)
        state_store = self._state()
        now = time.time()

        def apply(state: Dict[str, Any]) -> int:
            inflight = dict(state.get("inflight") or {})
            retry = dict(state.get("retry") or {})
            recovered = 0
            for path, row in list(inflight.items()):
                if not isinstance(row, dict):
                    continue
                retry[path] = {
                    "fingerprint": str(row.get("fingerprint") or ""),
                    "attempts": max(int(row.get("attempts") or 1), 1),
                    "retry_at": 0,
                    "last_error": "v3.4 私有整理 worker 重启恢复，重新进入待处理",
                    "recovered_at": now,
                }
                inflight.pop(path, None)
                recovered += 1
            state["inflight"] = inflight
            state["retry"] = retry
            return recovered

        try:
            recovered = int(state_store.mutate(apply) or 0)
        except Exception as err:  # noqa: BLE001
            logger.warning("【光鸭云盘助手】【独立worker】恢复 inflight 失败: %s", err)
            recovered = 0
        self.save_data(self._isolated_recovery_marker_key, {
            "process_token": id(self), "at": now, "recovered": recovered,
        })
        return recovered

    def _isolated_runtime_lock(self) -> threading.RLock:
        if self._isolated_lock is None:
            self._isolated_lock = threading.RLock()
        return self._isolated_lock

    def _ensure_isolated_worker(self) -> None:
        lock = self._isolated_runtime_lock()
        with lock:
            if self._isolated_queue is None:
                self._isolated_queue = queue.Queue(maxsize=self._isolated_queue_capacity)
            if self._isolated_pending_keys is None:
                self._isolated_pending_keys = set()
            if self._isolated_worker and self._isolated_worker.is_alive():
                return
            self._isolated_stop = threading.Event()
            self._isolated_worker = threading.Thread(
                target=self._isolated_worker_loop,
                name="ShukGuangYa-IsolatedTransfer",
                daemon=True,
            )
            self._isolated_worker.start()
            logger.info("【光鸭云盘助手】【独立worker】已启动，模式=background=False")

    def _isolated_queue_snapshot(self) -> Dict[str, Any]:
        lock = self._isolated_runtime_lock()
        with lock:
            qsize = self._isolated_queue.qsize() if self._isolated_queue is not None else 0
            pending = len(self._isolated_pending_keys or set())
            worker_alive = bool(self._isolated_worker and self._isolated_worker.is_alive())
            return {
                "mode": "isolated_sync_worker",
                "worker_alive": worker_alive,
                "queued": qsize,
                "owned": pending,
                "running_path": self._isolated_running_path,
                "last_result": self._isolated_last_result,
                "last_message": self._isolated_last_message,
                "last_finished_at": self._isolated_last_finished_at,
                "capacity": self._isolated_queue_capacity,
            }

    def _dispatch_to_moviepilot(self, item: Any) -> bool:
        self._ensure_isolated_worker()
        path = self._isolated_item_path(item)
        if not path:
            return False
        fingerprint = self._fingerprint(item)
        key = (path, fingerprint)
        lock = self._isolated_runtime_lock()
        with lock:
            pending_keys = self._isolated_pending_keys or set()
            self._isolated_pending_keys = pending_keys
            if key in pending_keys:
                return True
            try:
                self._isolated_queue.put_nowait((item, key))
            except queue.Full:
                logger.warning("【光鸭云盘助手】【独立worker】私有队列已满，延后处理: %s", path)
                return False
            pending_keys.add(key)
        self._save_monitor_status(execution_mode="isolated_sync_worker", isolated_queue=self._isolated_queue_snapshot())
        logger.info("【光鸭云盘助手】【独立worker】已进入插件私有队列: %s", path)
        return True

    def _execute_isolated_transfer(self, item: Any) -> Tuple[bool, str]:
        event_path = Path(self._isolated_item_path(item))
        fileitem_builder = getattr(self, "_fileitem_from_cloud_item", None)
        if not callable(fileitem_builder):
            raise RuntimeError("FileItem 构造器不可用")
        fileitem = fileitem_builder(item, event_path, self._disk_name)
        contextual_builder = getattr(self, "_build_context_meta", None)
        contextual = contextual_builder(event_path) if callable(contextual_builder) else None
        kwargs: Dict[str, Any] = {"fileitem": fileitem, "background": False, "manual": False}
        if contextual:
            meta, media_type, reason = contextual
            kwargs.update({"meta": meta, "mtype": media_type})
            logger.info(
                "【光鸭云盘助手】【独立worker】【识别上下文】%s -> %s；%s",
                event_path, getattr(media_type, "value", media_type), reason,
            )
        result = TransferChain().do_transfer(**kwargs)
        if isinstance(result, tuple):
            success = bool(result[0])
            message = result[1]
        else:
            success = bool(result)
            message = ""
        if isinstance(message, dict):
            message = str(message.get("message") or message)
        return success, str(message or "")

    def _fallback_terminal_state(self, item: Any, success: bool, message: str) -> None:
        path = self._organize_normalize_path(self._isolated_item_path(item))
        fingerprint = self._fingerprint(item)
        try:
            state_store = self._state()
            raw = state_store.load()
            still_inflight = path in dict(raw.get("inflight") or {})
            if not still_inflight:
                return
            if success:
                state_store.mark_completed(path=path, fingerprint=fingerprint)
            else:
                state_store.mark_failed(path=path, fingerprint=fingerprint, now=time.time(), reason=message or "MoviePilot 整理失败")
        except Exception as err:  # noqa: BLE001
            logger.warning("【光鸭云盘助手】【独立worker】兜底回写失败: %s - %s", path, err)

    def _isolated_worker_loop(self) -> None:
        while True:
            q = self._isolated_queue
            stop = self._isolated_stop
            if q is None or stop is None:
                return
            try:
                payload = q.get(timeout=1.0)
            except queue.Empty:
                if stop.is_set():
                    return
                continue
            if payload is None:
                q.task_done()
                return
            item, key = payload
            path = self._isolated_item_path(item)
            with self._isolated_runtime_lock():
                self._isolated_running_path = path
            self._save_monitor_status(isolated_queue=self._isolated_queue_snapshot())
            try:
                success, message = self._execute_isolated_transfer(item)
                self._fallback_terminal_state(item, success=success, message=message)
                self._isolated_last_result = "completed" if success else "failed"
                self._isolated_last_message = message
            except Exception as err:  # noqa: BLE001
                self._fallback_terminal_state(item, success=False, message=str(err))
                self._isolated_last_result = "failed"
                self._isolated_last_message = str(err)
                logger.exception("【光鸭云盘助手】【独立worker】整理异常: %s - %s", path, err)
            finally:
                with self._isolated_runtime_lock():
                    self._isolated_running_path = ""
                    if self._isolated_pending_keys is not None:
                        self._isolated_pending_keys.discard(key)
                    self._isolated_last_finished_at = time.time()
                q.task_done()
                self._save_monitor_status(isolated_queue=self._isolated_queue_snapshot())

    def _legacy_queue_blocks_isolated_start(self) -> Tuple[bool, Dict[str, Any]]:
        snapshot = self._legacy_global_queue_snapshot()
        return int(snapshot.get("active") or 0) > 0, snapshot

    @staticmethod
    def _queue_guard_message(blocked: bool, legacy: Dict[str, Any]) -> str:
        if not blocked:
            return "旧光鸭全局任务已清空，自动整理使用插件私有 Worker。"
        return (
            f"MoviePilot 全局整理队列仍有旧光鸭任务 {int(legacy.get('active') or 0)} 个；"
            "插件会自动清理可安全清理的遗留任务，无需反复重启 MoviePilot。"
        )

    def _refresh_queue_guard_status(self, blocked: bool, legacy: Dict[str, Any]) -> None:
        """每次实时检查都覆盖旧状态，防止任务已删除后仍显示历史错误。"""
        self._save_monitor_status(
            queue_guard_active=blocked,
            queue_guard_restart_required=False,
            queue_guard_message=self._queue_guard_message(blocked, legacy),
            legacy_global_queue=legacy,
            execution_mode="legacy_global_queue_blocked" if blocked else "isolated_sync_worker",
            isolated_queue=self._isolated_queue_snapshot(),
        )

    def init_organizer_monitor(self, force: bool = False) -> None:
        super().init_organizer_monitor(force=force)
        self._apply_legacy_queue_migration_once()
        blocked, legacy = self._legacy_queue_blocks_isolated_start()
        if not blocked:
            self._recover_isolated_inflight_once()
            self._ensure_isolated_worker()
        self._refresh_queue_guard_status(blocked, legacy)

    def api_organize_monitor_save(self, payload: dict) -> Dict[str, Any]:
        response = super().api_organize_monitor_save(dict(payload or {}))
        if isinstance(response, dict):
            data = response.setdefault("data", {})
            blocked, legacy = self._legacy_queue_blocks_isolated_start()
            self._refresh_queue_guard_status(blocked, legacy)
            data["queue_guard"] = {
                "active": blocked,
                "legacy_global_queue": legacy,
                "mode": "legacy_global_queue_blocked" if blocked else "isolated_sync_worker",
            }
            if blocked and bool((payload or {}).get("enabled")):
                response["message"] = self._queue_guard_message(True, legacy)
        return response

    def run_organize_monitor_scan(self, manual: bool = False) -> Dict[str, Any]:
        self.init_organizer_monitor()
        blocked, legacy = self._legacy_queue_blocks_isolated_start()
        self._refresh_queue_guard_status(blocked, legacy)
        if blocked:
            return {
                "success": False,
                "message": self._queue_guard_message(True, legacy),
                "data": {"legacy_global_queue": legacy, "restart_required": False},
            }
        self._ensure_isolated_worker()
        return super().run_organize_monitor_scan(manual=manual)

    def organize_monitor_tick(self) -> None:
        self.init_organizer_monitor()
        blocked, legacy = self._legacy_queue_blocks_isolated_start()
        self._refresh_queue_guard_status(blocked, legacy)
        if blocked:
            return
        self._ensure_isolated_worker()
        return super().organize_monitor_tick()

    def api_organize_monitor_status(self) -> Dict[str, Any]:
        response = super().api_organize_monitor_status()
        if isinstance(response, dict):
            data = response.setdefault("data", {})
            status = data.setdefault("status", {})
            blocked, legacy = self._legacy_queue_blocks_isolated_start()
            self._refresh_queue_guard_status(blocked, legacy)
            status.update({
                "queue_guard_active": blocked,
                "queue_guard_restart_required": False,
                "queue_guard_message": self._queue_guard_message(blocked, legacy),
                "legacy_global_queue": legacy,
                "execution_mode": "legacy_global_queue_blocked" if blocked else "isolated_sync_worker",
                "isolated_queue": self._isolated_queue_snapshot(),
            })
        return response

    def _organizer_selfcheck(self) -> Dict[str, Any]:
        report = dict(super()._organizer_selfcheck() or {})
        checks = dict(report.get("checks") or {})
        blocked, legacy = self._legacy_queue_blocks_isolated_start()
        isolated = self._isolated_queue_snapshot()
        checks.update({
            "execution_mode": "legacy_global_queue_blocked" if blocked else "isolated_sync_worker",
            "legacy_global_queue_active": int(legacy.get("active") or 0),
            "isolated_worker_alive": bool(isolated.get("worker_alive")),
            "isolated_queue_depth": int(isolated.get("queued") or 0),
            "isolated_running_path": str(isolated.get("running_path") or ""),
            "uses_moviepilot_background_queue": False,
        })
        report["checks"] = checks
        if blocked:
            report["healthy"] = False
            report["degraded"] = True
            report["restart_required"] = False
        return report

    def _stop_isolated_worker(self, timeout: float = 5.0) -> None:
        lock = self._isolated_runtime_lock()
        with lock:
            stop = self._isolated_stop
            worker = self._isolated_worker
            q = self._isolated_queue
            if stop:
                stop.set()
            if q is not None:
                try:
                    q.put_nowait(None)
                except queue.Full:
                    pass
        if worker and worker.is_alive() and worker is not threading.current_thread():
            worker.join(timeout=max(float(timeout), 0.0))
        with lock:
            self._isolated_worker = None
            self._isolated_stop = None
            self._isolated_queue = None
            self._isolated_pending_keys = set()
            self._isolated_running_path = ""

    def stop_service(self) -> None:
        self._stop_isolated_worker()
        return super().stop_service()


__all__ = ["GuangYaQueueRecoveryMixin"]
