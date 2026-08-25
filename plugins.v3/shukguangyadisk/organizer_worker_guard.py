"""光鸭 v3.4 私有整理 worker 的热重载与生命周期保护。

MoviePilot 插件可以热重载。远端同步整理可能持续较久，因此旧插件实例的私有 worker
在 stop_service() 的短等待窗口结束后仍可能继续收尾。若新实例立即再启动一个 worker，
同一源文件就可能并行整理两次。

本层只管理“哪个光鸭插件实例拥有私有 worker”。所有权保存在 MoviePilot 进程级
``global_vars`` 上，因此即使插件模块被重新加载也不会丢失。它不读取、不修改
MoviePilot 的整理队列和 worker。
"""

from __future__ import annotations

import queue
import threading
import time
import weakref
from typing import Any, Dict

from app.runtime.config import global_vars
from app.sdk.logging import logger


_OWNER_ATTR = "_shukguangya_isolated_worker_owner"
_LOCK_ATTR = "_shukguangya_isolated_worker_owner_lock"


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

    def _claim_isolated_runtime(self) -> bool:
        with _runtime_lock():
            owner = _runtime_owner()
            if owner is self:
                self._isolated_owner_conflict = False
                return True
            if owner is not None:
                worker = getattr(owner, "_isolated_worker", None)
                if worker is not None and worker.is_alive():
                    self._isolated_owner_conflict = True
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
        """每个真实插件实例只执行一次 inflight -> retry 恢复。

        不把 Python ``id(self)`` 持久化到数据库：对象 id 只在当前解释器生命周期内有意义，
        热重载/重启后不能作为稳定进程标识。
        """
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
                    "last_error": "v3.4 私有整理 worker 实例恢复，重新进入待处理",
                    "recovered_at": now,
                }
                inflight.pop(path, None)
                recovered += 1
            state["inflight"] = inflight
            state["retry"] = retry
            return recovered

        try:
            self._isolated_recovered_count = int(state_store.mutate(apply) or 0)
        except Exception as err:  # noqa: BLE001 - persistent compatibility boundary
            self._isolated_recovered_count = 0
            logger.warning("【光鸭云盘助手】【独立worker】恢复 inflight 失败: %s", err)
        return self._isolated_recovered_count

    def _ensure_isolated_worker(self) -> None:
        """只有取得进程级 owner 的插件实例才允许启动私有 worker。"""
        if not self._claim_isolated_runtime():
            owner = _runtime_owner()
            worker = getattr(owner, "_isolated_worker", None) if owner is not None else None
            logger.warning(
                "【光鸭云盘助手】【独立worker】旧插件实例仍在收尾，暂不启动新 worker: %s",
                getattr(worker, "name", "unknown"),
            )
            return
        try:
            return super()._ensure_isolated_worker()
        except Exception:
            self._release_isolated_runtime()
            raise

    def _dispatch_to_moviepilot(self, item: Any) -> bool:
        """热重载冲突时返回“暂未接收”，让上层进入可重试状态而不是制造第二个 worker。"""
        if not self._claim_isolated_runtime():
            logger.warning(
                "【光鸭云盘助手】【独立worker】旧实例仍在执行，当前文件延后: %s",
                getattr(item, "path", ""),
            )
            return False
        return super()._dispatch_to_moviepilot(item)

    def _finish_deferred_shutdown_from_worker(self) -> None:
        """长同步任务自然结束后再释放账号/存储对象，避免整理中途被置空。"""
        if not self._isolated_deferred_shutdown:
            return
        self._isolated_deferred_shutdown = False
        try:
            # 从 QueueRecovery 层继续执行插件原有 teardown。该层会再次调用
            # self._stop_isolated_worker()；当前线程已到最后收尾阶段，返回 False 也不会
            # 阻止其继续调用下游 stop_service()。
            super(GuangYaWorkerGuardMixin, self).stop_service()
        except Exception as err:  # noqa: BLE001 - shutdown must be best-effort
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
        """请求停止插件 worker；同步整理未完成时保留引用，禁止新实例并行接管。"""
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
            still_alive = bool(worker and worker.is_alive())
            if still_alive:
                logger.warning(
                    "【光鸭云盘助手】【独立worker】停止等待超时，当前同步整理继续收尾；"
                    "保留 owner，禁止热重载新实例并行启动"
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
        logger.warning(
            "【光鸭云盘助手】【独立worker】插件停止已进入延迟收尾；"
            "当前文件完成后自动释放旧实例，新实例在此之前不会启动第二个 worker"
        )
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
