"""v3.8.0 全量巡检、资源消费与日志策略收口。

该模块在 watch pipeline 安装完成后加载，收口以下产品语义：
- 用户手动停止全量后，一个自动全量周期内不自动复活；
- 自动补漏全量正在运行时，用户点击“强制全量”会废止旧会话并从根目录重新强校验；
- Worker 完成后的历史 ``run_organize_monitor_scan`` refill 也必须回到 v3.8.0 resource queue，
  禁止绕过持久队列重新走旧 known/discovery 直调度；
- 单轮可以快速收口一批已完成/空目录，但最多只提交一个真实资源给私有 Worker；
- 增量无变化轮次降为 DEBUG，只有真实变化、待整理队列变化、执行与错误进入 INFO/WARNING；
- 最近发生变化的资源目录维持 14 天 hot watch，覆盖常见周更周期；之后仍有冷目录轮转与全量兜底。

函数替换的是 ``organizer_watch_pipeline_v380`` 模块级策略函数；已安装 tick/API 闭包运行时
按模块全局名称查找，因此无需重装 monitor MRO，也不会再次引入热更新导入时序问题。
"""
from __future__ import annotations

import time
from typing import Any, Dict

from app.sdk.logging import logger

from . import organizer_watch_pipeline_v380 as _watch
from .organizer_monitor_v366 import GuangYaOrganizerMonitorV366Mixin as _MonitorMixin


_INSTALL_FLAG = "_v380_watch_policy_installed"
_HOT_WATCH_SECONDS = 14 * 24 * 3600.0
_TERMINAL_COMPACT_BUDGET = 32


