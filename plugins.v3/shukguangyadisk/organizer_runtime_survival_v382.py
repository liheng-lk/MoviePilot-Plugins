"""v3.8.2 runtime survival guard.

监控属于后台附加能力，任何远端目录/API/状态异常都不能冒泡到 MoviePilot 插件生命周期。
连续失败只暂停监控调度，插件本身、存储/API 和页面必须继续可用。
"""
from __future__ import annotations

import time
import traceback
from typing import Any, Dict

from app.sdk.logging import logger

from .organizer_monitor_v366 import GuangYaOrganizerMonitorV366Mixin as _MonitorMixin


_INSTALL_FLAG = "_v382_runtime_survival_installed"
_BOOT_GRACE_SECONDS = 180.0
_FAILURE_WINDOW_SECONDS = 600.0
_FAILURE_LIMIT = 3
_COOLDOWN_SECONDS = 300.0


def install_runtime_survival_v382() -> None:
    if bool(getattr(_MonitorMixin, _INSTALL_FLAG, False)):
        return

    original_tick = _MonitorMixin.organize_monitor_tick
    original_status = _MonitorMixin.api_organize_monitor_status

    def _state(self: Any) -> Dict[str, Any]:
        state = getattr(self, "_v382_survival_state", None)
        if not isinstance(state, dict):
            now = time.time()
            state = {
                "boot_at": now,
                "window_started_at": now,
                "failures": 0,
                "last_error_at": 0.0,
                "last_error": "",
                "cooldown_until": 0.0,
                "last_success_at": 0.0,
            }
            self._v382_survival_state = state
        return state

    def guarded_tick(self: Any) -> None:
        state = _state(self)
        now = time.time()

        # 插件刚安装/热更新后先给宿主、登录态和存储适配器一个稳定窗口。
        # 期间允许插件正常加载、页面/API 正常使用，但不自动触发后台全量扫描。
        if now < float(state.get("cooldown_until") or 0):
            return

        try:
            # 启动保护期内仍允许原 tick 的轻量条件判断，但暂时抑制自动 full-due。
            # v380 full_due 由模块级函数动态解析，因此短暂设置实例标记供策略读取。
            self._v382_boot_grace_active = now - float(state.get("boot_at") or now) < _BOOT_GRACE_SECONDS
            original_tick(self)
            state["last_success_at"] = now
            # 成功后清除连续失败窗口。
            if int(state.get("failures") or 0) > 0:
                state["failures"] = 0
                state["window_started_at"] = now
                state["last_error"] = ""
        except Exception as err:  # noqa: BLE001 - survival boundary intentionally catches all
            window_started = float(state.get("window_started_at") or 0)
            if not window_started or now - window_started > _FAILURE_WINDOW_SECONDS:
                state["window_started_at"] = now
                state["failures"] = 0
            state["failures"] = int(state.get("failures") or 0) + 1
            state["last_error_at"] = now
            state["last_error"] = f"{type(err).__name__}: {err}"
            logger.error(
                "【光鸭云盘助手】【监控存活保护】后台监控异常已隔离，不影响插件加载：%s",
                state["last_error"],
            )
            logger.debug(
                "【光鸭云盘助手】【监控存活保护】异常堆栈：%s",
                traceback.format_exc(),
            )
            if int(state.get("failures") or 0) >= _FAILURE_LIMIT:
                state["cooldown_until"] = now + _COOLDOWN_SECONDS
                logger.warning(
                    "【光鸭云盘助手】【监控存活保护】10 分钟内连续失败 %s 次，"
                    "仅暂停后台监控 %ss；插件本身保持可用",
                    state["failures"],
                    int(_COOLDOWN_SECONDS),
                )
            # 关键：绝不向 APScheduler/MoviePilot 插件管理器重新抛出。
            return
        finally:
            self._v382_boot_grace_active = False

    def status(self: Any):
        try:
            response = original_status(self)
        except Exception as err:  # 状态页也不能因为监控状态损坏而拖垮插件页面
            logger.error("【光鸭云盘助手】【监控存活保护】状态读取异常已隔离: %s", err)
            response = {
                "success": True,
                "message": "监控状态暂不可用，插件本身仍正常",
                "data": {"status": {}, "history": []},
            }
        if not isinstance(response, dict):
            response = {"success": True, "data": {"status": {}, "history": []}}
        row = response.setdefault("data", {}).setdefault("status", {})
        state = _state(self)
        row.update(
            {
                "runtime_survival_guard": "v3.8.2",
                "runtime_survival_failures": int(state.get("failures") or 0),
                "runtime_survival_last_error": str(state.get("last_error") or ""),
                "runtime_survival_last_error_at": float(state.get("last_error_at") or 0),
                "runtime_survival_cooldown_until": float(state.get("cooldown_until") or 0),
                "runtime_survival_last_success_at": float(state.get("last_success_at") or 0),
                "runtime_survival_boot_grace": bool(
                    time.time() - float(state.get("boot_at") or time.time()) < _BOOT_GRACE_SECONDS
                ),
            }
        )
        return response

    _MonitorMixin.organize_monitor_tick = guarded_tick
    _MonitorMixin.api_organize_monitor_status = status
    setattr(_MonitorMixin, _INSTALL_FLAG, True)
    logger.info("【光鸭云盘助手】【监控存活保护】v3.8.2 已启用：监控异常与插件生命周期隔离")


__all__ = ["install_runtime_survival_v382"]
