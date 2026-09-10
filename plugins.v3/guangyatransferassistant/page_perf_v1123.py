"""光鸭转存助手 v1.12.4：数据页性能、即时日期交互与大订阅配置体验。

目标：
- 数据页打开时不再同步逐个调用 MoviePilot 媒体库缺集检查；优先秒开最近快照，过期后后台刷新。
- 追剧日历不再依赖 PageRender 无法共享的 VTabs/VWindow v-model，改成浏览器原生 details 日期组，点击即展开。
- 日期明细使用轻量文本卡片，不在 7 个隐藏日期里预加载整套海报墙，保证切换即时且不拖慢首屏。
- 配置页的大量订阅改成“搜索筛选 + 批量选择 + 添加/取消接管”的固定高度管理器，支持全选当前结果。
"""

from __future__ import annotations

import datetime
import threading
from typing import Any, Dict, List, Optional, Set


def normalize_subscription_ids_v1124(values: Any) -> List[int]:
    """去重后的正整数订阅 ID 列表（保序）。"""
    result: List[int] = []
    seen: Set[int] = set()
    for raw in values or []:
        try:
            sid = int(raw)
        except (TypeError, ValueError):
            continue
        if sid <= 0 or sid in seen:
            continue
        seen.add(sid)
        result.append(sid)
    return result


def filter_visible_subscription_ids_v1124(
    catalog: List[Dict[str, Any]],
    query: Any = "",
) -> List[int]:
    """按搜索关键词过滤 catalog，返回可见订阅 ID。

    空关键词 = 全部可见。匹配字段为 title（含剧名/年份/季/类型/状态/#id）。
    """
    needle = str(query or "").strip().casefold()
    visible: List[int] = []
    for item in catalog or []:
        if not isinstance(item, dict):
            continue
        try:
            sid = int(item.get("value") or 0)
        except (TypeError, ValueError):
            continue
        if sid <= 0:
            continue
        title = str(item.get("title") or "")
        if needle and needle not in title.casefold():
            continue
        visible.append(sid)
    return normalize_subscription_ids_v1124(visible)


def union_selected_subscription_ids_v1124(
    selected_ids: Any,
    visible_ids: Any,
) -> List[int]:
    """全选当前结果：与已有选择做集合并，不覆盖、不去重同名。"""
    return normalize_subscription_ids_v1124(
        list(normalize_subscription_ids_v1124(selected_ids))
        + list(normalize_subscription_ids_v1124(visible_ids))
    )


def clear_selected_subscription_ids_v1124() -> List[int]:
    """取消全选：清空全部选择。"""
    return []


def all_visible_subscription_ids_selected_v1124(
    selected_ids: Any,
    visible_ids: Any,
) -> bool:
    selected = set(normalize_subscription_ids_v1124(selected_ids))
    visible = normalize_subscription_ids_v1124(visible_ids)
    return bool(visible) and all(sid in selected for sid in visible)


def toggle_takeover_subscription_ids_v1124(
    takeover_ids: Any,
    selected_ids: Any,
) -> List[int]:
    """对选中 ID 逐个切换是否已接管（沿用原单条 toggle 语义）。"""
    current = normalize_subscription_ids_v1124(takeover_ids)
    for sid in normalize_subscription_ids_v1124(selected_ids):
        if sid in current:
            current = [value for value in current if value != sid]
        else:
            current.append(sid)
    return normalize_subscription_ids_v1124(current)


