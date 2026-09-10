"""v1.10.15 频道事件外部搜索边界。

频道新增消息触发的批次只允许消费频道消息本身携带的光鸭分享、Magnet、ED2K。
如果频道 ResourceGroup 没覆盖当前缺集，不在频道线程里同步请求观影/Provider；
改为异步入队一次独立外部补搜（GYING 链），并按 sid 去重。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .channel_event_v1115 import GuangYaChannelEventV1115Mixin


class GuangYaChannelEventGuardV1115Mixin(GuangYaChannelEventV1115Mixin):
    """防止频道事件同步拉起 Provider；本地缺口改为异步外部补搜。"""

    build_id = "20260911-r92"

    def _dispatch_provider_candidate(
        self,
        subscribe: Any,
        uncovered: set[int],
    ) -> Optional[Dict[str, Any]]:
        if self._route_source_mode_value_v1115() == "channel_event":
            enqueue = getattr(self, "_enqueue_external_recall_v208", None)
            if callable(enqueue):
                enqueue(subscribe, reason="local_candidates_exhausted")
            else:
                self._plugin_log(
                    "INFO",
                    "【光鸭转存助手】【频道事件】频道资源未完全覆盖当前缺集；本轮不主动调用观影/Provider，等待独立轮询",
                )
            return None
        return super()._dispatch_provider_candidate(subscribe, uncovered)


__all__ = ["GuangYaChannelEventGuardV1115Mixin"]
