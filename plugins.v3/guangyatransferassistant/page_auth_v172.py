"""光鸭转存助手页面 API 与页面故障隔离兼容层。

MoviePilot V3 插件页面使用当前登录会话的 Bearer 鉴权。页面事件只传业务参数，
不把 API_TOKEN 作为 token/apikey 注入按钮参数。

状态页的“立即检查缺集/复查待落盘”不能在 HTTP 请求线程里同步跑完整频道读取、
分享解析和转存流程，否则前端会在网络稍慢时提示“服务无响应”。本层把这两类操作
送入插件已经存在的可靠后台合并队列，并立即返回标准三段式 Response envelope；
其余状态页操作也统一收口为严格的 success/message/data 三字段响应。

v1.10.2 追加页面故障隔离：新版控制台会同时读取自检、资源计划、频道缓存、Provider
配置和迅雷运行态。升级后任意一份旧缓存形态异常，或者任意运行时探针抛错，都不应让
MoviePilot 整个插件页返回“数据加载失败”。本层在不改变转存业务逻辑的前提下，对这些
只读页面数据做 fail-soft 包装：失败模块降级显示，控制台本身继续可用，并把详细异常写入
插件日志供排障。
"""

from __future__ import annotations

import functools
from typing import Any, Dict, List


_STATUS_ACTION_PATHS = {
    "/check_missing",
    "/recheck_pending",
    "/cancel_pending",
    "/reset_state",
    "/release_native",
    "/daily_summary",
    "/clear_plugin_logs",
}
_ASYNC_STATUS_PATHS = {
    "/check_missing": "状态页立即检查缺集",
    "/recheck_pending": "状态页复查待落盘",
}


def _response_envelope(result: Any, default_message: str = "操作完成") -> Dict[str, Any]:
    """把旧版插件 API 返回值规范成 MoviePilot V3 严格三段式响应。"""
    if isinstance(result, dict):
        success = bool(result.get("success", True))
        message = str(result.get("message") or (default_message if success else "操作失败"))
        data = {
            key: value
            for key, value in result.items()
            if key not in {"success", "message"}
        }
        return {
            "success": success,
            "message": message,
            "data": data or None,
        }
    return {
        "success": True,
        "message": default_message,
        "data": result,
    }


def _subscription_id(args: tuple, kwargs: dict) -> int:
    """从 FastAPI 绑定参数中稳健取得 subscribe_id。"""
    value = kwargs.get("subscribe_id")
    if value in (None, "") and args:
        value = args[0]
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _queue_status_action(path: str, endpoint: Any, *args, **kwargs) -> Dict[str, Any]:
    """校验状态页耗时操作并提交现有可靠后台队列，HTTP 立即返回。"""
    plugin = getattr(endpoint, "__self__", None)
    if plugin is None:
        return {
            "success": False,
            "message": "插件运行实例不可用，请刷新页面后重试",
            "data": None,
        }

    sid = _subscription_id(args, kwargs)
    subscribe = plugin._find_subscription(sid) if sid else None
    if not sid or subscribe is None:
        return {
            "success": False,
            "message": "订阅不存在",
            "data": {"subscribe_id": sid} if sid else None,
        }

    selected = {
        int(value)
        for value in (getattr(plugin, "_selected_subscriptions", None) or [])
        if str(value).isdigit() and int(value) > 0
    }
    if sid not in selected:
        return {
            "success": False,
            "message": "该订阅当前不是光鸭固定转存路线",
            "data": {"subscribe_id": sid},
        }

    runtime_check = getattr(plugin, "_runtime_is_current", None)
    if callable(runtime_check) and not runtime_check():
        return {
            "success": False,
            "message": "插件已热更新，请刷新当前页面后重试",
            "data": {"subscribe_id": sid},
        }

    # “立即检查缺集”保留原人工门禁：已有待落盘任务时不能强制重放旧消息。
    if path == "/check_missing":
        manual_guard = getattr(plugin, "_manual_transfer_guard", None)
        if callable(manual_guard):
            guard = manual_guard(subscribe)
            if guard:
                return _response_envelope(guard, default_message="检查被安全门禁阻止")

    trigger = _ASYNC_STATUS_PATHS[path]
    try:
        plugin._queue_async_route_check([sid], trigger=trigger)
        record_health = getattr(plugin, "_record_route_health", None)
        if callable(record_health):
            record_health(
                last_page_action_queued=trigger,
                last_page_action_id=sid,
                last_page_action_at=plugin._now_text(),
            )
        plugin._plugin_log(
            "INFO",
            "【光鸭转存助手】【页面操作】%s #%s %s 已进入后台队列，HTTP 请求立即返回",
            trigger,
            sid,
            getattr(subscribe, "name", ""),
        )
    except Exception as err:
        plugin._plugin_log(
            "EXCEPTION",
            "【光鸭转存助手】【页面操作】%s #%s 入队失败：%s",
            trigger,
            sid,
            err,
        )
        return {
            "success": False,
            "message": f"后台任务提交失败：{err}",
            "data": {"subscribe_id": sid},
        }

    return {
        "success": True,
        "message": "已进入后台检查队列，请稍后查看状态卡片或插件日志",
        "data": {
            "subscribe_id": sid,
            "queued": True,
            "action": path.lstrip("/"),
        },
    }


