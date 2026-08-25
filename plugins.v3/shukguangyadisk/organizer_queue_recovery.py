"""Emergency queue-safety guard for GuangYa auto organizer v3.3.2.

v3.3.0/v3.3.1 submitted every discovered cloud file to MoviePilot's global
``TransferChain`` background queue. MoviePilot persists those background tasks and
replays them at startup, so a large GuangYa library can monopolize the same queue
used by local disks and normal MoviePilot monitors.

This hotfix deliberately pauses automatic submission, quarantines only GuangYa
pending registrations that live under the configured auto-monitor root, and marks
those paths for cooperative cancellation. It never clears MoviePilot's global
queue, never touches local/other-storage pending rows, and never restarts workers.
A single MoviePilot restart after upgrading drops the old in-memory GuangYa queue;
quarantined registrations then cannot be replayed. The organizer state is retained
as retryable work for the isolated v3.4 scheduler.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

from app.application.chain.data import get_chain_transfer_pending_port
from app.runtime.config import global_vars
from app.sdk.logging import logger


class GuangYaQueueRecoveryMixin:
    """Pause unsafe background dispatch and quarantine only this plugin's backlog."""

    _queue_guard_marker_key = "organize_v332_queue_guard"
    _queue_guard_reason = (
        "v3.3.2 紧急队列保护已启用：自动整理暂时停止向 MoviePilot 全局整理队列提交任务。"
        "升级后请重启 MoviePilot 一次，以清除旧版已进入内存队列的光鸭任务；普通本地/其它存储任务不会被清理。"
    )

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

    def _quarantine_guangya_pending(self) -> Dict[str, Any]:
        """Remove restart replay registrations only for GuangYa auto-monitor paths."""
        pending_oper = get_chain_transfer_pending_port()
        storage_names = self._queue_guard_storage_names()
        quarantined: List[str] = []
        errors: List[str] = []
        try:
            pendings = list(pending_oper.list_all() or [])
        except Exception as err:  # noqa: BLE001 - host compatibility boundary
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
                # Cooperative, one-shot cancellation for a task already present in the
                # current process queue. The in-memory queue itself is intentionally not
                # mutated; a single host restart provides the clean boundary.
                global_vars.stop_transfer(str(src_path))
                quarantined.append(str(src_path))
            except Exception as err:  # noqa: BLE001
                errors.append(f"{storage}:{src_path}: {err}")

        return {
            "quarantined": len(quarantined),
            "paths": quarantined[:20],
            "errors": errors[:20],
        }

    def _move_quarantined_inflight_to_retry(self, paths: List[str]) -> int:
        """Preserve organizer work without letting old global-queue leases stay active."""
        path_set = {str(path) for path in paths if path}
        if not path_set:
            return 0
        state_store = self._state()
        now = time.time()

        def apply(state: Dict[str, Any]) -> int:
            moved = 0
            inflight = state.get("inflight") or {}
            retry = state.get("retry") or {}
            for path in list(path_set):
                row = inflight.pop(path, None)
                if not isinstance(row, dict):
                    continue
                retry[path] = {
                    "fingerprint": str(row.get("fingerprint") or ""),
                    "attempts": max(int(row.get("attempts") or 1), 1),
                    "retry_at": 0,
                    "last_error": "v3.3.2 已从 MoviePilot 全局待整理回放登记隔离，等待安全调度器重新处理",
                    "quarantined_at": now,
                }
                moved += 1
            state["inflight"] = inflight
            state["retry"] = retry
            return moved

        try:
            return int(state_store.mutate(apply) or 0)
        except Exception as err:  # noqa: BLE001
            logger.warning("【光鸭云盘助手】【队列保护】迁移 inflight 状态失败: %s", err)
            return 0

    def _apply_queue_guard_once(self) -> Dict[str, Any]:
        marker = self.get_data(self._queue_guard_marker_key) or {}
        if isinstance(marker, dict) and marker.get("applied"):
            return marker

        # Pause only the organizer switch; account/storage remains enabled and manual
        # MoviePilot transfer remains available.
        config = dict(self.get_data(self._monitor_config_key) or {})
        was_enabled = bool(config.get("enabled", getattr(self, "_organize_monitor_enabled", False)))
        config["enabled"] = False
        self.save_data(self._monitor_config_key, config)
        self._organize_monitor_enabled = False

        result = self._quarantine_guangya_pending()
        moved = self._move_quarantined_inflight_to_retry(list(result.get("paths") or []))
        marker = {
            "applied": True,
            "applied_at": time.time(),
            "was_enabled": was_enabled,
            "quarantined": int(result.get("quarantined") or 0),
            "state_moved_to_retry": moved,
            "errors": list(result.get("errors") or []),
            "restart_required": bool(result.get("quarantined")),
        }
        self.save_data(self._queue_guard_marker_key, marker)
        try:
            self._save_monitor_status(
                running=False,
                queue_guard_active=True,
                queue_guard_restart_required=marker["restart_required"],
                queue_guard_quarantined=marker["quarantined"],
                queue_guard_message=self._queue_guard_reason,
            )
        except Exception:
            pass
        logger.error(
            "【光鸭云盘助手】【队列保护】自动整理已暂停；隔离光鸭待回放任务 %s 个，"
            "请重启 MoviePilot 一次恢复干净的全局整理队列",
            marker["quarantined"],
        )
        return marker

    def init_organizer_monitor(self, force: bool = False) -> None:
        super().init_organizer_monitor(force=force)
        self._apply_queue_guard_once()

    def api_organize_monitor_save(self, payload: dict) -> Dict[str, Any]:
        """v3.3.2 intentionally refuses to re-enable unsafe automatic submission."""
        payload = dict(payload or {})
        requested_enabled = bool(payload.get("enabled"))
        payload["enabled"] = False
        response = super().api_organize_monitor_save(payload)
        if isinstance(response, dict):
            data = response.setdefault("data", {})
            data["queue_guard"] = self.get_data(self._queue_guard_marker_key) or {}
            if requested_enabled:
                response["message"] = self._queue_guard_reason
        return response

    def run_organize_monitor_scan(self, manual: bool = False) -> Dict[str, Any]:
        """Do not enqueue more tasks until the isolated v3.4 scheduler is installed."""
        self.init_organizer_monitor()
        marker = self.get_data(self._queue_guard_marker_key) or {}
        return {
            "success": False,
            "message": self._queue_guard_reason,
            "data": {
                "queue_guard": marker,
                "disabled": True,
                "restart_required": bool(marker.get("restart_required")) if isinstance(marker, dict) else False,
            },
        }

    def organize_monitor_tick(self) -> None:
        """Heartbeat is a no-op in the emergency queue-safe release."""
        self.init_organizer_monitor()
        return None

    def api_organize_monitor_status(self) -> Dict[str, Any]:
        response = super().api_organize_monitor_status()
        if isinstance(response, dict):
            data = response.setdefault("data", {})
            status = data.setdefault("status", {})
            marker = self.get_data(self._queue_guard_marker_key) or {}
            status.update({
                "queue_guard_active": True,
                "queue_guard_restart_required": bool(marker.get("restart_required")) if isinstance(marker, dict) else False,
                "queue_guard_quarantined": int(marker.get("quarantined") or 0) if isinstance(marker, dict) else 0,
                "queue_guard_message": self._queue_guard_reason,
            })
        return response


__all__ = ["GuangYaQueueRecoveryMixin"]
