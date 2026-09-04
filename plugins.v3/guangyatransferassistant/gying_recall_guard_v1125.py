"""v1.12.5 迅雷召回最终可用性门禁。

只修正“搜索结果是否足以停止关键词降级”的集数判定，不复制媒体身份规则：
- 标题/别名/年份/季号继续统一调用 v1.11.1 MediaIdentityGuard 的运行时权威；
- TV 候选若显式标出了集号且与 MoviePilot 当前真实缺集完全不相交，视为不可用；
- 未标集号的整季包/合集仍保留为潜在可用候选，避免为了扩大关键词无意义增加请求；
- 关键词降级真正命中后，把本轮已经请求过的各级详情结果合并回原关键词 120 秒缓存，
  后续 Magnet 可以直接复用同一个 SearchBundle，不再重复打开 downurl；
- 真正的媒体身份与文件级缺集校验仍由现有迅雷 JSON / Episode Planner 最终确认。

本层是标准 cooperative mixin，不继承旧 Hardening；运行时显式放在 Hardening 前面，
super() 仅用于无关键词变体时继续走原 GYING 搜索实现。
"""
from __future__ import annotations

import time
from typing import Any, Dict, Iterable, List, Set

from .episode_resolver_v190 import AUTO_SELECT_CONFIDENCE, reliable_episode_set, resolve_episode
from .gying_hardening_v193 import gying_keyword_variants


class GuangYaGyingRecallGuardV1125Mixin:
    """最终迅雷召回门禁：明确旧集不能提前终止关键词降级。"""

    build_id = "20260904-r51-preview"

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

    def _promote_search_bundle_v1125(self, primary: str, variants: Iterable[str]) -> None:
        """把已实际请求过的降级结果合并到原关键词缓存，供后续 Magnet 无请求复用。"""
        cache = getattr(self, "_gying_search_cache", None)
        primary = " ".join(str(primary or "").split())
        if not isinstance(cache, dict) or not primary:
            return

        attempted: List[str] = []
        merged: List[Dict[str, Any]] = []
        seen = set()
        final_state: Dict[str, Any] = {}
        latest_ts = 0.0
        for raw_variant in variants or []:
            variant = " ".join(str(raw_variant or "").split())
            if not variant or variant in attempted:
                continue
            attempted.append(variant)
            entry = dict(cache.get(variant) or {})
            if not entry:
                continue
            try:
                latest_ts = max(latest_ts, float(entry.get("ts") or 0))
            except (TypeError, ValueError):
                pass
            state = entry.get("state")
            if isinstance(state, dict):
                final_state = dict(state)
            for raw_row in entry.get("rows") or []:
                if not isinstance(raw_row, dict):
                    continue
                row = dict(raw_row)
                url = str(row.get("url") or row.get("uri") or "").strip()
                passcode = str(row.get("passcode") or "").strip()
                key = (url, passcode)
                if not url or key in seen:
                    continue
                seen.add(key)
                merged.append(row)

        if not merged:
            return
        effective = attempted[-1] if attempted else primary
        final_state.update({
            "success": True,
            "query_fallback": effective if effective != primary else final_state.get("query_fallback"),
            "search_bundle_v1125": True,
            "bundle_variants": attempted,
            "bundle_resources": len(merged),
        })
        cache[primary] = {
            "ts": max(time.time(), latest_ts),
            "rows": merged[:800],
            "state": final_state,
        }

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
        attempted: List[str] = []
        for variant in variants:
            attempted.append(variant)
            candidates, state = self._gying_xunlei_precise_variant_v1125(variant)
            last_state = dict(state or {})
            if not last_state.get("success"):
                return candidates, last_state

            matched: List[Dict[str, Any]] = list(candidates or [])
            missing: Set[int] = set()
            if subscribe is not None:
                # 不在这里重写标题/年份/季号规则；运行时 self 会优先解析到
                # GuangYaMediaIdentityGuardV1111Mixin._provider_candidate_matches。
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
                    # 当前轮已经付出的 downurl 请求不能浪费：把严格 + 降级级别的资源合并到
                    # 原关键词缓存，后续 Magnet 直接读取，无需再请求 GYING。
                    self._promote_search_bundle_v1125(variants[0], attempted)
                    promoted = dict(getattr(self, "_gying_search_cache", {}).get(variants[0]) or {})
                    promoted_state = promoted.get("state") if isinstance(promoted.get("state"), dict) else {}
                    if promoted_state:
                        last_state.update({
                            "search_bundle_v1125": True,
                            "bundle_variants": list(promoted_state.get("bundle_variants") or attempted),
                            "bundle_resources": int(promoted_state.get("bundle_resources") or 0),
                        })
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