def _wrap_status_endpoint(path: str, endpoint: Any) -> Any:
    """保持原 FastAPI 签名，同时统一状态页操作响应。"""
    if path in _ASYNC_STATUS_PATHS:
        @functools.wraps(endpoint)
        def queued_endpoint(*args, **kwargs):
            return _queue_status_action(path, endpoint, *args, **kwargs)

        return queued_endpoint

    @functools.wraps(endpoint)
    def response_endpoint(*args, **kwargs):
        return _response_envelope(endpoint(*args, **kwargs))

    return response_endpoint


def force_bear_auth(routes: Any) -> List[Dict[str, Any]]:
    """统一 Bearer 鉴权，并给状态页按钮安装非阻塞/标准响应适配器。"""
    result: List[Dict[str, Any]] = []
    for route in list(routes or []):
        if not isinstance(route, dict):
            continue
        item = dict(route)
        item["auth"] = "bear"
        path = str(item.get("path") or "")
        endpoint = item.get("endpoint")
        if path in _STATUS_ACTION_PATHS and callable(endpoint):
            item["endpoint"] = _wrap_status_endpoint(path, endpoint)
        result.append(item)
    return result


def strip_page_api_secrets(node: Any) -> None:
    """递归移除状态页按钮中的 token/apikey，仅保留业务参数。"""
    if isinstance(node, dict):
        events = node.get("events")
        if isinstance(events, dict):
            click = events.get("click")
            if isinstance(click, dict) and str(click.get("api") or "").startswith(
                "plugin/GuangYaTransferAssistant/"
            ):
                params = click.get("params")
                if isinstance(params, dict):
                    params.pop("token", None)
                    params.pop("apikey", None)
        for value in node.values():
            strip_page_api_secrets(value)
    elif isinstance(node, list):
        for value in node:
            strip_page_api_secrets(value)


# ---------------------------------------------------------------------------
# v1.10.2 页面数据故障隔离
# ---------------------------------------------------------------------------

def _page_log_error(plugin: Any, stage: str, err: Exception) -> None:
    """页面降级只记录异常，不让记录异常本身再次影响页面返回。"""
    try:
        log = getattr(plugin, "_plugin_log", None)
        if callable(log):
            log(
                "EXCEPTION",
                "【光鸭转存助手】【页面降级】%s 读取失败，已隔离该模块：%s",
                stage,
                err,
            )
    except Exception:
        pass


def _page_mark_error(plugin: Any, stage: str, err: Exception) -> None:
    """记录当前一次页面构建的降级模块名称，前端只展示模块名而不泄露异常原文。"""
    _page_log_error(plugin, stage, err)
    try:
        rows = getattr(plugin, "_page_resilience_errors_v1102", None)
        if not isinstance(rows, list):
            rows = []
            setattr(plugin, "_page_resilience_errors_v1102", rows)
        if stage not in rows:
            rows.append(stage)
    except Exception:
        pass


