"""2.0 根 Mixin：声明式 UI + 迁移 + 匹配轨迹 + 命名/门禁编排，旧流水线双轨运行。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .gy2_config import CONFIG_DEFAULTS_V2, merge_config_defaults
from .gy2_naming import NamingPolicy
from .gy2_migrate import ConfigMigratorV2
from .gy2_orchestrator import TransferOrchestrator
from .gy2_trace import DecisionTraceStore
from .gy2_ui import build_config_form, build_data_page


class _GuangYaTransferV2Mixin:
    """置于最终插件类 MRO 最前，覆盖表单/页面并增强匹配可观测性。

    注意：不要在此 Mixin 上声明 plugin_name/plugin_version。
    MoviePilot PluginLoader 按模块 globals 顺序取第一个“像插件”的类；
    公开暴露带元数据的中间类会导致装错类而安装/加载失败。
    """

    def _gy2_orchestrator(self) -> TransferOrchestrator:
        orch = getattr(self, "_gy2_orch_singleton", None)
        if orch is None:
            orch = TransferOrchestrator(self)
            self._gy2_orch_singleton = orch
        return orch

    def _gy2_traces(self) -> DecisionTraceStore:
        return DecisionTraceStore(self)

    def init_plugin(self, config: dict = None) -> None:
        config = merge_config_defaults(config or {})
        # 先跑旧初始化，保证服务/调度/状态机可用
        super().init_plugin(config)
        try:
            report = ConfigMigratorV2(self).migrate()
            self._plugin_log(
                "INFO",
                "【GY2】【迁移】schema %s -> %s touched=%s",
                report.get("from_schema"),
                report.get("to_schema"),
                ",".join(report.get("touched_state") or []) or "-",
            )
        except Exception as err:
            self._plugin_log("WARNING", "【GY2】【迁移】失败：%s", str(err)[:240])
        self._gy2_orch_singleton = TransferOrchestrator(self)

    def get_form(self):
        # 取旧 defaults（含订阅下拉 items），再用声明式 schema 重建布局
        _old_form, defaults = super().get_form()
        defaults = dict(defaults or {})
        for key, value in CONFIG_DEFAULTS_V2.items():
            defaults.setdefault(key, value)
        subscription_props = None
        # 从旧表单提取 selected_subscriptions 的 items
        try:
            finder = getattr(self, "_find_model_props", None)
            if callable(finder):
                subscription_props = finder(_old_form, "selected_subscriptions")
        except Exception:
            subscription_props = None
        return build_config_form(defaults, subscription_props=subscription_props)

    def _gy2_subscription_rows(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        selected = list(getattr(self, "_selected_subscriptions", []) or [])
        finder = getattr(self, "_find_subscription", None)
        for sid in selected:
            subscribe = finder(sid) if callable(finder) else None
            if not subscribe:
                rows.append({"id": sid, "name": f"订阅#{sid}", "missing": "?", "inflight": "-", "block_reason": "未找到"})
                continue
            missing = "-"
            inflight = "-"
            block = ""
            try:
                if hasattr(self, "_uncovered_missing_v1125"):
                    gap = self._uncovered_missing_v1125(subscribe)
                    missing = ",".join(str(x) for x in sorted(gap, key=str)[:12]) or "无"
                elif hasattr(self, "_missing_episodes"):
                    gap = self._missing_episodes(subscribe)
                    missing = ",".join(str(x) for x in sorted(gap or [], key=str)[:12]) or "无"
            except Exception as err:
                block = f"缺口读取失败:{err}"[:80]
            rows.append({
                "id": int(getattr(subscribe, "id", sid) or sid),
                "name": str(getattr(subscribe, "name", "") or sid),
                "missing": missing,
                "inflight": inflight,
                "block_reason": block,
            })
        return rows

    def _gy2_overview(self) -> Dict[str, Any]:
        selected = list(getattr(self, "_selected_subscriptions", []) or [])
        rejects = self._gy2_traces().rejected_hits(limit=50)
        return {
            "healthy": len(rejects) < 20,
            "selected": len(selected),
            "attention_count": len(rejects),
            "summary": f"2.0 已接管 {len(selected)} 个订阅；最近拒绝 {len(rejects)} 条可在诊断区查看。",
            "version": getattr(self, "plugin_version", "2.0.0"),
            "build": getattr(self, "build_id", ""),
        }

    def get_page(self):
        traces = self._gy2_traces()
        return build_data_page(
            calendar_nodes=self._gy2_calendar_nodes(),
            subscription_rows=self._gy2_subscription_rows(),
            reject_rows=traces.rejected_hits(limit=30),
            trace_rows=traces.recent(limit=30),
            overview=self._gy2_overview(),
        )

    def get_api(self):
        apis = list(super().get_api() or [])
        paths = {str(item.get("path") or "") for item in apis if isinstance(item, dict)}
        extras = [
            {
                "path": "/v2/traces",
                "endpoint": self.api_v2_traces,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "2.0 决策轨迹",
            },
            {
                "path": "/v2/overview",
                "endpoint": self.api_v2_overview,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "2.0 订阅中心概览",
            },
            {
                "path": "/v2/match/preview",
                "endpoint": self.api_v2_match_preview,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "预览频道条目匹配结果",
            },
        ]
        for item in extras:
            if item["path"] not in paths:
                apis.append(item)
        return apis

    def api_v2_traces(self, subscribe_id: int = 0, limit: int = 50) -> Dict[str, Any]:
        return {
            "success": True,
            "data": {
                "items": self._gy2_traces().recent(limit=limit, subscribe_id=int(subscribe_id or 0)),
                "rejects": self._gy2_traces().rejected_hits(limit=limit),
            },
        }

    def api_v2_overview(self) -> Dict[str, Any]:
        data = self._gy2_overview()
        data["subscriptions"] = self._gy2_subscription_rows()
        # 兼容旧 overview 字段名
        data.setdefault("overall", "healthy" if data.get("healthy") else "warning")
        return {"success": True, "data": data}

    def api_v2_match_preview(self, subscribe_id: int = 0) -> Dict[str, Any]:
        finder = getattr(self, "_find_subscription", None)
        subscribe = finder(int(subscribe_id or 0)) if callable(finder) else None
        if not subscribe:
            return {"success": False, "message": "订阅不存在"}
        index = self.get_data("channel_index") or {}
        items = list(index.get("items") or [])
        matched = self._gy2_orchestrator().match_channel_entries(subscribe, items)
        return {
            "success": True,
            "data": {
                "accepted": len(matched["accepted"]),
                "rejected": [
                    {
                        "reason_code": row["result"]["reason_code"],
                        "message": row["result"]["message"],
                        "title": row["result"].get("cleaned_title"),
                        "message_id": (row.get("entry") or {}).get("message_id"),
                    }
                    for row in matched["rejected"][:50]
                ],
            },
        }

    def _canonical_transfer_name_v11226(self, subscribe: Any, original: Any) -> str:
        """覆盖 1.12.26 命名，统一走 2.0 NamingPolicy。"""
        return NamingPolicy().canonical_name(
            subscribe,
            original,
            is_movie=self._gy2_orchestrator()._is_movie(subscribe),
        )

    def _gy2_legacy_transfer_inner(self, subscribe: Any, force: bool = False, refresh_channel: bool = True):
        """显式调用下一层 mixin/legacy，供编排器使用，避免再入本包装。"""
        return super()._try_transfer_subscription_inner(
            subscribe, force=force, refresh_channel=refresh_channel
        )

    def _try_transfer_subscription_inner(self, subscribe: Any, force: bool = False, refresh_channel: bool = True):
        """匹配预检写轨迹后，委托编排器调用旧内核。"""
        orch = self._gy2_orchestrator()
        try:
            index = self.get_data("channel_index") or {}
            items = list(index.get("items") or [])
            if items:
                orch.match_channel_entries(subscribe, items)
        except Exception as err:
            self._plugin_log("WARNING", "【GY2】【匹配】预检失败：%s", str(err)[:200])
        return orch.run_subscription(subscribe, force=force, refresh_channel=refresh_channel)

    def _gy2_calendar_nodes(self) -> List[Dict[str, Any]]:
        """只取周日历卡片，避免整页旧 DOM 拼装。"""
        try:
            snap = getattr(self, "_weekly_calendar_snapshot_v1121", None)
            builder = getattr(self, "_weekly_page_v1121", None)
            if callable(snap) and callable(builder):
                return [builder(snap())]
        except Exception as err:
            return [{
                "component": "VAlert",
                "props": {
                    "type": "warning",
                    "variant": "tonal",
                    "text": f"追剧日历暂时无法生成：{str(err)[:220]}",
                },
            }]
        return []
