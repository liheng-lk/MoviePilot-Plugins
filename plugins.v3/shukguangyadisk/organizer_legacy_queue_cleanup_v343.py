"""v3.4.3：清理重启后仍残留的旧光鸭全局任务。

只处理源存储为光鸭且位于当前监控目录的旧任务：
- waiting：直接使用 MoviePilot 公共删除接口移除；
- running/其它：只有 MoviePilot 整理历史已经确认成功时才判定为僵尸任务并移除。

同时清理旧 pending 回放登记，避免重启后再次出现；不访问 MoviePilot 私有队列，
也不处理本地硬盘和其它存储任务。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Set, Tuple

from app.application.chain.data import get_chain_transfer_pending_port
from app.chain.transfer import TransferChain
from app.runtime.config import global_vars
from app.sdk.logging import logger

from .organizer_queue_recovery import GuangYaQueueRecoveryMixin


def _history_confirms_completed(self, fileitem: Any, path: str) -> bool:
    """复用现有 MoviePilot history gate，只接受明确 completed。"""
    try:
        result = self._preflight_history(fileitem, path)
    except Exception as err:  # noqa: BLE001
        logger.debug("【光鸭云盘助手】【v3.4.3迁移】旧任务历史确认失败: %s - %s", path, err)
        return False
    return str((result or {}).get("decision") or "") == "completed"


def _cleanup_legacy_global_tasks(self) -> Dict[str, Any]:
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
        return {
            "removed": 0,
            "removed_waiting": 0,
            "removed_stale_running": 0,
            "retained_running": 0,
            "errors": [str(err)],
        }

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

            # 旧 background 队列的 pending 每次都清理，不能再被一次性 marker 跳过。
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
    })
    self.save_data(self._queue_guard_marker_key, marker)

    if removed:
        logger.warning(
            "【光鸭云盘助手】【v3.4.3迁移】清理旧光鸭全局任务 %s 个：waiting=%s，"
            "已完成但卡在 running=%s；其它存储未处理",
            removed,
            len(removed_waiting),
            len(removed_stale_running),
        )
    if retained_running:
        logger.info(
            "【光鸭云盘助手】【v3.4.3迁移】仍保留 %s 个未确认完成的旧 running 任务，不会强制删除",
            len(retained_running),
        )

    return {
        "removed": removed,
        "removed_waiting": len(removed_waiting),
        "removed_stale_running": len(removed_stale_running),
        "retained_running": len(retained_running),
        "removed_paths": (removed_waiting + removed_stale_running)[:20],
        "retained_paths": retained_running[:20],
        "errors": errors[:20],
    }


def install_legacy_queue_cleanup_v343() -> None:
    """安装兼容补丁；每次初始化都会重新检查，不能再被旧的一次性 marker 跳过。"""
    if getattr(GuangYaQueueRecoveryMixin, "_guangya_legacy_cleanup_v343", False):
        return

    original_init = GuangYaQueueRecoveryMixin.init_organizer_monitor

    def init_organizer_monitor(self, force: bool = False) -> None:
        original_init(self, force=force)
        legacy_before = self._legacy_global_queue_snapshot()
        cleanup = {
            "removed": 0,
            "removed_waiting": 0,
            "removed_stale_running": 0,
            "retained_running": 0,
            "errors": [],
        }
        if int(legacy_before.get("active") or 0) > 0:
            cleanup = _cleanup_legacy_global_tasks(self)

        legacy_after = self._legacy_global_queue_snapshot()
        blocked = int(legacy_after.get("active") or 0) > 0

        if not blocked:
            self._recover_isolated_inflight_once()
            self._ensure_isolated_worker()

        retained = int(cleanup.get("retained_running") or 0)
        self._save_monitor_status(
            queue_guard_active=blocked,
            queue_guard_restart_required=False,
            queue_guard_cleanup_v343=cleanup,
            legacy_global_queue=legacy_after,
            execution_mode="legacy_global_queue_blocked" if blocked else "isolated_sync_worker",
            queue_guard_message=(
                f"仍有 {retained or legacy_after.get('running', 0)} 个旧光鸭任务正在运行且尚未确认完成；"
                "完成后会自动切换私有 Worker。"
                if blocked else
                "旧光鸭全局任务已清理，自动整理已切换到插件私有 Worker。"
            ),
            isolated_queue=self._isolated_queue_snapshot(),
        )

    GuangYaQueueRecoveryMixin.init_organizer_monitor = init_organizer_monitor
    GuangYaQueueRecoveryMixin._guangya_legacy_cleanup_v343 = True


__all__ = ["install_legacy_queue_cleanup_v343"]
