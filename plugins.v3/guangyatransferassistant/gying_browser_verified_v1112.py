"""v1.10.12 CloakBrowser 验证态竞态修复。

站点 PoW 脚本可能先通过 Set-Cookie 写入 ``browser_verified``，随后才刷新/替换挑战页 DOM。
如果此时仅检查旧 DOM，插件会把已经验证成功的浏览器误判为仍在 challenge，并重复提交 PoW。
本层把浏览器验证 Cookie 作为比旧挑战 HTML 更强的确认信号；真正业务请求仍会再次验真，
因此不会把一个失效 Cookie 当成最终成功。
"""

from __future__ import annotations

import requests

from .gying_browser_v1112 import (
    GuangYaGyingBrowserV1112Mixin,
    _response_v1112,
)


class GuangYaGyingBrowserVerifiedV1112Mixin(GuangYaGyingBrowserV1112Mixin):
    """让 browser_verified 优先终止等待期的旧 challenge DOM。"""

    build_id = "20260902-r23"

    def _gying_browser_wait_site_solver_v1112(
        self,
        row,
        response: requests.Response,
    ) -> requests.Response:
        latest = super()._gying_browser_wait_site_solver_v1112(row, response)
        if not self._gying_browser_has_cookie_v1112(row, "browser_verified"):
            return latest

        # Cookie 已由同一个 CloakBrowser context 写入，旧 DOM 只是尚未刷新。
        # 返回一个“非 challenge”影子响应让 bootstrap 继续；紧接着的真实业务 fetch
        # 仍会由 _gying_request 再次判定 challenge，形成最终验真。
        page = row.get("page") if isinstance(row, dict) else None
        current_url = str(getattr(page, "url", "") or getattr(latest, "url", "") or "")
        return _response_v1112(
            current_url,
            int(getattr(latest, "status_code", 200) or 200),
            "",
            dict(getattr(latest, "headers", {}) or {}),
        )


__all__ = ["GuangYaGyingBrowserVerifiedV1112Mixin"]
