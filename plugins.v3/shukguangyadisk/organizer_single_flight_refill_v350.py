"""v3.5.0：单任务流水的可靠续跑与状态口径。

``organizer_single_flight_v350`` 已保证不积压任务；本层补齐两个运行细节：
- 当前同步整理尚未完全释放 worker 时，续跑定时器会继续短间隔等待，而不是一次命中 busy
  后就放弃到下一个普通扫描周期；
- UI/status 统一显示 queue_limit=1 和 single_flight，避免仍显示旧 batch_size=100 造成误解。
"""

from __future__ import annotations

import threading
from typing import Any, Dict

from app.sdk.logging import logger

from .organizer_folder_stream import GuangYaFolderStreamMixin
from .organizer_queue_recovery import GuangYaQueueRecoveryMixin


_MAX_IDLE_RETRIES = 30
_IDLE_RETRY_SECONDS = 0.5


def _schedule_until_idle(plugin: Any, attempt: int = 0) -> None:
    lock = plugin._isolated_runtime_lock()
    with lock:
        timer = getattr(plugin, "_guangya_single_flight_idle_timer_v350", None)
        if timer is not None and timer.is_alive():
            return

        def run() -> None:
            with plugin._isolated_runtime_lock():
                plugin._guangya_single_flight_idle_timer_v350 = None
            try:
                if not getattr(plugin, "_organize_monitor_enabled", False):
                    return
                snapshot = dict(plugin._isolated_queue_snapshot() or {})
                busy = bool(
                    snapshot.get("running_path")
                    or int(snapshot.get("queued") or 0) > 0
                    or int(snapshot.get("owned") or 0) > 0
                )
                if busy:
                    if attempt < _MAX_IDLE_RETRIES:
                        _schedule_until_idle(plugin, attempt + 1)
                    return
                plugin.run_organize_monitor_scan(manual=False)
            except Exception as err:  # noqa: BLE001
                logger.debug("【光鸭云盘助手】【单任务流水】等待 worker 空闲后续跑失败: %s", err)

        timer = threading.Timer(_IDLE_RETRY_SECONDS, run)
        timer.daemon = True
        plugin._guangya_single_flight_idle_timer_v350 = timer
        timer.start()


def install_single_flight_refill_v350() -> None:
    if getattr(GuangYaFolderStreamMixin, "_guangya_single_flight_refill_v350", False):
        return

    previous_fallback = GuangYaQueueRecoveryMixin._fallback_terminal_state

    def fallback(self: Any, item: Any, success: bool, message: str) -> None:
        try:
            return previous_fallback(self, item, success=success, message=message)
        finally:
            _schedule_until_idle(self)

    GuangYaQueueRecoveryMixin._fallback_terminal_state = fallback

    previous_run = GuangYaFolderStreamMixin.run_organize_monitor_scan

    def run_scan(self: Any, manual: bool = False) -> Dict[str, Any]:
        result = previous_run(self, manual=manual)
        snapshot = dict(self._isolated_queue_snapshot() or {})
        busy = bool(
            snapshot.get("running_path")
            or int(snapshot.get("queued") or 0) > 0
            or int(snapshot.get("owned") or 0) > 0
        )
        status = self._save_monitor_status(
            pipeline_mode="single_flight",
            queue_limit=1,
            queue_slots=0 if busy else 1,
            isolated_queue=snapshot,
        )
        if isinstance(result, dict):
            data = dict(result.get("data") or {})
            data.update({
                "pipeline_mode": "single_flight",
                "queue_limit": 1,
                "queue_slots": 0 if busy else 1,
            })
            result["data"] = data
            if getattr(self, "_guangya_single_flight_claimed_v350", False):
                members = int(data.get("submitted") or 0)
                result["message"] = (
                    f"单任务流水：当前资源已提交"
                    + (f"（成员 {members}）" if members else "")
                    + "，完成后自动发现并整理下一个资源"
                )
            elif busy:
                result["message"] = "单任务流水：当前资源仍在整理，本轮不会扫描或预排后续资源"
        return result

    GuangYaFolderStreamMixin.run_organize_monitor_scan = run_scan
    GuangYaFolderStreamMixin._guangya_single_flight_refill_v350 = True


__all__ = ["install_single_flight_refill_v350"]
