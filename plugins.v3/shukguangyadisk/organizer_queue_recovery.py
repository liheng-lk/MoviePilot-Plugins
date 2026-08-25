"""光鸭自动整理 v3.4 独立执行器与旧全局队列恢复边界。

v3.3.0/v3.3.1 曾把自动整理文件直接提交到 MoviePilot 全局
``TransferChain`` 后台队列。MoviePilot 的本地硬盘监控、下载器整理和插件整理共享
该队列，因此大量远端任务会把原生自动整理一起堵住。

v3.4 的固定边界：

``光鸭扫描 -> 插件私有 Queue -> 插件私有 Worker ->
TransferChain.do_transfer(background=False)``

MoviePilot 仍负责识别、目录选择、重命名、整理方式、覆盖、刮削与整理历史；插件只把
“在哪里排队、由谁驱动”隔离出去。此模块绝不写 MoviePilot 私有 ``_queue`` / ``_threads``
/ ``_worker_stop_event``，也不停止或重启 MoviePilot 整理 worker。
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
    """旧队列隔离 + 插件私有串行 worker。

    类名保留是为了兼容 v3.3.2 的 MRO/升级路径；v3.4 起它已经不是“停用自动整理”
    的临时保护器，而是自动整理真正的执行隔离层。
    """

    _queue_guard_marker_key = "organize_v332_queue_guard"
    _isolated_recovery_marker_key = "organize_v340_isolated_recovery"
    _isolated_queue_capacity = 256
    # 私有队列中的任务不再依赖 30 分钟租约自动重放。进程/插件重启时会把 inflight
    # 明确迁回 retry；正常运行期间保持长租约，避免长批次被重复入队。
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
        """只清理旧光鸭自动监控留下的 TransferPending 登记。

        这是从 3.3.0/3.3.1 迁移到独立 worker 的一次性动作；local 和其它存储永远不碰。
        """
        pending_oper = get_chain_transfer_pending_port()
        storage_names = self._queue_guard_storage_names()
        quarantined: List[str] = []
        errors: List[str] = []
        try:
            pendings = list(pending_oper.list_all() or [])
        except Exception as err:  # noqa: BLE001 - MoviePilot compatibility boundary
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
                # 当前进程中旧版任务可能已进入 MP 队列。只设置 MoviePilot 公开的协作取消
                # 标记；是否还有旧任务由 get_queue_tasks() 公开视图判断，绝不直接改队列。
                global_vars.stop_transfer(str(src_path))
                quarantined.append(str(src_path))
            except Exception as err:  # noqa: BLE001
                errors.append(f"{storage}:{src_path}: {err}")

        return {
            "quarantined": len(quarantined),
            "paths": quarantined,
            "errors": errors[:20],
        }

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
                "available": False,
                "active": 0,
                "waiting": 0,
                "running": 0,
                "other": 0,
                "sample": [],
                "error": str(err),
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
        """迁移旧版本后台队列登记，但不再关闭用户的自动监控开关。"""
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
            # 只有旧任务确实存在时才要求先把旧进程中的全局队列排空/重启。
            "restart_required": bool(result.get("quarantined")),
        }
        self.save_data(self._queue_guard_marker_key, marker)
        logger.warning(
            "【光鸭云盘助手】【v3.4迁移】隔离旧 MoviePilot pending=%s；"
            "自动整理后续改由插件私有 worker 执行",
            marker["quarantined"],
        )
        return marker

    def _recover_isolated_inflight_once(self) -> int:
        """插件/进程重启时把私有 worker 未终态任务安全迁回 retry。

        v3.4 使用 ``background=False``，因此这些任务不可能还躺在 MoviePilot 后台队列；
        只要公开队列确认没有旧光鸭 active，就可以安全重试。
        """
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
            "process_token": id(self),
            "at": now,
            "recovered": recovered,
        })
        return recovered

    def _isolated_runtime_lock(self) -> threading.RLock:
        if self._isolated_lock is None:
            self._isolated_lock = threading.RLock()
        return self._isolated_lock

    def _ensure_isolated_worker(self) -> None:
        """启动插件私有串行 worker；它与 MoviePilot TransferChain worker 无关。"""
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
        """自动整理提交边界：只进入插件私有队列，不进入 MP 全局 background queue。"""
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
        self._save_monitor_status(
            execution_mode="isolated_sync_worker",
            isolated_queue=self._isolated_queue_snapshot(),
        )
        logger.info("【光鸭云盘助手】【独立worker】已进入插件私有队列: %s", path)
        return True

    def _execute_isolated_transfer(self, item: Any) -> Tuple[bool, str]:
        """在插件线程同步调用 MoviePilot 原生整理业务链。"""
        event_path = Path(self._isolated_item_path(item))
        fileitem_builder = getattr(self, "_fileitem_from_cloud_item", None)
        if not callable(fileitem_builder):
            raise RuntimeError("FileItem 构造器不可用")
        fileitem = fileitem_builder(item, event_path, self._disk_name)

        contextual_builder = getattr(self, "_build_context_meta", None)
        contextual = contextual_builder(event_path) if callable(contextual_builder) else None
        kwargs: Dict[str, Any] = {
            "fileitem": fileitem,
            "background": False,
            "manual": False,
        }
        if contextual:
            meta, media_type, reason = contextual
            kwargs.update({"meta": meta, "mtype": media_type})
            logger.info(
                "【光鸭云盘助手】【独立worker】【识别上下文】%s -> %s；%s",
                event_path,
                getattr(media_type, "value", media_type),
                reason,
            )

        # 关键安全边界：background=False。MoviePilot 仍执行完整业务链，但不会把任务
        # 塞入 TransferChain 全局后台队列，也不会写该队列的 pending 回放登记。
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
        """正常情况下 MP 最终事件已同步回写；事件缺失时才做兜底收敛。"""
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
                state_store.mark_failed(
                    path=path,
                    fingerprint=fingerprint,
                    now=time.time(),
                    reason=message or "MoviePilot 同步整理失败",
                )
            self._append_monitor_history(self._history_row(
                now_text=time.strftime("%Y-%m-%d %H:%M:%S"),
                item=item,
                path=path,
                result="completed" if success else "failed",
                message=(
                    "独立 worker 同步整理完成（最终事件缺失，已由返回值兜底）"
                    if success else
                    f"独立 worker 同步整理失败（最终事件缺失）：{message}"
                ),
            ))
        except Exception as err:  # noqa: BLE001
            logger.warning("【光鸭云盘助手】【独立worker】终态兜底失败: %s - %s", path, err)

    def _isolated_worker_loop(self) -> None:
        q = self._isolated_queue
        stop = self._isolated_stop
        if q is None or stop is None:
            return
        while not stop.is_set() and not global_vars.is_system_stopped:
            try:
                payload = q.get(timeout=1.0)
            except queue.Empty:
                continue
            if payload is None:
                q.task_done()
                break
            item, key = payload
            path = self._isolated_item_path(item)
            self._isolated_running_path = path
            self._save_monitor_status(
                execution_mode="isolated_sync_worker",
                isolated_queue=self._isolated_queue_snapshot(),
            )
            try:
                success, message = self._execute_isolated_transfer(item)
                self._isolated_last_result = "completed" if success else "failed"
                self._isolated_last_message = message
                self._fallback_terminal_state(item, success=success, message=message)
                log = logger.info if success else logger.warning
                log(
                    "【光鸭云盘助手】【独立worker】%s: %s%s",
                    "整理完成" if success else "整理失败",
                    path,
                    f" - {message}" if message else "",
                )
            except Exception as err:  # noqa: BLE001 - persistent state fallback below
                self._isolated_last_result = "failed"
                self._isolated_last_message = str(err)
                self._fallback_terminal_state(item, success=False, message=str(err))
                logger.exception("【光鸭云盘助手】【独立worker】执行异常: %s - %s", path, err)
            finally:
                self._isolated_last_finished_at = time.time()
                self._isolated_running_path = ""
                lock = self._isolated_runtime_lock()
                with lock:
                    if self._isolated_pending_keys is not None:
                        self._isolated_pending_keys.discard(key)
                q.task_done()
                self._save_monitor_status(
                    execution_mode="isolated_sync_worker",
                    isolated_queue=self._isolated_queue_snapshot(),
                )

    def _legacy_queue_blocks_isolated_start(self) -> Tuple[bool, Dict[str, Any]]:
        snapshot = self._legacy_global_queue_snapshot()
        return int(snapshot.get("active") or 0) > 0, snapshot

    def init_organizer_monitor(self, force: bool = False) -> None:
        super().init_organizer_monitor(force=force)
        self._apply_legacy_queue_migration_once()
        blocked, legacy = self._legacy_queue_blocks_isolated_start()
        if not blocked:
            self._recover_isolated_inflight_once()
            self._ensure_isolated_worker()
        self._save_monitor_status(
            queue_guard_active=blocked,
            queue_guard_restart_required=blocked,
            queue_guard_quarantined=int((self.get_data(self._queue_guard_marker_key) or {}).get("quarantined") or 0),
            queue_guard_message=(
                "检测到旧版光鸭任务仍在 MoviePilot 全局后台队列；请先重启 MoviePilot 一次，"
                "队列清空后 v3.4 会自动切换到插件私有 worker。"
                if blocked else
                "v3.4 已使用插件私有 worker，光鸭自动整理不再进入 MoviePilot 全局后台队列。"
            ),
            legacy_global_queue=legacy,
            execution_mode="legacy_global_queue_blocked" if blocked else "isolated_sync_worker",
            isolated_queue=self._isolated_queue_snapshot(),
        )

    def api_organize_monitor_save(self, payload: dict) -> Dict[str, Any]:
        """v3.4 恢复正常保存；不再强制把 enabled 改成 False。"""
        response = super().api_organize_monitor_save(dict(payload or {}))
        if isinstance(response, dict):
            data = response.setdefault("data", {})
            blocked, legacy = self._legacy_queue_blocks_isolated_start()
            data["queue_guard"] = {
                "active": blocked,
                "legacy_global_queue": legacy,
                "mode": "legacy_global_queue_blocked" if blocked else "isolated_sync_worker",
            }
            if blocked and bool((payload or {}).get("enabled")):
                response["message"] = (
                    "设置已保存，但旧版光鸭任务仍在 MoviePilot 全局后台队列。"
                    "请重启 MoviePilot 一次后，自动整理会由 v3.4 私有 worker 接管。"
                )
        return response

    def run_organize_monitor_scan(self, manual: bool = False) -> Dict[str, Any]:
        self.init_organizer_monitor()
        blocked, legacy = self._legacy_queue_blocks_isolated_start()
        if blocked:
            return {
                "success": False,
                "message": (
                    f"MoviePilot 全局整理队列仍有旧光鸭任务 {legacy.get('active', 0)} 个；"
                    "为保护原生硬盘自动整理，v3.4 拒绝新增任务。请先重启 MoviePilot 一次。"
                ),
                "data": {"legacy_global_queue": legacy, "restart_required": True},
            }
        self._ensure_isolated_worker()
        return super().run_organize_monitor_scan(manual=manual)

    def organize_monitor_tick(self) -> None:
        self.init_organizer_monitor()
        blocked, legacy = self._legacy_queue_blocks_isolated_start()
        if blocked:
            self._save_monitor_status(
                queue_guard_active=True,
                queue_guard_restart_required=True,
                legacy_global_queue=legacy,
                execution_mode="legacy_global_queue_blocked",
            )
            return
        self._ensure_isolated_worker()
        return super().organize_monitor_tick()

    def api_organize_monitor_status(self) -> Dict[str, Any]:
        response = super().api_organize_monitor_status()
        if isinstance(response, dict):
            data = response.setdefault("data", {})
            status = data.setdefault("status", {})
            blocked, legacy = self._legacy_queue_blocks_isolated_start()
            status.update({
                "queue_guard_active": blocked,
                "queue_guard_restart_required": blocked,
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
            report["restart_required"] = True
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
        """只停止插件自己的 worker；MoviePilot TransferChain worker 完全不碰。"""
        self._stop_isolated_worker()
        return super().stop_service()


__all__ = ["GuangYaQueueRecoveryMixin"]
