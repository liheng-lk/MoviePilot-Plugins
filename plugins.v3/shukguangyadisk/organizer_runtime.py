"""光鸭自动整理与 MoviePilot 运行时事件桥。

事件注册属于运行时基础设施，不应和媒体识别规则混在一起。本模块只维护当前插件
实例引用，并把 MoviePilot 的存储选择和整理终态事件转发给该实例。
"""

from __future__ import annotations

import weakref
from typing import Any, Optional

from app.runtime.events import Event, eventmanager
from app.schemas.types import ChainEventType, EventType


_ACTIVE_PLUGIN_REF: Optional[weakref.ReferenceType[Any]] = None


def bind_organizer_runtime(plugin: Any) -> None:
    """绑定当前真实插件实例；热重载后新实例会原子替换旧弱引用。"""
    global _ACTIVE_PLUGIN_REF
    _ACTIVE_PLUGIN_REF = weakref.ref(plugin)


def active_organizer_plugin() -> Optional[Any]:
    ref = _ACTIVE_PLUGIN_REF
    plugin = ref() if ref else None
    if not plugin or not getattr(plugin, "_enabled", False):
        return None
    return plugin


def organizer_runtime_bound_to(plugin: Any) -> bool:
    return active_organizer_plugin() is plugin


def _dispatch(method_name: str, event: Event) -> None:
    plugin = active_organizer_plugin()
    if not plugin:
        return
    handler = getattr(plugin, method_name, None)
    if callable(handler):
        handler(event)


@eventmanager.register(ChainEventType.StorageOperSelection)
def _guangya_storage_selection_bridge(event: Event) -> None:
    _dispatch("storage_oper_selection", event)


@eventmanager.register(EventType.TransferComplete)
def _guangya_transfer_complete_bridge(event: Event) -> None:
    _dispatch("organizer_transfer_complete", event)


@eventmanager.register(EventType.TransferFailed)
def _guangya_transfer_failed_bridge(event: Event) -> None:
    _dispatch("organizer_transfer_failed", event)


@eventmanager.register(EventType.SubtitleTransferComplete)
def _guangya_subtitle_transfer_complete_bridge(event: Event) -> None:
    _dispatch("organizer_transfer_complete", event)


@eventmanager.register(EventType.SubtitleTransferFailed)
def _guangya_subtitle_transfer_failed_bridge(event: Event) -> None:
    _dispatch("organizer_transfer_failed", event)


@eventmanager.register(EventType.AudioTransferComplete)
def _guangya_audio_transfer_complete_bridge(event: Event) -> None:
    _dispatch("organizer_transfer_complete", event)


@eventmanager.register(EventType.AudioTransferFailed)
def _guangya_audio_transfer_failed_bridge(event: Event) -> None:
    _dispatch("organizer_transfer_failed", event)


__all__ = [
    "active_organizer_plugin",
    "bind_organizer_runtime",
    "organizer_runtime_bound_to",
]
