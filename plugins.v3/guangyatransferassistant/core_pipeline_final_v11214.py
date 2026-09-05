"""v1.12.14 核心链最终权威缺口实现。

Core 候选层只表达统一规则；本层把它绑定到 v1.12.13 已验证的 MoviePilot 缺集 ABI：
``_sync_media_library_progress`` 返回 library existing/missing，
``_base_missing_without_due_scope_v11213`` 返回成功事实 + 订阅 note 的完整逻辑缺口。

当前正在 resolve/create 的外部 source 必须从 active claims 中排除，否则它会用自己的
``target_episodes`` 把自己从 allowed 集合中扣空。
"""
from __future__ import annotations

from typing import Any, Set

from .core_pipeline_v11214 import (
    GuangYaCorePipelineV11214Mixin,
    _positive_episode_set_v11214,
)


class GuangYaCorePipelineFinalV11214Mixin(GuangYaCorePipelineV11214Mixin):
    """把所有 TV 最终写盘来源收紧到同一份 MoviePilot 权威缺口。"""

    plugin_version = "1.12.14"
    build_id = "20260905-r60"

    def _authoritative_missing_v11214(self, subscribe: Any, *, current_source_id: str = "") -> Set[int]:
        if self._is_movie_subscription(subscribe):
            return set()
        try:
            sync = dict(self._sync_media_library_progress(subscribe) or {})
        except Exception as err:
            sync = {"success": False, "missing": [], "message": str(err)[:260]}
        if not bool(sync.get("success")):
            raise RuntimeError(
                "MoviePilot 媒体库缺集事实读取失败，最终写盘 fail closed："
                + str(sync.get("message") or "unknown")[:260]
            )

        library_missing = _positive_episode_set_v11214(sync.get("missing") or [])
        try:
            logical_missing = set(self._base_missing_without_due_scope_v11213(subscribe) or set())
        except Exception:
            logical_missing = _positive_episode_set_v11214(self._subscription_missing_episodes(subscribe) or [])
        allowed = library_missing.intersection(_positive_episode_set_v11214(logical_missing))

        try:
            reservations = dict(self._pending_reservations(subscribe) or {})
            allowed -= _positive_episode_set_v11214(reservations.get("episodes") or [])
        except Exception:
            pass
        sid = int(getattr(subscribe, "id", 0) or 0)
        allowed -= self._other_source_claims_v11214(sid, current_source_id=current_source_id)
        return allowed


__all__ = ["GuangYaCorePipelineFinalV11214Mixin"]
