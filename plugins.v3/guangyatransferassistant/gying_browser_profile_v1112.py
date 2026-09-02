"""v1.10.12 CloakBrowser 宿主反检测配置对齐层。

MoviePilot 的 BrowserSessionHelper 创建浏览器上下文时，会统一传入默认 1280x720
viewport，以及 CLOAKBROWSER_HUMANIZE / CLOAKBROWSER_HUMAN_PRESET。插件仍只依赖公开
``app.sdk.browser.launch_browser_context`` 启动入口，但把同一组宿主运行配置显式传给它，
避免 GYING 使用一个“裸 CloakBrowser”而 MoviePilot 其它浏览器会话使用另一套指纹配置。
"""

from __future__ import annotations

from typing import Any, Dict

import requests

from .gying_browser_v1112 import (
    _GyingBrowserUnavailableV1112,
    _cookie_rows_v1112,
)
from .gying_browser_verified_v1112 import GuangYaGyingBrowserVerifiedV1112Mixin


_DEFAULT_VIEWPORT_V1112 = {"width": 1280, "height": 720}


class GuangYaGyingBrowserProfileV1112Mixin(GuangYaGyingBrowserVerifiedV1112Mixin):
    """使用 MoviePilot 宿主 CloakBrowser 运行配置建立 GYING 浏览器上下文。"""

    build_id = "20260902-r23"

    def _gying_browser_ensure_context_v1112(
        self,
        row: Dict[str, Any],
        node: str,
        session: requests.Session,
        timeout: int,
    ) -> None:
        if row.get("context") is not None and row.get("page") is not None:
            return

        try:
            from app.sdk.browser import launch_browser_context
        except Exception as err:
            raise _GyingBrowserUnavailableV1112(
                f"MoviePilot 浏览器 SDK 不可用：{type(err).__name__}"
            ) from err

        context_kwargs: Dict[str, Any] = {
            "viewport": dict(_DEFAULT_VIEWPORT_V1112),
        }
        try:
            from app.runtime.settings import get_runtime_setting

            humanize = get_runtime_setting("CLOAKBROWSER_HUMANIZE")
            human_preset = get_runtime_setting("CLOAKBROWSER_HUMAN_PRESET")
            if humanize is not None:
                context_kwargs["humanize"] = humanize
            if human_preset is not None:
                context_kwargs["human_preset"] = human_preset
        except Exception:
            # 兼容早期 MoviePilot V3：公开 browser SDK 可用时，即使运行设置入口发生变化，
            # 仍可使用 CloakBrowser 默认反检测参数，而不是把整个 GYING 链降级回 requests。
            pass

        try:
            context = launch_browser_context(headless=True, **context_kwargs)
            page = context.new_page()
            if hasattr(page, "set_default_timeout"):
                page.set_default_timeout(max(int(timeout), 5) * 1000)
        except Exception as err:
            raise _GyingBrowserUnavailableV1112(
                f"CloakBrowser 启动失败：{type(err).__name__}"
            ) from err

        row["context"] = context
        row["page"] = page

        # 只尝试注入业务/登录 Cookie；browser_pow/browser_verified/vrg_* 已被过滤。
        # 某些 CloakBrowser 版本未暴露 context.add_cookies，此时让账号自动登录重新建态，
        # 不使用固定 Cookie HTTP header，以免覆盖服务端随后写入的验证 Cookie。
        cookie_rows = _cookie_rows_v1112(
            "; ".join(
                f"{getattr(item, 'name', '')}={getattr(item, 'value', '')}"
                for item in list(session.cookies)
                if getattr(item, "name", None) and getattr(item, "value", None)
            ),
            node,
        )
        if cookie_rows:
            add_cookies = getattr(context, "add_cookies", None)
            if callable(add_cookies):
                try:
                    add_cookies(cookie_rows)
                except Exception:
                    pass

        self._gying_auth_log(
            "INFO",
            "CloakBrowser：已应用 MoviePilot 宿主浏览器配置，viewport=1280x720 humanize=%s preset=%s",
            "on" if "humanize" in context_kwargs else "default",
            "configured" if "human_preset" in context_kwargs else "default",
        )


__all__ = ["GuangYaGyingBrowserProfileV1112Mixin"]
