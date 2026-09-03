"""光鸭转存助手 v1.12.1：星期级普通追更门禁。

周视图/UI/星期推断主体保留在 ``airing_weekly_impl_v1121``；本层只收紧普通后台的
真正执行窗口，确保“周四剧只在周四、周五剧只在周五”这一产品语义。
人工强制和每日全员补漏由 v1.12.0 的 force 路径直接绕过本门禁。
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, Optional, Set

from .airing_weekly_impl_v1121 import GuangYaAiringWeeklyV1121Mixin as _WeeklyImplV1121


class GuangYaAiringWeeklyV1121Mixin(_WeeklyImplV1121):
    """在周视图实现之上把普通后台搜索严格限制到本更新日。"""

    build_id = "20260903-r47-preview"

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

    def _weekly_calendar_snapshot_v1121(self) -> Dict[str, Any]:
        """以 MoviePilot 媒体库事实修正周视图状态，避免把“非缺集”直接误当已入库。"""
        snapshot = dict(super()._weekly_calendar_snapshot_v1121() or {})
        days = list(snapshot.get("days") or [])
        today = self._date_v1121(snapshot.get("today")) or datetime.date.today()
        state_cache: Dict[int, Dict[str, Any]] = {}

        for day in days:
            items = list(day.get("items") or []) if isinstance(day, dict) else []
            for row in items:
                if not isinstance(row, dict):
                    continue
                sid = int(row.get("subscribe_id") or 0)
                episode = int(row.get("episode") or 0)
                if sid <= 0 or episode <= 0:
                    row["status"] = "unknown"
                    row["status_label"] = "待确认"
                    continue

                subscribe = self._find_subscription(sid)
                if not subscribe:
                    row["status"] = "unknown"
                    row["status_label"] = "待确认"
                    continue

                if sid not in state_cache:
                    try:
                        sync = dict(self._sync_media_library_progress(subscribe) or {})
                    except Exception:
                        sync = {"success": False, "existing": [], "missing": []}
                    existing = self._positive_set_v1121(sync.get("existing") or [])
                    missing = self._positive_set_v1121(sync.get("missing") or [])
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
                    raw_missing = self._positive_set_v1121(self._raw_subscription_missing_v1120(subscribe))
                    state_cache[sid] = {
                        "success": bool(sync.get("success")),
                        "existing": existing,
                        "missing": missing,
                        "note": note,
                        "reserved": reserved,
                        "claimed": claimed,
                        "raw_missing": raw_missing,
                    }

                state = state_cache[sid]
                day_value = self._date_v1121(row.get("air_date"))

                # 状态优先级必须以真实事实为先，而不是先看播出日期：
                # 已提前入库 > 在途 > 已完成回执 > 缺集(待补/待更新) > 无法确认。
                if episode in state["existing"]:
                    row["status"], row["status_label"] = "library", "已入库"
                elif episode in state["reserved"] or episode in state["claimed"]:
                    row["status"], row["status_label"] = "inflight", "转存中"
                elif state["success"]:
                    if episode not in state["missing"] and episode in state["note"]:
                        row["status"], row["status_label"] = "completed", "已完成"
                    elif day_value and day_value > today:
                        row["status"], row["status_label"] = "scheduled", "待更新"
                    else:
                        row["status"], row["status_label"] = "pending", "待补"
                elif episode in state["raw_missing"]:
                    if day_value and day_value > today:
                        row["status"], row["status_label"] = "scheduled", "待更新"
                    else:
                        row["status"], row["status_label"] = "pending", "待补"
                else:
                    row["status"], row["status_label"] = "unknown", "待确认"

            if isinstance(day, dict):
                day["items"] = items
                day["library"] = sum(1 for row in items if row.get("status") == "library")
                day["completed"] = sum(1 for row in items if row.get("status") == "completed")
                day["pending"] = sum(1 for row in items if row.get("status") == "pending")
                day["inflight"] = sum(1 for row in items if row.get("status") == "inflight")
                day["unknown"] = sum(1 for row in items if row.get("status") == "unknown")

        all_rows = [row for day in days if isinstance(day, dict) for row in (day.get("items") or []) if isinstance(row, dict)]
        snapshot.update({
            "days": days,
            "library": sum(1 for row in all_rows if row.get("status") == "library"),
            "completed": sum(1 for row in all_rows if row.get("status") == "completed"),
            "pending": sum(1 for row in all_rows if row.get("status") == "pending"),
            "inflight": sum(1 for row in all_rows if row.get("status") == "inflight"),
            "unknown": sum(1 for row in all_rows if row.get("status") == "unknown"),
            "status_source": "moviepilot_library",
        })
        self.save_data("airing_week_view_v1121", snapshot)
        return snapshot

    def _episode_card_v1121(self, row: Dict[str, Any]) -> Dict[str, Any]:
        card = dict(super()._episode_card_v1121(row) or {})
        try:
            chip = card["content"][1]["content"][0]
            chip.setdefault("props", {})["color"] = {
                "library": "success",
                "completed": "success",
                "pending": "error",
                "inflight": "warning",
                "unknown": "secondary",
                "scheduled": "info",
            }.get(str(row.get("status") or ""), "info")
        except (KeyError, IndexError, TypeError):
            pass
        return card


__all__ = ["GuangYaAiringWeeklyV1121Mixin"]
