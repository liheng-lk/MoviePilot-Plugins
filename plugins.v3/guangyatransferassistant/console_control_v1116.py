"""控制台真实交互闭环。

把旧控制台从“能画按钮/能展示快照”收口成真正可操作的运维面板：
- 页面按钮仍使用 MoviePilot 原生 get_page events API；
- 所有关键动作统一记录最近一次操作回执，API 完成后宿主自动刷新页面即可看到结果；
- 新增“立即处理缺失”，真正把仍缺资源的订阅送入可靠后台执行链，而不是只做搜索预览；
- failed / needs_review 来源提供重试、重新规划和停用动作；
- /console/state 汇总返回脱敏后的真实运行数据，供当前 Vuetify 页面和后续 Vue 前端复用。
"""

from __future__ import annotations

import functools
import inspect
from typing import Any, Dict, List

from .channel_event_guard_v1115 import GuangYaChannelEventGuardV1115Mixin


_CONSOLE_ACTION_PATHS_V1116 = {
    "/console/process",
    "/providers/search/selected",
    "/providers/test",
    "/xunlei/flash/preflight",
    "/viewing/nodes/refresh",
    "/refresh",
    "/selfcheck",
    "/diagnostics/full",
    "/offline/refresh",
    "/source/dispatch",
    "/source/retry",
    "/source/replan",
    "/source/disable",
    "/check_missing",
    "/recheck_pending",
}


