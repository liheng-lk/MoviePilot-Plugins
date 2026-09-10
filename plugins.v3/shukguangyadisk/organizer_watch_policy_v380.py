"""v3.8.0 全量巡检与日志策略收口。

该模块在 watch pipeline 安装完成后加载，收口以下产品语义：
- 用户手动停止全量后，一个自动全量周期内不自动复活；
- 自动补漏全量正在运行时，用户点击“强制全量”会废止旧会话并从根目录重新强校验，
  保证已经扫过的前半段也不会遗漏；
- 增量无变化轮次降为 DEBUG，只有真实变化、待整理队列变化、执行与错误进入 INFO/WARNING；
- 状态页明确显示最近全量完成时间和自动抑制截止时间。

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


def install_watch_policy_v380() -> None:
    if bool(getattr(_MonitorMixin, _INSTALL_FLAG, False)):
        return

    original_start = _watch._start_full
    original_stop = _watch._stop_full
    original_status = _MonitorMixin.api_organize_monitor_status
    original_log = _watch._log

    def filtered_log(scan_id: str, stage: str, message: str, *, level: str = "info") -> None:
        """日常空转不刷 INFO；有变化、执行、全量和错误仍保持清晰可追踪。"""
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
            }
        )
        return response

    _watch._log = filtered_log
    _watch._full_due = full_due
    _watch._start_full = start_full
    _watch._stop_full = stop_full
    _MonitorMixin.api_organize_monitor_status = status
    setattr(_MonitorMixin, _INSTALL_FLAG, True)
    logger.info(
        "【光鸭云盘助手】【监控】v3.8.0 策略已收口：停止抑制自动复活；手动强校验从根重启；空转日志降为 DEBUG"
    )


__all__ = ["install_watch_policy_v380"]