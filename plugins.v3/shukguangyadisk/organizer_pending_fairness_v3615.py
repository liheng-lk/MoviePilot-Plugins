"""v3.6.15：真实等待 pending 优先复查但不再饿死普通 discovery。

v3.6.8/v3.6.12 已把 pending-resource 收口为真实 stabilizing/history_wait/retry_wait/inflight
等待态，但最终 monitor 仍会在每个 tick 只要命中一个到期 pending 就立即 return。对于大量
“仍需等待、但当前没有活动执行”的资源，这会让 known scan 与 v3.6.9 continuous discovery
长期得不到执行机会，用户配置 60 秒监控却仍可能数十分钟发现不到新资源。

本层只修调度公平性和 retry 可观测性，不改变 MoviePilot/光鸭业务规则：
- pending 真正 scheduled 时继续独占本 tick；
- durable/证据 pending 的 inflight 仍独占，保持单资源执行边界；
- pending 目录/API 读取失败或 worker_not_accept 时保留原阻断，避免故障时继续打 API/入队；
- stabilizing/retry_wait/history_wait/no_ready 等“仅等待、无活动执行”的复查结果让出本 tick，
  通过一次 skip-priority 标记重新进入现有 v3.6.9 monitor wrapper，让 known scan + continuous
  discovery 在同一监控周期继续推进；
- OrganizerStateStore.stats 在不改持久 schema 的前提下，把 retry 统计拆成 retry_total、
  retry_wait（retry_at 尚未到期）和 retry_due（已到期、等待重新评估），避免把所有 retry 行
  都误显示成“仍在退避等待”。
"""

from __future__ import annotations

import time
from typing import Any, Dict, Tuple

from app.sdk.logging import logger

from .organizer_monitor_v366 import GuangYaOrganizerMonitorV366Mixin
from .organizer_pending_revisit_v361 import GuangYaOrganizerPendingRevisitV361Mixin
from .organizer_state import OrganizerStateStore


_PATCH_FLAG = "_v3615_pending_fairness_ready"
_SKIP_FLAG = "_v3615_skip_priority_once"
_LOG_CACHE_LIMIT = 256


def _priority_snapshot(result: Any) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    if not isinstance(result, dict):
        return {}, {}
    data = dict(result.get("data") or {})
    nested = dict(data.get("result") or {}) if isinstance(data.get("result"), dict) else {}
    return data, nested


def _priority_can_yield(result: Any) -> bool:
    """只有“无活动执行、无读取/入队故障”的 pending 复查才能把剩余 tick 让给 discovery。"""
    data, nested = _priority_snapshot(result)
    if not data.get("priority_revisit") or bool(data.get("scheduled")):
        return False
    # 读取失败、批量陈旧清理等返回没有 scheduler result；保持原行为，不扩大远端请求预算。
    if not nested:
        return False
    reason = str(nested.get("reason") or "")
    phases = dict(nested.get("phases") or {})
    try:
        inflight = int(phases.get("inflight") or 0)
    except (TypeError, ValueError):
        inflight = 0
    if inflight > 0:
        return False
    if reason == "worker_not_accept":
        return False
    return True


def _retry_schedule_counts(state: Dict[str, Any], *, now: float) -> Dict[str, int]:
    retry = dict((state or {}).get("retry") or {})
    waiting = due = 0
    max_attempts = 0
    for raw_row in retry.values():
        row = dict(raw_row or {}) if isinstance(raw_row, dict) else {}
        try:
            retry_at = float(row.get("retry_at") or 0)
        except (TypeError, ValueError):
            retry_at = 0
        try:
            attempts = max(int(row.get("attempts") or 0), 0)
        except (TypeError, ValueError):
            attempts = 0
        max_attempts = max(max_attempts, attempts)
        if retry_at > now:
            waiting += 1
        else:
            due += 1
    return {
        "retry_total": len(retry),
        "retry_wait": waiting,
        "retry_due": due,
        "retry_max_attempts": max_attempts,
    }


