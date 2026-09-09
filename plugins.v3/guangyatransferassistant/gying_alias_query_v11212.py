"""v1.12.12 GYING 精确官方别名检索补全。

v1.12.9 已经能按订阅精确 TMDB ID 取得电影官方 title/en_title/original_title，
但这些别名此前只参与“资源已经找到之后”的身份门禁；真正发往 GYING 的关键词仍只有
MoviePilot 中文标题 + 年份，因此可能出现网页详情存在 Runaway Jury，而
“失控陪审团 2003 / 失控陪审团”两档搜索始终碰不到目标的死区。

本层只对有明确 MoviePilot 订阅身份的 GYING 请求扩展查询：
- 先保留原中文关键词及既有年份/季号降级；
- 只有当前关键词没有得到“属于该订阅”的候选时，才使用同一 TMDB 身份下的官方别名；
- 电影官方别名仍由 v1.12.9 的 TMDB ID + 年份校验产生，不做编辑距离/拼音/模糊猜测；
- GYING 认证/节点搜索失败立即停止，不用别名掩盖真实网络故障；
- 迅雷与 Magnet/ED2K 共用同一别名查询语义，并保持既有来源优先级及最终真实资源门禁。

MoviePilot 自带全局搜索并不是 GYING Indexer；本层同时让插件自己的统一 Provider 搜索在
关键词能唯一对应已接管订阅时获得同样的官方别名能力。
"""
from __future__ import annotations

import re
import threading
from contextlib import contextmanager
from typing import Any, Dict, Iterable, Iterator, List, Optional

from .xunlei_season_fence_v11210 import GuangYaXunleiSeasonFenceV11210Mixin