class GuangYaConsoleControlV1116Mixin(GuangYaChannelEventGuardV1115Mixin):
    """给控制台补真实动作、真实回执和可处理任务按钮。"""

    build_id = "20260902-r27"

    # ------------------------------------------------------------------
    # 操作回执
    # ------------------------------------------------------------------
    def _record_console_action_v1116(self, path: str, result: Any) -> None:
        success = True
        message = "操作完成"
        if isinstance(result, dict):
            success = bool(result.get("success", True))
            message = str(result.get("message") or ("操作完成" if success else "操作失败"))[:500]
        row = {
            "path": str(path or ""),
            "success": success,
            "message": message,
            "updated_at": self._now_text(),
        }
        self.save_data("console_action_last_v1116", row)
        try:
            self._record_route_health(
                last_console_action=str(path or ""),
                last_console_action_success=success,
                last_console_action_message=message,
                last_console_action_at=row["updated_at"],
            )
        except Exception:
            pass

    def _wrap_console_endpoint_v1116(self, path: str, endpoint: Any) -> Any:
        if not callable(endpoint) or getattr(endpoint, "_guangya_console_observed_v1116", False):
            return endpoint

        if inspect.iscoroutinefunction(endpoint):
            @functools.wraps(endpoint)
            async def async_wrapper(*args, **kwargs):
                try:
                    result = await endpoint(*args, **kwargs)
                except Exception as err:
                    result = {"success": False, "message": f"操作执行异常：{str(err)[:300]}"}
                self._record_console_action_v1116(path, result)
                return result

            async_wrapper._guangya_console_observed_v1116 = True
            return async_wrapper

        @functools.wraps(endpoint)
        def wrapper(*args, **kwargs):
            try:
                result = endpoint(*args, **kwargs)
            except Exception as err:
                result = {"success": False, "message": f"操作执行异常：{str(err)[:300]}"}
            self._record_console_action_v1116(path, result)
            return result

        wrapper._guangya_console_observed_v1116 = True
        return wrapper

    # ------------------------------------------------------------------
    # 真正执行缺失订阅
    # ------------------------------------------------------------------
    def api_console_process_missing(self, subscribe_id: int = 0) -> Dict[str, Any]:
        selected = {
            int(value)
            for value in (getattr(self, "_selected_subscriptions", None) or [])
            if str(value).isdigit() and int(value) > 0
        }
        requested = int(subscribe_id or 0)
        if requested:
            selected &= {requested}
        if not selected:
            return {"success": False, "message": "没有可处理的固定转存订阅", "data": {"queued": []}}

        queued: List[int] = []
        skipped: List[Dict[str, Any]] = []
        for subscribe in self._list_subscriptions("N,R"):
            sid = int(getattr(subscribe, "id", 0) or 0)
            if sid not in selected or not self._is_guangya_route(subscribe):
                continue
            if not self._is_movie_subscription(subscribe):
                try:
                    missing = [int(value) for value in (self._subscription_missing_episodes(subscribe) or []) if int(value or 0) > 0]
                except Exception:
                    missing = []
                if not missing:
                    try:
                        self._finish_subscription_if_complete(subscribe)
                    except Exception:
                        pass
                    skipped.append({"subscribe_id": sid, "name": str(getattr(subscribe, "name", "") or ""), "reason": "当前无缺集"})
                    continue
            queued.append(sid)

        if not queued:
            return {
                "success": True,
                "message": "当前固定转存订阅没有需要处理的缺失内容",
                "data": {"queued": [], "skipped": skipped},
            }

        self._queue_async_route_check(queued, trigger="控制台处理缺集")
        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【控制台】已提交 %s 个缺失订阅进入真实后台处理链：%s",
            len(queued),
            queued,
        )
        return {
            "success": True,
            "message": f"已将 {len(queued)} 个订阅送入后台处理；先用频道缓存，未覆盖部分再走独立外部来源",
            "data": {"queued": queued, "skipped": skipped},
        }

    # ------------------------------------------------------------------
    # SourceStore 人工动作
    # ------------------------------------------------------------------
    def api_source_replan(self, source_id: str = "") -> Dict[str, Any]:
        source_id = str(source_id or "").strip()
        source = dict(self._source_store()["items"].get(source_id) or {})
        if not source:
            return {"success": False, "message": "来源不存在"}
        if str(source.get("task_id") or "").strip():
            return {"success": False, "message": "该来源已有光鸭 taskId，请使用“重试任务”而不是重新规划"}
        updated = self._update_source(
            source_id,
            state="new",
            enabled=True,
            next_retry_at=0,
            last_error="",
            resolved_episodes=[],
            selected_indexes=[],
            selection_diagnostics=[],
        ) or source
        self._spawn_source_dispatch(source_id)
        return {"success": True, "message": "来源已清除旧解析结果并进入重新规划队列", "data": self._source_public_view(updated)}

    def api_source_disable(self, source_id: str = "") -> Dict[str, Any]:
        source_id = str(source_id or "").strip()
        source = dict(self._source_store()["items"].get(source_id) or {})
        if not source:
            return {"success": False, "message": "来源不存在"}
        updated = self._update_source(
            source_id,
            enabled=False,
            state="disabled",
            next_retry_at=0,
            last_error="",
        ) or source
        return {"success": True, "message": "该来源已停用，不再自动提交或重试", "data": self._source_public_view(updated)}

    # ------------------------------------------------------------------
    # 真实控制台状态 API（不返回 Cookie / token / 原始 tracker）
    # ------------------------------------------------------------------
    def api_console_state(self) -> Dict[str, Any]:
        overview = dict(self._status_overview_v191() or {})
        plans = list((self.api_resource_plan().get("data") or []))
        sources = list((self.api_source_list().get("data") or []))
        cache = self._channel_cache_v1115()
        index = self.get_data("channel_index") or {}
        return {
            "success": True,
            "message": "控制台状态已刷新",
            "data": {
                "overview": overview,
                "last_action": dict(self.get_data("console_action_last_v1116") or {}),
                "resource_plans": plans[:100],
                "sources": sources[:100],
                "provider_search": dict(self.get_data("provider_search_last") or {}),
                "provider_test": dict(self.get_data("provider_test_last") or {}),
                "xunlei_preflight": dict(self.get_data("xunlei_preflight_last") or {}),
                "diagnostics": dict(self.get_data("full_diagnostics_last") or {}),
                "channel": {
                    "items": len(list(index.get("items") or [])),
                    "errors": len(list(index.get("errors") or [])),
                    "updated_at": str(index.get("time") or ""),
                    "cache_items": len(dict(cache.get("items") or {})),
                    "cache_updated_at": float(cache.get("updated_at") or 0),
                    "cache_last_cleanup_at": float(cache.get("last_cleanup_at") or 0),
                    "cache_retention_days": 7,
                },
            },
        }

    def get_api(self):
        apis = list(super().get_api() or [])
        paths = {str(item.get("path") or "") for item in apis if isinstance(item, dict)}
        extras = [
            {"path": "/console/state", "endpoint": self.api_console_state, "methods": ["GET"], "summary": "读取真实控制台状态"},
            {"path": "/console/process", "endpoint": self.api_console_process_missing, "methods": ["POST"], "summary": "立即处理固定转存订阅的缺失内容"},
            {"path": "/source/replan", "endpoint": self.api_source_replan, "methods": ["POST"], "summary": "清除旧解析结果并重新规划来源"},
            {"path": "/source/disable", "endpoint": self.api_source_disable, "methods": ["POST"], "summary": "停用一个外部来源"},
        ]
        apis.extend(item for item in extras if item["path"] not in paths)

        observed: List[Dict[str, Any]] = []
        for raw in apis:
            if not isinstance(raw, dict):
                continue
            item = dict(raw)
            path = str(item.get("path") or "")
            if path in _CONSOLE_ACTION_PATHS_V1116:
                item["endpoint"] = self._wrap_console_endpoint_v1116(path, item.get("endpoint"))
            observed.append(item)
        return observed

    # ------------------------------------------------------------------
    # 页面：给所有真实异常补动作，并展示最近一次 API 回执/缺集计划
    # ------------------------------------------------------------------
    @staticmethod
    def _console_button_v1116(text: str, path: str, *, params: Dict[str, Any] | None = None, color: str = "primary", icon: str = "") -> Dict[str, Any]:
        props: Dict[str, Any] = {
            "size": "small",
            "variant": "tonal",
            "color": color,
            "class": "mr-2 mt-2",
            "style": "border-radius:10px;font-weight:600;",
        }
        if icon:
            props["prepend-icon"] = icon
        click: Dict[str, Any] = {
            "api": f"plugin/GuangYaTransferAssistant{path}",
            "method": "post",
        }
        if params:
            click["params"] = dict(params)
        return {"component": "VBtn", "props": props, "text": text, "events": {"click": click}}

    def _attention_cards(self, overview: Dict[str, Any]) -> List[Dict[str, Any]]:
        cards: List[Dict[str, Any]] = []
        for item in overview.get("critical_checks") or []:
            cards.append({
                "component": "VCard",
                "props": {"variant": "tonal", "color": "error", "class": "mb-2", "style": "border-radius:14px;"},
                "content": [
                    {"component": "VCardText", "content": [
                        {"component": "div", "props": {"style": "font-weight:700;"}, "text": str(item.get("label") or "关键检查失败")},
                        {"component": "div", "props": {"class": "mt-1", "style": "font-size:12px;line-height:1.6;"}, "text": str(item.get("detail") or "需要检查插件运行状态")},
                        self._console_button_v1116("重新自检", "/selfcheck", color="error", icon="mdi-stethoscope"),
                    ]},
                ],
            })

        for row in overview.get("attention_sources") or []:
            state = str(row.get("state") or "")
            source_id = str(row.get("id") or "")
            error = str(row.get("last_error") or "")
            title = self._source_title(row)
            actions: List[Dict[str, Any]] = []
            if state == "needs_review":
                actions.append(self._console_button_v1116("重新规划", "/source/replan", params={"source_id": source_id}, color="warning", icon="mdi-source-branch-refresh"))
            elif state == "failed":
                actions.append(self._console_button_v1116("重试任务", "/source/retry", params={"source_id": source_id}, color="error", icon="mdi-reload"))
            if source_id:
                actions.append(self._console_button_v1116("停用来源", "/source/disable", params={"source_id": source_id}, color="secondary", icon="mdi-cancel"))
            cards.append({
                "component": "VCard",
                "props": {"variant": "tonal", "color": "warning" if state == "needs_review" else "error", "class": "mb-2", "style": "border-radius:14px;"},
                "content": [
                    {"component": "VCardText", "content": [
                        {"component": "div", "props": {"style": "font-weight:700;"}, "text": title},
                        {"component": "div", "props": {"class": "mt-1", "style": "font-size:12px;line-height:1.6;"}, "text": error or ("文件集号需要重新规划" if state == "needs_review" else "云添加任务失败")},
                        {"component": "div", "props": {"class": "d-flex flex-wrap"}, "content": actions},
                    ]},
                ],
            })

        for row in overview.get("failed_transfer_rows") or []:
            if len(cards) >= 10:
                break
            sid = int(row.get("subscribe_id") or row.get("sid") or 0)
            error = str(row.get("error") or row.get("message") or "转存任务失败")[:300]
            actions = []
            if sid > 0:
                actions.append(self._console_button_v1116("重新检查缺集", "/check_missing", params={"subscribe_id": sid}, color="error", icon="mdi-refresh"))
            cards.append({
                "component": "VCard",
                "props": {"variant": "tonal", "color": "error", "class": "mb-2", "style": "border-radius:14px;"},
                "content": [{"component": "VCardText", "content": [
                    {"component": "div", "props": {"style": "font-weight:700;"}, "text": self._transfer_title(row)},
                    {"component": "div", "props": {"class": "mt-1", "style": "font-size:12px;line-height:1.6;"}, "text": error},
                    {"component": "div", "props": {"class": "d-flex flex-wrap"}, "content": actions},
                ]}],
            })
        return cards[:10]

    def _console_receipt_panel_v1116(self) -> Dict[str, Any]:
        row = dict(self.get_data("console_action_last_v1116") or {})
        if row:
            ok = bool(row.get("success"))
            text = f"{row.get('message') or '-'} · {row.get('updated_at') or '-'}"
            path = str(row.get("path") or "")
            if path:
                text += f" · {path}"
        else:
            ok = True
            text = "尚未执行控制台动作。点击任一操作后，这里会显示后端真实返回结果。"
        return {
            "component": "VAlert",
            "props": {
                "type": "success" if ok else "error",
                "variant": "tonal",
                "density": "compact",
                "class": "mb-4",
                "title": "最近操作回执",
                "text": text,
                "style": "border-radius:14px;",
            },
        }

    def _console_plan_panel_v1116(self) -> Dict[str, Any]:
        plans = list((self.api_resource_plan().get("data") or []))
        rows: List[Dict[str, Any]] = []
        for plan in plans[:8]:
            sid = int(plan.get("subscribe_id") or 0)
            name = str(plan.get("name") or f"订阅 #{sid}")
            missing = [int(v) for v in (plan.get("missing") or []) if int(v or 0) > 0]
            uncovered = [int(v) for v in (plan.get("uncovered") or []) if int(v or 0) > 0]
            actions = list(plan.get("actions") or [])
            detail = f"缺失 {len(missing)} · 尚未覆盖 {len(uncovered)} · 已生成执行 {len(actions)}"
            if uncovered:
                detail += " · " + ", ".join(f"E{v:02d}" for v in uncovered[:12])
            controls: List[Dict[str, Any]] = []
            if sid > 0 and (uncovered or missing):
                controls.append(self._console_button_v1116("立即处理", "/console/process", params={"subscribe_id": sid}, color="primary", icon="mdi-play-circle-outline"))
            rows.append({
                "component": "VSheet",
                "props": {"class": "pa-3 mb-2", "style": "border:1px solid rgba(var(--v-border-color),.10);border-radius:14px;"},
                "content": [
                    {"component": "div", "props": {"style": "font-size:13px;font-weight:700;"}, "text": name},
                    {"component": "div", "props": {"class": "mt-1", "style": "font-size:12px;line-height:1.6;opacity:.72;"}, "text": detail},
                    {"component": "div", "props": {"class": "d-flex flex-wrap"}, "content": controls},
                ],
            })
        if not rows:
            rows = [{"component": "VAlert", "props": {"type": "info", "variant": "tonal", "density": "compact", "text": "暂无资源计划。执行一次“立即处理缺失”或等待频道/观影产生计划后，这里会显示真实缺集覆盖情况。"}}]
        return {
            "component": "VCard",
            "props": {"variant": "flat", "class": "mb-4", "style": "border:1px solid rgba(var(--v-border-color),.10);border-radius:18px;"},
            "content": [
                {"component": "VCardText", "content": [
                    {"component": "div", "props": {"style": "font-size:17px;font-weight:700;"}, "text": "订阅缺集与资源计划"},
                    {"component": "div", "props": {"class": "mt-1 mb-3", "style": "font-size:12px;opacity:.65;"}, "text": "这里来自 ResourcePlanner 的真实持久状态，不是静态演示数据。"},
                    *rows,
                ]},
            ],
        }

    def _inject_real_process_button_v1116(self, node: Any) -> None:
        if isinstance(node, list):
            for index, item in enumerate(list(node)):
                if isinstance(item, dict) and str(item.get("text") or "") == "搜索缺失资源":
                    item["text"] = "仅搜索预览"
                    if not any(isinstance(row, dict) and str(row.get("text") or "") == "立即处理缺失" for row in node):
                        node.insert(index, self._console_button_v1116("立即处理缺失", "/console/process", color="success", icon="mdi-play-circle-outline"))
                    return
            for item in node:
                self._inject_real_process_button_v1116(item)
        elif isinstance(node, dict):
            for value in node.values():
                self._inject_real_process_button_v1116(value)

    def get_page(self):
        pages = list(super().get_page() or [])
        self._inject_real_process_button_v1116(pages)
        receipt = self._console_receipt_panel_v1116()
        plans = self._console_plan_panel_v1116()
        if len(pages) >= 3:
            return [pages[0], pages[1], receipt, pages[2], plans, *pages[3:]]
        return [receipt, plans, *pages]


__all__ = ["GuangYaConsoleControlV1116Mixin"]