def _log_yield_once(plugin: Any, *, path: str, reason: str, phases: Dict[str, Any]) -> None:
    signature = (
        str(path or ""),
        str(reason or ""),
        tuple(sorted((str(key), int(value or 0)) for key, value in phases.items())),
    )
    seen = getattr(plugin, "_v3615_yield_log_seen", None)
    if not isinstance(seen, set):
        seen = set()
        setattr(plugin, "_v3615_yield_log_seen", seen)
    if signature in seen:
        return
    if len(seen) >= _LOG_CACHE_LIMIT:
        seen.clear()
    seen.add(signature)
    logger.info(
        "【光鸭云盘助手】【v3.6.15】【pending公平性】优先复查仍在等待，当前无活动执行；"
        "本 tick 继续 known/discovery: path=%s reason=%s phases=%s",
        path,
        reason,
        phases,
    )


def install_pending_fairness_v3615() -> None:
    """幂等安装 pending 公平调度与 retry 时间语义统计。"""
    monitor_cls = GuangYaOrganizerMonitorV366Mixin
    if getattr(monitor_cls, _PATCH_FLAG, False):
        return

    previous_monitor_scan = monitor_cls.run_organize_monitor_scan
    previous_try_due = GuangYaOrganizerPendingRevisitV361Mixin._v361_try_due_resource
    previous_stats = OrganizerStateStore.stats

    def try_due_resource(plugin: Any):
        if bool(getattr(plugin, _SKIP_FLAG, False)):
            return None
        return previous_try_due(plugin)

    def monitor_scan(plugin: Any, manual: bool = False) -> Dict[str, Any]:
        first = previous_monitor_scan(plugin, manual=manual)
        if manual or not _priority_can_yield(first):
            return first

        priority_data, priority_result = _priority_snapshot(first)
        priority_path = str(priority_data.get("path") or "")
        priority_reason = str(priority_result.get("reason") or "")
        priority_phases = dict(priority_result.get("phases") or {})

        # 第一次已经完成本 tick 的“优先复查”。第二次只跳过 pending 入口，其余全部重新进入
        # 既有 v3.6.9 wrapper，保留 owner、known scan、网络保护、baseline 与 continuous discovery。
        setattr(plugin, _SKIP_FLAG, True)
        try:
            progressed = previous_monitor_scan(plugin, manual=False)
        finally:
            setattr(plugin, _SKIP_FLAG, False)

        if not isinstance(progressed, dict):
            return first
        data = progressed.setdefault("data", {})
        if not isinstance(data, dict):
            data = {}
            progressed["data"] = data
        data.update(
            {
                "priority_revisit_yielded": True,
                "priority_revisit_path": priority_path,
                "priority_revisit_reason": priority_reason,
                "priority_revisit_phases": priority_phases,
            }
        )
        try:
            plugin._save_monitor_status(
                priority_revisit_yielded=True,
                priority_revisit_yielded_at=time.time(),
                priority_revisit_yield_path=priority_path,
                priority_revisit_yield_reason=priority_reason,
                priority_revisit_yield_phases=priority_phases,
            )
        except Exception:
            pass
        _log_yield_once(
            plugin,
            path=priority_path,
            reason=priority_reason,
            phases=priority_phases,
        )
        return progressed

    def stats(store: OrganizerStateStore) -> Dict[str, int]:
        base = dict(previous_stats(store) or {})
        try:
            counts = _retry_schedule_counts(store.load(), now=time.time())
        except Exception:
            return base
        base.update(counts)
        return base

    GuangYaOrganizerPendingRevisitV361Mixin._v361_try_due_resource = try_due_resource
    monitor_cls.run_organize_monitor_scan = monitor_scan
    OrganizerStateStore.stats = stats
    setattr(monitor_cls, _PATCH_FLAG, True)
    logger.info(
        "【光鸭云盘助手】【v3.6.15】pending 公平调度已启用：等待态复查不再饿死 known/discovery；"
        "inflight/真实提交仍保持单资源阻断；retry 统计拆分 wait/due/total"
    )


__all__ = [
    "install_pending_fairness_v3615",
    "_priority_can_yield",
    "_retry_schedule_counts",
]
