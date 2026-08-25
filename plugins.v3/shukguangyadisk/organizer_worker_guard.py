"""光鸭私有整理 worker 的热重载与生命周期保护。

MoviePilot 插件可以热重载，目录整理又可能持续较久。旧实现只等待旧 worker 自然退出，
但 stop 标记只会在队列空时生效，导致旧实例继续把整个私有队列跑完，新实例长时间无法
接管，并反复输出“旧插件实例仍在收尾”。

本层保证：热更新时只允许当前正在执行的任务自然收尾；尚未开始的私有队列任务立即退回
持久状态机等待新实例重新发现，旧队列不再继续排空。所有权保存在 MoviePilot 进程级
``global_vars`` 上，不读取、不修改 MoviePilot 的全局整理队列。
"""

from __future__ import annotations

import queue
import threading
import time
import weakref
from typing import Any, Dict, List, Tuple

from app.runtime.config import global_vars
from app.sdk.logging import logger


_OWNER_ATTR = "_shukguangya_isolated_worker_owner"
_LOCK_ATTR = "_shukguangya_isolated_worker_owner_lock"
_WARN_AT_ATTR = "_shukguangya_isolated_worker_owner_warn_at"
_WARN_INTERVAL = 30.0


def _runtime_lock() -> threading.RLock:
    lock = getattr(global_vars, _LOCK_ATTR, None)
    if lock is None:
        lock = threading.RLock()
        setattr(global_vars, _LOCK_ATTR, lock)
    return lock


def _runtime_owner() -> Any:
    ref = getattr(global_vars, _OWNER_ATTR, None)
    if isinstance(ref, weakref.ReferenceType):
        return ref()
    return None


