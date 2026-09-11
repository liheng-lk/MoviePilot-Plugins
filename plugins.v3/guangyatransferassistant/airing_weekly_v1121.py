"""追更周视图与星期调度单一 Authority。

- 剧集按逐集 air_date 放入周一至周日；普通后台只搜索当天应播订阅；
- date 精度不允许提前窗口跨到前一天，精确 air_at 仍保留提前检查；
- TMDB 下一集缺日期时，用最近已知集数的主要更新星期回退；
- 电影没有固定星期，不进入星期筛选，继续由新资源触发和每日全员补漏处理。
"""
from __future__ import annotations

import datetime
import time
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from app.chain.media import MediaChain
from app.schemas.types import MediaSource, MediaType

from .channel_event_v1115 import (
    _CHANNEL_CACHE_MAX_ITEMS_V1115,
    _CHANNEL_CACHE_RETENTION_SECONDS_V1115,
    _entry_key_v1115,
)



class GuangYaAiringWeeklyV1121Mixin:
    """在 v1.12.0 逐集日历之上增加星期调度与周视图。"""

    build_id = "20260903-r48-preview"
    _weekday_confidence_min_v1121 = 0.60
    _weekday_sample_limit_v1121 = 16
    _poster_cache_days_v1121 = 7
    _weekday_labels_v1121 = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

    @staticmethod
    def _date_v1121(value: Any) -> Optional[datetime.date]:
        text = str(value or "").strip()[:10]
        if not text:
            return None
        try:
            return datetime.date.fromisoformat(text)
        except ValueError:
            return None

    @staticmethod
    def _positive_set_v1121(values: Iterable[Any]) -> Set[int]:
        result: Set[int] = set()
        for raw in values or []:
            try:
                value = int(raw or 0)
            except (TypeError, ValueError):
                continue
            if value > 0:
                result.add(value)
        return result

    def _weekly_pattern_v1121(self, item: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """从最近已知 air_date 推断稳定周更星期；样本不足或分布不稳定时不猜。"""
        rows: List[Tuple[datetime.date, int]] = []
        for row in (item or {}).get("episodes") or []:
            if not isinstance(row, dict):
                continue
            day = self._date_v1121(row.get("air_date"))
            if not day:
                continue
            try:
                episode = int(row.get("episode") or row.get("episode_number") or 0)
            except (TypeError, ValueError):
                episode = 0
            if episode > 0:
                rows.append((day, episode))
        rows.sort(key=lambda pair: (pair[0], pair[1]))
        rows = rows[-int(self._weekday_sample_limit_v1121):]
        if len(rows) < 2:
            return {"weekday": None, "confidence": 0.0, "samples": len(rows)}
        counts = Counter(day.weekday() for day, _ in rows)
        weekday, hits = max(counts.items(), key=lambda pair: (pair[1], pair[0]))
        confidence = hits / max(len(rows), 1)
        if hits < 2 or confidence < float(self._weekday_confidence_min_v1121):
            return {"weekday": None, "confidence": round(confidence, 3), "samples": len(rows)}
        return {
            "weekday": int(weekday),
            "weekday_label": self._weekday_labels_v1121[int(weekday)],
            "confidence": round(confidence, 3),
            "samples": len(rows),
        }

    def _scheduled_rows_v1121(self, item: Optional[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
        result: Dict[int, Dict[str, Any]] = {}
        for row in (item or {}).get("episodes") or []:
            if not isinstance(row, dict):
                continue
            try:
                episode = int(row.get("episode") or row.get("episode_number") or 0)
            except (TypeError, ValueError):
                continue
            if episode > 0:
                result[episode] = dict(row)
        return result

    def _airing_gate_base_v1121(self, subscribe: Any, payload: Dict[str, Any] = None) -> Dict[str, Any]:
        """收紧 date 精度到自然日，并为缺日期周更剧增加星期级回退。"""
        result = dict(super()._airing_gate_v1120(subscribe, payload=payload) or {})
        if self._is_movie_subscription(subscribe):
            return result

        calendar = payload or self._refresh_airing_calendar_v1120(force=False)
        item = self._calendar_item_for_v1120(subscribe, calendar)
        scheduled_rows = self._scheduled_rows_v1121(item)
        today = datetime.date.today()

        due = self._positive_set_v1121(result.get("due_missing") or [])
        future = self._positive_set_v1121(result.get("future_missing") or [])
        unscheduled = self._positive_set_v1121(result.get("unscheduled_missing") or [])
        reserved = self._positive_set_v1121(result.get("reserved") or [])
        claimed = self._positive_set_v1121(result.get("claimed") or [])

        # 只有日期时严格等到该自然日；精确 air_at 仍允许 v1.12.0 的提前窗口。
        strict_removed: Set[int] = set()
        for episode in list(due):
            row = scheduled_rows.get(episode) or {}
            if str(row.get("precision") or "") != "date":
                continue
            air_date = self._date_v1121(row.get("air_date"))
            if air_date and air_date > today:
                due.discard(episode)
                future.add(episode)
                strict_removed.add(episode)

        pattern = self._weekly_pattern_v1121(item)
        fallback_episode = 0
        inferred_weekday = pattern.get("weekday")
        if (
            not (due - reserved - claimed)
            and unscheduled
            and inferred_weekday is not None
            and int(inferred_weekday) == today.weekday()
        ):
            fallback_episode = min(unscheduled)
            due.add(fallback_episode)
            unscheduled.discard(fallback_episode)

        result.update({
            "due_missing": sorted(due),
            "due_uncovered": sorted(due - reserved - claimed),
            "future_missing": sorted(future),
            "unscheduled_missing": sorted(unscheduled),
            "weekday": inferred_weekday,
            "weekday_label": pattern.get("weekday_label") or "",
            "weekday_confidence": pattern.get("confidence") or 0.0,
            "weekday_samples": pattern.get("samples") or 0,
            "weekday_fallback": bool(fallback_episode),
            "weekday_fallback_episode": fallback_episode,
            "date_strict_removed": sorted(strict_removed),
            "date_strict": True,
        })

        sid = int(getattr(subscribe, "id", 0) or 0)
        state = self.get_data("airing_gate_state_v1120") or {}
        if not isinstance(state, dict):
            state = {}
        state[str(sid)] = result
        if len(state) > 1000:
            state = dict(list(state.items())[-1000:])
        self.save_data("airing_gate_state_v1120", state)

        if fallback_episode:
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【星期排期】#%s %s 最近排期稳定在%s（置信 %.0f%%/%s集），TMDB 下一缺集无日期；今天命中星期，仅补 E%02d",
                sid,
                str(getattr(subscribe, "name", "") or ""),
                str(pattern.get("weekday_label") or ""),
                float(pattern.get("confidence") or 0.0) * 100,
                int(pattern.get("samples") or 0),
                fallback_episode,
            )
        return result

    def _poster_v1121(self, item: Dict[str, Any]) -> str:
        for key in ("poster", "poster_url", "poster_path"):
            value = str(item.get(key) or "").strip()
            if value.startswith("http://") or value.startswith("https://"):
                return value
        tmdb_id = str(item.get("tmdb_id") or "").strip()
        if not tmdb_id.isdigit():
            return ""
        cache = self.get_data("airing_poster_cache_v1121") or {}
        if not isinstance(cache, dict):
            cache = {}
        entry = cache.get(tmdb_id) if isinstance(cache.get(tmdb_id), dict) else {}
        try:
            fetched_at = datetime.datetime.fromisoformat(str(entry.get("fetched_at") or ""))
        except (TypeError, ValueError):
            fetched_at = None
        if fetched_at and datetime.datetime.now() - fetched_at < datetime.timedelta(days=self._poster_cache_days_v1121):
            return str(entry.get("poster") or "")

        poster = ""
        try:
            try:
                recognize = getattr(self, "_recognize_media_cached_v208", None)
                if callable(recognize):
                    info = recognize(
                        mtype=MediaType.TV,
                        media_source=MediaSource.TMDB,
                        media_id=tmdb_id,
                        cache=True,
                    )
                else:
                    info = MediaChain().recognize_media(
                        mtype=MediaType.TV,
                        media_source=MediaSource.TMDB,
                        media_id=tmdb_id,
                        cache=True,
                    )
            except TypeError:
                recognize = getattr(self, "_recognize_media_cached_v208", None)
                if callable(recognize):
                    info = recognize(mtype=MediaType.TV, media_source=MediaSource.TMDB, media_id=tmdb_id)
                else:
                    info = MediaChain().recognize_media(mtype=MediaType.TV, media_source=MediaSource.TMDB, media_id=tmdb_id)
            getter = getattr(info, "get_poster_image", None) if info else None
            if callable(getter):
                poster = str(getter() or "")
            if not poster and info:
                poster = str(getattr(info, "poster", None) or getattr(info, "poster_path", None) or "")
        except Exception:
            poster = ""
        cache[tmdb_id] = {"poster": poster, "fetched_at": datetime.datetime.now().isoformat(timespec="seconds")}
        if len(cache) > 500:
            cache = dict(list(cache.items())[-500:])
        self.save_data("airing_poster_cache_v1121", cache)
        return poster

    def _movie_pool_v1121(self) -> List[Dict[str, Any]]:
        selected = {
            int(value) for value in (getattr(self, "_selected_subscriptions", []) or [])
            if str(value).isdigit() and int(value) > 0
        }
        rows: List[Dict[str, Any]] = []
        for subscribe in self._list_subscriptions(None) or []:
            sid = int(getattr(subscribe, "id", 0) or 0)
            if sid not in selected or not self._is_movie_subscription(subscribe):
                continue
            if str(getattr(subscribe, "state", "") or "") not in {"N", "R"}:
                continue
            rows.append({
                "subscribe_id": sid,
                "title": str(getattr(subscribe, "name", "") or ""),
                "year": str(getattr(subscribe, "year", "") or ""),
            })
        return rows

    def _weekly_calendar_snapshot_base_v1121(self) -> Dict[str, Any]:
        calendar = self._refresh_airing_calendar_v1120(force=False)
        today = datetime.date.today()
        week_start = today - datetime.timedelta(days=today.weekday())
        week_end = week_start + datetime.timedelta(days=6)
        days = [{
            "date": (week_start + datetime.timedelta(days=index)).isoformat(),
            "weekday": index,
            "weekday_label": self._weekday_labels_v1121[index],
            "is_today": index == today.weekday(),
            "items": [],
        } for index in range(7)]

        library = pending = inflight = 0
        for item in calendar.get("subscriptions") or []:
            if not isinstance(item, dict):
                continue
            sid = int(item.get("subscribe_id") or 0)
            subscribe = self._find_subscription(sid) if sid else None
            if not subscribe:
                continue
            raw_missing = self._positive_set_v1121(self._raw_subscription_missing_v1120(subscribe))
            try:
                reservations = dict(self._pending_reservations(subscribe) or {})
                reserved = self._positive_set_v1121(reservations.get("episodes") or [])
            except Exception:
                reserved = set()
            try:
                claimed = self._positive_set_v1121(self._active_source_claims(sid) or [])
            except Exception:
                claimed = set()
            poster = self._poster_v1121(item)
            pattern = self._weekly_pattern_v1121(item)

            for raw in item.get("episodes") or []:
                if not isinstance(raw, dict):
                    continue
                day = self._date_v1121(raw.get("air_date"))
                if not day or day < week_start or day > week_end:
                    continue
                try:
                    episode = int(raw.get("episode") or raw.get("episode_number") or 0)
                except (TypeError, ValueError):
                    episode = 0
                if episode <= 0:
                    continue

                if day > today:
                    status, status_label = "scheduled", "待更新"
                elif episode in reserved or episode in claimed:
                    status, status_label = "inflight", "转存中"
                    inflight += 1
                elif episode in raw_missing:
                    status, status_label = "pending", "待补"
                    pending += 1
                else:
                    status, status_label = "library", "已入库"
                    library += 1

                days[day.weekday()]["items"].append({
                    "subscribe_id": sid,
                    "title": str(item.get("title") or getattr(subscribe, "name", "") or ""),
                    "year": str(item.get("year") or getattr(subscribe, "year", "") or ""),
                    "tmdb_id": str(item.get("tmdb_id") or ""),
                    "season": int(item.get("season") or getattr(subscribe, "season", 0) or 1),
                    "episode": episode,
                    "air_date": day.isoformat(),
                    "air_at": str(raw.get("air_at") or ""),
                    "precision": str(raw.get("precision") or "date"),
                    "poster": poster,
                    "status": status,
                    "status_label": status_label,
                    "weekday_label": self._weekday_labels_v1121[day.weekday()],
                    "series_weekday": pattern.get("weekday_label") or "",
                    "series_weekday_confidence": pattern.get("confidence") or 0.0,
                })

        for day in days:
            day["items"].sort(key=lambda row: (str(row.get("air_at") or row.get("air_date") or ""), str(row.get("title") or "")))
            day["count"] = len(day["items"])
            day["library"] = sum(1 for row in day["items"] if row.get("status") == "library")
            day["pending"] = sum(1 for row in day["items"] if row.get("status") == "pending")
            day["inflight"] = sum(1 for row in day["items"] if row.get("status") == "inflight")

        movies = self._movie_pool_v1121()
        snapshot = {
            "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "today": today.isoformat(),
            "today_index": today.weekday(),
            "week_total": sum(int(day.get("count") or 0) for day in days),
            "today_total": len(days[today.weekday()]["items"]),
            "library": library,
            "pending": pending,
            "inflight": inflight,
            "days": days,
            "movies": movies,
            "movie_count": len(movies),
            "calendar_provider_dailyassistant": int(calendar.get("dailyassistant") or 0),
            "calendar_provider_fallback": int(calendar.get("fallback") or 0),
        }
        self.save_data("airing_week_view_v1121", snapshot)
        return snapshot

    @staticmethod
    def _legacy_calendar_card_v1121(node: Any) -> bool:
        if not isinstance(node, dict) or node.get("component") != "VCard":
            return False
        return any(
            isinstance(child, dict)
            and child.get("component") == "VCardTitle"
            and str(child.get("text") or "") == "追更日历与每日补漏"
            for child in node.get("content") or []
        )

    @staticmethod
    def _metric_chip_v1121(label: str, value: Any, icon: str) -> Dict[str, Any]:
        return {
            "component": "VChip",
            "props": {"variant": "tonal", "prependIcon": icon, "class": "ma-1"},
            "text": f"{label} {value}",
        }

    def _episode_card_base_v1121(self, row: Dict[str, Any]) -> Dict[str, Any]:
        status = str(row.get("status") or "")
        color = {"library": "success", "pending": "error", "inflight": "warning"}.get(status, "info")
        poster = str(row.get("poster") or "")
        media = ({
            "component": "VImg",
            "props": {"src": poster, "height": "220", "cover": True},
        } if poster.startswith(("http://", "https://")) else {
            "component": "VSheet",
            "props": {"height": "220", "class": "d-flex align-center justify-center", "color": "surface-variant"},
            "content": [{"component": "VIcon", "props": {"icon": "mdi-television-classic", "size": "56"}}],
        })
        season = int(row.get("season") or 1)
        episode = int(row.get("episode") or 0)
        air_at = str(row.get("air_at") or "")
        time_text = air_at[11:16] if "T" in air_at and len(air_at) >= 16 else "日期排期"
        return {
            "component": "VCard",
            "props": {"variant": "outlined", "class": "h-100 overflow-hidden"},
            "content": [
                media,
                {"component": "VCardText", "content": [
                    {"component": "VChip", "props": {"size": "x-small", "variant": "flat", "color": color, "class": "mb-2"}, "text": str(row.get("status_label") or "")},
                    {"component": "div", "props": {"class": "text-subtitle-2 font-weight-bold text-truncate"}, "text": str(row.get("title") or "-")},
                    {"component": "div", "props": {"class": "text-caption text-medium-emphasis mt-1"}, "text": f"S{season:02d}E{episode:02d} · {time_text}"},
                ]},
            ],
        }

    def _weekly_page_base_v1121(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        days = list(snapshot.get("days") or [])
        today_index = int(snapshot.get("today_index") or 0)
        today = days[today_index] if 0 <= today_index < len(days) else {"items": []}
        day_strip: List[Dict[str, Any]] = []
        for day in days:
            title = f"今天 · {day.get('weekday_label')}" if day.get("is_today") else str(day.get("weekday_label") or "")
            day_strip.append({
                "component": "VCol",
                "props": {"cols": 6, "sm": 4, "md": 3, "lg": 2, "style": "min-width:135px; flex:1 1 0;"},
                "content": [{
                    "component": "VCard",
                    "props": {"variant": "tonal" if day.get("is_today") else "outlined", "class": "h-100"},
                    "content": [{"component": "VCardText", "content": [
                        {"component": "div", "props": {"class": "text-subtitle-2 font-weight-bold"}, "text": title},
                        {"component": "div", "props": {"class": "text-caption text-medium-emphasis"}, "text": str(day.get("date") or "")[5:]},
                        {"component": "div", "props": {"class": "text-caption mt-1"}, "text": f"{int(day.get('count') or 0)} 部 · 已入库 {int(day.get('library') or 0)} · 待补 {int(day.get('pending') or 0)}"},
                    ]}],
                }],
            })

        today_cards = [{
            "component": "VCol",
            "props": {"cols": 6, "sm": 4, "md": 3, "lg": 2},
            "content": [self._episode_card_v1121(row)],
        } for row in (today.get("items") or [])]
        if not today_cards:
            today_cards = [{
                "component": "VCol",
                "props": {"cols": 12},
                "content": [{"component": "VAlert", "props": {
                    "type": "info", "variant": "tonal",
                    "text": "今天没有进入排期的剧集；其它星期的订阅不会触发外部资源站搜索。",
                }}],
            }]

        return {
            "component": "VCard",
            "props": {"variant": "outlined", "class": "mb-3"},
            "content": [
                {"component": "VCardTitle", "text": "追剧日历"},
                {"component": "VCardSubtitle", "text": "逐集上映日期 + 星期排期驱动光鸭搜索；电影不参与星期筛选。"},
                {"component": "VCardText", "content": [
                    {"component": "div", "props": {"class": "d-flex flex-wrap mb-3"}, "content": [
                        self._metric_chip_v1121("本周更新", snapshot.get("week_total") or 0, "mdi-calendar-week"),
                        self._metric_chip_v1121("今日更新", snapshot.get("today_total") or 0, "mdi-white-balance-sunny"),
                        self._metric_chip_v1121("已入库", snapshot.get("library") or 0, "mdi-check-circle-outline"),
                        self._metric_chip_v1121("待补", snapshot.get("pending") or 0, "mdi-clock-alert-outline"),
                        self._metric_chip_v1121("电影待匹配", snapshot.get("movie_count") or 0, "mdi-movie-open-outline"),
                    ]},
                    {"component": "VRow", "props": {"dense": True}, "content": day_strip},
                    {"component": "div", "props": {"class": "text-subtitle-1 font-weight-bold mt-4 mb-2"}, "text": f"今日更新 · {snapshot.get('today')} · {int(snapshot.get('today_total') or 0)} 部"},
                    {"component": "VRow", "props": {"dense": True}, "content": today_cards},
                    {"component": "VAlert", "props": {
                        "type": "info", "variant": "tonal", "class": "mt-3",
                        "text": (
                            "星期筛选只约束剧集普通后台匹配：例如周四更新的《完美世界》只在周四进入日常搜索，"
                            "周五更新的《沧元图》只在周五进入日常搜索。电影继续由新资源触发 + 每日全员补漏处理；"
                            "人工强制和每日 04:10 全员补漏不会被星期门禁挡住。"
                        ),
                    }},
                ]},
            ],
        }

    def get_page(self):
        pages = [node for node in list(super().get_page() or []) if not self._legacy_calendar_card_v1121(node)]
        try:
            weekly = self._weekly_page_v1121(self._weekly_calendar_snapshot_v1121())
        except Exception as err:
            self._plugin_log("WARNING", "【光鸭转存助手】【追剧日历】周视图生成失败：%s", err)
            weekly = {"component": "VAlert", "props": {
                "type": "warning", "variant": "tonal", "class": "mb-3",
                "text": f"追剧日历暂时无法生成：{str(err)[:220]}",
            }}
        return [weekly, *pages]


    # ------------------------------------------------------------------
    # Consolidated final weekly behavior (formerly airing_weekly_v1121 wrapper)
    # ------------------------------------------------------------------
    def _airing_gate_v1120(self, subscribe: Any, payload: Dict[str, Any] = None) -> Dict[str, Any]:
        result = dict(self._airing_gate_base_v1121(subscribe, payload=payload) or {})
        if self._is_movie_subscription(subscribe):
            return result

        calendar = payload or self._refresh_airing_calendar_v1120(force=False)
        item = self._calendar_item_for_v1120(subscribe, calendar)
        scheduled = self._scheduled_rows_v1121(item)
        today = datetime.date.today()
        now = datetime.datetime.now()

        due = self._positive_set_v1121(result.get("due_missing") or [])
        future = self._positive_set_v1121(result.get("future_missing") or [])
        unscheduled = self._positive_set_v1121(result.get("unscheduled_missing") or [])
        reserved = self._positive_set_v1121(result.get("reserved") or [])
        claimed = self._positive_set_v1121(result.get("claimed") or [])

        active: Set[int] = set()
        off_day: Set[int] = set()
        for episode in sorted(due):
            row = scheduled.get(episode)
            if not row:
                # 仅保留本轮由稳定星期推断明确放行的一个未知日期缺集。
                if (
                    bool(result.get("weekday_fallback"))
                    and int(result.get("weekday_fallback_episode") or 0) == episode
                    and result.get("weekday") is not None
                    and int(result.get("weekday")) == today.weekday()
                ):
                    active.add(episode)
                else:
                    off_day.add(episode)
                continue

            precision = str(row.get("precision") or "date")
            air_date = self._date_v1121(row.get("air_date"))
            if precision == "datetime":
                air_at: Optional[datetime.datetime] = self._episode_air_at_v1120(row)
                if not air_at:
                    off_day.add(episode)
                    continue
                early = datetime.timedelta(hours=int(getattr(self, "_calendar_early_hours_v1120", 12) or 12))
                window_start = air_at - early
                window_end = datetime.datetime.combine(air_at.date() + datetime.timedelta(days=1), datetime.time.min)
                if window_start <= now < window_end:
                    active.add(episode)
                elif now < window_start:
                    future.add(episode)
                else:
                    off_day.add(episode)
                continue

            # 只有日期精度时，严格只在 air_date 当天进入普通后台搜索。
            if air_date == today:
                active.add(episode)
            elif air_date and air_date > today:
                future.add(episode)
            else:
                off_day.add(episode)

        result.update({
            "due_missing": sorted(active),
            "due_uncovered": sorted(active - reserved - claimed),
            "future_missing": sorted(future - active),
            "unscheduled_missing": sorted(unscheduled),
            "off_day_missing": sorted(off_day),
            "weekday_strict": True,
            "weekday_today": today.weekday(),
            "weekday_today_label": self._weekday_labels_v1121[today.weekday()],
        })

        sid = int(getattr(subscribe, "id", 0) or 0)
        state = self.get_data("airing_gate_state_v1120") or {}
        if not isinstance(state, dict):
            state = {}
        state[str(sid)] = result
        if len(state) > 1000:
            state = dict(list(state.items())[-1000:])
        self.save_data("airing_gate_state_v1120", state)

        previous = self.get_data("airing_weekday_log_v1121") or {}
        previous = previous if isinstance(previous, dict) else {}
        signature = {
            "due": result.get("due_uncovered") or [],
            "off_day": result.get("off_day_missing") or [],
            "weekday": today.weekday(),
        }
        if previous.get(str(sid)) != signature:
            previous[str(sid)] = signature
            if len(previous) > 1000:
                previous = dict(list(previous.items())[-1000:])
            self.save_data("airing_weekday_log_v1121", previous)
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【星期门禁】#%s %s 今天=%s；允许普通搜索=%s；其它日期缺集=%s",
                sid,
                str(getattr(subscribe, "name", "") or ""),
                self._weekday_labels_v1121[today.weekday()],
                ",".join(f"E{value:02d}" for value in sorted(active - reserved - claimed)) or "无",
                ",".join(f"E{value:02d}" for value in sorted(off_day)) or "无",
            )
        return result

    # ------------------------------------------------------------------
    # 追剧日历：只保留 已入库 / 转存中 / 待补 三种状态
    # ------------------------------------------------------------------
    def _weekly_calendar_snapshot_v1121(self) -> Dict[str, Any]:
        """MoviePilot 媒体库是“已入库”唯一强事实，其他只分在途或待补。"""
        snapshot = dict(self._weekly_calendar_snapshot_base_v1121() or {})
        days = list(snapshot.get("days") or [])
        state_cache: Dict[int, Dict[str, Any]] = {}

        for day in days:
            items = list(day.get("items") or []) if isinstance(day, dict) else []
            for row in items:
                if not isinstance(row, dict):
                    continue
                try:
                    sid = int(row.get("subscribe_id") or 0)
                    episode = int(row.get("episode") or 0)
                except (TypeError, ValueError):
                    sid = episode = 0

                subscribe = self._find_subscription(sid) if sid > 0 else None
                if sid <= 0 or episode <= 0 or not subscribe:
                    row["status"], row["status_label"] = "pending", "待补"
                    continue

                if sid not in state_cache:
                    try:
                        sync = dict(self._sync_media_library_progress(subscribe) or {})
                    except Exception:
                        sync = {"success": False, "existing": [], "missing": []}
                    existing = self._positive_set_v1121(sync.get("existing") or [])
                    note = self._positive_set_v1121(getattr(subscribe, "note", None) or [])
                    try:
                        reservations = dict(self._pending_reservations(subscribe) or {})
                        reserved = self._positive_set_v1121(reservations.get("episodes") or [])
                    except Exception:
                        reserved = set()
                    try:
                        claimed = self._positive_set_v1121(self._active_source_claims(sid) or [])
                    except Exception:
                        claimed = set()
                    state_cache[sid] = {
                        "existing": existing,
                        "note": note,
                        "reserved": reserved,
                        "claimed": claimed,
                    }

                state = state_cache[sid]
                if episode in state["existing"]:
                    row["status"], row["status_label"] = "library", "已入库"
                elif (
                    episode in state["reserved"]
                    or episode in state["claimed"]
                    or (episode in state["note"] and episode not in state["existing"])
                ):
                    # 已有成功回执但媒体库扫描尚未确认时，也继续显示“转存中”，
                    # 直到 MoviePilot 媒体库真正确认后再切到“已入库”。
                    row["status"], row["status_label"] = "inflight", "转存中"
                else:
                    # 包括未来排期：日期本身已经在卡片上展示，状态统一表达“尚未入库”。
                    row["status"], row["status_label"] = "pending", "待补"

            if isinstance(day, dict):
                day["items"] = items
                day["library"] = sum(1 for row in items if row.get("status") == "library")
                day["inflight"] = sum(1 for row in items if row.get("status") == "inflight")
                day["pending"] = sum(1 for row in items if row.get("status") == "pending")
                day.pop("completed", None)
                day.pop("unknown", None)

        all_rows = [
            row
            for day in days if isinstance(day, dict)
            for row in (day.get("items") or []) if isinstance(row, dict)
        ]
        snapshot.update({
            "days": days,
            "library": sum(1 for row in all_rows if row.get("status") == "library"),
            "inflight": sum(1 for row in all_rows if row.get("status") == "inflight"),
            "pending": sum(1 for row in all_rows if row.get("status") == "pending"),
            "status_source": "moviepilot_library_three_state",
        })
        snapshot.pop("completed", None)
        snapshot.pop("unknown", None)
        self.save_data("airing_week_view_v1121", snapshot)
        return snapshot

    def _episode_card_v1121(self, row: Dict[str, Any]) -> Dict[str, Any]:
        card = dict(self._episode_card_base_v1121(row) or {})
        try:
            chip = card["content"][1]["content"][0]
            status = str(row.get("status") or "pending")
            chip.setdefault("props", {})["color"] = {
                "library": "success",
                "inflight": "warning",
                "pending": "error",
            }.get(status, "error")
        except (KeyError, IndexError, TypeError):
            pass
        return card

    def _weekly_page_v1121(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        page = dict(self._weekly_page_base_v1121(snapshot) or {})
        try:
            body = page["content"][2]["content"]
            metrics = body[0]["content"]
            if not any("转存中" in str(item.get("text") or "") for item in metrics if isinstance(item, dict)):
                metrics.insert(3, self._metric_chip_v1121("转存中", snapshot.get("inflight") or 0, "mdi-progress-clock"))

            strip = body[1].get("content") or []
            days = list(snapshot.get("days") or [])
            for index, col in enumerate(strip):
                if index >= len(days) or not isinstance(col, dict):
                    continue
                day = days[index]
                summary = col["content"][0]["content"][0]["content"][2]
                summary["text"] = (
                    f"{int(day.get('count') or 0)} 部 · 已入库 {int(day.get('library') or 0)}"
                    f" · 转存中 {int(day.get('inflight') or 0)} · 待补 {int(day.get('pending') or 0)}"
                )
        except (KeyError, IndexError, TypeError):
            pass
        return page

    # ------------------------------------------------------------------
    # 频道缓存：资源只要仍在当前频道扫描中就持续可匹配
    # ------------------------------------------------------------------
    def _refresh_channel_cache_v1115(self, rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """资源缓存按最后看见时间过期；事件去重仍由独立 message cursor/seen 负责。"""
        cache = self._channel_cache_v1115()
        items = dict(cache.get("items") or {})
        now = time.time()
        had_cache = bool(items)
        new_rows: List[Dict[str, Any]] = []

        for raw in rows or []:
            if not isinstance(raw, dict) or raw.get("stale"):
                continue
            entry = dict(raw)
            key = _entry_key_v1115(entry)
            if not key:
                continue
            previous = dict(items.get(key) or {})
            try:
                added_at = float(previous.get("cache_added_at") or entry.get("cache_added_at") or 0) or now
            except (TypeError, ValueError):
                added_at = now
            entry["cache_key_v1115"] = key
            entry["cache_added_at"] = added_at
            entry["cache_seen_at"] = now
            if had_cache and not previous and not entry.get("cached_index"):
                new_rows.append(dict(entry))
            items[key] = entry

        cutoff = now - _CHANNEL_CACHE_RETENTION_SECONDS_V1115
        items = {
            key: row for key, row in items.items()
            if float((row or {}).get("cache_seen_at") or (row or {}).get("cache_added_at") or now) >= cutoff
        }
        if len(items) > _CHANNEL_CACHE_MAX_ITEMS_V1115:
            items = dict(sorted(
                items.items(),
                key=lambda pair: float((pair[1] or {}).get("cache_seen_at") or (pair[1] or {}).get("cache_added_at") or 0),
                reverse=True,
            )[:_CHANNEL_CACHE_MAX_ITEMS_V1115])

        self._save_channel_cache_v1115({
            "items": items,
            "last_cleanup_at": now,
            "updated_at": now,
            "retention_days": 7,
            "retention_basis": "last_seen",
        })
        return new_rows

    # ------------------------------------------------------------------
    # 观影常规轮询：频道优先，但不能因为频道持续有新消息而长期饿死
    # ------------------------------------------------------------------
    def _run_reliability_route_batch(self, batch: List[int], trigger: str) -> None:
        text = str(trigger or "")
        if "频道新增资源" not in text:
            return super()._run_reliability_route_batch(batch, trigger)

        channel_batch = sorted({int(value) for value in batch if int(value or 0) > 0})
        self._run_v1115_mode_batch(channel_batch, trigger, "channel_event", force=False)

        channel_set = set(channel_batch)
        viewing_ids = [
            sid for sid in self._viewing_due_subscription_ids_v1115()
            if int(sid or 0) > 0 and int(sid) not in channel_set
        ]
        if viewing_ids:
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【观影轮询】频道命中批次结束后继续处理 %s 个到期订阅；观影不会被频道事件长期饿死",
                len(viewing_ids),
            )
            self._run_v1115_mode_batch(
                viewing_ids,
                "频道后观影定时轮询",
                "viewing_poll",
                force=False,
            )

    def _spawn_route_prime(self, sids: Iterable[int], trigger: str = "立即检查") -> None:
        ids = sorted({
            int(value) for value in sids
            if str(value).isdigit() and int(value) > 0
        })
        if not ids or not self._enabled:
            return

        missing_cache: List[int] = []
        for sid in ids:
            subscribe = self._find_subscription(sid)
            if not subscribe or not self._is_guangya_route(subscribe):
                continue
            try:
                if not self._cached_matches_for_subscription(subscribe):
                    missing_cache.append(sid)
            except Exception:
                missing_cache.append(sid)

        if missing_cache:
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【新订阅】%s 个订阅频道缓存未命中，先合并现查频道一次，再继续观影搜索",
                len(missing_cache),
            )
            try:
                self.refresh_channels(force=True)
            except Exception as err:
                self._plugin_log(
                    "WARNING",
                    "【光鸭转存助手】【新订阅】频道现查失败，继续观影搜索兜底：%s",
                    str(err)[:260],
                )

        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【新订阅】进入频道缓存/现查 + 观影立即搜索联合匹配，共 %s 个订阅",
            len(ids),
        )
        self._queue_async_route_check(ids, trigger="新订阅资源匹配")


__all__ = ["GuangYaAiringWeeklyV1121Mixin"]
