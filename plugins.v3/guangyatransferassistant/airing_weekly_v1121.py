"""光鸭转存助手 v1.12.2 预览：星期门禁、三态追剧日历与来源轮询修复。

- 普通剧集搜索仍严格受星期/上映日门禁约束；
- 追剧日历只显示“已入库 / 转存中 / 待补”三种剧集状态；
- 观影不是只在新增订阅时搜索，正常追更日也会按外部搜索冷却周期参与；
- 频道新增资源优先处理，但不能长期饿死观影轮询；
- 当前频道仍可见的资源按最后看见时间续期，避免“频道明明有、缓存却过期”；
- 新订阅缓存未命中时只补一次频道现查，然后再进入观影搜索。
"""
from __future__ import annotations

import datetime
import time
from typing import Any, Dict, Iterable, List, Optional, Set

from .airing_weekly_impl_v1121 import GuangYaAiringWeeklyV1121Mixin as _WeeklyImplV1121
from .channel_event_v1115 import (
    _CHANNEL_CACHE_MAX_ITEMS_V1115,
    _CHANNEL_CACHE_RETENTION_SECONDS_V1115,
    _entry_key_v1115,
)


class GuangYaAiringWeeklyV1121Mixin(_WeeklyImplV1121):
    """最终追更层：更新日门禁、三态日历，以及频道/观影常规轮询补强。"""

    build_id = "20260903-r48-preview"

    # ------------------------------------------------------------------
    # 星期级普通追更门禁
    # ------------------------------------------------------------------
    def _airing_gate_v1120(self, subscribe: Any, payload: Dict[str, Any] = None) -> Dict[str, Any]:
        result = dict(super()._airing_gate_v1120(subscribe, payload=payload) or {})
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
        snapshot = dict(super()._weekly_calendar_snapshot_v1121() or {})
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
        card = dict(super()._episode_card_v1121(row) or {})
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
        page = dict(super()._weekly_page_v1121(snapshot) or {})
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
