"""光鸭转存助手 v1.9.1 紧凑状态页。

旧版状态页由多个历史 mixin 的 get_page 逐层叠加，结果是正常订阅、诊断、来源任务、
路由健康和高级信息全部铺在同一页。本层作为最终展示层，不再拼接旧页面。

首页固定为 5 个区域：总览、关键指标、需要处理、正在处理、系统状态。
“等待新资源”属于正常状态，只统计数量，不进入“需要处理”；完成历史、长日志和正常订阅
也不在首页逐条展示。详细数据继续由既有 API、自检和 resource plan 提供。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

from .source_types_v180 import SOURCE_INFLIGHT_STATES, SOURCE_PENDING_STATES


_SOURCE_STATE_TEXT = {
    "new": "待处理",
    "retry": "自动重试中",
    "dispatching": "正在解析",
    "submitted": "已提交",
    "queued": "排队中",
    "waiting": "云添加中",
    "completed": "已完成",
    "failed": "失败",
    "needs_review": "待确认",
    "disabled": "已停用",
}

_TRANSFER_ACTIVE_STATES = {"submitting", "submitted", "task_confirmed", "verifying"}


class GuangYaStatusUiMixin:
    """最终状态页展示层；由 PlannerSafety 置于运行 MRO 最前端。"""

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

    def _status_transfer_rows_v191(self) -> List[Dict[str, Any]]:
        rows = []
        for key, raw in (self.get_data("transfer_jobs") or {}).items():
            if not isinstance(raw, dict):
                continue
            row = dict(raw)
            row["_key"] = str(key)
            rows.append(row)
        rows.sort(
            key=lambda row: str(row.get("updated_at") or row.get("time") or row.get("submitted_at") or ""),
            reverse=True,
        )
        return rows

    def _status_overview_v191(self) -> Dict[str, Any]:
        report = dict(self._build_selfcheck() or {})
        sources = self._status_source_rows_v191()
        transfer_rows = self._status_transfer_rows_v191()
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
            if str(row.get("state") or "") in {"failed", "needs_review"}
        ]
        active_sources = [
            row for row in sources
            if str(row.get("state") or "new") in SOURCE_PENDING_STATES | SOURCE_INFLIGHT_STATES
        ]
        active_transfer_rows = [
            row for row in transfer_rows
            if str(row.get("status") or "") in _TRANSFER_ACTIVE_STATES
        ]
        failed_transfer_rows = [
            row for row in transfer_rows
            if str(row.get("status") or "") == "failed"
        ]
        unresolved_plans = [row for row in plans if row.get("uncovered")]

        attention_count = len(critical_checks) + len(attention_sources) + len(failed_transfer_rows)
        overall = "healthy"
        if critical_checks:
            overall = "error"
        elif attention_count:
            overall = "warning"

        overview = {
            "overall": overall,
            "healthy": not bool(critical_checks),
            "attention_count": attention_count,
            "selected": self._safe_int(report.get("selected"), len(self._selected_subscriptions)),
            "channel_count": len(index.get("items") or []),
            "channel_updated": str(index.get("time") or last_run.get("time") or "-"),
            "channel_errors": len(index.get("errors") or []),
            "sources": source_summary,
            "critical_checks": critical_checks,
            "warning_checks": warning_checks,
            "attention_sources": attention_sources[:8],
            "failed_transfer_rows": failed_transfer_rows[:8],
            "active_sources": active_sources[:8],
            "active_transfer_rows": active_transfer_rows[:8],
            "waiting_resource_count": len(unresolved_plans),
            "resource_plan_count": len(plans),
            "version": str(getattr(self, "plugin_version", "")),
            "build": str(getattr(self, "build_id", "")),
        }

        viewing = self.get_data("viewing_session_state") or {}
        if not isinstance(viewing, dict):
            viewing = {}
        active_node = str(viewing.get("active_node") or "")
        node_row = dict(((viewing.get("nodes") or {}).get(active_node) or {})) if active_node else {}
        overview["viewing"] = {
            "enabled": bool(getattr(self, "_viewing_enabled", False)),
            "active_node": active_node,
            "status": str(
                node_row.get("status")
                or ("waiting" if getattr(self, "_viewing_enabled", False) else "disabled")
            ),
            "verified": bool(node_row.get("verified")),
            "login_mode": str(node_row.get("login_mode") or ""),
        }

        xunlei = self.get_data("xunlei_flash_state") or {}
        items = (
            (xunlei.get("items") or {}).values()
            if isinstance(xunlei, dict) and isinstance(xunlei.get("items"), dict)
            else []
        )
        completed = failed = 0
        for raw in items:
            if not isinstance(raw, dict):
                continue
            state = str(raw.get("state") or "")
            if state == "completed":
                completed += 1
            elif state == "failed":
                failed += 1
        overview["xunlei_flash"] = {
            "enabled": bool(getattr(self, "_xunlei_flash_enabled", True)),
            "completed": completed,
            "failed": failed,
        }
        return overview

    def api_status_overview(self) -> Dict[str, Any]:
        """返回首页使用的轻量汇总，供后续独立前端复用。"""
        return {"success": True, "data": self._status_overview_v191()}

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
    def _metric(title: str, value: str, *, alert_type: str = "info", subtitle: str = "") -> Dict[str, Any]:
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
                    "density": "compact",
                    "title": title,
                    "text": text,
                },
            }],
        }

    def _source_title(self, row: Dict[str, Any]) -> str:
        sid = self._safe_int(row.get("subscribe_id"))
        subscribe = self._find_subscription(sid) if sid else None
        name = str(getattr(subscribe, "name", "") or row.get("resolved_name") or row.get("name") or "未命名资源")
        source_type = str(row.get("type") or "source").upper()
        return f"{source_type} · {name}"

    def _transfer_title(self, row: Dict[str, Any]) -> str:
        sid = self._safe_int(row.get("subscribe_id") or row.get("sid"))
        subscribe = self._find_subscription(sid) if sid else None
        name = str(getattr(subscribe, "name", "") or row.get("name") or "光鸭转存任务")
        return f"光鸭转存 · {name}"

    def _source_trace(self, row: Dict[str, Any]) -> str:
        source_id = str(row.get("id") or "").strip()
        task_id = str(row.get("task_id") or "").strip()
        trace = f"追踪 source #{source_id[:16] or '-'}"
        if task_id:
            trace += f" · task {task_id[:20]}"
        return trace

    @staticmethod
    def _source_action_hint(state: str, row: Dict[str, Any] | None = None) -> str:
        error = str((row or {}).get("last_error") or "")
        if state == "needs_review" and "REMOTE_VERIFY_TIMEOUT" in error:
            return "建议：先刷新云任务并确认目标目录/媒体库；若仍缺失，可让后续候选继续或手动重试该来源。"
        if state == "needs_review":
            return "建议：核对集号后再执行来源重试。"
        if state == "failed":
            return "建议：先刷新云任务确认最新状态，再执行来源重试。"
        return ""

    def _attention_cards(self, overview: Dict[str, Any]) -> List[Dict[str, Any]]:
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
            error = str(row.get("last_error") or "")
            detail = error or ("集号置信度不足，已停止自动拆包" if state == "needs_review" else "云添加任务失败")
            hint = self._source_action_hint(state, row)
            text = f"{_SOURCE_STATE_TEXT.get(state, state)} · {detail}\n（{self._source_trace(row)}）"
            if hint:
                text += f"\n{hint}"
            cards.append({
                "component": "VAlert",
                "props": {
                    "type": "warning" if state == "needs_review" else "error",
                    "variant": "tonal",
                    "density": "compact",
                    "class": "mb-2",
                    "title": self._source_title(row),
                    "text": text,
                },
            })

        for row in overview.get("failed_transfer_rows") or []:
            if len(cards) >= 8:
                break
            error = str(row.get("error") or row.get("message") or "转存任务失败")[:300]
            cards.append({
                "component": "VAlert",
                "props": {
                    "type": "error",
                    "variant": "tonal",
                    "density": "compact",
                    "class": "mb-2",
                    "title": self._transfer_title(row),
                    "text": error,
                },
            })
        return cards[:8]

    def _active_cards(self, overview: Dict[str, Any]) -> List[Dict[str, Any]]:
        cards: List[Dict[str, Any]] = []

        for row in overview.get("active_transfer_rows") or []:
            cards.append({
                "component": "VAlert",
                "props": {
                    "type": "info",
                    "variant": "tonal",
                    "density": "compact",
                    "class": "mb-2",
                    "title": self._transfer_title(row),
                    "text": "已提交到光鸭，等待目标文件落盘确认",
                },
            })
            if len(cards) >= 6:
                return cards

        for row in overview.get("active_sources") or []:
            state = str(row.get("state") or "new")
            progress = max(0, min(100, self._safe_int(row.get("progress"))))
            episodes = row.get("resolved_episodes") or row.get("target_episodes") or []
            episode_text = ", ".join(f"E{self._safe_int(value):02d}" for value in episodes[:12])
            error = str(row.get("last_error") or "")
            if state == "waiting" and error.startswith("PENDING_VERIFY:"):
                try:
                    since = float(row.get("pending_verify_since") or 0)
                except (TypeError, ValueError):
                    since = 0.0
                waited = max(0, int(time.time() - since)) if since > 0 else 0
                if waited >= 60:
                    wait_text = f" · 已等待 {waited // 60} 分钟"
                else:
                    wait_text = " · 刚进入核验"
                detail = f"远端任务已完成，正在核验正片{wait_text}"
            else:
                detail = f"{_SOURCE_STATE_TEXT.get(state, state)} · {progress}%"
            if episode_text:
                detail += f" · {episode_text}"
            detail += f"\n（{self._source_trace(row)}）"
            cards.append({
                "component": "VAlert",
                "props": {
                    "type": "info" if state in SOURCE_INFLIGHT_STATES else "warning",
                    "variant": "tonal",
                    "density": "compact",
                    "class": "mb-2",
                    "title": self._source_title(row),
                    "text": detail,
                },
            })
            if len(cards) >= 6:
                break
        return cards

    def get_page(self):
        """返回单屏状态页，不再调用 super().get_page 拼接历史诊断卡。"""
        overview = self._status_overview_v191()
        sources = overview["sources"]
        viewing = dict(overview.get("viewing") or {})
        xunlei = dict(overview.get("xunlei_flash") or {})
        active_node = str(viewing.get("active_node") or "-")
        viewing_state = str(viewing.get("status") or "-")
        attention_cards = self._attention_cards(overview)
        active_cards = self._active_cards(overview)

        if overview["overall"] == "healthy":
            overall_title = "运行正常"
            overall_type = "success"
        elif overview["overall"] == "error":
            overall_title = "存在关键异常"
            overall_type = "error"
        else:
            overall_title = "有待处理事项"
            overall_type = "warning"

        hero = {
            "component": "VCard",
            "props": {"variant": "flat", "class": "mb-3"},
            "content": [
                {"component": "VCardTitle", "text": "光鸭转存助手"},
                {
                    "component": "VCardText",
                    "text": (
                        f"{overall_title} · 最近刷新 {overview['channel_updated']}。\n"
                        "资源策略：观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K。\n"
                        "Magnet/ED2K 使用光鸭原生云添加。"
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
                {
                    "component": "VAlert",
                    "props": {
                        "type": "info",
                        "variant": "tonal",
                        "density": "compact",
                        "class": "mt-2",
                        "text": (
                            "操作说明：\n"
                            "1) 刷新云任务只轮询已有 taskId，不会重复创建云任务；\n"
                            "2) 手动重试仅在失败/待确认状态下建议使用。"
                        ),
                    },
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
                        self._metric("固定转存", str(overview["selected"]), alert_type="info", subtitle="MoviePilot 订阅"),
                        self._metric(
                            "正在处理",
                            str(len(overview["active_transfer_rows"]) + len(overview["active_sources"])),
                            alert_type="info",
                            subtitle="转存 + 云添加",
                        ),
                        self._metric(
                            "需要处理",
                            str(overview["attention_count"]),
                            alert_type="warning" if overview["attention_count"] else "success",
                            subtitle="失败 / 待确认",
                        ),
                        self._metric(
                            "等待资源",
                            str(overview["waiting_resource_count"]),
                            alert_type="info",
                            subtitle="正常等待，不算异常",
                        ),
                    ],
                },
            ],
        }

        attention = {
            "component": "VCard",
            "props": {"variant": "flat", "class": "mb-3"},
            "content": [
                {"component": "VCardTitle", "text": "需要处理"},
                {
                    "component": "VCardText",
                    "text": (
                        "这里只显示真正需要干预的异常；自动重试、等待新资源和正常订阅不会占页面。"
                        if attention_cards else "当前没有需要人工处理的事项。"
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
                            "text": "关键检查正常，没有失败或低置信待确认任务。",
                        },
                    }]
                ),
            ],
        }

        active = {
            "component": "VCard",
            "props": {"variant": "flat", "class": "mb-3"},
            "content": [
                {"component": "VCardTitle", "text": "正在处理"},
                {
                    "component": "VCardText",
                    "text": (
                        "只显示当前在途任务，最多 6 条；完成历史不再重复铺在首页。"
                        if active_cards else "当前没有正在处理的转存或云添加任务。"
                    ),
                },
                *active_cards,
            ],
        }

        checks = list(self._build_selfcheck().get("checks") or [])
        check_map = {str(item.get("key") or ""): item for item in checks if isinstance(item, dict)}

        def flag(key: str) -> str:
            return "正常" if (check_map.get(key) or {}).get("ok") else "异常"

        system = {
            "component": "VCard",
            "props": {"variant": "flat", "class": "mb-3"},
            "content": [
                {"component": "VCardTitle", "text": "系统状态"},
                {
                    "component": "VCardText",
                    "text": (
                        f"核心检查：登录 {flag('guangya_runtime')} / 搜索 {flag('search_guard')} / "
                        f"RSS {flag('match_guard')} / 下载 {flag('download_guard')} / 原生云添加 {flag('native_offline')}。\n"
                        f"索引 {overview['channel_count']} 条，最近错误 {overview['channel_errors']} 个；"
                        f"Magnet {sources['magnet']}，ED2K {sources['ed2k']}，"
                        f"计划 {overview['resource_plan_count']} 个。\n"
                        "详细诊断通过“运行自检”、/resource/plan 和 /status/overview 查看，首页不再展示长日志。\n"
                        f"观影：{viewing_state} · 当前节点 {active_node} · "
                        f"迅雷秒传：完成 {int(xunlei.get('completed') or 0)} / "
                        f"失败 {int(xunlei.get('failed') or 0)}。"
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
