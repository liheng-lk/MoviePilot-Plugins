"""协议适配占位：2.0 仍委托旧 mixin 执行真实网络协议。"""

from __future__ import annotations

from typing import Any


class GyingAdapter:
    def __init__(self, plugin: Any):
        self.plugin = plugin

    def enabled(self) -> bool:
        return bool(getattr(self.plugin, "_viewing_enabled", True))


class XunleiAdapter:
    def __init__(self, plugin: Any):
        self.plugin = plugin

    def enabled(self) -> bool:
        return bool(getattr(self.plugin, "_xunlei_flash_enabled", True))


class GuangYaStorageAdapter:
    def __init__(self, plugin: Any):
        self.plugin = plugin

    def runtime(self):
        getter = getattr(self.plugin, "_get_guangya_runtime", None)
        if callable(getter):
            return getter()
        return None, None


class MoviePilotSubscribeAdapter:
    def __init__(self, plugin: Any):
        self.plugin = plugin

    def selected_ids(self) -> list[int]:
        return list(getattr(self.plugin, "_selected_subscriptions", []) or [])
