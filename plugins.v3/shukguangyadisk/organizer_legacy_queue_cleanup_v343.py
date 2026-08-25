"""v3.4.3：清理重启后仍残留的旧光鸭全局等待任务。

仅处理同时满足以下条件的 MoviePilot 公共整理队列任务：
1. 源存储为光鸭当前/历史存储名；
2. 源路径位于当前自动整理监控目录；
3. 状态为 waiting。

使用 MoviePilot 公共 ``remove_from_queue`` 接口，不访问私有队列，也不影响本地硬盘或
其它存储任务。running 任务不会被强制终止，待其自然结束后再切换到插件私有 worker。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Set, Tuple

from app.application.chain.data import get_chain_transfer_pending_port
from app.chain.transfer import TransferChain
from app.sdk.logging import logger

from .organizer_queue_recovery import GuangYaQueueRecoveryMixin


def _cleanup_legacy_waiting_tasks(self) -> Dict[str, Any]:
    chain = TransferChain()
    storage_names = self._queue_guard_storage_names()
    removed: List[str] = []
    errors: List[str] = []
    seen: Set[Tuple[str, str]] = set()

    try:
        jobs = chain.get_queue_tasks() or []
    except Exception as err:  # noqa: BLE001
        return {"removed": 0, "paths": [], "errors": [str(err)]}

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
            path = str(self._queue_obj_get(fileitem, "path", "") or "")
            state = str(self._queue_obj_get(task, "state", "waiting") or "waiting")
            if storage not in storage_names or not self._queue_guard_path_matches(path):
                continue
            # 只清理尚未开始的旧任务；运行中的任务不强杀。
            if state != "waiting":
                continue
            key = (storage, path)
            if key in seen:
                continue
            seen.add(key)
            try:
                # 先清除旧版本的持久 pending，避免下次重启再次回放。
                if pending_oper is not None:
                    try:
                        pending_oper.discard(storage=storage, src_path=path)
                    except Exception as err:  # noqa: BLE001
                        logger.debug(
                            "【光鸭云盘助手】【v3.4.3迁移】清理 pending 失败但继续移除队列: %s - %s",
                            path,
                            err,
                        )
                # MoviePilot 官方公开删除接口；不直接访问 _queue/_threads。
                chain.remove_from_queue(fileitem)
                removed.append(path)
            except Exception as err:  # noqa: BLE001
                errors.append(f"{storage}:{path}: {err}")

    marker = dict(self.get_data(self._queue_guard_marker_key) or {})
    marker.update({
        "v343_cleanup_at": time.time(),
        "v343_removed_waiting": len(removed),
        "v343_cleanup_errors": errors[:20],
    })
    self.save_data(self._queue_guard_marker_key, marker)

    if removed:
        logger.warning(
            "【光鸭云盘助手】【v3.4.3迁移】已从 MoviePilot 全局队列移除旧光鸭 waiting 任务 %s 个；"
            "本地硬盘及其它存储任务未处理",
            len(removed),
        )
    return {"removed": len(removed), "paths": removed, "errors": errors[:20]}


def install_legacy_queue_cleanup_v343() -> None:
    """安装一次性兼容补丁，热重载时幂等。"""
    if getattr(GuangYaQueueRecoveryMixin, "_guangya_legacy_cleanup_v343", False):
        return

    original_init = GuangYaQueueRecoveryMixin.init_organizer_monitor

    def init_organizer_monitor(self, force: bool = False) -> None:
        original_init(self, force=force)
        legacy_before = self._legacy_global_queue_snapshot()
        if int(legacy_before.get("active") or 0) <= 0:
            return

        cleanup = _cleanup_legacy_waiting_tasks(self)
        legacy_after = self._legacy_global_queue_snapshot()
        blocked = int(legacy_after.get("active") or 0) > 0

        if not blocked:
            self._recover_isolated_inflight_once()
            self._ensure_isolated_worker()

        self._save_monitor_status(
            queue_guard_active=blocked,
            queue_guard_restart_required=False,
            queue_guard_cleanup_v343=cleanup,
            legacy_global_queue=legacy_after,
            execution_mode="legacy_global_queue_blocked" if blocked else "isolated_sync_worker",
            queue_guard_message=(
                f"仍有 {legacy_after.get('running', 0)} 个旧光鸭任务正在运行，完成后自动切换私有 worker。"
                if blocked else
                "旧光鸭全局等待任务已清理，自动整理已切换到插件私有 worker。"
            ),
            isolated_queue=self._isolated_queue_snapshot(),
        )

    GuangYaQueueRecoveryMixin.init_organizer_monitor = init_organizer_monitor
    GuangYaQueueRecoveryMixin._guangya_legacy_cleanup_v343 = True


__all__ = ["install_legacy_queue_cleanup_v343"]
