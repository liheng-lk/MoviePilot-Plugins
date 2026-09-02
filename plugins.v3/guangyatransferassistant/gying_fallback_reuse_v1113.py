"""v1.10.13 CloakBrowser 不可用时的 PanSou 会话复用层。

v1.10.12 正常浏览器模式会故意从新 requests.Session 中清除 browser_pow /
browser_verified / vrg_sc / vrg_go，避免把浏览器绑定验证态注入新的 CloakBrowser。
但宿主如果根本无法启动 CloakBrowser，`_gying_request()` 会稳定回退到 PanSou requests
链；此时继续清除这些节点内验证 Cookie 会导致每个订阅/搜索都重复执行 3 秒 PoW。

本层只在 Browser 层已经确认发生 SDK/启动级 fallback 后生效：
- 从该节点自己持久化的 saved_cookie 中恢复验证 Cookie；
- 不修改跨镜像共享逻辑，跨镜像仍由 v1.10.12 过滤浏览器验证态；
- 不从手工 Cookie 或其它节点复制验证 Cookie；
- CloakBrowser 正常可用时行为完全不变。
"""

from __future__ import annotations

from typing import Any

import requests

from .gying_browser_profile_v1112 import GuangYaGyingBrowserProfileV1112Mixin


_FALLBACK_NODE_COOKIES_V1113 = frozenset(
    {"browser_pow", "browser_verified", "vrg_sc", "vrg_go"}
)


def _restore_fallback_node_cookies_v1113(
    session: requests.Session,
    saved_cookie: str,
) -> int:
    """仅从当前节点自己的持久 Cookie 恢复 PanSou 验证态。"""
    restored = 0
    seen = set()
    for raw in str(saved_cookie or "").split(";"):
        item = raw.strip()
        if not item or "=" not in item:
            continue
        name, value = item.split("=", 1)
        name = name.strip()
        value = value.strip()
        lowered = name.lower()
        if (
            not name
            or not value
            or lowered not in _FALLBACK_NODE_COOKIES_V1113
            or lowered in seen
        ):
            continue
        try:
            session.cookies.set(name, value)
            restored += 1
            seen.add(lowered)
        except Exception:
            continue
    return restored


class GuangYaGyingFallbackReuseV1113Mixin(GuangYaGyingBrowserProfileV1112Mixin):
    """Browser fallback 后保留同节点 PanSou 验证态，避免每次搜索重复 PoW。"""

    build_id = "20260902-r24"

    def init_plugin(self, config: dict = None) -> None:
        self._gying_fallback_reuse_logged_v1113 = False
        return super().init_plugin(dict(config or {}))

    def _gying_new_session(self, node: str, saved_cookie: str = "") -> requests.Session:
        session = super()._gying_new_session(node, saved_cookie=saved_cookie)
        # Browser 层只有在 SDK/启动资源不可用时才会把此标记置 True。
        # 此时后续请求已经稳定走 PanSou requests；恢复当前节点自己的验证 Cookie
        # 才能保持 challenge -> login -> search -> downurl 的同节点验证态。
        if bool(getattr(self, "_gying_browser_fallback_logged_v1112", False)):
            restored = _restore_fallback_node_cookies_v1113(session, saved_cookie)
            if restored and not bool(getattr(self, "_gying_fallback_reuse_logged_v1113", False)):
                self._gying_fallback_reuse_logged_v1113 = True
                logger = getattr(self, "_gying_auth_log", None)
                if callable(logger):
                    logger(
                        "INFO",
                        "PanSou fallback：已复用当前节点验证态，后续搜索不再主动清空 browser_verified/browser_pow",
                    )
        return session


__all__ = [
    "GuangYaGyingFallbackReuseV1113Mixin",
    "_restore_fallback_node_cookies_v1113",
]
