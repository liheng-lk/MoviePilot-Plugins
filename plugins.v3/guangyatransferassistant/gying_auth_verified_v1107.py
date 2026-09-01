"""v1.10.7 观影登录态验真补丁。

任何配置 Cookie 或历史 Cookie 都不能仅因“存在”就视为已登录。统一先请求受限搜索验证；
无效时进入人工汉字验证码流程，不再回落到 v1.10.6 的 configured_cookie 假成功。
"""

from __future__ import annotations

from typing import Any, Dict

import requests

from .gying_auth_v1107 import GuangYaGyingAuthV1107Mixin, _AUTH_COOKIE_MODES_V1107


class GuangYaGyingAuthVerifiedV1107Mixin(GuangYaGyingAuthV1107Mixin):
    """对所有 Cookie 做服务器侧受限接口验真后才允许复用。"""

    build_id = "20260902-r18"

    def _gying_login(self, session: requests.Session, node: str) -> Dict[str, Any]:
        try:
            state = self._gying_state()
            row = dict(((state.get("nodes") or {}).get(node) or {}))
        except Exception:
            state, row = {}, {}

        login_mode = str(row.get("login_mode") or "")
        has_cookie = bool(len(session.cookies))
        if has_cookie and self._gying_authenticated_probe(session, node):
            mode = login_mode if login_mode in _AUTH_COOKIE_MODES_V1107 else "cookie_reuse"
            self._gying_persist_session(
                node,
                session,
                status="ok",
                login_mode=mode,
                authenticated=True,
                verified=bool(
                    session.cookies.get("browser_verified")
                    or session.cookies.get("browser_pow")
                ),
            )
            return {
                "success": True,
                "mode": "cookie_reuse" if mode == "manual_captcha" else mode,
                "message": "观影 Cookie 已通过受限搜索验真并复用",
            }

        if has_cookie:
            row["authenticated"] = False
            row["status"] = "login_expired"
            if isinstance(state, dict):
                state.setdefault("nodes", {})[node] = row
                self._save_gying_state(state)

        username = str(getattr(self, "_viewing_username", "") or "").strip()
        password = str(getattr(self, "_viewing_password", "") or "")
        if username and password:
            return self._gying_login_password(session, node)
        return {
            "success": True,
            "mode": "anonymous",
            "message": "未配置观影账号；仅尝试公开访问",
        }


__all__ = ["GuangYaGyingAuthVerifiedV1107Mixin"]
