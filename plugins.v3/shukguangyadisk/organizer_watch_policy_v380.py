"""v3.8.0 全量巡检策略收口。

该模块在 watch pipeline 安装完成后加载，仅收口三个产品语义：
- 用户手动停止全量后，一个自动全量周期内不自动复活；
- 自动补漏全量正在运行时，用户点击“强制全量”会把当前会话升级为 force_verify；
- 状态页明确显示 v3.8.0 最近全量完成时间和自动抑制截止时间。

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
            existing["force_verify"] = True
            existing["trigger"] = "manual"
            existing["upgraded_to_force_at"] = time.time()
            _watch._full_save(plugin, existing)
            _watch._log(
                str(existing.get("scan_id") or "FULL"),
                "全量升级",
                "用户手动触发：当前自动补漏会话已升级为强制全资源校验",
            )
            return _watch._full_step(plugin, trigger="manual-force-upgrade")
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
            }
        )
        return response

    _watch._full_due = full_due
    _watch._start_full = start_full
    _watch._stop_full = stop_full
    _MonitorMixin.api_organize_monitor_status = status
    setattr(_MonitorMixin, _INSTALL_FLAG, True)
    logger.info("【光鸭云盘助手】【监控】v3.8.0 全量策略已收口：停止抑制自动复活，手动可升级强校验")


__all__ = ["install_watch_policy_v380"]