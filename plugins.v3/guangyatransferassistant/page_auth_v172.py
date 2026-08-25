"""光鸭转存助手 v1.7.3 页面 API 兼容层。

MoviePilot V3 插件页面使用当前登录会话的 Bearer 鉴权。页面事件只传业务参数，
不把 API_TOKEN 作为 token/apikey 注入按钮参数。

状态页的“立即检查缺集/复查待落盘”不能在 HTTP 请求线程里同步跑完整频道读取、
分享解析和转存流程，否则前端会在网络稍慢时提示“服务无响应”。本层把这两类操作
送入插件已经存在的可靠后台合并队列，并立即返回标准三段式 Response envelope；
其余状态页操作也统一收口为严格的 success/message/data 三字段响应。
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


__all__ = [
    "force_bear_auth",
    "strip_page_api_secrets",
]
