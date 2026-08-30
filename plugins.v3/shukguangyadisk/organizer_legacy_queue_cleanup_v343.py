"""v3.4.3：清理重启后仍残留的旧光鸭全局任务。

只处理源存储为光鸭且位于当前监控目录的旧任务：
- waiting：直接使用 MoviePilot 公共删除接口移除；
- running/其它：只有 MoviePilot 整理历史已经确认成功时才判定为僵尸任务并移除。

v3.6.2 收口迁移生命周期：这段代码只负责“旧 background 全局队列迁移”，不能继续作为
自动整理热路径的一部分。插件实例启动时最多主动清理一次；若确实还保留无法确认完成的
旧 running，只按低频间隔重新核验。任何当前/旧私有 Worker 仍活跃时都禁止触碰 MoviePilot
全局队列，避免把当前 ``background=False`` 同步整理误认成 v3.3 遗留任务。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Set, Tuple

from app.application.chain.data import get_chain_transfer_pending_port
from app.chain.transfer import TransferChain
from app.runtime.config import global_vars
from app.sdk.logging import logger

from .organizer_queue_recovery import GuangYaQueueRecoveryMixin


_V362_RECHECK_SECONDS = 60.0
_V362_RETAINED_LOG_SECONDS = 300.0


def _history_confirms_completed(self, fileitem: Any, path: str) -> bool:
    """复用现有 MoviePilot history gate，只接受明确 completed。"""
    try:
        result = self._preflight_history(fileitem, path)
    except Exception as err:  # noqa: BLE001
        logger.debug("【光鸭云盘助手】【v3.4.3迁移】旧任务历史确认失败: %s - %s", path, err)
        return False
    return str((result or {}).get("decision") or "") == "completed"


def _isolated_runtime_active(self) -> bool:
    """当前或旧私有 Worker 只要仍活着，迁移器就绝不能碰 MoviePilot 全局队列。"""
    try:
        snapshot = dict(self._isolated_queue_snapshot() or {})
    except Exception:
        return False
    return bool(
        str(snapshot.get("running_path") or "")
        or int(snapshot.get("queued") or 0) > 0
        or int(snapshot.get("owned") or 0) > 0
        or bool(snapshot.get("worker_alive"))
        or bool(snapshot.get("owner_worker_alive"))
    )


def _empty_cleanup(*, skipped: str = "") -> Dict[str, Any]:
    return {
        "removed": 0,
        "removed_waiting": 0,
        "removed_stale_running": 0,
        "retained_running": 0,
        "removed_paths": [],
        "retained_paths": [],
        "errors": [],
        "skipped": skipped,
    }


def _cleanup_legacy_global_tasks(self) -> Dict[str, Any]:
    """执行一次旧全局队列迁移；私有 Worker 活跃时 fail-closed。"""
    if _isolated_runtime_active(self):
        return _empty_cleanup(skipped="isolated_worker_active")

    chain = TransferChain()
    storage_names = self._queue_guard_storage_names()
    removed_waiting: List[str] = []
    removed_stale_running: List[str] = []
    retained_running: List[str] = []
    errors: List[str] = []
    seen: Set[Tuple[str, str]] = set()

    try:
        jobs = chain.get_queue_tasks() or []
    except Exception as err:  # noqa: BLE001
        result = _empty_cleanup()
        result["errors"] = [str(err)]
        return result

    try:
        pending_oper = get_chain_transfer_pending_port()
    except Exception:
        pending_oper = None

    for job in jobs:
        for task in self._queue_obj_get(job, "tasks", []) or []:
            fileitem = self._queue_obj_get(task, "fileitem")
            if not fileitem:
                continue
            storage = str(self._queue_obj_get(fileitem, "storage", "") or "")
            path = self._organize_normalize_path(self._queue_obj_get(fileitem, "path", "") or "")
            state = str(self._queue_obj_get(task, "state", "waiting") or "waiting")
            if storage not in storage_names or not self._queue_guard_path_matches(path):
                continue

            key = (storage, path)
            if key in seen:
                continue
            seen.add(key)

            # 这里只处理旧 background pending。v3.6.2 已确保私有 Worker 活跃时不会进入本函数。
            if pending_oper is not None:
                try:
                    pending_oper.discard(storage=storage, src_path=path)
                except Exception as err:  # noqa: BLE001
                    errors.append(f"pending:{storage}:{path}: {err}")

            remove = state == "waiting"
            stale_completed = False
            if not remove:
                stale_completed = _history_confirms_completed(self, fileitem, path)
                remove = stale_completed

            if not remove:
                if state == "running":
                    retained_running.append(path)
                continue

            try:
                # 与 MoviePilot DELETE /transfer/queue 的公开行为一致。
                chain.remove_from_queue(fileitem)
                global_vars.stop_transfer(path)
                if state == "waiting":
                    removed_waiting.append(path)
                elif stale_completed:
                    removed_stale_running.append(path)
            except Exception as err:  # noqa: BLE001
                errors.append(f"queue:{storage}:{path}: {err}")

    removed = len(removed_waiting) + len(removed_stale_running)
    marker = dict(self.get_data(self._queue_guard_marker_key) or {})
    marker.update({
        "v343_cleanup_at": time.time(),
        "v343_removed": removed,
        "v343_removed_waiting": len(removed_waiting),
        "v343_removed_stale_running": len(removed_stale_running),
        "v343_retained_running": len(retained_running),
        "v343_cleanup_errors": errors[:20],
        "v362_cleanup_mode": "startup_once_then_low_frequency_running_recheck",
    })
    self.save_data(self._queue_guard_marker_key, marker)

    if removed:
        logger.warning(
            "【光鸭云盘助手】【v3.6.2迁移】清理旧光鸭全局任务 %s 个：waiting=%s，"
            "已完成但卡在 running=%s；其它存储未处理",
            removed,
            len(removed_waiting),
            len(removed_stale_running),
        )

    return {
        "removed": removed,
        "removed_waiting": len(removed_waiting),
        "removed_stale_running": len(removed_stale_running),
        "retained_running": len(retained_running),
        "removed_paths": (removed_waiting + removed_stale_running)[:20],
        "retained_paths": retained_running[:20],
        "errors": errors[:20],
        "skipped": "",
    }


def _maybe_log_retained(self, cleanup: Dict[str, Any], now_mono: float) -> None:
    """未确认 running 只在首次/集合变化/每 5 分钟输出一次。"""
    retained_paths = tuple(sorted(str(path) for path in (cleanup.get("retained_paths") or []) if path))
    if not retained_paths:
        self._v362_legacy_retained_signature = ()
        return

    previous = tuple(getattr(self, "_v362_legacy_retained_signature", ()) or ())
    last_log = float(getattr(self, "_v362_legacy_retained_log_at", 0.0) or 0.0)
    changed = retained_paths != previous
    if changed or not last_log or now_mono - last_log >= _V362_RETAINED_LOG_SECONDS:
        logger.info(
            "【光鸭云盘助手】【v3.6.2迁移】仍保留 %s 个未确认完成的旧 running 任务；"
            "仅低频复查，不会强制删除，也不会在扫描热路径重复清理",
            len(retained_paths),
        )
        self._v362_legacy_retained_log_at = now_mono
    self._v362_legacy_retained_signature = retained_paths


def install_legacy_queue_cleanup_v343() -> None:
    """安装旧队列迁移；v3.6.2 起从热路径退役，仅启动一次 + retained running 低频复查。"""
    if getattr(GuangYaQueueRecoveryMixin, "_guangya_legacy_cleanup_v343", False):
        return

    original_init = GuangYaQueueRecoveryMixin.init_organizer_monitor

    def init_organizer_monitor(self, force: bool = False) -> None:
        # 原始恢复层仍负责基础初始化和只读 legacy snapshot；这里仅决定是否需要执行破坏性清理。
        original_init(self, force=force)

        now_mono = time.monotonic()
        checked = bool(getattr(self, "_v362_legacy_cleanup_checked", False))
        next_recheck = float(getattr(self, "_v362_legacy_cleanup_next_recheck", 0.0) or 0.0)

        # 当前实例或热更新旧实例的私有 Worker 仍存在时，MoviePilot 队列中的任务可能就是当前
        # background=False 执行链，绝不允许迁移器按“旧 waiting”删除。
        if _isolated_runtime_active(self):
            return

        if checked and now_mono < next_recheck:
            return

        legacy_before = self._legacy_global_queue_snapshot()
        cleanup = _empty_cleanup()
        if int(legacy_before.get("active") or 0) > 0:
            cleanup = _cleanup_legacy_global_tasks(self)

        legacy_after = self._legacy_global_queue_snapshot()
        blocked = int(legacy_after.get("active") or 0) > 0

        self._v362_legacy_cleanup_checked = True
        # 只有真正还有遗留任务时才低频复查；清空后本实例永久退出迁移热路径。
        self._v362_legacy_cleanup_next_recheck = (
            now_mono + _V362_RECHECK_SECONDS if blocked else float("inf")
        )
        _maybe_log_retained(self, cleanup, now_mono)

        if not blocked:
            self._recover_isolated_inflight_once()
            self._ensure_isolated_worker()

        retained = int(cleanup.get("retained_running") or 0)
        marker = dict(self.get_data(self._queue_guard_marker_key) or {})
        marker.update({
            "v362_checked_at": time.time(),
            "v362_blocked": blocked,
            "v362_next_recheck_seconds": _V362_RECHECK_SECONDS if blocked else 0,
            "v362_private_worker_guard": True,
        })
        self.save_data(self._queue_guard_marker_key, marker)

        self._save_monitor_status(
            queue_guard_active=blocked,
            queue_guard_restart_required=False,
            queue_guard_cleanup_v343=cleanup,
            legacy_global_queue=legacy_after,
            execution_mode="legacy_global_queue_blocked" if blocked else "isolated_sync_worker",
            queue_guard_message=(
                f"仍有 {retained or legacy_after.get('running', 0)} 个旧光鸭任务尚未确认完成；"
                "每 60 秒安全复查一次，期间不会清理当前私有 Worker 任务。"
                if blocked else
                "旧光鸭全局任务迁移已收口，本实例不再重复扫描/清理全局队列。"
            ),
            isolated_queue=self._isolated_queue_snapshot(),
        )

    GuangYaQueueRecoveryMixin.init_organizer_monitor = init_organizer_monitor
    GuangYaQueueRecoveryMixin._guangya_legacy_cleanup_v343 = True


__all__ = ["install_legacy_queue_cleanup_v343"]
