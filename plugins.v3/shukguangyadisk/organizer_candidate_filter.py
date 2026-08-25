"""v3.4+ 自动整理候选过滤与私有队列连续补充。

独立 worker 架构不再需要 ``TransferDispatcher``：它的核心职责是把文件事件提交到
MoviePilot 全局后台整理队列，而 v3.4 明确禁止走这条路径。本模块只读取 MoviePilot
公开运行设置中的媒体/字幕/音频扩展名与临时文件扩展名，用于扫描阶段过滤候选。

v3.4.1 修复私有队列完成一批后可能等待完整扫描周期才继续的问题。
v3.4.2 把资源目录升级为真正的“一个文件夹一个整理任务”。
v3.4.3 清理重启后仍残留的旧光鸭全局任务并自动切换到私有 worker。
v3.4.4 中文发布目录只作为 MoviePilot 识别提示，并增加标题/年份一致性保护。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, List, Tuple

from app.runtime.settings import get_runtime_setting
from app.sdk.logging import logger


class _MoviePilotCandidateFilter:
    """只实现 folder-stream 所需的候选判断合同，不持有任何 MP 队列状态。"""

    @staticmethod
    def _list_setting(name: str) -> List[str]:
        value: Any = get_runtime_setting(name)
        if not value:
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return [str(item).strip() for item in value if str(item).strip()]

    @classmethod
    def is_transfer_candidate_path(cls, file_path: Path) -> bool:
        suffix = str(file_path.suffix or "").casefold()
        if not suffix:
            return False
        temp_exts = {item.casefold() for item in cls._list_setting("DOWNLOAD_TMPEXT")}
        if suffix in temp_exts:
            return False
        allowed = {
            item.casefold()
            for key in ("RMT_MEDIAEXT", "RMT_SUBEXT", "RMT_AUDIOEXT")
            for item in cls._list_setting(key)
        }
        return suffix in allowed

    @staticmethod
    def retry_pending() -> None:
        """兼容旧 folder-stream 调用点；独立路径没有 dispatcher pending。"""
        return None


class GuangYaCandidateFilterMixin:
    """无 MP 队列状态的候选过滤器 + 私有队列低水位连续补充。"""

    _organize_candidate_filter: _MoviePilotCandidateFilter | None = None

    _monitor_heartbeat = 10
    _isolated_refill_low_watermark = 8
    _isolated_refill_min_gap = 8.0
    _organize_last_fast_refill: float = 0.0

    def _get_organize_dispatcher(self) -> _MoviePilotCandidateFilter:
        if self._organize_candidate_filter is None:
            self._organize_candidate_filter = _MoviePilotCandidateFilter()
        return self._organize_candidate_filter

    def _fast_refill_needed(self) -> Tuple[bool, str]:
        if not getattr(self, "_organize_monitor_enabled", False):
            return False, "disabled"

        snapshot_getter = getattr(self, "_isolated_queue_snapshot", None)
        if not callable(snapshot_getter):
            return False, "no_isolated_queue"
        try:
            isolated = dict(snapshot_getter() or {})
        except Exception:
            return False, "snapshot_error"

        queued = int(isolated.get("queued") or 0)
        if queued > self._isolated_refill_low_watermark:
            return False, "queue_has_buffer"

        status = dict(self.get_data(self._monitor_status_key) or {})
        capacity_wait = int(status.get("capacity_wait") or 0)
        waiting = int(status.get("waiting") or 0)
        if capacity_wait > 0:
            return True, f"capacity_wait={capacity_wait},queued={queued}"
        if waiting > 0 and queued == 0 and not str(isolated.get("running_path") or ""):
            return True, f"stability_wait={waiting},queued=0"
        return False, "no_backlog"

    def organize_monitor_tick(self) -> None:
        self.init_organizer_monitor()
        if not self._organize_monitor_enabled:
            return

        now = time.monotonic()
        needed, reason = self._fast_refill_needed()
        if needed and now - self._organize_last_fast_refill >= self._isolated_refill_min_gap:
            self._organize_last_fast_refill = now
            self._organize_monitor_last_tick = now
            self._save_monitor_status(
                fast_refill_active=True,
                fast_refill_reason=reason,
                fast_refill_at=time.time(),
            )
            logger.info("【光鸭云盘助手】【独立worker】【连续补充】触发下一批扫描: %s", reason)
            try:
                return self.run_organize_monitor_scan(manual=False)
            finally:
                self._save_monitor_status(fast_refill_active=False)

        return super().organize_monitor_tick()


from .organizer_folder_batch_v342 import install_folder_batch_v342
from .organizer_legacy_queue_cleanup_v343 import install_legacy_queue_cleanup_v343
from .organizer_safe_recognition_v344 import install_safe_recognition_v344

install_folder_batch_v342()
install_legacy_queue_cleanup_v343()
install_safe_recognition_v344()


__all__ = ["GuangYaCandidateFilterMixin"]
