"""v3.6.12：pending-resource 只接受真实等待态，阻断 blocked/completed 抖动。

v3.6.1/v3.6.8 的 pending-resource 用于让 stabilizing/history_wait/retry_wait/inflight
资源优先回访。v3.6.7 的最终 scheduler 为兼容 loose 单文件，会在“没有 ready 成员”时统一
返回 ``member_wait``；当成员其实已经 blocked/completed/ignored 时，旧 pending 注册条件仍
会仅凭 reason 把目录写入 pending，下一轮 v3.6.8 又因没有等待态证据立即清掉，于是形成
“每轮重新登记 -> 自愈删除”的无效状态抖动。

本层只在最终写 pending 前收紧语义：必须由 phases 明确给出真实等待态。它不改变
MoviePilot 历史判定、durable retry、识别、分类、命名、目标目录或文件操作规则。
"""

from __future__ import annotations

from typing import Any, Dict, Sequence, Tuple

from app.sdk.logging import logger

from .organizer_pending_revisit_v361 import GuangYaOrganizerPendingRevisitV361Mixin


_PATCH_FLAG = "_v3612_pending_truth_ready"
_REAL_WAIT_PHASES: Tuple[str, ...] = (
    "stabilizing",
    "history_wait",
    "retry_wait",
    "inflight",
)
_LOG_CACHE_LIMIT = 256


def _real_wait_phases(result: Dict[str, Any]) -> Dict[str, int]:
    """只投影能够证明资源仍需自动回访的 scheduler phase。"""
    phases = dict((result or {}).get("phases") or {})
    waiting: Dict[str, int] = {}
    for name in _REAL_WAIT_PHASES:
        try:
            count = int(phases.get(name) or 0)
        except (TypeError, ValueError):
            count = 0
        if count > 0:
            waiting[name] = count
    return waiting


def install_pending_truth_v3612() -> None:
    """幂等安装最终 pending 注册门禁。"""
    cls = GuangYaOrganizerPendingRevisitV361Mixin
    if getattr(cls, _PATCH_FLAG, False):
        return

    previous_register = cls._v361_register_pending

    def register_pending(
        plugin: Any,
        group_path: str,
        files: Sequence[Any],
        result: Dict[str, Any],
    ) -> None:
        waiting = _real_wait_phases(result)
        if waiting:
            return previous_register(plugin, group_path, files, result)

        # reason=member_wait/resource_wait 只是调度层外壳，不是等待证据。
        # blocked/completed/ignored/no-ready 必须从 pending 中收口，不能每分钟重新登记。
        remover = getattr(plugin, "_v361_remove_pending", None)
        if callable(remover):
            remover(group_path)

        reason = str((result or {}).get("reason") or "")
        phases = dict((result or {}).get("phases") or {})
        if reason not in {"member_wait", "resource_wait"}:
            return

        normalized = str(group_path or "")
        normalizer = getattr(plugin, "_v360_norm", None)
        if callable(normalizer):
            try:
                normalized = str(normalizer(group_path) or normalized)
            except Exception:
                pass
        signature = (normalized, reason, tuple(sorted((str(k), int(v or 0)) for k, v in phases.items())))
        seen = getattr(plugin, "_v3612_nonwait_log_seen", None)
        if not isinstance(seen, set):
            seen = set()
            setattr(plugin, "_v3612_nonwait_log_seen", seen)
        if signature in seen:
            return
        if len(seen) >= _LOG_CACHE_LIMIT:
            seen.clear()
        seen.add(signature)
        logger.info(
            "【光鸭云盘助手】【v3.6.12】【pending门禁】非等待态不进入优先回访: path=%s reason=%s phases=%s",
            normalized,
            reason,
            phases,
        )

    cls._v361_register_pending = register_pending
    setattr(cls, _PATCH_FLAG, True)
    logger.info(
        "【光鸭云盘助手】【v3.6.12】pending 真等待门禁已启用：仅 stabilizing/history_wait/retry_wait/inflight 可登记优先回访"
    )


__all__ = ["install_pending_truth_v3612"]
