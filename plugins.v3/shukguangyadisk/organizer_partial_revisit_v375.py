"""v3.7.5：部分 ready 剧集提交后保留目录级 pending，确保剩余成员继续回访。

v3.7.4 允许同一资源目录里已经 ready 的成员先提交，避免被仍处于 stabilizing /
history_wait / retry_wait / inflight 的兄弟成员整体阻塞。但提交成功后 v3.6.6 的终态
会删除整个目录的 pending；与此同时 known-resource 已记录的是完整目录签名，因此等待态
到期但文件路径/大小未变化时，增量扫描会认为目录“无变化”，剩余成员可能永久失联。

本补丁处理两件事：
- “本次已成功提交 + 仍存在可回访等待态成员”时重新登记目录 pending；
- 升级后强制执行一次完整 baseline discovery，把旧版本已经丢失 pending 的半整理目录
  重新发现出来；完成一次后写持久标记，不会每次重启都强制全量扫描。

已提交成员仍按原流程进入 worker，不回滚、不重复提交；completed/blocked/ignored/unknown
不会为了续跑制造永久 pending，全成员 ready 或目录真正完成时仍按原逻辑删除 pending。
"""

from __future__ import annotations

from functools import wraps
import time
from typing import Any, Dict, Sequence

from app.sdk.logging import logger

from .organizer_monitor_v366 import GuangYaOrganizerMonitorV366Mixin


_WAIT_PHASES = ("stabilizing", "history_wait", "retry_wait", "inflight")
_INSTALL_FLAG = "_v375_partial_revisit_installed"
_RECOVERY_KEY = "organize_v375_partial_revisit_recovery"


def _remaining_wait_count(result: Dict[str, Any]) -> int:
    phases = dict(result.get("phases") or {})
    return sum(int(phases.get(name) or 0) for name in _WAIT_PHASES)


def install_partial_revisit_v375() -> None:
    """给最终调度边界补上部分续跑，并一次性唤醒旧版本遗留的半整理目录。"""
    cls = GuangYaOrganizerMonitorV366Mixin
    if bool(getattr(cls, _INSTALL_FLAG, False)):
        return

    original_finish = cls._v366_finish_schedule
    original_baseline_due = cls._v366_baseline_due
    original_mark_baseline_complete = cls._v366_mark_baseline_complete

    @wraps(original_finish)
    def finish_wrapped(
        self,
        group_path: str,
        files: Sequence[Any],
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        returned = original_finish(self, group_path, files, result)

        if not bool(result.get("scheduled")):
            return returned

        remaining_wait = _remaining_wait_count(result)
        if remaining_wait <= 0:
            return returned

        register_pending = getattr(self, "_v361_register_pending", None)
        if not callable(register_pending):
            return returned

        # original_finish() 会在 scheduled=True 时先删除目录 pending。这里仅对仍有
        # hard-wait sibling 的“部分成功”重新登记；due_at 仍由 v3.6.1 pending 层计算。
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

    @wraps(original_baseline_due)
    def baseline_due_wrapped(self) -> bool:
        """旧版本可能已经把 pending 丢掉；升级后强制一次完整 discovery 自愈。"""
        raw = self.get_data(_RECOVERY_KEY) or {}
        if not isinstance(raw, dict) or not float(raw.get("completed_at") or 0):
            return True
        return bool(original_baseline_due(self))

    @wraps(original_mark_baseline_complete)
    def mark_baseline_complete_wrapped(self) -> None:
        result = original_mark_baseline_complete(self)
        raw = self.get_data(_RECOVERY_KEY) or {}
        if not isinstance(raw, dict) or not float(raw.get("completed_at") or 0):
            self.save_data(
                _RECOVERY_KEY,
                {
                    "completed_at": time.time(),
                    "reason": "v3.7.5 partial-ready pending recovery completed",
                },
            )
            logger.info(
                "【光鸭云盘助手】【v3.7.5】【部分续跑】升级自愈基线已完成；"
                "旧版本可能遗留的半整理目录已重新进入发现范围"
            )
        return result

    setattr(finish_wrapped, "_v375_partial_revisit_wrapper", True)
    cls._v366_finish_schedule = finish_wrapped
    cls._v366_baseline_due = baseline_due_wrapped
    cls._v366_mark_baseline_complete = mark_baseline_complete_wrapped
    setattr(cls, _INSTALL_FLAG, True)


__all__ = ["install_partial_revisit_v375"]
