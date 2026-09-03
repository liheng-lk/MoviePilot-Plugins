"""光鸭转存助手 v1.12.1 预览：周视图追剧日历 + 星期级订阅门禁。

- 剧集按逐集 air_date 放入周一至周日；普通后台只搜索当天应播订阅；
- date 精度不允许提前窗口跨到前一天，精确 air_at 仍保留提前检查；
- TMDB 下一集缺日期时，用最近已知集数的主要更新星期回退；
- 电影没有固定星期，不进入星期筛选，继续由新资源触发和每日全员补漏处理。
"""
from __future__ import annotations

import datetime
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from app.chain.media import MediaChain
from app.schemas.types import MediaSource, MediaType


class GuangYaAiringWeeklyV1121Mixin:
    """在 v1.12.0 逐集日历之上增加星期调度与周视图。"""

    build_id = "20260903-r45-preview"
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

    def _airing_gate_v1120(self, subscribe: Any, payload: Dict[str, Any] = None) -> Dict[str, Any]:
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
                info = MediaChain().recognize_media(
                    mtype=MediaType.TV,
                    media_source=MediaSource.TMDB,
                    media_id=tmdb_id,
                    cache=True,
                )
            except TypeError:
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

    def _weekly_calendar_snapshot_v1121(self) -> Dict[str, Any]:
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

    def _episode_card_v1121(self, row: Dict[str, Any]) -> Dict[str, Any]:
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

    def _weekly_page_v1121(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
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


__all__ = ["GuangYaAiringWeeklyV1121Mixin"]
