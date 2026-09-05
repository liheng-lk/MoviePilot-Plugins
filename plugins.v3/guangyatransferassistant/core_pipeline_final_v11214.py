"""v1.12.14 核心链最终权威缺口实现。

Core 候选层只表达统一规则；本层把它绑定到 v1.12.13 已验证的 MoviePilot 缺集 ABI：
``_sync_media_library_progress`` 返回 library existing/missing，
``_base_missing_without_due_scope_v11213`` 返回成功事实 + 订阅 note 的完整逻辑缺口。

当前正在 resolve/create 的外部 source 必须从 active claims 中排除，否则它会用自己的
``target_episodes`` 把自己从 allowed 集合中扣空。

同时补足直接光鸭分享的 rootless 文件身份：只有文件名在明确 Episode 标记前存在可信
标题前缀时，才把该前缀提升为 actual primary evidence。这样 ``Other.Show.S01E11.mkv``
会作为真实冲突被拒绝，而 ``S01E11.mkv`` 仍保持“信息不足但无冲突”的保守语义；
``Show.Name.S01E11-GROUP.mkv`` 只取 Episode 前的 ``Show.Name``，不会把发布组误当标题。
"""
from __future__ import annotations

import re
from typing import Any, List, Sequence, Set

from .core_pipeline_v11214 import (
    GuangYaCorePipelineV11214Mixin,
    _positive_episode_set_v11214,
)
from .media_identity_v1111 import title_key_v1111


_ACTUAL_EP_MARKER_V11214 = re.compile(
    r"(?i)(?:\bS\d{1,2}[ ._\-]*E\d{1,4}\b|\b(?:E|EP|Episode)[ ._\-]*0*\d{1,4}\b|第\s*\d{1,4}\s*(?:集|话))"
)
_GENERIC_ACTUAL_TITLE_KEYS_V11214 = {
    "file", "files", "video", "videos", "tv", "season", "resource", "share",
    "资源", "文件", "视频", "电视剧", "剧集", "分享", "全集", "全季",
}


class GuangYaCorePipelineFinalV11214Mixin(GuangYaCorePipelineV11214Mixin):
    """把所有 TV 最终写盘来源收紧到同一份 MoviePilot 权威缺口。"""

    plugin_version = "1.12.14"
    build_id = "20260905-r60"

    @staticmethod
    def _direct_share_primary_roots_v11214(paths: Sequence[str], expected_year: Any = None) -> List[str]:
        """在单文件无父目录时，仅抽取明确 Episode 标记之前的实际标题前缀。"""
        rows = list(GuangYaCorePipelineV11214Mixin._direct_share_primary_roots_v11214(paths, expected_year))
        seen = {str(value or "").casefold() for value in rows}
        for raw in paths or []:
            name = str(raw or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
            matched = _ACTUAL_EP_MARKER_V11214.search(name)
            if not matched:
                continue
            prefix = name[:matched.start()].strip(" ._-[]()（）【】")
            key = title_key_v1111(prefix, expected_year=expected_year).casefold()
            if len(key) < 3 or key in _GENERIC_ACTUAL_TITLE_KEYS_V11214:
                continue
            marker = prefix.casefold()
            if marker and marker not in seen:
                seen.add(marker)
                rows.append(prefix)
        return rows

    def _hydrate_viewing_guangya_shares_v11214(self, subscribe: Any) -> int:
        """让 GYING 光鸭分享与迅雷/Magnet 共用同一订阅 TMDB alias scope。"""
        scope = getattr(self, "_gying_alias_scope_v11212", None)
        if not callable(scope):
            return int(super()._hydrate_viewing_guangya_shares_v11214(subscribe) or 0)
        with scope(subscribe):
            return int(super()._hydrate_viewing_guangya_shares_v11214(subscribe) or 0)

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
