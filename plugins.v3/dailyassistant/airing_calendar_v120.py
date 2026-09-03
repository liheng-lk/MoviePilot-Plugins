"""每日助手 v1.2.0：向 GYSub/光鸭转存发布整季逐集上映日历。

设计边界：
- 使用 MoviePilot ChainBase 的 ``tmdb_info(..., season=...)`` 合同读取 TMDB 季详情，
  不直接实例化/访问 TheMovieDb 私有客户端；
- 输出逐集 ``air_date``，若上游未来提供 ``air_at``/``air_time`` 也原样保留；
- 结果按 TMDB+Season 缓存 6 小时，光鸭转存助手可通过运行中的 DailyAssistant
  实例调用 ``get_airing_schedule_snapshot``；
- TMDB 季详情不可用时退回 ``next_episode_to_air`` 单集摘要，不让每日助手成为硬依赖。
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, Iterable, List

from app.chain.media import MediaChain
from app.schemas.types import MediaSource, MediaType
from app.sdk.logging import logger


class DailyAssistantCalendarV120Mixin:
    """为其它插件提供稳定的逐集播出日历只读接口。"""

    build_id = "20260903-daily-calendar-r1"
    _airing_calendar_ttl_v120 = datetime.timedelta(hours=6)

    @staticmethod
    def _calendar_value_v120(obj: Any, field: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(field, default)
        return getattr(obj, field, default)

    @classmethod
    def _episode_rows_v120(cls, detail: Any, season: int) -> List[Dict[str, Any]]:
        episodes = cls._calendar_value_v120(detail, "episodes", []) or []
        rows: List[Dict[str, Any]] = []
        for raw in episodes:
            try:
                episode = int(cls._calendar_value_v120(raw, "episode_number", 0) or 0)
            except (TypeError, ValueError):
                episode = 0
            try:
                season_number = int(cls._calendar_value_v120(raw, "season_number", season) or season)
            except (TypeError, ValueError):
                season_number = season
            if episode <= 0 or season_number != season:
                continue
            air_date = str(cls._calendar_value_v120(raw, "air_date", "") or "").strip()
            air_at = str(
                cls._calendar_value_v120(raw, "air_at", "")
                or cls._calendar_value_v120(raw, "air_datetime", "")
                or cls._calendar_value_v120(raw, "release_at", "")
                or ""
            ).strip()
            if "T" in air_date and not air_at:
                air_at = air_date
                air_date = air_date[:10]
            elif air_date:
                air_date = air_date[:10]
            rows.append({
                "episode": episode,
                "season": season_number,
                "air_date": air_date,
                "air_at": air_at,
                "name": str(cls._calendar_value_v120(raw, "name", "") or "")[:180],
                "runtime": cls._calendar_value_v120(raw, "runtime", None),
                "precision": "datetime" if air_at else ("date" if air_date else "unknown"),
            })
        rows.sort(key=lambda row: int(row.get("episode") or 0))
        return rows

    @staticmethod
    def _cache_fresh_v120(row: Dict[str, Any], now: datetime.datetime) -> bool:
        try:
            fetched = datetime.datetime.fromisoformat(str(row.get("fetched_at") or ""))
        except (TypeError, ValueError):
            return False
        return now - fetched < DailyAssistantCalendarV120Mixin._airing_calendar_ttl_v120

    def _fallback_next_episode_v120(
        self,
        chain: MediaChain,
        *,
        tmdb_id: str,
        season: int,
        title: str,
        force: bool,
    ) -> List[Dict[str, Any]]:
        try:
            try:
                info = chain.recognize_media(
                    mtype=MediaType.TV,
                    media_source=MediaSource.TMDB,
                    media_id=tmdb_id,
                    cache=not force,
                )
            except TypeError:
                info = chain.recognize_media(
                    mtype=MediaType.TV,
                    media_source=MediaSource.TMDB,
                    media_id=tmdb_id,
                )
        except Exception as err:
            logger.debug("【每日助手】【逐集日历】%s TMDB 摘要回退失败: %s", title or tmdb_id, err)
            return []
        next_episode = getattr(info, "next_episode_to_air", None) if info else None
        if not next_episode:
            return []
        row = self._episode_rows_v120({"episodes": [next_episode]}, season)
        return row

    def get_airing_schedule_snapshot(
        self,
        requests: Iterable[Dict[str, Any]],
        force: bool = False,
    ) -> Dict[str, Any]:
        """返回请求中 TMDB 剧集的整季逐集日历。

        ``requests`` 每项至少包含 ``tmdb_id`` 和 ``season``，可附带 ``subscribe_id``、
        ``title``、``year``。这是插件间只读合同，不要求每日助手启用自动榜单订阅。
        """
        normalized: List[Dict[str, Any]] = []
        seen = set()
        for raw in requests or []:
            row = dict(raw or {})
            tmdb_id = str(row.get("tmdb_id") or "").strip()
            try:
                season = int(row.get("season") or 1)
            except (TypeError, ValueError):
                season = 1
            if not tmdb_id.isdigit() or season <= 0:
                continue
            key = f"{tmdb_id}:s{season:02d}"
            if key in seen:
                continue
            seen.add(key)
            row["tmdb_id"] = tmdb_id
            row["season"] = season
            row["calendar_key"] = key
            normalized.append(row)

        now = datetime.datetime.now()
        previous = self.get_data("airing_schedule_v120") or {}
        cached_items = {
            str(item.get("calendar_key") or ""): dict(item)
            for item in (previous.get("items") or [])
            if isinstance(item, dict) and item.get("calendar_key")
        } if isinstance(previous, dict) else {}

        chain = MediaChain()
        items: List[Dict[str, Any]] = []
        errors: List[str] = []
        cache_hits = 0
        for request in normalized:
            key = str(request["calendar_key"])
            cached = cached_items.get(key)
            if cached and not force and self._cache_fresh_v120(cached, now):
                cached["subscribe_id"] = int(request.get("subscribe_id") or cached.get("subscribe_id") or 0)
                cached["title"] = str(request.get("title") or cached.get("title") or "")
                items.append(cached)
                cache_hits += 1
                continue

            tmdb_id = str(request["tmdb_id"])
            season = int(request["season"])
            title = str(request.get("title") or tmdb_id)
            episodes: List[Dict[str, Any]] = []
            try:
                detail = chain.tmdb_info(tmdbid=int(tmdb_id), mtype=MediaType.TV, season=season)
                episodes = self._episode_rows_v120(detail or {}, season)
            except Exception as err:
                errors.append(f"{title} S{season:02d}: {str(err)[:180]}")
            if not episodes:
                episodes = self._fallback_next_episode_v120(
                    chain,
                    tmdb_id=tmdb_id,
                    season=season,
                    title=title,
                    force=force,
                )

            items.append({
                "calendar_key": key,
                "subscribe_id": int(request.get("subscribe_id") or 0),
                "title": title,
                "year": str(request.get("year") or ""),
                "tmdb_id": tmdb_id,
                "season": season,
                "episodes": episodes,
                "episode_count": len(episodes),
                "provider": "dailyassistant_tmdb_season",
                "fetched_at": now.isoformat(timespec="seconds"),
            })

        payload = {
            "success": bool(items),
            "provider": "DailyAssistant",
            "updated_at": now.isoformat(timespec="seconds"),
            "requests": len(normalized),
            "cache_hits": cache_hits,
            "items": items,
            "errors": errors[:30],
        }
        self.save_data("airing_schedule_v120", payload)
        logger.info(
            "【每日助手】【逐集日历】刷新完成：请求=%s 条目=%s 缓存=%s 异常=%s",
            len(normalized), len(items), cache_hits, len(errors),
        )
        return payload


__all__ = ["DailyAssistantCalendarV120Mixin"]