class GuangYaGyingAliasQueryV11212Mixin(GuangYaXunleiSeasonFenceV11210Mixin):
    """把精确 TMDB 官方别名补到 GYING 搜索前，而不是只用于搜索后的身份判断。"""

    plugin_version = "1.12.12"
    build_id = "20260905-r58"
    _gying_alias_query_limit_v11212 = 4

    @staticmethod
    def _query_key_v11212(value: Any) -> str:
        return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").casefold())

    def _alias_query_local_v11212(self) -> threading.local:
        local = getattr(self, "_gying_alias_query_local_v11212", None)
        if local is None:
            local = threading.local()
            self._gying_alias_query_local_v11212 = local
        return local

    @contextmanager
    def _gying_alias_scope_v11212(self, subscribe: Any) -> Iterator[None]:
        local = self._alias_query_local_v11212()
        had_previous = hasattr(local, "subscribe")
        previous = getattr(local, "subscribe", None)
        local.subscribe = subscribe
        try:
            yield
        finally:
            if had_previous:
                local.subscribe = previous
            else:
                try:
                    delattr(local, "subscribe")
                except AttributeError:
                    pass

    def _gying_alias_subscribe_v11212(self) -> Any:
        local = getattr(self, "_gying_alias_query_local_v11212", None)
        subscribe = getattr(local, "subscribe", None) if local is not None else None
        if subscribe is not None:
            return subscribe
        xunlei_context = getattr(self, "_gying_xunlei_context_v1125", None)
        return getattr(xunlei_context, "subscribe", None) if xunlei_context is not None else None

    def _gying_alias_keywords_v11212(self, subscribe: Any, primary: str) -> List[str]:
        primary = " ".join(str(primary or "").split())
        if not primary or subscribe is None:
            return [primary] if primary else []

        rows: List[str] = [primary]
        checker = getattr(self, "_is_movie_v1129", None)
        is_movie = False
        if callable(checker):
            try:
                is_movie = bool(checker(subscribe))
            except Exception:
                is_movie = False
        if not is_movie:
            return rows

        alias_getter = getattr(self, "_movie_tmdb_aliases_v1129", None)
        if not callable(alias_getter):
            return rows
        try:
            aliases = list(alias_getter(subscribe) or [])
        except Exception:
            return rows

        year = str(getattr(subscribe, "year", "") or "").strip()
        seen_roots = {self._query_key_v11212(getattr(subscribe, "name", ""))}
        primary_root = re.sub(r"\s+(?:19|20)\d{2}\s*$", "", primary).strip()
        if primary_root:
            seen_roots.add(self._query_key_v11212(primary_root))

        for alias in aliases:
            title = " ".join(str(alias or "").split())
            key = self._query_key_v11212(title)
            if not title or len(key) < 2 or key in seen_roots:
                continue
            seen_roots.add(key)
            candidate = f"{title} {year}".strip() if year else title
            if candidate not in rows:
                rows.append(candidate)
            if len(rows) >= max(2, int(self._gying_alias_query_limit_v11212 or 4)):
                break
        return rows

    def _gying_rows_match_v11212(self, subscribe: Any, rows: Iterable[Dict[str, Any]]) -> bool:
        return bool(self._gying_matching_rows_v11223(subscribe, rows))

    def _gying_matching_rows_v11223(
        self,
        subscribe: Any,
        rows: Iterable[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """只把属于当前订阅的资源行交给上层；请求成功不等于媒体命中。"""
        source_rows = [dict(row or {}) for row in rows or []]
        matcher = getattr(self, "_provider_candidate_matches", None)
        if not callable(matcher):
            return []
        matched: List[Dict[str, Any]] = []
        for row in source_rows:
            try:
                if matcher(subscribe, dict(row or {})):
                    matched.append(row)
            except Exception:
                continue
        return matched

    def _gying_raw_results(self, keyword: str, force: bool = False):
        subscribe = self._gying_alias_subscribe_v11212()
        queries = self._gying_alias_keywords_v11212(subscribe, keyword)
        if subscribe is None:
            return super()._gying_raw_results(keyword, force=force)

        first_rows: List[Dict[str, Any]] = []
        first_state: Dict[str, Any] = {}
        attempted: List[str] = []
        for index, query in enumerate(queries):
            rows, state = super()._gying_raw_results(query, force=force)
            rows = list(rows or [])
            state = dict(state or {})
            attempted.append(query)
            if index == 0:
                first_rows, first_state = rows, state
            if state.get("success") is False:
                if index == 0:
                    state.update({
                        "raw_resources": len(rows),
                        "matched_resources": 0,
                        "target_match": None,
                        "search_complete": False,
                    })
                    return [], state
                alias_error = str(state.get("message") or "官方别名请求失败")[:300]
                first_state.update({
                    "success": False,
                    "healthy": True,
                    "search_complete": False,
                    "partial_error": True,
                    "alias_query_error_v11212": alias_error,
                    "target_match": None,
                    "message": (
                        f"主查询请求正常，但官方别名检索在 {query} 中断：{alias_error}；"
                        "无法确认当前订阅是否存在精确候选"
                    )[:500],
                })
                break
            matched_rows = self._gying_matching_rows_v11223(subscribe, rows)
            if matched_rows:
                state.update({
                    "raw_resources": len(rows),
                    "matched_resources": len(matched_rows),
                    "target_match": True,
                    "search_complete": True,
                })
                if index > 0:
                    state["query_alias_v11212"] = query
                    state["searched_aliases_v11212"] = list(attempted)
                    state["message"] = (
                        f"{state.get('message') or '观影搜索请求完成'} · 中文关键词无当前媒体精确候选，"
                        f"已使用 TMDB 官方别名 {query}"
                    )
                return matched_rows, state

        first_state = dict(first_state or {})
        first_state["searched_aliases_v11212"] = list(attempted)
        first_state.update({
            "raw_resources": len(first_rows),
            "matched_resources": 0,
        })
        if first_state.get("search_complete") is False:
            first_state["target_match"] = None
        else:
            first_state["search_complete"] = True
            first_state["target_match"] = False
        if first_state.get("success") and first_state.get("search_complete"):
            first_state["message"] = (
                f"观影搜索请求正常；已尝试 {len(attempted)} 档精确官方标题，"
                "未找到当前订阅精确候选"
            )
        return [], first_state

    def _search_viewing_xunlei(self, keyword: str):
        subscribe = self._gying_alias_subscribe_v11212()
        queries = self._gying_alias_keywords_v11212(subscribe, keyword)
        if subscribe is None or len(queries) <= 1:
            return super()._search_viewing_xunlei(keyword)

        first_state: Dict[str, Any] = {}
        attempted: List[str] = []
        for index, query in enumerate(queries):
            rows, state = super()._search_viewing_xunlei(query)
            rows = list(rows or [])
            state = dict(state or {})
            attempted.append(query)
            if index == 0:
                first_state = state
            if state.get("success") is False:
                if index == 0:
                    state.update({"search_complete": False, "target_match": None})
                    return rows, state
                alias_error = str(state.get("message") or "官方别名请求失败")[:300]
                first_state.update({
                    "success": False,
                    "healthy": True,
                    "search_complete": False,
                    "partial_error": True,
                    "alias_query_error_v11212": alias_error,
                    "target_match": None,
                    "message": (
                        f"主查询请求正常，但官方别名迅雷检索在 {query} 中断：{alias_error}；"
                        "无法确认当前订阅是否存在精确迅雷候选"
                    )[:500],
                })
                break
            if rows:
                state.update({"search_complete": True, "target_match": True})
                if index > 0:
                    state["query_alias_v11212"] = query
                    state["searched_aliases_v11212"] = list(attempted)
                    state["message"] = (
                        f"{state.get('message') or '观影迅雷搜索成功'} · 已使用 TMDB 官方别名 {query}"
                    )
                return rows, state

        first_state = dict(first_state or {})
        first_state["searched_aliases_v11212"] = list(attempted)
        if first_state.get("search_complete") is False:
            first_state["target_match"] = None
        else:
            first_state.update({"search_complete": True, "target_match": False})
        if first_state.get("success") and first_state.get("search_complete"):
            first_state["message"] = (
                f"{first_state.get('message') or '观影迅雷搜索完成'} · 已尝试 {len(attempted)} 档精确官方标题，"
                "仍无当前媒体可用迅雷"
            )
        return [], first_state

    def _viewing_external_candidates_v1113(self, subscribe: Any):
        with self._gying_alias_scope_v11212(subscribe):
            return super()._viewing_external_candidates_v1113(subscribe)

    def _resolve_unified_subscription_v11212(self, keyword: str) -> Optional[Any]:
        """插件统一搜索仅在关键词唯一对应已接管订阅时借用其 TMDB 身份。"""
        clean = " ".join(str(keyword or "").split())
        if not clean:
            return None
        selected = {
            int(value)
            for value in (getattr(self, "_selected_subscriptions", []) or [])
            if str(value).isdigit() and int(value) > 0
        }
        if not selected:
            return None
        key = self._query_key_v11212(clean)
        matches: List[Any] = []
        for subscribe in self._list_subscriptions(None) or []:
            sid = int(getattr(subscribe, "id", 0) or 0)
            if sid not in selected:
                continue
            name = str(getattr(subscribe, "name", "") or "").strip()
            year = str(getattr(subscribe, "year", "") or "").strip()
            primary = str(self._provider_keyword(subscribe) or "").strip()
            exact_keys = {
                self._query_key_v11212(name),
                self._query_key_v11212(f"{name} {year}".strip()),
                self._query_key_v11212(primary),
            }
            if key and key in exact_keys:
                matches.append(subscribe)
        return matches[0] if len(matches) == 1 else None

    def _unified_provider_search(self, keyword: str) -> Dict[str, Any]:
        if self._gying_alias_subscribe_v11212() is not None:
            return super()._unified_provider_search(keyword)
        subscribe = self._resolve_unified_subscription_v11212(keyword)
        if subscribe is None:
            return super()._unified_provider_search(keyword)
        with self._gying_alias_scope_v11212(subscribe):
            result = dict(super()._unified_provider_search(keyword) or {})
        result["tmdb_alias_query_v11212"] = True
        result["subscribe_id_v11212"] = int(getattr(subscribe, "id", 0) or 0)
        return result


__all__ = ["GuangYaGyingAliasQueryV11212Mixin"]
