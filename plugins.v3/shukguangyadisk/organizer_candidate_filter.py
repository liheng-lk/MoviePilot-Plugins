"""v3.4 自动整理候选文件过滤器。

独立 worker 架构不再需要 ``TransferDispatcher``：它的核心职责是把文件事件提交到
MoviePilot 全局后台整理队列，而 v3.4 明确禁止走这条路径。本模块只读取 MoviePilot
公开运行设置中的媒体/字幕/音频扩展名与临时文件扩展名，用于扫描阶段过滤候选。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List

from app.runtime.settings import get_runtime_setting


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
    """用无队列状态的候选过滤器替换基础 organizer 的 TransferDispatcher 实例。"""

    _organize_candidate_filter: _MoviePilotCandidateFilter | None = None

    def _get_organize_dispatcher(self) -> _MoviePilotCandidateFilter:
        if self._organize_candidate_filter is None:
            self._organize_candidate_filter = _MoviePilotCandidateFilter()
        return self._organize_candidate_filter


__all__ = ["GuangYaCandidateFilterMixin"]
