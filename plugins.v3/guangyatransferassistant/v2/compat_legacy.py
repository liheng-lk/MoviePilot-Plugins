"""必要时调用尚未搬迁的旧协议实现。"""

from __future__ import annotations

from typing import Any, Callable, Optional


def call_legacy(plugin: Any, method: str, *args: Any, **kwargs: Any) -> Any:
    target: Optional[Callable[..., Any]] = getattr(plugin, method, None)
    if not callable(target):
        raise AttributeError(method)
    return target(*args, **kwargs)