def _fallback_overview(plugin: Any, stage: str = "状态汇总") -> Dict[str, Any]:
    """提供新控制台所需的完整最小字段，避免二次 KeyError。"""
    try:
        selected = len(list(getattr(plugin, "_selected_subscriptions", None) or []))
    except Exception:
        selected = 0
    return {
        "overall": "warning",
        "healthy": False,
        "attention_count": 0,
        "selected": selected,
        "channel_count": 0,
        "channel_updated": "-",
        "channel_errors": 0,
        "sources": {
            "total": 0,
            "magnet": 0,
            "ed2k": 0,
            "pending": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "review": 0,
        },
        "critical_checks": [],
        "warning_checks": [{
            "key": "page_data_degraded",
            "label": "页面状态数据已降级",
            "detail": f"{stage}暂时不可用，后台转存任务不会因此停止",
            "critical": False,
            "ok": False,
        }],
        "attention_sources": [],
        "failed_transfer_rows": [],
        "active_sources": [],
        "active_transfer_rows": [],
        "waiting_resource_count": 0,
        "resource_plan_count": 0,
        "version": str(getattr(plugin, "plugin_version", "")),
        "build": str(getattr(plugin, "build_id", "")),
        "viewing": {
            "enabled": bool(getattr(plugin, "_viewing_enabled", False)),
            "active_node": "",
            "status": "unknown",
            "verified": False,
            "login_mode": "",
        },
        "xunlei_flash": {
            "enabled": bool(getattr(plugin, "_xunlei_flash_enabled", True)),
            "completed": 0,
            "failed": 0,
        },
        "page_degraded": True,
        "page_degraded_stage": stage,
    }


def _page_fallback_cards(plugin: Any, stage: str) -> List[Dict[str, Any]]:
    """即便主控制台构建异常，也返回 MoviePilot 能渲染的最小页面而不是 HTTP 失败。"""
    version = str(getattr(plugin, "plugin_version", "") or "-")
    build = str(getattr(plugin, "build_id", "") or "-")
    return [
        {
            "component": "VAlert",
            "props": {
                "type": "warning",
                "variant": "tonal",
                "title": "控制台已降级显示",
                "text": (
                    f"{stage}读取异常，已隔离故障模块。后台转存逻辑不会因页面异常被停止。"
                    "请先打开插件设置检查配置，或查看后台日志中的【页面降级】记录。"
                ),
                "class": "mb-3",
                "style": "border-radius:16px;",
            },
        },
        {
            "component": "VCard",
            "props": {"variant": "flat", "class": "mb-3"},
            "content": [
                {"component": "VCardTitle", "text": "光鸭转存助手"},
                {
                    "component": "VCardText",
                    "text": f"v{version} · build {build} · 页面保护模式已生效",
                },
            ],
        },
    ]