class GuangYaWorkerGuardMixin:
    """保证同一 MoviePilot 进程最多只有一个光鸭私有整理 worker owner。"""

    _isolated_recovery_done: bool = False
    _isolated_recovered_count: int = 0
    _isolated_owner_conflict: bool = False
    _isolated_deferred_shutdown: bool = False
    _isolated_handoff_requested: bool = False

    def _log_owner_conflict(self, owner: Any) -> None:
        """冲突日志按进程节流，避免热更新期间每次扫描都刷同一条 WARNING。"""
        now = time.monotonic()
        with _runtime_lock():
            last = float(getattr(global_vars, _WARN_AT_ATTR, 0.0) or 0.0)
            if last and now - last < _WARN_INTERVAL:
                return
            setattr(global_vars, _WARN_AT_ATTR, now)
        worker = getattr(owner, "_isolated_worker", None) if owner is not None else None
        running_path = str(getattr(owner, "_isolated_running_path", "") or "") if owner is not None else ""
        logger.warning(
            "【光鸭云盘助手】【独立worker】旧插件实例正在交接，暂不启动新 worker: %s%s",
            getattr(worker, "name", "unknown"),
            f"；当前任务={running_path}" if running_path else "",
        )

    def _return_items_to_retry_now(self, items: List[Any], reason: str) -> int:
        """把尚未开始执行的旧队列成员立即退回 retry，不制造指数退避等待。"""
        rows: List[Tuple[str, str]] = []
        for item in items:
            members = list(getattr(item, "members", None) or [item])
            for member in members:
                try:
                    path = self._organize_normalize_path(getattr(member, "path", ""))
                    fingerprint = self._fingerprint(member)
                except Exception:
                    continue
                if path:
                    rows.append((path, fingerprint))
        if not rows:
            return 0

        now = time.time()

        def apply(state: Dict[str, Any]) -> int:
            recovered = 0
            inflight = dict(state.get("inflight") or {})
            retry = dict(state.get("retry") or {})
            completed = dict(state.get("completed") or {})
            for path, fingerprint in rows:
                if completed.get(path) == fingerprint:
                    inflight.pop(path, None)
                    retry.pop(path, None)
                    continue
                previous = inflight.pop(path, None) or retry.get(path) or {}
                retry[path] = {
                    "fingerprint": fingerprint,
                    "attempts": max(int(previous.get("attempts") or 1), 1),
                    "retry_at": 0,
                    "last_error": reason,
                    "recovered_at": now,
                }
                recovered += 1
            state["inflight"] = inflight
            state["retry"] = retry
            return recovered

        try:
            return int(self._state().mutate(apply) or 0)
        except Exception as err:  # noqa: BLE001
            logger.warning("【光鸭云盘助手】【独立worker】旧队列任务退回待处理失败: %s", err)
            return 0

    def _drain_owner_waiting_queue(self, owner: Any, *, reason: str) -> int:
        """停止 owner 继续取新任务，只保留已经从队列取出的当前任务自然收尾。"""
        if owner is None:
            return 0
        lock_getter = getattr(owner, "_isolated_runtime_lock", None)
        if not callable(lock_getter):
            return 0

        waiting_items: List[Any] = []
        try:
            lock = lock_getter()
            with lock:
                stop = getattr(owner, "_isolated_stop", None)
                q = getattr(owner, "_isolated_queue", None)
                pending_keys = getattr(owner, "_isolated_pending_keys", None)
                if stop is not None:
                    stop.set()
                if q is not None:
                    while True:
                        try:
                            payload = q.get_nowait()
                        except queue.Empty:
                            break
                        try:
                            if payload is None:
                                continue
                            try:
                                item, key = payload
                            except Exception:
                                continue
                            waiting_items.append(item)
                            if pending_keys is not None:
                                pending_keys.discard(key)
                        finally:
                            q.task_done()
                    # 旧 worker 的循环只会在取到 None 或 queue.Empty+stop 时退出。
                    # 清空旧等待项后放入哨兵，确保当前任务结束即退出，不再继续排队任务。
                    try:
                        q.put_nowait(None)
                    except queue.Full:
                        pass
                try:
                    setattr(owner, "_isolated_handoff_requested", True)
                    setattr(owner, "_isolated_deferred_shutdown", True)
                except Exception:
                    pass
        except Exception as err:  # noqa: BLE001
            logger.warning("【光鸭云盘助手】【独立worker】请求旧实例交接失败: %s", err)
            return 0

        recovered = self._return_items_to_retry_now(waiting_items, reason=reason)
        if waiting_items:
            logger.info(
                "【光鸭云盘助手】【独立worker】热更新交接：旧队列未开始任务 %s 个已退回待处理，"
                "仅保留当前任务收尾",
                len(waiting_items),
            )
        return recovered

    def _request_old_owner_handoff(self, owner: Any) -> None:
        """新实例可主动终止旧版本继续排空队列，兼容从 v3.4.4 热更新到本版本。"""
        if owner is None or owner is self:
            return
        if bool(getattr(owner, "_isolated_handoff_requested", False)):
            return
        self._drain_owner_waiting_queue(
            owner,
            reason="插件热更新交接：旧 worker 未开始任务已退回待处理",
        )

    def _claim_isolated_runtime(self) -> bool:
        with _runtime_lock():
            owner = _runtime_owner()
            if owner is self:
                self._isolated_owner_conflict = False
                return True
            if owner is not None:
                worker = getattr(owner, "_isolated_worker", None)
                if worker is not None and worker.is_alive():
                    # 主动让旧 owner 停止继续取队列任务。当前正在执行的同步 TransferChain
                    # 不做强杀，避免源/目标文件处于半移动状态。
                    self._request_old_owner_handoff(owner)
                    try:
                        worker.join(timeout=0.2)
                    except RuntimeError:
                        pass
                    if worker.is_alive():
                        self._isolated_owner_conflict = True
                        self._log_owner_conflict(owner)
                        return False
            setattr(global_vars, _OWNER_ATTR, weakref.ref(self))
            self._isolated_owner_conflict = False
            return True

    def _release_isolated_runtime(self) -> None:
        with _runtime_lock():
            if _runtime_owner() is self:
                setattr(global_vars, _OWNER_ATTR, None)
        self._isolated_owner_conflict = False

    def _recover_isolated_inflight_once(self) -> int:
        """每个真实插件实例只执行一次 inflight -> retry 恢复。"""
        if self._isolated_recovery_done:
            return int(self._isolated_recovered_count or 0)
        self._isolated_recovery_done = True

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
                    "last_error": "私有整理 worker 实例恢复，重新进入待处理",
                    "recovered_at": now,
                }
                inflight.pop(path, None)
                recovered += 1
            state["inflight"] = inflight
            state["retry"] = retry
            return recovered

        try:
            self._isolated_recovered_count = int(state_store.mutate(apply) or 0)
        except Exception as err:  # noqa: BLE001
            self._isolated_recovered_count = 0
            logger.warning("【光鸭云盘助手】【独立worker】恢复 inflight 失败: %s", err)
        return self._isolated_recovered_count

    def _ensure_isolated_worker(self) -> None:
        """只有取得进程级 owner 的插件实例才允许启动私有 worker。"""
        if not self._claim_isolated_runtime():
            return
        try:
            return super()._ensure_isolated_worker()
        except Exception:
            self._release_isolated_runtime()
            raise

    def _dispatch_to_moviepilot(self, item: Any) -> bool:
        """热重载冲突时返回暂未接收，由状态机等待 owner 完成交接。"""
        if not self._claim_isolated_runtime():
            return False
        return super()._dispatch_to_moviepilot(item)

    def _finish_deferred_shutdown_from_worker(self) -> None:
        """长同步任务自然结束后再释放账号/存储对象，避免整理中途被置空。"""
        if not self._isolated_deferred_shutdown:
            return
        self._isolated_deferred_shutdown = False
        try:
            super(GuangYaWorkerGuardMixin, self).stop_service()
        except Exception as err:  # noqa: BLE001
            logger.warning("【光鸭云盘助手】【独立worker】延迟释放插件运行态失败: %s", err)

    def _isolated_worker_loop(self) -> None:
        """无论正常退出还是异常退出，都完成延迟 teardown 并释放进程级 owner。"""
        try:
            return super()._isolated_worker_loop()
        finally:
            self._finish_deferred_shutdown_from_worker()
            lock = self._isolated_runtime_lock()
            with lock:
                worker = self._isolated_worker
                if worker is threading.current_thread():
                    self._isolated_worker = None
                    self._isolated_stop = None
                    self._isolated_queue = None
                    self._isolated_pending_keys = set()
                    self._isolated_running_path = ""
            self._release_isolated_runtime()

    def _stop_isolated_worker(self, timeout: float = 5.0) -> bool:
        """停止时只等待当前任务收尾；未开始任务立即退回，禁止旧实例继续排空队列。"""
        # 先清空尚未开始的任务，再给旧循环放退出哨兵。当前正在执行的任务已经从 queue
        # 取走，因此不会被 drain，也不会被强行中断。
        returned = self._drain_owner_waiting_queue(
            self,
            reason="插件停止/热更新：未开始的私有队列任务已退回待处理",
        )
        if returned:
            self._save_monitor_status(worker_handoff_returned=returned)

        lock = self._isolated_runtime_lock()
        with lock:
            worker = self._isolated_worker

        if worker and worker.is_alive() and worker is not threading.current_thread():
            worker.join(timeout=max(float(timeout), 0.0))

        with lock:
            still_alive = bool(worker and worker.is_alive())
            if still_alive:
                logger.warning(
                    "【光鸭云盘助手】【独立worker】当前整理任务仍在收尾；未开始任务已全部退回，"
                    "完成后自动交接给新实例"
                )
                return False
            self._isolated_worker = None
            self._isolated_stop = None
            self._isolated_queue = None
            self._isolated_pending_keys = set()
            self._isolated_running_path = ""

        self._release_isolated_runtime()
        return True

    def stop_service(self) -> None:
        """同步任务超过停止预算时延迟 teardown，避免把正在使用的存储对象提前释放。"""
        if self._stop_isolated_worker():
            return super().stop_service()
        self._isolated_deferred_shutdown = True
        return None

    def _isolated_queue_snapshot(self) -> Dict[str, Any]:
        snapshot = dict(super()._isolated_queue_snapshot())
        owner = _runtime_owner()
        snapshot.update({
            "owner_current": owner is self,
            "owner_conflict": bool(self._isolated_owner_conflict),
            "owner_worker_alive": bool(
                owner is not None
                and getattr(owner, "_isolated_worker", None)
                and owner._isolated_worker.is_alive()
            ),
            "deferred_shutdown": bool(self._isolated_deferred_shutdown),
        })
        return snapshot


__all__ = ["GuangYaWorkerGuardMixin"]
