"""PanSou fallback 验证态隔离层。

历史 v1.10.13 曾尝试在 CloakBrowser 不可用时，把当前节点持久化保存的
``browser_pow/browser_verified/vrg_sc/vrg_go`` 恢复到一个新的 requests.Session，
以减少重复 PoW。真实运行证明这些 Cookie 与服务器当前 challenge / 浏览器运行态有
生命周期绑定：序列化后跨 Session 恢复会出现“PoW 提交已确认，但原请求仍返回挑战页”。

因此保留原类名/MRO 合同，但明确改成正确性优先：
- 新 Session 永远不恢复 browser_pow/browser_verified/vrg_*；
- 这四类挑战 Cookie 也不再写入持久化节点 Cookie；
- CloakBrowser fallback 后仍让 PanSou requests 在当前 Session 内完成
  challenge -> /res/pow -> retry；
- 登录/业务 Cookie 仍由既有节点持久化逻辑处理；
- 如果以后要减少 PoW，只能复用同一个活 Session，而不能复活挑战 Cookie。
"""

from __future__ import annotations

from typing import Any

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


def _persistent_cookie_header_v1113(session: requests.Session) -> str:
    """仅序列化可跨 Session 保存的登录/业务 Cookie。"""
    pairs = []
    seen = set()
    for cookie in list(session.cookies):
        name = str(getattr(cookie, "name", "") or "").strip()
        value = str(getattr(cookie, "value", "") or "")
        lowered = name.lower()
        if not name or not value or lowered in _FALLBACK_NODE_COOKIES_V1113 or lowered in seen:
            continue
        pairs.append(f"{name}={value}")
        seen.add(lowered)
    return "; ".join(pairs)


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

    def _gying_persist_session(self, node: str, session: requests.Session, **extra: Any) -> None:
        """复用既有节点状态写入逻辑，但写回前永久剔除挑战 Cookie。"""
        super()._gying_persist_session(node, session, **extra)
        try:
            state = self._gying_state()
            nodes = state.setdefault("nodes", {})
            row = dict(nodes.get(node) or {})
            filtered = _persistent_cookie_header_v1113(session)
            if str(row.get("cookie") or "") != filtered:
                row["cookie"] = filtered
                nodes[node] = row
                self._save_gying_state(state)
        except Exception:
            # 持久化收口失败不能影响当前活 Session 的搜索/登录。
            pass


__all__ = [
    "GuangYaGyingFallbackReuseV1113Mixin",
    "_drop_stale_challenge_cookies_v1113",
    "_persistent_cookie_header_v1113",
]