def _install_page_resilience_v1102() -> None:
    """给已加载的 UI mixin 安装 fail-soft 包装；重复导入时保持幂等。"""
    try:
        from .status_ui_v191 import GuangYaStatusUiMixin
        from .console_ui_v1100 import GuangYaConsoleUiV1100Mixin
        from .channel_ui_v1101 import GuangYaChannelUiV1101Mixin
    except Exception:
        # 极早期兼容环境缺少某个新版 UI 模块时，不影响插件原有导入路径。
        return

    # 1) 状态汇总是新版控制台的总入口。旧缓存/ResourcePlan/自检任一异常都只返回降级数据。
    original_overview = getattr(GuangYaStatusUiMixin, "_status_overview_v191", None)
    if callable(original_overview) and not getattr(original_overview, "_guangya_page_resilience_v1102", False):
        @functools.wraps(original_overview)
        def safe_overview(self, *args, **kwargs):
            try:
                result = original_overview(self, *args, **kwargs)
                if not isinstance(result, dict):
                    raise TypeError("status overview is not a dict")
                return result
            except Exception as err:
                _page_mark_error(self, "状态汇总", err)
                return _fallback_overview(self, "状态汇总")

        safe_overview._guangya_page_resilience_v1102 = True
        GuangYaStatusUiMixin._status_overview_v191 = safe_overview

    # 2) Provider 定义解析此前没有 try/except，单行历史配置格式错误即可拖死整页。
    original_health = getattr(GuangYaConsoleUiV1100Mixin, "_runtime_health_rows", None)
    if callable(original_health) and not getattr(original_health, "_guangya_page_resilience_v1102", False):
        @functools.wraps(original_health)
        def safe_health(self, *args, **kwargs):
            try:
                result = original_health(self, *args, **kwargs)
                return list(result or [])
            except Exception as err:
                _page_mark_error(self, "资源来源运行态", err)
                return [{
                    "component": "VCol",
                    "props": {"cols": 12},
                    "content": [{
                        "component": "VAlert",
                        "props": {
                            "type": "warning",
                            "variant": "tonal",
                            "density": "compact",
                            "text": "资源来源运行态暂时无法读取，已跳过该模块；可继续使用其它控制台功能。",
                            "style": "border-radius:14px;",
                        },
                    }],
                }]

        safe_health._guangya_page_resilience_v1102 = True
        GuangYaConsoleUiV1100Mixin._runtime_health_rows = safe_health

    # 3) 频道索引是 v1.10.1 新增区块；坏的 channel_index 不应反向拖垮 v1.10.0 主控制台。
    original_channel_card = getattr(GuangYaChannelUiV1101Mixin, "_channel_page_card_v1101", None)
    if callable(original_channel_card) and not getattr(original_channel_card, "_guangya_page_resilience_v1102", False):
        @functools.wraps(original_channel_card)
        def safe_channel_card(self, *args, **kwargs):
            try:
                result = original_channel_card(self, *args, **kwargs)
                if not isinstance(result, dict):
                    raise TypeError("channel card is not a dict")
                return result
            except Exception as err:
                _page_mark_error(self, "频道资源", err)
                return {
                    "component": "VAlert",
                    "props": {
                        "type": "warning",
                        "variant": "tonal",
                        "density": "compact",
                        "class": "mb-4",
                        "title": "频道资源暂时无法读取",
                        "text": "频道索引异常已被隔离，不影响其它状态卡和后台转存。可尝试重新刷新频道。",
                        "style": "border-radius:14px;",
                    },
                }

        safe_channel_card._guangya_page_resilience_v1102 = True
        GuangYaChannelUiV1101Mixin._channel_page_card_v1101 = safe_channel_card

    # 4) 最外层兜底。任何未来新增页面模块忘记做容错，也不能再向 MoviePilot 抛出整页异常。
    original_console_page = getattr(GuangYaConsoleUiV1100Mixin, "get_page", None)
    if callable(original_console_page) and not getattr(original_console_page, "_guangya_page_resilience_v1102", False):
        @functools.wraps(original_console_page)
        def safe_console_page(self, *args, **kwargs):
            try:
                result = original_console_page(self, *args, **kwargs)
                if not isinstance(result, list):
                    raise TypeError("console page is not a list")
                return result
            except Exception as err:
                _page_mark_error(self, "主控制台", err)
                return _page_fallback_cards(self, "主控制台")

        safe_console_page._guangya_page_resilience_v1102 = True
        GuangYaConsoleUiV1100Mixin.get_page = safe_console_page

    # 5) ChannelUi 位于最终 MRO 最前；再兜一层可覆盖频道 get_page 自身的插入逻辑异常。
    original_channel_page = getattr(GuangYaChannelUiV1101Mixin, "get_page", None)
    if callable(original_channel_page) and not getattr(original_channel_page, "_guangya_page_resilience_v1102", False):
        @functools.wraps(original_channel_page)
        def safe_channel_page(self, *args, **kwargs):
            try:
                setattr(self, "_page_resilience_errors_v1102", [])
            except Exception:
                pass
            try:
                result = original_channel_page(self, *args, **kwargs)
                if not isinstance(result, list):
                    raise TypeError("plugin page is not a list")
            except Exception as err:
                _page_mark_error(self, "页面总入口", err)
                return _page_fallback_cards(self, "页面总入口")

            try:
                errors = list(getattr(self, "_page_resilience_errors_v1102", None) or [])
            except Exception:
                errors = []
            if errors:
                result.insert(0, {
                    "component": "VAlert",
                    "props": {
                        "type": "warning",
                        "variant": "tonal",
                        "density": "compact",
                        "class": "mb-4",
                        "title": "部分状态数据已降级",
                        "text": "已隔离：" + "、".join(errors[:6]) + "。页面其余功能可继续使用，详细原因见后台【页面降级】日志。",
                        "style": "border-radius:14px;",
                    },
                })
            return result

        safe_channel_page._guangya_page_resilience_v1102 = True
        GuangYaChannelUiV1101Mixin.get_page = safe_channel_page


_install_page_resilience_v1102()


__all__ = [
    "force_bear_auth",
    "strip_page_api_secrets",
]
