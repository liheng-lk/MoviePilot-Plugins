"""v1.12.5 迅雷召回最终可用性门禁。

只修正“搜索结果是否足以停止关键词降级”的判定，不改变 GYING 请求协议或迅雷秒传实现：
- 同标题/年份但显式错误季号的候选不能阻止继续搜索正确季；
- TV 候选若显式标出了集号且与 MoviePilot 当前真实缺集完全不相交，视为不可用；
- 未标集号的整季包/合集仍保留为潜在可用候选，避免为了扩大关键词无意义增加请求；
- 真正的媒体身份与文件级缺集校验仍由现有迅雷 JSON / Episode Planner 最终确认。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Set

from .episode_resolver_v190 import AUTO_SELECT_CONFIDENCE, reliable_episode_set, resolve_episode
from .gying_hardening_v193 import GuangYaGyingHardeningMixin, gying_keyword_variants
from .legacy import _normalize_media_text


_SEASON_MARKER_RE_V1125 = re.compile(
    r"(?i)(?:\bS(?:eason)?[ ._-]*0*(\d{1,2})\b|第\s*0*(\d{1,2})\s*季)"
)


class GuangYaGyingRecallGuardV1125Mixin(GuangYaGyingHardeningMixin):
    """最终迅雷召回门禁：错误季/明确旧集不能提前终止关键词降级。"""

    build_id = "20260904-r51-preview"

    @staticmethod
    def _candidate_seasons_v1125(row: Dict[str, Any]) -> Set[int]:
        text = " ".join(
            str(value or "").strip()
            for value in (row.get("search_title"), row.get("name"))
            if str(value or "").strip()
        )
        result: Set[int] = set()
        for pair in _SEASON_MARKER_RE_V1125.findall(text):
            for value in pair:
                if not value:
                    continue
                try:
                    season = int(value)
                except (TypeError, ValueError):
                    continue
                if season > 0:
                    result.add(season)
        return result

    @staticmethod
    def _provider_candidate_matches(subscribe: Any, row: Dict[str, Any]) -> bool:
        """沿用标题/年份门禁，并拒绝候选文本中显式冲突的季号。"""
        expected = _normalize_media_text(getattr(subscribe, "name", ""))
        actual = _normalize_media_text(row.get("search_title") or row.get("name") or "")
        if not expected or not actual or not (expected in actual or actual in expected):
            return False
        try:
            expected_year = int(getattr(subscribe, "year", 0) or 0)
        except (TypeError, ValueError):
            expected_year = 0
        try:
            actual_year = int(row.get("year") or 0)
        except (TypeError, ValueError):
            actual_year = 0
        if expected_year and actual_year and expected_year != actual_year:
            return False

        try:
            expected_season = int(getattr(subscribe, "season", 0) or 0)
        except (TypeError, ValueError):
            expected_season = 0
        seasons = GuangYaGyingRecallGuardV1125Mixin._candidate_seasons_v1125(row)
        if expected_season > 0 and seasons and expected_season not in seasons:
            return False
        return True

    @staticmethod
    def _candidate_episode_hint_v1125(subscribe: Any, row: Dict[str, Any]) -> Set[int]:
        label = " ".join(
            str(value or "").strip()
            for value in (row.get("name"), row.get("search_title"))
            if str(value or "").strip()
        )
        if not label:
            return set()
        try:
            parsed = resolve_episode(label, season_hint=getattr(subscribe, "season", None))
            return set(reliable_episode_set(parsed, AUTO_SELECT_CONFIDENCE))
        except Exception:
            return set()

    def _candidate_can_cover_missing_v1125(
        self,
        subscribe: Any,
        row: Dict[str, Any],
        missing: Set[int],
    ) -> bool:
        """显式旧集直接排除；无集号候选保留给分享文件级 planner 最终确认。"""
        if self._is_movie_subscription(subscribe) or not missing:
            return True
        explicit = self._candidate_episode_hint_v1125(subscribe, row)
        return not explicit or bool(explicit.intersection(missing))

    def _search_viewing_xunlei(self, keyword: str):
        """关键词降级必须找到当前媒体且可能覆盖当前缺集的迅雷候选才停止。"""
        variants = gying_keyword_variants(keyword)
        if not variants:
            return super()._search_viewing_xunlei(keyword)

        context = getattr(self, "_gying_xunlei_context_v1125", None)
        subscribe = getattr(context, "subscribe", None) if context is not None else None
        last_state: Dict[str, Any] = {
            "provider": "viewing_xunlei",
            "success": False,
            "message": "观影迅雷搜索失败",
        }
        for variant in variants:
            candidates, state = self._gying_xunlei_precise_variant_v1125(variant)
            last_state = dict(state or {})
            if not last_state.get("success"):
                return candidates, last_state

            matched: List[Dict[str, Any]] = list(candidates or [])
            missing: Set[int] = set()
            if subscribe is not None:
                matched = [row for row in matched if self._provider_candidate_matches(subscribe, row)]
                if not self._is_movie_subscription(subscribe):
                    try:
                        missing = {
                            int(value)
                            for value in (self._subscription_missing_episodes(subscribe) or [])
                            if int(value or 0) > 0
                        }
                    except Exception:
                        missing = set()
                    matched = [
                        row for row in matched
                        if self._candidate_can_cover_missing_v1125(subscribe, row, missing)
                    ]

            if matched:
                if subscribe is not None and missing:
                    matched.sort(key=lambda row: self._xunlei_candidate_priority_v1125(subscribe, row, missing))
                last_state["matched_candidates"] = len(matched)
                last_state["missing_candidates"] = len(matched)
                if variant != variants[0]:
                    last_state["query_fallback"] = variant
                    last_state["message"] = (
                        f"{last_state.get('message') or '观影迅雷搜索成功'} · "
                        f"严格关键词没有可覆盖当前缺集的迅雷，已降级到 {variant}"
                    )
                return matched, last_state

        last_state["searched_variants"] = variants
        last_state["message"] = (
            f"观影可访问，但 {len(variants)} 级关键词均没有当前订阅可用迅雷分享"
            if last_state.get("success") else last_state.get("message")
        )
        return [], last_state


__all__ = ["GuangYaGyingRecallGuardV1125Mixin"]
