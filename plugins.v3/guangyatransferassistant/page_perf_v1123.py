"""光鸭转存助手 v1.12.4-preview：数据页性能、即时日期交互与大订阅配置体验。

目标：
- 数据页打开时不再同步逐个调用 MoviePilot 媒体库缺集检查；优先秒开最近快照，过期后后台刷新。
- 追剧日历不再依赖 PageRender 无法共享的 VTabs/VWindow v-model，改成浏览器原生 details 日期组，点击即展开。
- 日期明细使用轻量文本卡片，不在 7 个隐藏日期里预加载整套海报墙，保证切换即时且不拖慢首屏。
- 配置页的大量订阅不再为每一项实时计算剧集进度，也不再铺满多选 chips。
"""

from __future__ import annotations

import datetime
import threading
from typing import Any, Dict, List, Optional, Set


class GuangYaPagePerfV1123Mixin:
    """页面只读快照层：把耗时校准移出 HTTP 页面加载路径。"""

    build_id = "20260904-r50-preview"
    _weekly_page_cache_seconds_v1123 = 600

    # ------------------------------------------------------------------
    # 配置页：大量订阅时只构造轻量候选，不逐项算缺集进度
    # ------------------------------------------------------------------
    def _subscription_options(self) -> List[Dict[str, Any]]:
        selected: Set[int] = {
            int(value)
            for value in (getattr(self, "_selected_subscriptions", []) or [])
            if str(value).isdigit() and int(value) > 0
        }
        rows: List[Dict[str, Any]] = []
        for sub in self._list_subscriptions(None) or []:
            try:
                sid = int(getattr(sub, "id", 0) or 0)
            except (TypeError, ValueError):
                continue
            if sid <= 0:
                continue
            state = str(getattr(sub, "state", "") or "")
            # 未选中的历史/暂停订阅不再塞进候选列表；已经选中的仍保留，避免升级后配置值丢失。
            if state not in {"N", "R"} and sid not in selected:
                continue
            name = str(getattr(sub, "name", "") or f"订阅 #{sid}").strip()
            year = str(getattr(sub, "year", "") or "-").strip()
            media_type = str(getattr(sub, "type", "") or "媒体").strip()
            try:
                season = int(getattr(sub, "season", 0) or 0)
            except (TypeError, ValueError):
                season = 0
            season_text = f" · S{season:02d}" if season > 0 else ""
            state_text = {"N": "新建", "R": "订阅中", "P": "待定", "S": "暂停"}.get(state, state or "-")
            picked = sid in selected
            prefix = "✓ " if picked else ""
            rows.append({
                "title": f"{prefix}{name} ({year}){season_text} · {media_type} · {state_text} · #{sid}",
                "value": sid,
                "_picked": picked,
                "_name": name.casefold(),
            })
        rows.sort(key=lambda row: (0 if row.get("_picked") else 1, str(row.get("_name") or ""), int(row.get("value") or 0)))
        for row in rows:
            row.pop("_picked", None)
            row.pop("_name", None)
        return rows

    def get_form(self):
        form, defaults = super().get_form()
        try:
            props = self._find_model_props(form, "selected_subscriptions") or {}
            selected_count = len({
                int(value)
                for value in (getattr(self, "_selected_subscriptions", []) or [])
                if str(value).isdigit() and int(value) > 0
            })
            props.update({
                "label": f"固定接管订阅 · 已选 {selected_count}",
                "placeholder": "输入剧名 / 年份 / 季 / 订阅 ID 搜索",
                "multiple": True,
                # 大量 chips 会把配置页撑得很高；关闭 chips 后保持单行输入和搜索体验。
                "chips": False,
                "closable-chips": False,
                # 已选项仍保留在下拉中，用户可以再次点击单独取消，不必只能“全部清空”。
                "hide-selected": False,
                "clearable": True,
                "auto-select-first": True,
                "menu-props": {"maxHeight": 420},
                "no-data-text": "没有匹配的活跃订阅",
                "hint": (
                    f"当前固定接管 {selected_count} 个订阅。只列出活跃订阅和已接管订阅；"
                    "输入关键词搜索添加，已选项带 ✓ 并可再次点击取消，页面不再铺满 chips。"
                ),
                "persistent-hint": True,
            })
        except Exception:
            pass
        return form, defaults

    # ------------------------------------------------------------------
    # 数据页：快照秒开，强事实校准放后台
    # ------------------------------------------------------------------
    @staticmethod
    def _week_bounds_v1123() -> tuple[str, str]:
        today = datetime.date.today()
        start = today - datetime.timedelta(days=today.weekday())
        end = start + datetime.timedelta(days=6)
        return start.isoformat(), end.isoformat()

    def _weekly_snapshot_usable_v1123(self, snapshot: Any) -> bool:
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("days"), list):
            return False
        start, end = self._week_bounds_v1123()
        return str(snapshot.get("week_start") or "") == start and str(snapshot.get("week_end") or "") == end

    def _weekly_snapshot_stale_v1123(self, snapshot: Dict[str, Any]) -> bool:
        try:
            updated = datetime.datetime.fromisoformat(str(snapshot.get("updated_at") or ""))
        except (TypeError, ValueError):
            return True
        return (datetime.datetime.now() - updated).total_seconds() >= self._weekly_page_cache_seconds_v1123

    def _spawn_weekly_snapshot_refresh_v1123(self) -> None:
        lock = getattr(self, "_weekly_page_refresh_lock_v1123", None)
        if lock is None:
            lock = threading.Lock()
            self._weekly_page_refresh_lock_v1123 = lock
        with lock:
            if bool(getattr(self, "_weekly_page_refreshing_v1123", False)):
                return
            self._weekly_page_refreshing_v1123 = True

        def worker() -> None:
            try:
                # 明确跳过本层缓存方法，调用上一层真实媒体库校准快照；耗时不再阻塞页面 HTTP。
                super(GuangYaPagePerfV1123Mixin, self)._weekly_calendar_snapshot_v1121()
            except Exception as err:
                try:
                    self._plugin_log("WARNING", "【光鸭转存助手】【数据页】后台刷新追剧快照失败：%s", type(err).__name__)
                except Exception:
                    pass
            finally:
                with lock:
                    self._weekly_page_refreshing_v1123 = False

        threading.Thread(target=worker, name="GuangYa-WeeklyPageRefresh", daemon=True).start()

    def _empty_week_snapshot_v1123(self) -> Dict[str, Any]:
        today = datetime.date.today()
        start = today - datetime.timedelta(days=today.weekday())
        days = []
        for index in range(7):
            day = start + datetime.timedelta(days=index)
            days.append({
                "date": day.isoformat(),
                "weekday": index,
                "weekday_label": ("周一", "周二", "周三", "周四", "周五", "周六", "周日")[index],
                "is_today": day == today,
                "items": [],
                "count": 0,
                "library": 0,
                "inflight": 0,
                "pending": 0,
            })
        return {
            "updated_at": "",
            "week_start": start.isoformat(),
            "week_end": (start + datetime.timedelta(days=6)).isoformat(),
            "today": today.isoformat(),
            "today_index": today.weekday(),
            "week_total": 0,
            "today_total": 0,
            "library": 0,
            "inflight": 0,
            "pending": 0,
            "days": days,
            "movies": [],
            "movie_count": 0,
            "page_loading": True,
            "status_source": "background_refresh_pending",
        }

    def _weekly_calendar_snapshot_v1121(self) -> Dict[str, Any]:
        """HTTP 页面只读最近快照；缓存过期在后台校准，避免打开数据页逐剧同步媒体库。"""
        cached = self.get_data("airing_week_view_v1121") or {}
        if self._weekly_snapshot_usable_v1123(cached):
            if self._weekly_snapshot_stale_v1123(cached):
                self._spawn_weekly_snapshot_refresh_v1123()
            result = dict(cached)
            result["page_cache"] = True
            return result

        # 第一次安装/跨周后的首次打开也先返回轻量骨架，后台立即生成真实快照。
        self._spawn_weekly_snapshot_refresh_v1123()
        return self._empty_week_snapshot_v1123()

    # ------------------------------------------------------------------
    # 数据页：PageRender 原生即时日期切换
    # ------------------------------------------------------------------
    def _weekly_day_rows_v1124(self, day: Dict[str, Any]) -> List[Dict[str, Any]]:
        """生成不含海报请求的轻量剧集行，确保 7 天内容预渲染也不会卡顿。"""
        items = [row for row in (day.get("items") or []) if isinstance(row, dict)]
        if not items:
            return [{
                "component": "VAlert",
                "props": {
                    "type": "info",
                    "variant": "tonal",
                    "density": "compact",
                    "text": f"{day.get('weekday_label') or '该日'}没有进入排期的剧集。",
                },
            }]

        palette = {"library": "success", "inflight": "warning", "pending": "error"}
        rows: List[Dict[str, Any]] = []
        for item in items:
            status = str(item.get("status") or "pending")
            label = str(item.get("status_label") or "待补")
            title = str(item.get("title") or "未知剧集")
            try:
                season = int(item.get("season") or 1)
            except (TypeError, ValueError):
                season = 1
            try:
                episode = int(item.get("episode") or 0)
            except (TypeError, ValueError):
                episode = 0
            schedule = str(item.get("air_at") or item.get("air_date") or "排期未知")
            rows.append({
                "component": "VCard",
                "props": {"variant": "tonal", "class": "mb-2"},
                "content": [{
                    "component": "VCardText",
                    "props": {"class": "py-2 px-3"},
                    "content": [
                        {
                            "component": "div",
                            "props": {"class": "d-flex align-center justify-space-between ga-2"},
                            "content": [
                                {"component": "div", "props": {"class": "text-body-2 font-weight-medium text-truncate flex-grow-1"}, "text": title},
                                {"component": "VChip", "props": {"size": "x-small", "variant": "tonal", "color": palette.get(status, "error")}, "text": label},
                            ],
                        },
                        {"component": "div", "props": {"class": "text-caption text-medium-emphasis mt-1"}, "text": f"S{season:02d}E{episode:02d} · {schedule}"},
                    ],
                }],
            })
        return rows

    def _weekly_page_v1121(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        days = [dict(day) for day in (snapshot.get("days") or []) if isinstance(day, dict)]
        today_index = int(snapshot.get("today_index") or 0)
        # 今天始终排第一并默认展开，其余六天按顺序紧跟；点击由浏览器本地 details 原生状态处理。
        if days and 0 <= today_index < len(days):
            ordered_days = days[today_index:] + days[:today_index]
        else:
            ordered_days = days

        day_details: List[Dict[str, Any]] = []
        for day in ordered_days:
            date_text = str(day.get("date") or "")
            short_date = date_text[5:].replace("-", "/") if len(date_text) >= 10 else date_text
            is_today = bool(day.get("is_today"))
            label = f"今天 {short_date}" if is_today else f"{day.get('weekday_label') or ''} {short_date}"
            count = int(day.get("count") or len(day.get("items") or []))
            day_details.append({
                # PageRender 只会 v-bind props，不支持 FormRender 那套共享 v-model；
                # 原生 details 不需要 Vue model、API 请求或 VWindow 过渡，点击即刻生效。
                "component": "details",
                "props": {
                    "name": "guangya-airing-day",
                    "open": is_today,
                    "class": "mb-2 rounded-lg border-sm",
                },
                "content": [
                    {
                        "component": "summary",
                        "props": {"class": "px-3 py-3 cursor-pointer"},
                        "content": [{
                            "component": "div",
                            "props": {"class": "d-flex flex-wrap align-center ga-2"},
                            "content": [
                                {"component": "span", "props": {"class": "text-body-2 font-weight-bold"}, "text": f"{label} · {count}"},
                                {"component": "VChip", "props": {"size": "x-small", "variant": "tonal", "color": "success"}, "text": f"已入库 {int(day.get('library') or 0)}"},
                                {"component": "VChip", "props": {"size": "x-small", "variant": "tonal", "color": "warning"}, "text": f"转存中 {int(day.get('inflight') or 0)}"},
                                {"component": "VChip", "props": {"size": "x-small", "variant": "tonal", "color": "error"}, "text": f"待补 {int(day.get('pending') or 0)}"},
                            ],
                        }],
                    },
                    {
                        "component": "div",
                        "props": {"class": "px-3 pb-2"},
                        "content": self._weekly_day_rows_v1124(day),
                    },
                ],
            })

        loading_alert: List[Dict[str, Any]] = []
        if snapshot.get("page_loading"):
            loading_alert.append({
                "component": "VAlert",
                "props": {
                    "type": "info",
                    "variant": "tonal",
                    "class": "mb-3",
                    "text": "首次打开或刚跨周：页面先秒开，真实媒体库状态正在后台生成；稍后重新进入数据页即可看到完整排期。",
                },
            })

        return {
            "component": "VCard",
            "props": {"variant": "outlined", "class": "mb-3"},
            "content": [
                {"component": "VCardTitle", "text": "追剧日历"},
                {"component": "VCardSubtitle", "text": "点击任意日期立即展开对应剧集；当天默认展开。切换只发生在浏览器本地，不发接口请求、不等待后台。"},
                {"component": "VCardText", "content": [
                    *loading_alert,
                    {
                        "component": "div",
                        "props": {"class": "d-flex flex-wrap mb-3"},
                        "content": [
                            self._metric_chip_v1121("本周更新", snapshot.get("week_total") or 0, "mdi-calendar-week"),
                            self._metric_chip_v1121("今日更新", snapshot.get("today_total") or 0, "mdi-white-balance-sunny"),
                            self._metric_chip_v1121("已入库", snapshot.get("library") or 0, "mdi-check-circle-outline"),
                            self._metric_chip_v1121("转存中", snapshot.get("inflight") or 0, "mdi-progress-clock"),
                            self._metric_chip_v1121("待补", snapshot.get("pending") or 0, "mdi-clock-alert-outline"),
                            self._metric_chip_v1121("电影待匹配", snapshot.get("movie_count") or 0, "mdi-movie-open-outline"),
                        ],
                    },
                    *day_details,
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "info",
                            "variant": "tonal",
                            "class": "mt-3",
                            "text": "星期筛选只约束普通后台追更；人工强制和每日 04:10 全员补漏仍会跨星期检查全部真实缺集。",
                        },
                    },
                ]},
            ],
        }


__all__ = ["GuangYaPagePerfV1123Mixin"]