def install_watch_policy_v380() -> None:
    if bool(getattr(_MonitorMixin, _INSTALL_FLAG, False)):
        return

    original_start = _watch._start_full
    original_stop = _watch._stop_full
    original_status = _MonitorMixin.api_organize_monitor_status
    original_log = _watch._log
    original_dispatch = _watch._dispatch_one

    def filtered_log(scan_id: str, stage: str, message: str, *, level: str = "info") -> None:
        """日常空转和批量终态收口不刷 INFO；真实活动保持可追踪。"""
        effective = level
        if level == "info":
            if stage == "1/4 发现":
                effective = "debug"
            elif stage == "2/4 变更" and "变化=0" in message and "错误=0" in message:
                effective = "debug"
            elif stage == "3/4 待整理" and "新增/刷新=0" in message:
                effective = "debug"
            elif stage == "4/4 完成":
                effective = "debug"
            elif stage == "收口":
                effective = "debug"
        return original_log(scan_id, stage, message, level=effective)

    def full_due(plugin: Any) -> bool:
        raw = plugin.get_data(_watch._FULL_LAST_KEY) or {}
        if not isinstance(raw, dict) or plugin._v360_norm(raw.get("monitor_path")) != _watch._root(plugin):
            return True
        now = time.time()
        if float(raw.get("suppressed_until") or 0) > now:
            return False
        completed_at = float(raw.get("completed_at") or 0)
        return completed_at <= 0 or now - completed_at >= _watch._FULL_SCAN_INTERVAL

    def start_full(plugin: Any, *, trigger: str, force_verify: bool) -> Dict[str, Any]:
        existing = _watch._full_load(plugin)
        if existing.get("active") and force_verify and not existing.get("force_verify"):
            # 自动补漏可能已经扫过前半棵树。仅把当前 flag 改为 True 会漏掉已扫部分，
            # 因此手动强校验必须废止旧会话并从根目录重新开始一个新的 FULL scan_id。
            old_id = str(existing.get("scan_id") or "FULL")
            existing.update(
                {
                    "active": False,
                    "superseded_at": time.time(),
                    "superseded_by": "manual-force-restart",
                }
            )
            _watch._full_save(plugin, existing)
            filtered_log(
                old_id,
                "全量重启",
                "用户要求强制全量：已结束自动补漏会话，将从监控根重新校验全部资源",
            )
            return original_start(plugin, trigger="manual", force_verify=True)
        return original_start(plugin, trigger=trigger, force_verify=force_verify)

    def stop_full(plugin: Any, *, trigger: str) -> Dict[str, Any]:
        result = original_stop(plugin, trigger=trigger)
        now = time.time()
        previous = plugin.get_data(_watch._FULL_LAST_KEY) or {}
        if not isinstance(previous, dict):
            previous = {}
        plugin.save_data(
            _watch._FULL_LAST_KEY,
            {
                "monitor_path": _watch._root(plugin),
                "completed_at": float(previous.get("completed_at") or 0),
                "scan_id": str(previous.get("scan_id") or ""),
                "suppressed_until": now + _watch._FULL_SCAN_INTERVAL,
                "stopped_at": now,
            },
        )
        try:
            plugin._save_monitor_status(
                full_scan_active=False,
                full_scan_suppressed_until=now + _watch._FULL_SCAN_INTERVAL,
            )
        except Exception:
            pass
        return result

    def dispatch_compact(plugin: Any, *, trigger: str) -> Dict[str, Any]:
        """快速跳过终态目录，但每次调用至多让一个真实资源进入 Worker。"""
        last: Dict[str, Any] = {"scheduled": False, "reason": "queue_empty", "queue_depth": 0}
        compacted = 0
        for _ in range(_TERMINAL_COMPACT_BUDGET):
            before = len(_watch._load_rows(plugin, _watch._RESOURCE_KEY))
            result = dict(original_dispatch(plugin, trigger=trigger) or {})
            last = result
            after = len(_watch._load_rows(plugin, _watch._RESOURCE_KEY))
            if result.get("scheduled"):
                break
            reason = str(result.get("reason") or "")
            if reason in {"queue_empty", "queue_wait", "worker_busy", "handoff", "read_error"}:
                break
            if after < before:
                compacted += before - after
                continue
            break
        if compacted:
            last["terminal_compacted"] = compacted
            last["queue_depth"] = len(_watch._load_rows(plugin, _watch._RESOURCE_KEY))
        return last

    def run_scan_bridge(plugin: Any, manual: bool = False) -> Dict[str, Any]:
        """兼容旧 refill 调用，但最终只允许经过 watch/resource queue。"""
        if manual:
            return start_full(plugin, trigger="manual", force_verify=True)
        if not getattr(plugin, "_organize_monitor_enabled", False):
            return {"success": True, "message": "自动整理监控未启用", "data": {"disabled": True}}
        if not getattr(plugin, "_enabled", False) or not getattr(plugin, "_guangya_api", None):
            return {"success": False, "message": "光鸭云盘未启用或未登录"}
        if _watch._root(plugin) == "/":
            return {"success": False, "message": "请先选择具体监控目录，禁止直接监控根目录"}

        dispatch = dispatch_compact(plugin, trigger="refill")
        if str(dispatch.get("reason") or "") == "queue_empty":
            # Worker 刚完成而队列恰好为空时，做一次有界只读观察再尝试消费；
            # 发现器本身没有 Worker busy gate，因此这个兼容入口也不会重新耦合发现与执行。
            observed = _watch._watch_pulse(plugin, trigger="refill", budget=_watch._WATCH_BUDGET)
            dispatch = dispatch_compact(plugin, trigger="refill-after-watch")
        else:
            observed = None
        return {
            "success": True,
            "message": "v3.8.0 持久待整理队列补充完成",
            "data": {
                "monitor_pipeline": "watch-pipeline-v3.8.0",
                "dispatch": dispatch,
                "observed": dict((observed or {}).get("data") or {}) if isinstance(observed, dict) else {},
            },
        }

    def status(plugin: Any) -> Dict[str, Any]:
        response = original_status(plugin)
        if not isinstance(response, dict) or not response.get("success"):
            return response
        row = response.setdefault("data", {}).setdefault("status", {})
        last = plugin.get_data(_watch._FULL_LAST_KEY) or {}
        if not isinstance(last, dict):
            last = {}
        row.update(
            {
                "full_scan_last_completed_at": float(last.get("completed_at") or 0),
                "full_scan_suppressed_until": float(last.get("suppressed_until") or 0),
                "monitor_log_policy": "idle-debug/activity-info/error-warning",
                "watch_hot_window_hours": int(_HOT_WATCH_SECONDS // 3600),
                "terminal_compact_budget": _TERMINAL_COMPACT_BUDGET,
                "refill_path": "resource-queue-only",
            }
        )
        return response

    # _scan_directory 在运行时读取模块全局常量，因此策略层可以安全收口 hot window。
    _watch._HOT_SECONDS = _HOT_WATCH_SECONDS
    _watch._log = filtered_log
    _watch._full_due = full_due
    _watch._start_full = start_full
    _watch._stop_full = stop_full
    _watch._dispatch_one = dispatch_compact
    _MonitorMixin.run_organize_monitor_scan = run_scan_bridge
    _MonitorMixin.api_organize_monitor_status = status
    setattr(_MonitorMixin, _INSTALL_FLAG, True)
    logger.info(
        "【光鸭云盘助手】【监控】v3.8.0 策略已收口：单一 resource queue 执行路径；Worker 完成走持久队列 refill；14 天 hot watch；空转日志降 DEBUG"
    )


__all__ = ["install_watch_policy_v380"]