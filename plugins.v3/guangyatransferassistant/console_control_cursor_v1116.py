"""把真实控制台控制层叠加到严格频道游标层之上。

ConsoleControl 自身基于频道事件 guard；这里通过 C3 MRO 把 ChannelCursorEvent 插到
ConsoleControl 的 super() 下一层，确保控制台修复不会绕开刷新前 message_id 游标判新。
"""

from __future__ import annotations

from typing import List

from .channel_cursor_event_v1115 import GuangYaChannelCursorEventV1115Mixin
from .console_control_v1116 import GuangYaConsoleControlV1116Mixin


class GuangYaConsoleControlCursorV1116Mixin(
    GuangYaConsoleControlV1116Mixin,
    GuangYaChannelCursorEventV1115Mixin,
):
    """真实控制台 + 严格频道游标最终组合层。"""

    build_id = "20260902-r27"

    def _run_reliability_route_batch(self, batch: List[int], trigger: str) -> None:
        if "控制台处理缺集" in str(trigger or ""):
            return self._run_v1115_mode_batch(
                batch,
                trigger,
                "subscription_prime",
                force=True,
            )
        return super()._run_reliability_route_batch(batch, trigger)


__all__ = ["GuangYaConsoleControlCursorV1116Mixin"]
