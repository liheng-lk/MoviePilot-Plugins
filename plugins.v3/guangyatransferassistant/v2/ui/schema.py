"""声明式配置页与数据页（禁止对旧 JSON 树做 mutation）。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


_CARD = "border:1px solid rgba(var(--v-border-color),.10);border-radius:16px;"


def _col(content: List[Dict[str, Any]], *, cols: int = 12, md: Optional[int] = None) -> Dict[str, Any]:
    props: Dict[str, Any] = {"cols": cols}
    if md is not None:
        props["md"] = md
    return {"component": "VCol", "props": props, "content": content}


def _switch(model: str, label: str, *, md: int = 3, hint: str = "") -> Dict[str, Any]:
    props: Dict[str, Any] = {"model": model, "label": label, "density": "compact", "color": "primary", "inset": True}
    if hint:
        props.update({"hint": hint, "persistent-hint": True})
    return _col([{"component": "VSwitch", "props": props}], md=md)


def _field(model: str, label: str, *, md: int = 4, component: str = "VTextField", **extra: Any) -> Dict[str, Any]:
    props = {
        "model": model,
        "label": label,
        "variant": "outlined",
        "density": "comfortable",
        **extra,
    }
    return _col([{"component": component, "props": props}], md=md)


def _textarea(model: str, label: str, *, md: int = 12, rows: int = 3, hint: str = "") -> Dict[str, Any]:
    props: Dict[str, Any] = {
        "model": model,
        "label": label,
        "rows": rows,
        "auto-grow": True,
        "variant": "outlined",
        "density": "comfortable",
    }
    if hint:
        props.update({"hint": hint, "persistent-hint": True})
    return _col([{"component": "VTextarea", "props": props}], md=md)


def _section(title: str, subtitle: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "component": "VCard",
        "props": {"variant": "flat", "class": "mb-4", "style": _CARD},
        "content": [{
            "component": "VCardText",
            "props": {"class": "pa-4"},
            "content": [
                {"component": "div", "props": {"style": "font-size:16px;font-weight:700;"}, "text": title},
                {"component": "div", "props": {"class": "mb-3", "style": "font-size:12px;opacity:.65;"}, "text": subtitle},
                *rows,
            ],
        }],
    }


def build_config_form(defaults: Dict[str, Any], *, subscription_props: Optional[Dict[str, Any]] = None) -> tuple[List[dict], Dict[str, Any]]:
    from ..config import CONFIG_DEFAULTS_V2

    merged = dict(CONFIG_DEFAULTS_V2)
    if isinstance(defaults, dict):
        merged.update(defaults)
    defaults = merged
    selected = dict(subscription_props or {
        "model": "selected_subscriptions",
        "items": [],
        "multiple": True,
        "chips": True,
    })
    selected.update({
        "model": "selected_subscriptions",
        "label": "固定接管的订阅",
        "multiple": True,
        "chips": True,
        "closable-chips": True,
        "clearable": True,
        "variant": "outlined",
        "density": "comfortable",
        "hint": "未勾选的订阅仍走 MoviePilot 原生下载。",
        "persistent-hint": True,
    })
    save_path = {
        "model": "save_path",
        "label": "光鸭目标文件夹",
        "variant": "outlined",
        "density": "comfortable",
    }

    hero = {
        "component": "VAlert",
        "props": {
            "type": "info",
            "variant": "tonal",
            "class": "mb-4",
            "title": "光鸭转存助手 2.0",
            "text": "优先级：观影迅雷秒传 → 光鸭直接转存 → Magnet → ED2K。匹配失败会留下可查原因，不再静默跳过。",
        },
    }

    takeover = _section(
        "接管",
        "开关、订阅与保存路径。",
        [
            {"component": "VRow", "content": [
                _switch("enabled", "启用插件"),
                _switch("notify", "任务通知"),
                _switch("sync_subscription_progress", "同步追剧进度"),
                _switch("protect_ongoing", "连载保护"),
            ]},
            {"component": "VRow", "content": [
                _col([{"component": "VAutocomplete", "props": selected}]),
            ]},
            {"component": "VRow", "content": [
                _col([{"component": "VCombobox", "props": save_path}], md=8),
                _switch("create_media_folder", "媒体名子文件夹", md=4),
            ]},
            {"component": "VRow", "content": [
                _switch("auto_transfer_on_refresh", "刷新后自动处理", md=4),
                _switch("media_only", "仅媒体/字幕", md=4),
                _switch("strict_subscription_rules", "遵循订阅质量规则", md=4),
            ]},
        ],
    )

    channels = _section(
        "频道",
        "自行按后缀添加 tgm 频道地址；每行一个。",
        [
            {"component": "VRow", "content": [
                _textarea("channel_urls", "资源频道地址", md=12, rows=4, hint="例如 https://tgm.li668.asia/regengguangya"),
            ]},
            {"component": "VRow", "content": [
                _field("refresh_minutes", "刷新间隔(分钟)", md=3, type="number"),
                _field("history_pages", "每频道历史页数", md=3, type="number"),
                _switch("proxy", "使用代理", md=3),
                _field("max_files_per_run", "每轮最大文件数", md=3, type="number"),
            ]},
        ],
    )

    viewing = _section(
        "观影 / 迅雷",
        "观影检索与迅雷秒传开关；账号细节仍走既有高级配置键。",
        [
            {"component": "VRow", "content": [
                _switch("viewing_enabled", "启用观影检索", md=4),
                _switch("xunlei_flash_enabled", "启用迅雷秒传", md=4),
                _switch("provider_auto_search", "外部补源自动搜索", md=4),
            ]},
            {"component": "VRow", "content": [
                _textarea("magnet_api_sources", "Magnet/ED2K 搜索接口", md=12, rows=3, hint="可选；每行一个 API。"),
            ]},
        ],
    )

    advanced = {
        "component": "VExpansionPanels",
        "props": {"class": "mb-4", "variant": "accordion"},
        "content": [{
            "component": "VExpansionPanel",
            "content": [
                {"component": "VExpansionPanelTitle", "text": "高级：重试 / 日历 / 清理"},
                {"component": "VExpansionPanelText", "content": [
                    {"component": "VRow", "content": [
                        _field("retry_minutes", "失败重试(分钟)", md=3, type="number"),
                        _field("ongoing_guard_days", "连载保护天数", md=3, type="number"),
                        _field("calendar_default_hour", "默认更新时刻", md=3, type="number"),
                        _field("calendar_early_hours", "提前提取小时", md=3, type="number"),
                    ]},
                    {"component": "VRow", "content": [
                        _switch("daily_summary", "每日摘要", md=4),
                        _field("summary_cron", "摘要 Cron", md=4),
                        _switch("clear_inventory", "清空库存(危险)", md=4, hint="下次保存后清空去重库存"),
                    ]},
                ]},
            ],
        }],
    }

    form = [
        {"component": "VForm", "content": [hero, takeover, channels, viewing, advanced]},
    ]
    return form, dict(defaults)


def _btn(text: str, event: str, *, color: str = "primary", variant: str = "flat") -> Dict[str, Any]:
    return {
        "component": "VBtn",
        "props": {"color": color, "variant": variant, "class": "mr-2 mb-2"},
        "text": text,
        "events": {"click": {"api": event, "method": "post"}},
    }


def build_data_page(
    *,
    calendar_nodes: Optional[List[Dict[str, Any]]] = None,
    subscription_rows: Optional[List[Dict[str, Any]]] = None,
    reject_rows: Optional[List[Dict[str, Any]]] = None,
    trace_rows: Optional[List[Dict[str, Any]]] = None,
    overview: Optional[Dict[str, Any]] = None,
) -> List[dict]:
    overview = overview or {}
    calendar_nodes = calendar_nodes or []
    subscription_rows = subscription_rows or []
    reject_rows = reject_rows or []
    trace_rows = trace_rows or []

    kpi = {
        "component": "VAlert",
        "props": {
            "type": "success" if overview.get("healthy", True) else "warning",
            "variant": "tonal",
            "class": "mb-4",
            "title": f"运行态 · 接管 {overview.get('selected', 0)} · 待处理 {overview.get('attention_count', 0)}",
            "text": str(overview.get("summary") or "2.0 运行台：订阅缺口、拒绝原因与主操作集中在此。"),
        },
    }

    actions = {
        "component": "VCard",
        "props": {"variant": "flat", "class": "mb-4", "style": _CARD},
        "content": [{
            "component": "VCardText",
            "content": [
                {"component": "div", "props": {"class": "mb-2", "style": "font-weight:700;"}, "text": "运行台"},
                {"component": "div", "props": {"class": "mb-3", "style": "font-size:12px;opacity:.65;"}, "text": "主操作：立即处理缺失 / 刷新频道 / 刷新云任务。诊断按钮在下方。"},
                {
                    "component": "div",
                    "content": [
                        _btn("立即处理缺失", "/api/v1/plugin/GuangYaTransferAssistant/console/process"),
                        _btn("刷新频道", "/api/v1/plugin/GuangYaTransferAssistant/refresh", color="secondary", variant="tonal"),
                        _btn("刷新云任务", "/api/v1/plugin/GuangYaTransferAssistant/offline/refresh", color="secondary", variant="tonal"),
                    ],
                },
            ],
        }],
    }

    sub_lines = []
    for row in subscription_rows[:40]:
        sub_lines.append({
            "component": "div",
            "props": {"class": "mb-2", "style": "font-size:13px;line-height:1.5;"},
            "text": (
                f"#{row.get('id')} {row.get('name')} · 缺口={row.get('missing') or '-'} · "
                f"在途={row.get('inflight') or '-'} · 阻塞={row.get('block_reason') or '无'}"
            ),
        })
    if not sub_lines:
        sub_lines = [{"component": "div", "props": {"style": "opacity:.6;"}, "text": "暂无接管订阅。"}]

    subscriptions = {
        "component": "VCard",
        "props": {"variant": "flat", "class": "mb-4", "style": _CARD},
        "content": [{
            "component": "VCardText",
            "content": [
                {"component": "div", "props": {"class": "mb-2", "style": "font-weight:700;"}, "text": "订阅进度"},
                *sub_lines,
            ],
        }],
    }

    reject_lines = []
    for row in reject_rows[:30]:
        reject_lines.append({
            "component": "div",
            "props": {"class": "mb-2", "style": "font-size:12px;"},
            "text": (
                f"{row.get('time')} · #{row.get('subscribe_id')} {row.get('title')} · "
                f"{row.get('reason_code')} · {row.get('message')}"
            ),
        })
    if not reject_lines:
        reject_lines = [{"component": "div", "props": {"style": "opacity:.6;"}, "text": "暂无“命中但拒绝”记录。"}]

    diagnostics = {
        "component": "VCard",
        "props": {"variant": "flat", "class": "mb-4", "style": _CARD},
        "content": [{
            "component": "VCardText",
            "content": [
                {"component": "div", "props": {"class": "mb-2", "style": "font-weight:700;"}, "text": "诊断"},
                {
                    "component": "div",
                    "props": {"class": "mb-3"},
                    "content": [
                        _btn("完整自检", "/api/v1/plugin/GuangYaTransferAssistant/diagnostics/full", color="secondary", variant="tonal"),
                        _btn("刷新轨迹", "/api/v1/plugin/GuangYaTransferAssistant/v2/traces", color="secondary", variant="tonal"),
                    ],
                },
                {"component": "div", "props": {"class": "mb-1", "style": "font-weight:600;"}, "text": "命中未转"},
                *reject_lines,
                {"component": "div", "props": {"class": "mt-4 mb-1", "style": "font-weight:600;"}, "text": "最近决策轨迹"},
                *[
                    {
                        "component": "div",
                        "props": {"class": "mb-1", "style": "font-size:12px;opacity:.85;"},
                        "text": f"{row.get('time')} · {row.get('stage')} · {row.get('decision')} · {row.get('reason_code')} · {row.get('message')}",
                    }
                    for row in (trace_rows[:20] or [{"time": "-", "stage": "-", "decision": "-", "reason_code": "-", "message": "暂无轨迹"}])
                ],
            ],
        }],
    }

    calendar = {
        "component": "VCard",
        "props": {"variant": "flat", "class": "mb-4", "style": _CARD},
        "content": [{
            "component": "VCardText",
            "content": [
                {"component": "div", "props": {"class": "mb-2", "style": "font-weight:700;"}, "text": "追剧"},
                *(calendar_nodes or [{"component": "div", "props": {"style": "opacity:.6;"}, "text": "日历由后台周快照提供；若为空将在下次刷新后出现。"}]),
            ],
        }],
    }

    return [kpi, calendar, actions, subscriptions, diagnostics]
