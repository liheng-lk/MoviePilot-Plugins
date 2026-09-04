"""v1.12.5 迅雷召回最终可用性门禁。

只修正“搜索结果是否足以停止关键词降级”的集数判定，不复制媒体身份规则：
- 标题/别名/年份/季号继续统一调用 v1.11.1 MediaIdentityGuard 的运行时权威；
- TV 候选若显式标出了集号且与 MoviePilot 当前真实缺集完全不相交，视为不可用；
- 未标集号的整季包/合集仍保留为潜在可用候选，避免为了扩大关键词无意义增加请求；
- 关键词降级后，把本轮真正成功请求过的各级详情结果合并回原关键词 120 秒缓存，
  即使没有可用迅雷，后续 Magnet 也能复用已经付出的 downurl 请求；
- 某一级迅雷候选通过预筛但实际秒传失败时，才继续下一档关键词；已失败分享只保存在
  thread-local 去重集合中，本轮不会因宽关键词再次返回同一分享而重复尝试；
- 若某一级搜索本身失败（节点/登录/HTTP），立即停止继续放宽，不能把服务异常放大成请求风暴；
- Magnet/ED2K 以“实际执行结果”为准：严格候选存在但因旧集、错媒体或历史失败未产生 action 时，
  才逐级补查宽关键词；若严格搜索本身没有成功缓存则不继续放宽。
- 真正的媒体身份与文件级缺集校验仍由现有迅雷 JSON / Episode Planner 最终确认。

本层是标准 cooperative mixin，不继承旧 Hardening；运行时显式放在 Hardening 前面。
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Iterable, List, Set

from .episode_resolver_v190 import AUTO_SELECT_CONFIDENCE, reliable_episode_set, resolve_episode
from .gying_hardening_v193 import gying_keyword_variants


class GuangYaGyingRecallGuardV1125Mixin:
    """最终迅雷召回门禁：预筛、真实执行失败后的渐进降级、SearchBundle 复用。"""

    build_id = "20260904-r51-preview"

    def _recall_retry_local_v1125(self):
        local = getattr(self, "_gying_recall_retry_local_v1125", None)
        if local is None:
            local = threading.local()
            self._gying_recall_retry_local_v1125 = local
        return local

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
        """只合并真实成功缓存；绝不把失败/不存在的关键词伪装成已请求成功。"""
        cache = getattr(self, "_gying_search_cache", None)
        primary = " ".join(str(primary or "").split())
        if not isinstance(cache, dict) or not primary:
            return

        valid_variants: List[str] = []
        merged: List[Dict[str, Any]] = []
        seen = set()
        final_state: Dict[str, Any] = {}
        latest_ts = 0.0
        for raw_variant in variants or []:
            variant = " ".join(str(raw_variant or "").split())
            if not variant or variant in valid_variants:
                continue
            entry = dict(cache.get(variant) or {})
            if not entry:
                continue
            state = entry.get("state")
            if isinstance(state, dict) and state.get("success") is False:
                continue
            valid_variants.append(variant)
            try:
                latest_ts = max(latest_ts, float(entry.get("ts") or 0))
            except (TypeError, ValueError):
                pass
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

        if not valid_variants:
            return
        effective = valid_variants[-1]
        final_state.update({
            "success": True,
            "query_fallback": effective if effective != primary else final_state.get("query_fallback"),
            "search_bundle_v1125": True,
            "bundle_variants": valid_variants,
            "bundle_resources": len(merged),
        })
        cache[primary] = {
            # 保留真实请求时间，不能用“合并动作发生时间”延长旧缓存寿命。
            "ts": latest_ts or time.time(),
            "rows": merged[:800],
            "state": final_state,
        }

    def _search_viewing_xunlei(self, keyword: str):
        """只有当前媒体且可能覆盖当前缺集的迅雷候选，才能停止当前一档搜索。"""
        all_variants = gying_keyword_variants(keyword)
        if not all_variants:
            return super()._search_viewing_xunlei(keyword)

        retry_local = self._recall_retry_local_v1125()
        try:
            start_index = max(0, int(getattr(retry_local, "start_index", 0) or 0))
        except (TypeError, ValueError):
            start_index = 0
        start_index = min(start_index, len(all_variants))
        variants = all_variants[start_index:]
        if not variants:
            return [], {
                "provider": "viewing_xunlei",
                "success": True,
                "message": "观影迅雷关键词层级已全部尝试",
                "searched_variants": all_variants,
            }

        context = getattr(self, "_gying_xunlei_context_v1125", None)
        subscribe = getattr(context, "subscribe", None) if context is not None else None
        seen_identities = set(getattr(retry_local, "seen_identities", set()) or set())
        last_state: Dict[str, Any] = {
            "provider": "viewing_xunlei",
            "success": False,
            "message": "观影迅雷搜索失败",
        }
        successful: List[str] = []
        for relative_index, variant in enumerate(variants):
            absolute_index = start_index + relative_index
            retry_local.last_attempted_index = absolute_index
            candidates, state = self._gying_xunlei_precise_variant_v1125(variant)
            last_state = dict(state or {})
            if not last_state.get("success"):
                retry_local.stop_after_failure = True
                bundle_variants = [all_variants[0], *successful] if start_index else successful
                if len(set(bundle_variants)) > 1:
                    self._promote_search_bundle_v1125(all_variants[0], bundle_variants)
                return candidates, last_state
            successful.append(variant)

            matched: List[Dict[str, Any]] = []
            for row in list(candidates or []):
                identity = str((row or {}).get("share_id") or (row or {}).get("identity") or "").strip()
                if identity and identity in seen_identities:
                    continue
                matched.append(row)

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
                for row in matched:
                    identity = str((row or {}).get("share_id") or (row or {}).get("identity") or "").strip()
                    if identity:
                        seen_identities.add(identity)
                retry_local.seen_identities = seen_identities
                last_state["matched_candidates"] = len(matched)
                last_state["missing_candidates"] = len(matched)
                if absolute_index > 0:
                    bundle_variants = [all_variants[0], *successful] if start_index else successful
                    self._promote_search_bundle_v1125(all_variants[0], bundle_variants)
                    promoted = dict(getattr(self, "_gying_search_cache", {}).get(all_variants[0]) or {})
                    promoted_state = promoted.get("state") if isinstance(promoted.get("state"), dict) else {}
                    if promoted_state:
                        last_state.update({
                            "search_bundle_v1125": True,
                            "bundle_variants": list(promoted_state.get("bundle_variants") or bundle_variants),
                            "bundle_resources": int(promoted_state.get("bundle_resources") or 0),
                        })
                    last_state["query_fallback"] = variant
                    last_state["message"] = (
                        f"{last_state.get('message') or '观影迅雷搜索成功'} · "
                        f"前一档迅雷未完成，已降级到 {variant}"
                    )
                return matched, last_state

        bundle_variants = [all_variants[0], *successful] if start_index else successful
        if len(set(bundle_variants)) > 1:
            self._promote_search_bundle_v1125(all_variants[0], bundle_variants)
            promoted = dict(getattr(self, "_gying_search_cache", {}).get(all_variants[0]) or {})
            promoted_state = promoted.get("state") if isinstance(promoted.get("state"), dict) else {}
            if promoted_state:
                last_state.update({
                    "search_bundle_v1125": True,
                    "bundle_variants": list(promoted_state.get("bundle_variants") or bundle_variants),
                    "bundle_resources": int(promoted_state.get("bundle_resources") or 0),
                })
        last_state["searched_variants"] = list(successful)
        last_state["message"] = (
            f"观影可访问，但本轮 {len(successful)} 级关键词均没有当前订阅可用迅雷分享"
            if last_state.get("success") else last_state.get("message")
        )
        return [], last_state

    @staticmethod
    def _merge_xunlei_rounds_v1125(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
        if not base:
            return dict(extra or {})
        if not extra:
            return dict(base or {})
        merged = {**dict(base), **dict(extra)}
        for key in ("shares", "attempted_files", "successful_files"):
            merged[key] = int((base or {}).get(key) or 0) + int((extra or {}).get(key) or 0)
        merged["success"] = bool((base or {}).get("success")) or bool((extra or {}).get("success"))
        merged["handled"] = bool((base or {}).get("handled")) or bool((extra or {}).get("handled"))
        merged["movie"] = bool((base or {}).get("movie")) or bool((extra or {}).get("movie"))
        merged["subscription_completed"] = bool((base or {}).get("subscription_completed")) or bool(
            (extra or {}).get("subscription_completed")
        )
        episodes = {
            int(value)
            for value in [*((base or {}).get("episodes") or []), *((extra or {}).get("episodes") or [])]
            if str(value).isdigit() and int(value) > 0
        }
        merged["episodes"] = sorted(episodes)
        merged["errors"] = [
            *list((base or {}).get("errors") or []),
            *list((extra or {}).get("errors") or []),
        ][:20]
        messages = []
        for row in (base, extra):
            value = str((row or {}).get("message") or "").strip()
            if value and value not in messages:
                messages.append(value)
        merged["message"] = "；".join(messages)[:800]
        return merged

    def _dispatch_xunlei_flash(self, subscribe: Any) -> Dict[str, Any]:
        """真实秒传失败后才继续下一档关键词；搜索本身失败则立即停止。"""
        all_variants = gying_keyword_variants(str(self._provider_keyword(subscribe) or ""))
        local = self._recall_retry_local_v1125()
        tracked = ("start_index", "last_attempted_index", "seen_identities", "stop_after_failure")
        previous = {
            key: (hasattr(local, key), getattr(local, key, None))
            for key in tracked
        }
        local.start_index = 0
        local.last_attempted_index = -1
        local.seen_identities = set()
        local.stop_after_failure = False
        combined: Dict[str, Any] = {}
        try:
            while True:
                before_index = int(getattr(local, "start_index", 0) or 0)
                local.stop_after_failure = False
                current = dict(super()._dispatch_xunlei_flash(subscribe) or {})
                combined = self._merge_xunlei_rounds_v1125(combined, current)
                if bool(combined.get("handled")) or bool(combined.get("movie")):
                    break
                if bool(getattr(local, "stop_after_failure", False)):
                    break
                try:
                    last_index = int(getattr(local, "last_attempted_index", before_index) or 0)
                except (TypeError, ValueError):
                    last_index = before_index
                next_index = last_index + 1
                if next_index <= before_index or next_index >= len(all_variants):
                    break
                local.start_index = next_index
            return combined
        finally:
            for key, (had_value, value) in previous.items():
                if had_value:
                    setattr(local, key, value)
                else:
                    try:
                        delattr(local, key)
                    except AttributeError:
                        pass

    def _dispatch_viewing_external_v1113(self, subscribe: Any) -> Dict[str, Any]:
        """只有实际没有产生可用 Magnet/ED2K action，才逐级扩大关键词。"""
        result = dict(super()._dispatch_viewing_external_v1113(subscribe) or {})
        if bool(result.get("success")) or list(result.get("actions") or []):
            return result

        primary = " ".join(str(self._provider_keyword(subscribe) or "").split())
        variants = gying_keyword_variants(primary)
        if len(variants) <= 1:
            return result

        # 没有“严格关键词成功搜索”的事实时，不能因为资源站故障继续扩大请求。
        cache = getattr(self, "_gying_search_cache", None)
        strict_entry = dict(cache.get(variants[0]) or {}) if isinstance(cache, dict) else {}
        strict_state = strict_entry.get("state") if isinstance(strict_entry.get("state"), dict) else {}
        if not strict_entry or strict_state.get("success") is False:
            return result

        attempted: List[str] = [variants[0]]
        last_result = result
        for variant in variants[1:]:
            _unused_xunlei, state = self._gying_xunlei_precise_variant_v1125(variant)
            state = dict(state or {})
            if not state.get("success"):
                return last_result
            attempted.append(variant)
            self._promote_search_bundle_v1125(variants[0], attempted)
            current = dict(super()._dispatch_viewing_external_v1113(subscribe) or {})
            current["query_fallback_v1125"] = variant
            current["search_bundle_v1125"] = True
            current["bundle_variants_v1125"] = list(attempted)
            last_result = current
            if bool(current.get("success")) or list(current.get("actions") or []):
                return current
        return last_result


__all__ = ["GuangYaGyingRecallGuardV1125Mixin"]
