"""v3.6.20：MoviePilot 全局终态事件的存储/监控路径隔离。

MoviePilot 的 TransferComplete / TransferFailed 是全局事件，插件实例会收到其它存储的
整理终态。底层 organizer_recognition 原本已经只处理光鸭 + 当前监控路径，但 v3.5.1 的
MP history wrapper 与 v3.6.8 的 pending 终态收口位于它外层：即使底层因其它存储 return，
外层仍会继续写光鸭历史计数、日志并触发 pending 自愈。

本层只修事件归属边界：
- fileitem.storage 必须属于光鸭存储；
- fileitem.path 必须位于当前自动整理监控路径；
- 缺少 fileitem / storage / path 归属证据时 fail-closed，不写任何光鸭终态状态；
- 同时包住 v3.5.1 history wrapper 与 v3.6.8 pending wrapper，避免任何外层副作用；
- 不改变 MoviePilot 整理行为，也不读取/移动/删除其它存储文件。
"""

from __future__ import annotations

from typing import Any

from app.sdk.logging import logger

from .organizer_pending_revisit_v361 import GuangYaOrganizerPendingRevisitV361Mixin
from .organizer_recognition import GuangYaOrganizerMixin as GuangYaRecognitionMixin


_INSTALLED = False


def _event_fileitem_v3620(plugin: Any, event: Any) -> Any:
    """只从 MoviePilot 终态事件中投影 fileitem，不自行猜测来源。"""
    payload_getter = getattr(plugin, "_event_payload", None)
    if callable(payload_getter):
        try:
            payload = payload_getter(event)
        except Exception:
            return None
    else:
        payload = getattr(event, "event_data", None)
    if not isinstance(payload, dict):
        return None
    return payload.get("fileitem")


def terminal_event_owned_v3620(plugin: Any, event: Any) -> bool:
    """只有“光鸭存储 + 当前监控路径”同时成立才允许进入插件终态链。"""
    fileitem = _event_fileitem_v3620(plugin, event)
    if not fileitem:
        return False

    own_matcher = getattr(plugin, "_is_own_transfer_fileitem", None)
    if not callable(own_matcher):
        return False
    try:
        if not bool(own_matcher(fileitem)):
            return False
    except Exception:
        return False

    source_path = str(getattr(fileitem, "path", "") or "")
    if not source_path:
        return False
    monitored_matcher = getattr(plugin, "_is_monitored_path", None)
    if not callable(monitored_matcher):
        return False
    try:
        return bool(monitored_matcher(source_path))
    except Exception:
        return False


def install_terminal_event_scope_v3620() -> None:
    """在最终历史/pending wrapper 外再加一层归属门禁；幂等安装。"""
    global _INSTALLED
    if _INSTALLED:
        return

    recognition_record = GuangYaRecognitionMixin._record_terminal_transfer
    pending_record = GuangYaOrganizerPendingRevisitV361Mixin._record_terminal_transfer

    def scoped_recognition_record(self: Any, event: Any, success: bool) -> Any:
        if not terminal_event_owned_v3620(self, event):
            return None
        return recognition_record(self, event, success)

    def scoped_pending_record(self: Any, event: Any, success: bool) -> Any:
        # 这一层必须先于 v3.6.8 的 super + prune：否则其它存储成功事件虽然不改 completed，
        # 仍会触发光鸭 pending 自愈和状态 I/O。
        if not terminal_event_owned_v3620(self, event):
            return None
        return pending_record(self, event, success)

    GuangYaRecognitionMixin._record_terminal_transfer = scoped_recognition_record
    GuangYaOrganizerPendingRevisitV361Mixin._record_terminal_transfer = scoped_pending_record
    _INSTALLED = True
    logger.info(
        "【光鸭云盘助手】【v3.6.20】【终态隔离】已启用：仅处理光鸭存储且位于当前监控路径的 MoviePilot 终态事件"
    )


__all__ = [
    "install_terminal_event_scope_v3620",
    "terminal_event_owned_v3620",
]
