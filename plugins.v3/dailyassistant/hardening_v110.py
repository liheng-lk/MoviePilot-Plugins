"""每日助手 v1.1.0 运行韧性层。

重点解决：
- 同一媒体同时出现在多个榜单时，不再因为“第一个来源赢”而丢失其它来源及自动订阅资格；
- 单个榜单短时故障时可继续使用最近 48 小时的成功缓存，但缓存候选不会触发新的自动 GYSub；
- GYSub 广播后的 pending 状态每 5 分钟主动与 MoviePilot 订阅事实对账，不必等到下一次整榜刷新；
- 候选记录同时保留全部来源，自动订阅只要命中任一“本轮新鲜且允许自动”的来源即可。
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, List

from app.sdk.logging import logger

from .sources import fetch_source


class DailyAssistantV110Mixin:
    """v1.1.0 多来源合并、故障缓存与 GYSub 对账。"""

    plugin_version = "1.1.0"
    _source_cache_ttl = datetime.timedelta(hours=48)

    def get_service(self) -> List[Dict[str, Any]]:
        services = list(super().get_service() or [])
        if self._enabled:
            services.append({
                "id": "DailyAssistantGYSubReconcile",
                "name": "每日助手 GYSub 落库对账",
                "trigger": "interval",
                "func": self._reconcile_pending_gysub,
                "kwargs": {"minutes": 5},
            })
        return services

    @staticmethod
    def _cache_time(value: Any) -> datetime.datetime | None:
        try:
            return datetime.datetime.fromisoformat(str(value or ""))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _merge_candidate(existing: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
        """合并同一 TMDB/标题身份的榜单事实，保留全部来源与更完整元数据。"""
        row = dict(existing)
        source_keys = list(dict.fromkeys([
            *(row.get("source_keys") or [row.get("source_key")]),
            *(incoming.get("source_keys") or [incoming.get("source_key")]),
        ]))
        source_keys = [str(value) for value in source_keys if str(value or "").strip()]
        source_labels = list(dict.fromkeys([
            *(row.get("source_labels") or [row.get("source_label")]),
            *(incoming.get("source_labels") or [incoming.get("source_label")]),
        ]))
        source_labels = [str(value) for value in source_labels if str(value or "").strip()]
        fresh_keys = list(dict.fromkeys([
            *(row.get("fresh_source_keys") or []),
            *(incoming.get("fresh_source_keys") or []),
        ]))
        row["source_keys"] = source_keys
        row["source_labels"] = source_labels
        row["fresh_source_keys"] = fresh_keys
        row["source_key"] = source_keys[0] if source_keys else str(row.get("source_key") or "")
        row["source_label"] = " / ".join(source_labels) if source_labels else str(row.get("source_label") or "")
        try:
            row["rank"] = min(int(row.get("rank") or 9999), int(incoming.get("rank") or 9999))
        except (TypeError, ValueError):
            pass
        for key in ("poster", "detail_link", "tmdb_id", "imdb_id", "douban_id", "bangumi_id", "anilist_id", "year", "season"):
            if row.get(key) in (None, "") and incoming.get(key) not in (None, ""):
                row[key] = incoming.get(key)
        try:
            left = float(row.get("vote_average")) if row.get("vote_average") not in (None, "") else None
        except (TypeError, ValueError):
            left = None
        try:
            right = float(incoming.get("vote_average")) if incoming.get("vote_average") not in (None, "") else None
        except (TypeError, ValueError):
            right = None
        if left is None and right is not None:
            row["vote_average"] = right
        elif left is not None and right is not None:
            row["vote_average"] = max(left, right)
        return row

    def refresh(self, manual: bool = False) -> Dict[str, Any]:
        """刷新榜单；失败来源使用短期缓存，多来源候选按统一媒体身份合并。"""
        now = datetime.datetime.now()
        cache = self.get_data("dailyassistant_source_cache") or {}
        if not isinstance(cache, dict):
            cache = {}
        statuses: List[Dict[str, Any]] = []
        aggregated: Dict[str, Dict[str, Any]] = {}
        filtered_library = 0
        unresolved = 0
        auto_requested = 0
        auto_confirmed = 0
        auto_failed = 0
        cache_hits = 0

        for source_key in self._source_keys:
            result = fetch_source(source_key, self._rank_limit, self._proxy)
            items = list(result.get("items") or [])
            fresh = bool(result.get("ok"))
            using_cache = False
            if fresh:
                cache[source_key] = {
                    "updated_at": now.isoformat(timespec="seconds"),
                    "label": result.get("label") or source_key,
                    "items": items,
                }
            else:
                cached = cache.get(source_key) if isinstance(cache.get(source_key), dict) else {}
                cached_at = self._cache_time(cached.get("updated_at"))
                if cached_at and now - cached_at <= self._source_cache_ttl:
                    items = list(cached.get("items") or [])
                    using_cache = bool(items)
                    cache_hits += 1 if using_cache else 0

            statuses.append({
                "key": source_key,
                "label": result.get("label") or (cache.get(source_key) or {}).get("label") or source_key,
                "ok": fresh,
                "using_cache": using_cache,
                "count": len(items),
                "error": result.get("error") or "",
            })

            for raw in items:
                row, info = self._resolve_tmdb(raw)
                vote = row.get("vote_average")
                try:
                    if self._vote_min > 0 and vote is not None and float(vote) < self._vote_min:
                        continue
                except (TypeError, ValueError):
                    pass
                if self._library_complete(info, row):
                    filtered_library += 1
                    continue
                row["source_keys"] = [source_key]
                row["source_labels"] = [str(row.get("source_label") or result.get("label") or source_key)]
                row["fresh_source_keys"] = [source_key] if fresh else []
                identity = self._candidate_identity(row)
                if identity in aggregated:
                    aggregated[identity] = self._merge_candidate(aggregated[identity], row)
                else:
                    aggregated[identity] = dict(row)

        self.save_data("dailyassistant_source_cache", cache)
        candidates = list(aggregated.values())
        candidates.sort(key=lambda row: (
            0 if row.get("tmdb_id") else 1,
            int(row.get("rank") or 9999),
            str(row.get("title") or "").casefold(),
        ))
        submitted = self.get_data("gysub_submitted") or {}
        pending = self.get_data("gysub_pending") or {}
        if not isinstance(submitted, dict):
            submitted = {}
        if not isinstance(pending, dict):
            pending = {}
        for index, row in enumerate(candidates, 1):
            row["index"] = index
            row["resolved"] = bool(row.get("tmdb_id"))
            if not row["resolved"]:
                unresolved += 1
            identity = self._candidate_identity(row)
            row["gysub_status"] = "confirmed" if identity in submitted else ("pending" if identity in pending else "new")

        reconcile = self._reconcile_pending_gysub()
        auto_allowed = set(self._auto_source_keys)
        if self._auto_gysub and auto_allowed:
            for row in candidates:
                if not row.get("tmdb_id"):
                    continue
                # 故障缓存只用于页面和人工选择，不用旧榜单事实触发新自动订阅。
                if not auto_allowed.intersection(set(row.get("fresh_source_keys") or [])):
                    continue
                result = self._dispatch_gysub(row, source="每日助手自动订阅")
                if not result.get("success"):
                    auto_failed += 1
                elif result.get("status") == "requested":
                    auto_requested += 1
                elif result.get("status") == "confirmed":
                    auto_confirmed += 1

        current_pending = self.get_data("gysub_pending") or {}
        reconcile["pending"] = len(current_pending) if isinstance(current_pending, dict) else 0
        payload = {
            "batch_id": now.strftime("%Y%m%d%H%M%S%f"),
            "updated_at": now.isoformat(timespec="seconds"),
            "manual": bool(manual),
            "source_count": len(self._source_keys),
            "statuses": statuses,
            "candidates": candidates,
            "filtered_library": filtered_library,
            "unresolved": unresolved,
            "cache_hits": cache_hits,
            "gysub_reconcile": reconcile,
            "auto_requested": auto_requested,
            "auto_confirmed": auto_confirmed,
            "auto_success": auto_requested + auto_confirmed,
            "auto_failed": auto_failed,
        }
        self.save_data("dailyassistant_candidates", payload)
        logger.info(
            "【每日助手】v1.1.0 刷新完成：榜单=%s 候选=%s 缓存回退=%s 媒体库过滤=%s 未识别=%s GYSub请求=%s 确认=%s 失败=%s 待确认=%s",
            len(self._source_keys), len(candidates), cache_hits, filtered_library, unresolved,
            auto_requested, auto_confirmed, auto_failed, reconcile.get("pending", 0),
        )
        return {
            "success": True,
            "data": payload,
            "message": f"发现 {len(candidates)} 个候选，缓存回退 {cache_hits} 个榜单，自动 GYSub 请求 {auto_requested} 个，已确认 {auto_confirmed} 个",
        }


__all__ = ["DailyAssistantV110Mixin"]
