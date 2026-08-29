"""光鸭自动整理与 MoviePilot 运行时事件桥。

事件注册属于运行时基础设施，不应和媒体识别规则混在一起。本模块只维护当前插件
实例引用，并把 MoviePilot 的存储选择、重命名链式事件和整理终态事件转发给该实例。

不同 MoviePilot V3 小版本的事件枚举并不完全一致。基础视频整理事件是必需能力，
字幕/音频/重命名事件属于可选增强；缺少可选枚举时必须跳过注册，而不能让插件在导入阶段
直接失败，从而出现“插件安装不了”。
"""

from __future__ import annotations

import weakref
from typing import Any, Callable, Optional

try:
    from app.runtime.events import Event, eventmanager
except ImportError:  # 兼容仍暴露旧事件模块的 V3 小版本
    from app.core.event import Event, eventmanager

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


def _register_optional(event_type: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """仅在宿主存在对应事件枚举时注册，避免导入期 AttributeError。"""
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if event_type is None:
            return func
        return eventmanager.register(event_type)(func)

    return decorator


@_register_optional(getattr(ChainEventType, "StorageOperSelection", None))
def _guangya_storage_selection_bridge(event: Event) -> None:
    _dispatch("storage_oper_selection", event)


@_register_optional(getattr(ChainEventType, "TransferRename", None))
def _guangya_transfer_rename_bridge(event: Event) -> None:
    """只在 v3.5.3 当前线程存在版本消歧上下文时才会真正改写名称。"""
    _dispatch("organizer_transfer_rename", event)


@_register_optional(getattr(EventType, "TransferComplete", None))
def _guangya_transfer_complete_bridge(event: Event) -> None:
    _dispatch("organizer_transfer_complete", event)


@_register_optional(getattr(EventType, "TransferFailed", None))
def _guangya_transfer_failed_bridge(event: Event) -> None:
    _dispatch("organizer_transfer_failed", event)


@_register_optional(getattr(EventType, "SubtitleTransferComplete", None))
def _guangya_subtitle_transfer_complete_bridge(event: Event) -> None:
    _dispatch("organizer_transfer_complete", event)


@_register_optional(getattr(EventType, "SubtitleTransferFailed", None))
def _guangya_subtitle_transfer_failed_bridge(event: Event) -> None:
    _dispatch("organizer_transfer_failed", event)


@_register_optional(getattr(EventType, "AudioTransferComplete", None))
def _guangya_audio_transfer_complete_bridge(event: Event) -> None:
    _dispatch("organizer_transfer_complete", event)


@_register_optional(getattr(EventType, "AudioTransferFailed", None))
def _guangya_audio_transfer_failed_bridge(event: Event) -> None:
    _dispatch("organizer_transfer_failed", event)


__all__ = [
    "active_organizer_plugin",
    "bind_organizer_runtime",
    "organizer_runtime_bound_to",
]