class GuangYaPagePerfV1123Mixin:
    """页面只读快照层：把耗时校准移出 HTTP 页面加载路径。"""

    build_id = "20260904-r51"
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
            rows.append({
                "title": f"{name} ({year}){season_text} · {media_type} · {state_text} · #{sid}",
                "value": sid,
                "_picked": picked,
                "_name": name.casefold(),
            })
        # 已接管订阅仍排在前面，方便搜索确认；不再把 ✓ 写死在标题里，避免前端切换后出现旧状态文案。
        rows.sort(key=lambda row: (0 if row.get("_picked") else 1, str(row.get("_name") or ""), int(row.get("value") or 0)))
        for row in rows:
            row.pop("_picked", None)
            row.pop("_name", None)
        return rows

    @classmethod
    def _find_model_node_v1124(cls, node: Any, model: str) -> Optional[Dict[str, Any]]:
        """返回表单里的真实节点引用；旧 _find_model_props 会 deepcopy，修改副本不会影响最终 UI。"""
        if isinstance(node, dict):
            props = node.get("props")
            if isinstance(props, dict) and str(props.get("model") or "") == model:
                return node
            for value in node.values():
                found = cls._find_model_node_v1124(value, model)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for value in node:
                found = cls._find_model_node_v1124(value, model)
                if found is not None:
                    return found
        return None

    def init_plugin(self, config=None):
        """剔除只用于配置页交互的临时选择值，避免写入插件持久配置。"""
        if isinstance(config, dict):
            config = dict(config)
            config.pop("_subscription_pick_v1124", None)
            config.pop("_subscription_batch_v1124", None)
            config.pop("_subscription_query_v1124", None)
            config.pop("_subscription_catalog_v1124", None)
        return super().init_plugin(config)

    @staticmethod
    def _subscription_picker_card_v1124(items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """生产接管订阅管理器卡片（供 get_form 与测试共用）。"""
        # 全选用 mousedown：先于 Autocomplete blur 清空 search，避免“当前结果”被误当成全量。
        select_all_js = (
            "function () { "
            "const catalog = Array.isArray(_subscription_catalog_v1124) ? _subscription_catalog_v1124 : []; "
            "const q = String(_subscription_query_v1124 || '').trim().toLowerCase(); "
            "const visible = catalog.filter(item => { "
            "if (!item) return false; "
            "const sid = Number(item.value); "
            "if (!Number.isFinite(sid) || sid <= 0) return false; "
            "if (!q) return true; "
            "return String(item.title || '').toLowerCase().includes(q); "
            "}).map(item => Number(item.value)); "
            "if (!visible.length) return; "
            "const source = Array.isArray(_subscription_batch_v1124) ? _subscription_batch_v1124 : []; "
            "const current = [...new Set(source.map(Number).filter(v => Number.isFinite(v) && v > 0))]; "
            "if (visible.every(id => current.includes(id))) return; "
            "_subscription_batch_v1124 = [...new Set([...current, ...visible])]; "
            "}"
        )
        clear_all_js = (
            "function () { "
            "if (!(Array.isArray(_subscription_batch_v1124) && _subscription_batch_v1124.length)) return; "
            "_subscription_batch_v1124 = []; "
            "}"
        )
        apply_js = (
            "function () { "
            "const picks = [...new Set((Array.isArray(_subscription_batch_v1124) ? _subscription_batch_v1124 : []).map(Number).filter(v => Number.isFinite(v) && v > 0))]; "
            "if (!picks.length) return; "
            "let current = [...new Set((Array.isArray(selected_subscriptions) ? selected_subscriptions : []).map(Number).filter(v => Number.isFinite(v) && v > 0))]; "
            "for (const id of picks) { "
            "current = current.includes(id) ? current.filter(v => v !== id) : [...current, id]; "
            "} "
            "selected_subscriptions = current; "
            "}"
        )
        # props 内 {{ }} 由 FormRender 求值；config.text 不会求值，按钮文案必须静态。
        alert_text = (
            "{{ "
            "'已选择 ' + (Array.isArray(_subscription_batch_v1124) ? _subscription_batch_v1124.length : 0) + ' 项'"
            " + ' · 已固定接管 ' + (Array.isArray(selected_subscriptions) ? selected_subscriptions.length : 0) + ' 个'"
            " + ' · 当前结果 ' + (function(){"
            "const catalog = Array.isArray(_subscription_catalog_v1124) ? _subscription_catalog_v1124 : [];"
            "const q = String(_subscription_query_v1124 || '').trim().toLowerCase();"
            "const visible = catalog.filter(item => {"
            "if (!item) return false;"
            "const sid = Number(item.value);"
            "if (!Number.isFinite(sid) || sid <= 0) return false;"
            "if (!q) return true;"
            "return String(item.title || '').toLowerCase().includes(q);"
            "});"
            "const selected = [...new Set((Array.isArray(_subscription_batch_v1124) ? _subscription_batch_v1124 : []).map(Number).filter(v => Number.isFinite(v) && v > 0))];"
            "const allSelected = visible.length > 0 && visible.every(item => selected.includes(Number(item.value)));"
            "return visible.length + ' 个' + (allSelected ? '（已全选）' : '');"
            "})()"
            " + '。搜索只影响可见结果与全选范围，不会清空已选；保存后接管名单生效。'"
            " }}"
        )
        return {
            "component": "VCard",
            "props": {"variant": "outlined", "class": "pa-3"},
            "content": [
                {
                    "component": "VRow",
                    "props": {"dense": True, "class": "align-center"},
                    "content": [
                        {
                            "component": "VCol",
                            "props": {"cols": 12},
                            "content": [{
                                "component": "VAutocomplete",
                                "props": {
                                    "model": "_subscription_batch_v1124",
                                    "model:search": "_subscription_query_v1124",
                                    "label": "搜索要添加 / 取消接管的订阅",
                                    "placeholder": "剧名 / 年份 / 季 / 订阅 ID",
                                    "items": items,
                                    "item-title": "title",
                                    "item-value": "value",
                                    "multiple": True,
                                    "chips": False,
                                    "closable-chips": False,
                                    "clearable": True,
                                    "density": "compact",
                                    "hide-details": True,
                                    "hide-selected": False,
                                    "prepend-inner-icon": "mdi-magnify",
                                    "menu-props": {"maxHeight": 360},
                                    "no-data-text": "没有匹配的活跃订阅",
                                },
                            }],
                        },
                        {
                            "component": "VCol",
                            "props": {"cols": 12, "sm": 4},
                            "content": [{
                                "component": "VBtn",
                                "props": {
                                    "block": True,
                                    "variant": "tonal",
                                    "color": "secondary",
                                    "prepend-icon": "mdi-checkbox-multiple-marked-outline",
                                    "disabled": (
                                        "{{ (function(){ "
                                        "const catalog = Array.isArray(_subscription_catalog_v1124) ? _subscription_catalog_v1124 : []; "
                                        "const q = String(_subscription_query_v1124 || '').trim().toLowerCase(); "
                                        "const visible = catalog.filter(item => { "
                                        "if (!item) return false; "
                                        "const sid = Number(item.value); "
                                        "if (!Number.isFinite(sid) || sid <= 0) return false; "
                                        "if (!q) return true; "
                                        "return String(item.title || '').toLowerCase().includes(q); "
                                        "}); "
                                        "if (!visible.length) return true; "
                                        "const selected = [...new Set((Array.isArray(_subscription_batch_v1124) ? _subscription_batch_v1124 : []).map(Number).filter(v => Number.isFinite(v) && v > 0))]; "
                                        "return visible.every(item => selected.includes(Number(item.value))); "
                                        "})() }}"
                                    ),
                                    "onMousedown": select_all_js,
                                    "onClick": select_all_js,
                                },
                                "text": "全选当前结果",
                            }],
                        },
                        {
                            "component": "VCol",
                            "props": {"cols": 12, "sm": 4},
                            "content": [{
                                "component": "VBtn",
                                "props": {
                                    "block": True,
                                    "variant": "tonal",
                                    "color": "secondary",
                                    "prepend-icon": "mdi-checkbox-blank-outline",
                                    "disabled": "{{ !(Array.isArray(_subscription_batch_v1124) && _subscription_batch_v1124.length) }}",
                                    "onClick": clear_all_js,
                                },
                                "text": "取消全选",
                            }],
                        },
                        {
                            "component": "VCol",
                            "props": {"cols": 12, "sm": 4},
                            "content": [{
                                "component": "VBtn",
                                "props": {
                                    "block": True,
                                    "variant": "tonal",
                                    "color": "primary",
                                    "prepend-icon": "mdi-swap-horizontal",
                                    "disabled": "{{ !(Array.isArray(_subscription_batch_v1124) && _subscription_batch_v1124.length) }}",
                                    "onClick": apply_js,
                                },
                                "text": "添加 / 取消接管",
                            }],
                        },
                    ],
                },
                {
                    "component": "VAlert",
                    "props": {
                        "type": "info",
                        "variant": "tonal",
                        "density": "compact",
                        "class": "mt-2",
                        "text": alert_text,
                    },
                },
            ],
        }

    def get_form(self):
        form, defaults = super().get_form()
        defaults = dict(defaults or {})
        defaults["_subscription_pick_v1124"] = None
        defaults["_subscription_batch_v1124"] = []
        defaults["_subscription_query_v1124"] = ""
        try:
            selected_node = self._find_model_node_v1124(form, "selected_subscriptions")
            if selected_node is None:
                return form, defaults

            old_props = dict(selected_node.get("props") or {})
            items = list(old_props.get("items") or self._subscription_options())
            defaults["_subscription_catalog_v1124"] = [
                {"title": str(item.get("title") or ""), "value": int(item.get("value") or 0)}
                for item in items
                if isinstance(item, dict) and int(item.get("value") or 0) > 0
            ]

            # 不再让 multiple VAutocomplete 直接绑定 selected_subscriptions。
            # 唯一搜索态：model:search -> _subscription_query_v1124；选择态：_subscription_batch_v1124。
            selected_node.clear()
            selected_node.update(self._subscription_picker_card_v1124(items))
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


__all__ = [
    "GuangYaPagePerfV1123Mixin",
    "normalize_subscription_ids_v1124",
    "filter_visible_subscription_ids_v1124",
    "union_selected_subscription_ids_v1124",
    "clear_selected_subscription_ids_v1124",
    "all_visible_subscription_ids_selected_v1124",
    "toggle_takeover_subscription_ids_v1124",
]
