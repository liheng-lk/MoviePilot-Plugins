"""PanSou fallback 验证态隔离层。

历史 v1.10.13 曾尝试在 CloakBrowser 不可用时，把当前节点持久化保存的
``browser_pow/browser_verified/vrg_sc/vrg_go`` 恢复到一个新的 requests.Session，
以减少重复 PoW。真实运行证明这些 Cookie 与服务器当前 challenge / 浏览器运行态有
生命周期绑定：序列化后跨 Session 恢复会出现“PoW 提交已确认，但原请求仍返回挑战页”。

因此保留原类名/MRO 合同，但明确改成正确性优先：
- 新 Session 永远不恢复 browser_pow/browser_verified/vrg_*；
- CloakBrowser fallback 后仍让 PanSou requests 在当前 Session 内完成
  challenge -> /res/pow -> retry；
- 登录/业务 Cookie 仍由既有节点持久化逻辑处理；
- 如果以后要减少 PoW，只能复用同一个活 Session，而不能复活挑战 Cookie。
"""

from __future__ import annotations

import requests

from .gying_browser_profile_v1112 import GuangYaGyingBrowserProfileV1112Mixin


_FALLBACK_NODE_COOKIES_V1113 = frozenset(
    {"browser_pow", "browser_verified", "vrg_sc", "vrg_go"}
)


def _drop_stale_challenge_cookies_v1113(session: requests.Session) -> int:
    """从新建 requests.Session 删除不可跨 Session 复用的挑战 Cookie。"""
    removed = 0
    for cookie in list(session.cookies):
        name = str(getattr(cookie, "name", "") or "").lower()
        if name not in _FALLBACK_NODE_COOKIES_V1113:
            continue
        try:
            session.cookies.clear(
                domain=getattr(cookie, "domain", None),
                path=getattr(cookie, "path", None),
                name=getattr(cookie, "name", None),
            )
            removed += 1
        except Exception:
            try:
                session.cookies.pop(getattr(cookie, "name", ""), None)
                removed += 1
            except Exception:
                pass
    return removed


class GuangYaGyingFallbackReuseV1113Mixin(GuangYaGyingBrowserProfileV1112Mixin):
    """兼容历史类名；实际行为是隔离持久化挑战态，避免 stale PoW 回归。"""

    build_id = "20260902-r27"

    def init_plugin(self, config: dict = None) -> None:
        self._gying_fallback_isolation_logged_v1113 = False
        return super().init_plugin(dict(config or {}))

    def _gying_new_session(self, node: str, saved_cookie: str = "") -> requests.Session:
        session = super()._gying_new_session(node, saved_cookie=saved_cookie)
        removed = _drop_stale_challenge_cookies_v1113(session)
        if (
            removed
            and not bool(getattr(self, "_gying_fallback_isolation_logged_v1113", False))
        ):
            self._gying_fallback_isolation_logged_v1113 = True
            logger = getattr(self, "_gying_auth_log", None)
            if callable(logger):
                logger(
                    "INFO",
                    "PanSou fallback：已丢弃持久化挑战 Cookie；新 Session 将重新完成 challenge→PoW→retry",
                )
        return session


__all__ = [
    "GuangYaGyingFallbackReuseV1113Mixin",
    "_drop_stale_challenge_cookies_v1113",
]
