"""光鸭转存助手 v1.9.1 紧凑状态页。

旧版状态页由 legacy/routing/experience/reliability/multisource/planner 多层 get_page 逐层
prepend 卡片，功能完整但信息重复、层级过深。本层作为最终展示层，不再拼接旧页面，而是把
底层已有状态汇总成 5 个固定区域：总览、关键指标、需要处理、正在处理、系统状态。

原则：
- 首页只显示“现在怎么样、哪里有问题、正在做什么”；
- 正常诊断不逐条铺开，只有异常才展开；
- 历史、ResourceGroup 细节、自检明细继续通过现有 API 提供，不塞进首页；
- 不展示原始 Magnet/ED2K URI、tracker、长日志或完整 task 历史。
"""

from __future__ import annotations

from typing import Any, Dict, List

from .source_types_v180 import SOURCE_INFLIGHT_STATES, SOURCE_PENDING_STATES


_SOURCE_STATE_TEXT = {
    "new": "待处理",
    "retry": "等待重试",
    "dispatching": "正在解析",
    "submitted": "已提交",
    "queued": "排队中",
    "waiting": "云添加中",
    "completed": "已完成",
    "failed": "失败",
    "needs_review": "待确认",
    "disabled": "已停用",
}


class GuangYaStatusUiMixin:
    """最终状态页展示层；必须位于插件 MRO 第一位。"""

    build_id = "20260901-r3"

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return int(default)

    def _status_source_rows_v191(self) -> List[Dict[str, Any]]:
        rows = [dict(row) for row in self._source_store()["items"].values() if isinstance(row, dict)]
        rows.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
        return rows

    def _status_diagnosis_rows_v191(self) -> List[Dict[str, Any]]:
        selected_ids = set(self._selected_subscriptions)
        rows: List[Dict[str, Any]] = []
        for subscribe in self._list_subscriptions(None):
            sid = self._safe_int(getattr(subscribe, "id", 0))
            if not sid or sid not in selected_ids:
                continue
            try:
                row = dict(self._diagnose_subscription(subscribe) or {})
            except Exception as err:
                row = {
                    "id": sid,
                    "name": str(getattr(subscribe, "name", "") or "未命名订阅"),
                    "severity": "warning",
                    "reason": f"状态诊断暂不可用：{err}",
                    "done": 0,
                    "total": 0,
                    "lack": 0,
                }
            rows.append(row)
        return rows

    def _status_overview_v191(self) -> Dict[str, Any]:
        report = dict(self._build_selfcheck() or {})
        sources = self._status_source_rows_v191()
        diagnoses = self._status_diagnosis_rows_v191()
        index = self.get_data("channel_index") or {}
        last_run = self.get_data("last_run") or {}
        plans = list((self.api_resource_plan().get("data") or []))

        source_summary = {
            "total": len(sources),
            "magnet": 0,
            "ed2k": 0,
            "pending": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "review": 0,
        }
        for row in sources:
            source_type = str(row.get("type") or "").lower()
            if source_type in {"magnet", "ed2k"}:
                source_summary[source_type] += 1
            state = str(row.get("state") or "new")
            if state in SOURCE_PENDING_STATES:
                source_summary["pending"] += 1
            elif state in SOURCE_INFLIGHT_STATES:
                source_summary["running"] += 1
            elif state == "completed":
                source_summary["completed"] += 1
            elif state == "failed":
                source_summary["failed"] += 1
            elif state == "needs_review":
                source_summary["review"] += 1

        critical_checks = [
            dict(item) for item in (report.get("checks") or [])
            if isinstance(item, dict) and item.get("critical") and not item.get("ok")
        ]
        warning_checks = [
            dict(item) for item in (report.get("checks") or [])
            if isinstance(item, dict) and not item.get("critical") and not item.get("ok")
        ]

        attention_sources = [
            row for row in sources
            if str(row.get("state") or "") in {"failed", "needs_review", "retry"}
        ]
        attention_subscriptions = [
            row for row in diagnoses
            if str(row.get("severity") or "").lower() in {"warning", "error"}
        ]
        active_sources = [
            row for row in sources
            if str(row.get("state") or "new") in SOURCE_PENDING_STATES | SOURCE_INFLIGHT_STATES
        ]

        unresolved_plans = [row for row in plans if row.get("uncovered")]
        attention_count = (
            len(critical_checks)
            + len(attention_sources)
            + len(attention_subscriptions)
            + len(unresolved_plans)
        )
        overall = "healthy"
        if critical_checks:
            overall = "error"
        elif attention_count:
            overall = "warning"

        return {
            "overall": overall,
            "healthy": not bool(critical_checks),
            "attention_count": attention_count,
            "selected": self._safe_int(report.get("selected"), len(self._selected_subscriptions)),
            "channel_count": len(index.get("items") or []),
            "channel_updated": str(index.get("time") or last_run.get("time") or "-"),
            "channel_errors": len(index.get("errors") or []),
            "pending_transfer_jobs": self._safe_int(report.get("pending_jobs")),
            "failed_transfer_jobs": self._safe_int(report.get("failed_jobs")),
            "sources": source_summary,
            "critical_checks": critical_checks,
            "warning_checks": warning_checks,
            "attention_sources": attention_sources[:8],
            "attention_subscriptions": attention_subscriptions[:8],
            "active_sources": active_sources[:8],
            "unresolved_plans": unresolved_plans[:8],
            "resource_plan_count": len(plans),
            "version": str(getattr(self, "plugin_version", "")),
            "build": str(getattr(self, "build_id", "")),
        }

    def api_status_overview(self) -> Dict[str, Any]:
        data = self._status_overview_v191()
        return {"success": True, "data": data}

    def get_api(self) -> List[Dict[str, Any]]:
        apis = list(super().get_api() or [])
        if not any(str(item.get("path") or "") == "/status/overview" for item in apis if isinstance(item, dict)):
            apis.append({
                "path": "/status/overview",
                "endpoint": self.api_status_overview,
                "methods": ["GET"],
                "summary": "读取紧凑状态页汇总",
            })
        return apis

    @staticmethod
    def _status_metric_v191(title: str, value: str, *, alert_type: str = "info", subtitle: str = "") -> Dict[str, Any]:
        text = str(value)
        if subtitle:
            text += f"\n{subtitle}"
        return {
            "component": "VCol",
            "props": {"cols": 6, "md": 3},
            "content": [{
                "component": "VAlert",
                "props": {
                    "type": alert_type,
                    "variant": "tonal",
                    "title": title,
                    "text": text,
                    "density": "compact",
                },
            }],
        }

    def _status_attention_cards_v191(self, overview: Dict[str, Any]) -> List[Dict[str, Any]]:
        cards: List[Dict[str, Any]] = []

        for item in overview.get("critical_checks") or []:
            cards.append({
                "component": "VAlert",
                "props": {
                    "type": "error",
                    "variant": "tonal",
                    "density": "compact",
                    "class": "mb-2",
                    "title": str(item.get("label") or "关键检查失败"),
                    "text": str(item.get("detail") or "需要检查插件运行状态"),
                },
            })

        for row in overview.get("attention_sources") or []:
            state = str(row.get("state") or "")
            sid = self._safe_int(row.get("subscribe_id"))
            subscribe = self._find_subscription(sid) if sid else None
            name = str(getattr(subscribe, "name", "") or row.get("resolved_name") or row.get("name") or "未命名资源")
            source_type = str(row.get("type") or "source").upper()
            error = str(row.get("last_error") or "")
            if state == "needs_review":
                detail = error or "集号置信度不足，已停止自动拆包"
            elif state == "retry":
                detail = error or "上次处理失败，等待自动重试"
            else:
                detail = error or "云添加任务失败"
            cards.append({
                "component": "VAlert",
                "props": {
                    "type": "warning" if state in {"needs_review", "retry"} else "error",
                    "variant": "tonal",
                    "density": "compact",
                    "class": "mb-2",
                    "title": f"{source_type} · {name}",
                    "text": f"{_SOURCE_STATE_TEXT.get(state, state)} · {detail}",
                },
            })

        for row in overview.get("attention_subscriptions") or []:
            if len(cards) >= 8:
                break
            done = self._safe_int(row.get("done"))
            total = self._safe_int(row.get("total"))
            lack = self._safe_int(row.get("lack"))
            progress = f"{done}/{total}，缺 {lack} 集" if total else "进度待确认"
            cards.append({
                "component": "VAlert",
                "props": {
                    "type": "warning" if str(row.get("severity") or "") != "error" else "error",
                    "variant": "tonal",
                    "density": "compact",
                    "class": "mb-2",
                    "title": f"#{row.get('id')} {row.get('name') or '未命名订阅'}",
                    "text": f"{row.get('reason') or '需要检查'} · {progress}",
                },
            })

        for row in overview.get("unresolved_plans") or []:
            if len(cards) >= 8:
                break
            name = str(row.get("name") or row.get("title") or f"订阅 #{row.get('subscribe_id') or '-'}")
            uncovered = row.get("uncovered") or []
            episodes = ", ".join(f"E{self._safe_int(value):02d}" for value in uncovered[:16])
            cards.append({
                "component": "VAlert",
                "props": {
                    "type": "warning",
                    "variant": "tonal",
                    "density": "compact",
                    "class": "mb-2",
                    "title": f"资源暂未覆盖 · {name}",
                    "text": f"仍缺：{episodes or '待确认'}；会继续等待光鸭 / Magnet / ED2K 后续候选。",
                },
            })

        return cards[:8]

    def _status_active_cards_v191(self, overview: Dict[str, Any]) -> List[Dict[str, Any]]:
        cards: List[Dict[str, Any]] = []
        for row in overview.get("active_sources") or []:
            sid = self._safe_int(row.get("subscribe_id"))
            subscribe = self._find_subscription(sid) if sid else None
            name = str(getattr(subscribe, "name", "") or row.get("resolved_name") or row.get("name") or "未命名资源")
            state = str(row.get("state") or "new")
            source_type = str(row.get("type") or "source").upper()
            progress = max(0, min(100, self._safe_int(row.get("progress"))))
            episodes = row.get("resolved_episodes") or row.get("target_episodes") or []
            episode_text = ", ".join(f"E{self._safe_int(value):02d}" for value in episodes[:12])
            detail = f"{_SOURCE_STATE_TEXT.get(state, state)} · {progress}%"
            if episode_text:
                detail += f" · {episode_text}"
            cards.append({
                "component": "VAlert",
                "props": {
                    "type": "info" if state in SOURCE_INFLIGHT_STATES else "warning",
                    "variant": "tonal",
                    "density": "compact",
                    "class": "mb-2",
                    "title": f"{source_type} · {name}",
                    "text": detail,
                },
            })
        return cards[:6]

    def get_page(self):
        """返回新的单屏状态页，不再拼接旧版逐层诊断卡。"""
        overview = self._status_overview_v191()
        source_summary = overview["sources"]
        overall_type = "success" if overview["overall"] == "healthy" else ("error" if overview["overall"] == "error" else "warning")
        overall_title = "运行正常" if overview["overall"] == "healthy" else ("存在关键异常" if overview["overall"] == "error" else "有待处理事项")

        hero = {
            "component": "VCard",
            "props": {"variant": "flat", "class": "mb-3"},
            "content": [
                {"component": "VCardTitle", "text": "光鸭转存助手"},
                {
                    "component": "VCardText",
                    "text": (
                        f"{overall_title} · 固定转存 {overview['selected']} 个 · "
                        f"频道最近刷新 {overview['channel_updated']}。"
                        " 资源策略：光鸭直接转存 > Magnet > ED2K；Magnet/ED2K 使用光鸭原生云添加。"
                    ),
                },
                {
                    "component": "VCardActions",
                    "content": [
                        {
                            "component": "VBtn",
                            "props": {"size": "small", "variant": "outlined", "prepend-icon": "mdi-refresh"},
                            "text": "刷新频道",
                            "events": {"click": {"api": "plugin/GuangYaTransferAssistant/refresh", "method": "post"}},
                        },
                        {
                            "component": "VBtn",
                            "props": {"size": "small", "variant": "outlined", "prepend-icon": "mdi-cloud-sync-outline"},
                            "text": "刷新云任务",
                            "events": {"click": {"api": "plugin/GuangYaTransferAssistant/offline/refresh", "method": "post"}},
                        },
                        {
                            "component": "VBtn",
                            "props": {"size": "small", "variant": "text", "prepend-icon": "mdi-stethoscope"},
                            "text": "运行自检",
                            "events": {"click": {"api": "plugin/GuangYaTransferAssistant/selfcheck", "method": "post"}},
                        },
                    ],
                },
            ],
        }

        metrics = {
            "component": "VCard",
            "props": {"variant": "flat", "class": "mb-3"},
            "content": [
                {"component": "VCardTitle", "text": "当前状态"},
                {
                    "component": "VRow",
                    "props": {"class": "px-2 pb-2"},
                    "content": [
                        self._status_metric_v191(
                            "需要处理",
                            str(overview["attention_count"]),
                            alert_type="warning" if overview["attention_count"] else "success",
                            subtitle="只统计需要你关注的事项",
                        ),
                        self._status_metric_v191(
                            "正在处理",
                            str(source_summary["pending"] + source_summary["running"] + overview["pending_transfer_jobs"]),
                            alert_type="info",
                            subtitle="转存 + 云添加",
                        ),
                        self._status_metric_v191(
                            "来源",
                            str(source_summary["total"]),
                            alert_type="info",
                            subtitle=f"Magnet {source_summary['magnet']} · ED2K {source_summary['ed2k']}",
                        ),
                        self._status_metric_v191(
                            "频道索引",
                            str(overview["channel_count"]),
                            alert_type="warning" if overview["channel_errors"] else "success",
                            subtitle=f"最近错误 {overview['channel_errors']} 个",
                        ),
                    ],
                },
            ],
        }

        attention_cards = self._status_attention_cards_v191(overview)
        attention = {
            "component": "VCard",
            "props": {"variant": "flat", "class": "mb-3"},
            "content": [
                {"component": "VCardTitle", "text": "需要处理"},
                {
                    "component": "VCardText",
                    "text": (
                        "这里只显示异常、待确认和未覆盖资源；正常订阅不会占页面。"
                        if attention_cards else "当前没有需要人工处理的异常。"
                    ),
                },
                *(
                    attention_cards
                    if attention_cards
                    else [{
                        "component": "VAlert",
                        "props": {
                            "type": "success",
                            "variant": "tonal",
                            "density": "compact",
                            "text": "所有关键检查正常，当前没有失败或待确认来源。",
                        },
                    }]
                ),
            ],
        }

        active_cards = self._status_active_cards_v191(overview)
        active = {
            "component": "VCard",
            "props": {"variant": "flat", "class": "mb-3"},
            "content": [
                {"component": "VCardTitle", "text": "正在处理"},
                {
                    "component": "VCardText",
                    "text": (
                        "只保留当前在途的 Magnet/ED2K 云添加；完成历史不在首页重复铺开。"
                        if active_cards else "当前没有正在运行的 Magnet/ED2K 云添加任务。"
                    ),
                },
                *active_cards,
            ],
        }

        checks = list(self._build_selfcheck().get("checks") or [])
        check_map = {str(item.get("key") or ""): item for item in checks if isinstance(item, dict)}
        def flag(key: str) -> str:
            item = check_map.get(key) or {}
            return "正常" if item.get("ok") else "异常"

        system = {
            "component": "VCard",
            "props": {"variant": "flat", "class": "mb-3"},
            "content": [
                {"component": "VCardTitle", "text": "系统状态"},
                {
                    "component": "VCardText",
                    "text": (
                        f"光鸭登录：{flag('guangya_runtime')} · "
                        f"搜索分流：{flag('search_guard')} · "
                        f"RSS 门禁：{flag('match_guard')} · "
                        f"下载断路器：{flag('download_guard')} · "
                        f"原生云添加：{flag('native_offline')}。\n"
                        f"ResourceGroup 计划 {overview['resource_plan_count']} 个 · "
                        f"低置信待确认 {source_summary['review']} 个 · "
                        f"云添加失败 {source_summary['failed']} 个。\n"
                        "详细检查继续通过“运行自检”和 /resource/plan、/status/overview API 获取，首页不再展示长日志。"
                    ),
                },
                {
                    "component": "VAlert",
                    "props": {
                        "type": overall_type,
                        "variant": "tonal",
                        "density": "compact",
                        "text": f"v{overview['version']} · build {overview['build']}",
                    },
                },
            ],
        }

        return [hero, metrics, attention, active, system]


__all__ = ["GuangYaStatusUiMixin"]
