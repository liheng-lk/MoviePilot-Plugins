"""v3.7.5：部分 ready 剧集提交后保留目录级 pending，确保剩余成员继续回访。

v3.7.4 允许同一资源目录里已经 ready 的成员先提交，避免被仍处于 stabilizing /
history_wait / retry_wait / inflight 的兄弟成员整体阻塞。但提交成功后 v3.6.6 的终态
会删除整个目录的 pending；与此同时 known-resource 已记录的是完整目录签名，因此等待态
到期但文件路径/大小未变化时，增量扫描会认为目录“无变化”，剩余成员可能永久失联。

本补丁只在“本次已成功提交 + 仍存在可回访等待态成员”时重新登记目录 pending：
- 已提交成员仍按原流程进入 worker，不回滚、不重复提交；
- 剩余 stabilizing/retry/history/inflight 成员按 v3.6.1 的 due_at 机制优先回访；
- completed/blocked/ignored/unknown 不会为了续跑而制造永久 pending；
- 全成员 ready 或目录已真正完成时仍按原逻辑删除 pending。
"""

from __future__ import annotations

from functools import wraps
from typing import Any, Dict, Sequence

from app.sdk.logging import logger

from .organizer_monitor_v366 import GuangYaOrganizerMonitorV366Mixin


_WAIT_PHASES = ("stabilizing", "history_wait", "retry_wait", "inflight")
_INSTALL_FLAG = "_v375_partial_revisit_installed"


def _remaining_wait_count(result: Dict[str, Any]) -> int:
    phases = dict(result.get("phases") or {})
    return sum(int(phases.get(name) or 0) for name in _WAIT_PHASES)


def install_partial_revisit_v375() -> None:
    """给 v3.6.6 最终调度边界补上“部分提交后继续回访”的目录级 pending。"""
    cls = GuangYaOrganizerMonitorV366Mixin
    if bool(getattr(cls, _INSTALL_FLAG, False)):
        return

    original = cls._v366_finish_schedule

    @wraps(original)
    def wrapped(
        self,
        group_path: str,
        files: Sequence[Any],
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        returned = original(self, group_path, files, result)

        if not bool(result.get("scheduled")):
            return returned

        remaining_wait = _remaining_wait_count(result)
        if remaining_wait <= 0:
            return returned

        register_pending = getattr(self, "_v361_register_pending", None)
        if not callable(register_pending):
            return returned

        # original() 会在 scheduled=True 时先删除目录 pending。这里仅对仍有 hard-wait
        # sibling 的“部分成功”重新登记；due_at 仍完全交给 v3.6.1 pending 层计算。
        pending_result = dict(result)
        pending_result["scheduled"] = False
        pending_result["reason"] = "partial_wait"
        register_pending(group_path, files, pending_result)

        normalized_group = self._v360_norm(group_path)
        try:
            self._save_monitor_status(
                partial_revisit_pending=remaining_wait,
                partial_revisit_path=normalized_group,
            )
        except Exception:
            pass

        logger.info(
            "【光鸭云盘助手】【v3.7.5】【部分续跑】当前 ready 成员已提交，仍有等待成员=%s；"
            "已保留资源 pending，后续优先回访: %s",
            remaining_wait,
            normalized_group,
        )
        return returned

    setattr(wrapped, "_v375_partial_revisit_wrapper", True)
    cls._v366_finish_schedule = wrapped
    setattr(cls, _INSTALL_FLAG, True)


__all__ = ["install_partial_revisit_v375"]
