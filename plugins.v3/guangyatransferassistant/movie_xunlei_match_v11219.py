"""v1.12.19 迅雷电影真实 payload 最终匹配。

搜索卡片只负责发现。电影迅雷分享在真正导入 JSON 前，再用真实分享标题与真实视频路径
执行 actual-only 身份校验；如果普通官方别名无法覆盖合法双语资源，只允许复用 v1.12.16
已经建立的严格“同一分享双语标题 -> 真实视频”桥接。
"""
from __future__ import annotations

from typing import Any, Dict, Tuple

from .legacy import _is_video
from .media_match_v11219 import movie_actual_match_v11219


class GuangYaMovieXunleiMatchV11219Mixin:
    """让迅雷电影与光鸭分享、Magnet/ED2K 使用同等级真实内容门禁。"""

    def _xunlei_json_identity_matches_v1123(
        self,
        subscribe: Any,
        candidate: Dict[str, Any],
        info: Dict[str, Any],
        template: Dict[str, Any],
    ) -> Tuple[bool, str]:
        accepted, reason = super()._xunlei_json_identity_matches_v1123(
            subscribe,
            candidate,
            info,
            template,
        )
        if not accepted or not self._is_movie_subscription(subscribe):
            return bool(accepted), str(reason or "")

        search_title = str(candidate.get("search_title") or "").strip()
        resource_name = str(candidate.get("name") or "").strip()
        # panlist 缺 name 时会把 search_title 回填到 candidate.name；它仍只是 discovery。
        if resource_name and search_title and resource_name.casefold() == search_title.casefold():
            resource_name = ""

        video_files = [
            str(row.get("path") or row.get("name") or "").strip()
            for row in (template.get("files") or [])
            if isinstance(row, dict)
            and _is_video(str(row.get("path") or row.get("name") or ""))
        ]
        if not video_files:
            return False, "迅雷电影真实 payload 未发现可验证的视频文件"

        aliases_fn = getattr(self, "_identity_aliases_v1111", None)
        aliases = list(
            aliases_fn(subscribe)
            if callable(aliases_fn)
            else [str(getattr(subscribe, "name", "") or "")]
        )
        primary = [
            str(info.get("title") or "").strip(),
            resource_name,
        ]
        assessment = movie_actual_match_v11219(
            aliases=aliases,
            expected_year=getattr(subscribe, "year", None),
            primary_evidences=primary,
            file_evidences=video_files,
        )
        if bool(assessment.get("ok")):
            return True, (
                "迅雷电影真实 payload 通过："
                + str(assessment.get("reason") or f"score={assessment.get('score', 0)}")[:300]
            )

        # 保留 v1.12.16 已证明安全的严格双语真实资源桥；不做其它模糊救回。
        bridge = getattr(self, "_bilingual_bridge_v11216", None)
        if callable(bridge):
            try:
                rescued, bridge_reason = bridge(subscribe, candidate, info, template)
            except Exception:
                rescued, bridge_reason = False, ""
            if rescued:
                return True, f"迅雷电影真实 payload 双语闭环通过：{str(bridge_reason or '')[:300]}"

        return False, (
            "迅雷电影真实 payload 身份拒绝："
            + str(assessment.get("reason") or "实际标题未命中 MoviePilot/TMDB 官方别名")[:320]
        )


__all__ = ["GuangYaMovieXunleiMatchV11219Mixin"]
