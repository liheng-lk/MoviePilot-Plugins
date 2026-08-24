"""光鸭转存助手 v1.7.2 页面 API 鉴权兼容层。

MoviePilot V3 插件页面应使用当前登录会话的 Bearer 鉴权。页面事件本身只传业务参数，
不再把 API_TOKEN 作为 token/apikey 注入按钮参数，避免 POST 请求鉴权失败后前端跳回登录页。
"""

from __future__ import annotations

from typing import Any, Dict, List


def force_bear_auth(routes: Any) -> List[Dict[str, Any]]:
    """把插件自身 API 路由统一声明为 MoviePilot 页面使用的 bear 鉴权。"""
    result: List[Dict[str, Any]] = []
    for route in list(routes or []):
        if not isinstance(route, dict):
            continue
        item = dict(route)
        item["auth"] = "bear"
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


__all__ = ["force_bear_auth", "strip_page_api_secrets"]
