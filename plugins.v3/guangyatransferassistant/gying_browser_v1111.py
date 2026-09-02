"""v1.10.11 用 MoviePilot 官方 CloakBrowser 保持 GYING 浏览器请求指纹。

PanSou 的公开排障记录说明，GYING 新版 PoW 不只依赖 y 与 Cookie：挑战页、验证提交和
重试原请求还必须处于同一浏览器化请求指纹。真实 MoviePilot 日志也已证明纯 requests
平方取模即使 POST /res/pow 返回 HTTP 200，服务器仍可能不确认。

本层优先使用稳定 SDK ``app.sdk.browser.launch_browser_context``，让站点自己的挑战页
与 refresh overlay 完成验证，并在同一个浏览器上下文继续 login/search/downurl。
无浏览器运行时或浏览器执行失败时，继续回退 v1.10.11 的 PanSou 算法补丁。

``browser_pow`` 是短期节点 challenge，不允许跨镜像复用；人工汉字验证码仍只由用户
本人点击，不做 OCR 或自动代点。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, urlparse

import requests

try:
    from app.sdk.browser import launch_browser_context
except Exception:  # pragma: no cover
    launch_browser_context = None

try:
    from app.sdk.config import settings
except Exception:  # pragma: no cover
    settings = None

from .gying_hardening_v193 import canonical_gying_node
from .gying_pansou_v1110 import _challenge_kind_v1110
from .gying_pow_v1111 import GuangYaGyingPowV1111Mixin
from .gying_runtime_v193 import _apply_cookie_header
from .provider_sources_v192 import _proxy_dict


_BROWSER_WAIT_SECONDS_V1111 = 28
_BROWSER_CHALLENGE_MARKERS_V1111 = (
    "正在确认你是不是机器人",
    "浏览器安全验证",
    "正在进行浏览器计算验证",
    "powSolve-",
    "pow.worker-",
)
_BLOCK_MARKERS_V1111 = ("angie", "request forbidden", "access denied")
_EPHEMERAL_COOKIE_NAMES_V1111 = frozenset({"browser_pow"})


class _GyingBrowserSessionV1111(requests.Session):
    """requests Session 加同节点 CloakBrowser 上下文。"""

    def __init__(self) -> None:
        super().__init__()
        self._gying_browser_context_v1111: Any = None
        self._gying_browser_page_v1111: Any = None
        self._gying_browser_node_v1111: str = ""

    def close(self) -> None:
        page = getattr(self, "_gying_browser_page_v1111", None)
        context = getattr(self, "_gying_browser_context_v1111", None)
        self._gying_browser_page_v1111 = None
        self._gying_browser_context_v1111 = None
        self._gying_browser_node_v1111 = ""
        try:
            if page is not None:
                page.close()
        except Exception:
            pass
        try:
            if context is not None:
                context.close()
        except Exception:
            pass
        super().close()


def _clear_ephemeral_cookies_v1111(session: requests.Session) -> None:
    for cookie in list(session.cookies):
        if str(getattr(cookie, "name", "") or "").lower() not in _EPHEMERAL_COOKIE_NAMES_V1111:
            continue
        try:
            session.cookies.clear(cookie.domain, cookie.path, cookie.name)
        except Exception:
            try:
                session.cookies.set(cookie.name, None)
            except Exception:
                pass


def _browser_cookie_seed_v1111(session: requests.Session, node: str) -> List[Dict[str, Any]]:
    base = canonical_gying_node(node)
    if not base:
        return []
    rows: List[Dict[str, Any]] = []
    seen = set()
    for cookie in list(session.cookies):
        name = str(getattr(cookie, "name", "") or "").strip()
        value = str(getattr(cookie, "value", "") or "").strip()
        if not name or not value or name.lower() in _EPHEMERAL_COOKIE_NAMES_V1111 or name in seen:
            continue
        seen.add(name)
        rows.append({"name": name, "value": value, "url": base.rstrip("/") + "/"})
    return rows


def _sync_browser_cookies_v1111(session: requests.Session, cookies: Any, node: str) -> None:
    """只同步当前节点稳定 Cookie，并从 requests 清除旧 browser_pow。"""
    host = str(urlparse(canonical_gying_node(node)).hostname or "").lower()
    if not host:
        return
    _clear_ephemeral_cookies_v1111(session)
    for row in list(cookies or []):
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        value = str(row.get("value") or "").strip()
        domain = str(row.get("domain") or "").lstrip(".").lower()
        if not name or not value or name.lower() in _EPHEMERAL_COOKIE_NAMES_V1111:
            continue
        if domain and domain != host and not host.endswith("." + domain):
            continue
        try:
            session.cookies.set(name, value, domain=host, path="/")
        except Exception:
            session.cookies.set(name, value)


def _browser_response_v1111(result: Dict[str, Any], method: str, url: str) -> requests.Response:
    response = requests.Response()
    response.status_code = int(result.get("status") or 0)
    response.url = str(result.get("url") or url)
    response._content = str(result.get("text") or "").encode("utf-8")
    response.encoding = "utf-8"
    headers = result.get("headers") or {}
    if isinstance(headers, dict):
        response.headers.update({str(k): str(v) for k, v in headers.items()})
    try:
        response.request = requests.Request(method=str(method or "GET").upper(), url=url).prepare()
    except Exception:
        pass
    return response


class GuangYaGyingBrowserV1111Mixin(GuangYaGyingPowV1111Mixin):
    """浏览器验证优先；PanSou 算法作为兼容回退。"""

    build_id = "20260902-r22"

    # v1.10.8 曾跨镜像共享整套 Cookie；这里显式关闭，避免 browser_pow challenge 串节点。
    def _gying_group_cookie_seed_v1108(self) -> str:
        return ""

    def _gying_sync_cookie_v1108(self, session: requests.Session, node: str) -> None:
        return None

    def _gying_new_session(self, node: str, saved_cookie: str = "") -> requests.Session:
        node = canonical_gying_node(node)
        session = _GyingBrowserSessionV1111()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/json,text/plain,*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        })
        proxies = _proxy_dict(bool(getattr(self, "_provider_proxy", False)))
        if proxies:
            session.proxies.update(proxies)
        if saved_cookie:
            _apply_cookie_header(session, saved_cookie)
        configured_cookie = str(getattr(self, "_viewing_cookie", "") or "").strip()
        preferred = canonical_gying_node(str(getattr(self, "_viewing_base_url", "") or ""))
        if configured_cookie and preferred and node == preferred:
            _apply_cookie_header(session, configured_cookie)
        _clear_ephemeral_cookies_v1111(session)
        return session

    def _gying_browser_available_v1111(self) -> bool:
        return callable(launch_browser_context)

    def _gying_browser_proxy_v1111(self) -> Any:
        if not bool(getattr(self, "_provider_proxy", False)) or settings is None:
            return None
        return getattr(settings, "PROXY", None)

    def _gying_browser_ensure_v1111(self, session: requests.Session, node: str, timeout: int) -> Any:
        if not self._gying_browser_available_v1111():
            raise RuntimeError("MoviePilot 浏览器运行时不可用")
        node = canonical_gying_node(node)
        if not node:
            raise RuntimeError("观影浏览器节点无效")
        context = getattr(session, "_gying_browser_context_v1111", None)
        page = getattr(session, "_gying_browser_page_v1111", None)
        current_node = str(getattr(session, "_gying_browser_node_v1111", "") or "")
        if context is not None and page is not None and current_node == node:
            return page
        try:
            if page is not None:
                page.close()
        except Exception:
            pass
        try:
            if context is not None:
                context.close()
        except Exception:
            pass
        kwargs: Dict[str, Any] = {}
        proxy = self._gying_browser_proxy_v1111()
        if proxy:
            kwargs["proxy"] = proxy
        context = launch_browser_context(headless=True, **kwargs)
        page = context.new_page()
        page.set_default_timeout(max(15, int(timeout or 15)) * 1000)
        seed = _browser_cookie_seed_v1111(session, node)
        if seed:
            page.context.add_cookies(seed)
        session._gying_browser_context_v1111 = context
        session._gying_browser_page_v1111 = page
        session._gying_browser_node_v1111 = node
        return page

    @staticmethod
    def _gying_browser_verified_v1111(page: Any) -> bool:
        try:
            cookies = list(page.context.cookies() or [])
        except Exception:
            cookies = []
        return any(
            str(row.get("name") or "") == "browser_verified" and bool(str(row.get("value") or ""))
            for row in cookies if isinstance(row, dict)
        )

    def _gying_browser_bootstrap_v1111(
        self,
        session: requests.Session,
        node: str,
        timeout: int,
        *,
        force: bool = False,
    ) -> Any:
        page = self._gying_browser_ensure_v1111(session, node, timeout)
        node = canonical_gying_node(node)
        if not force and self._gying_browser_verified_v1111(page):
            try:
                _sync_browser_cookies_v1111(session, page.context.cookies(), node)
            except Exception:
                pass
            return page

        self._gying_auth_log("INFO", "浏览器验证：节点=%s，交由 MoviePilot CloakBrowser 建立验证态", node)
        page.goto(node.rstrip("/") + "/", wait_until="domcontentloaded", timeout=max(20, timeout) * 1000)
        deadline = time.monotonic() + _BROWSER_WAIT_SECONDS_V1111
        verified = False
        normal_page = False
        while time.monotonic() < deadline:
            verified = self._gying_browser_verified_v1111(page)
            try:
                body = str(page.content() or "")
            except Exception:
                body = ""
            normal_page = bool(body) and not any(marker in body for marker in _BROWSER_CHALLENGE_MARKERS_V1111)
            if verified or normal_page:
                break
            try:
                page.wait_for_timeout(500)
            except Exception:
                time.sleep(0.5)
        try:
            cookies = list(page.context.cookies() or [])
        except Exception:
            cookies = []
        _sync_browser_cookies_v1111(session, cookies, node)
        try:
            ua = str(page.evaluate("() => navigator.userAgent") or "").strip()
        except Exception:
            ua = ""
        if ua:
            session.headers["User-Agent"] = ua
        if not (verified or normal_page):
            raise RuntimeError("观影 CloakBrowser 等待验证态超时")
        self._gying_auth_log(
            "INFO",
            "浏览器验证完成：节点=%s browser_verified=%s，将复用同节点浏览器请求链",
            node,
            bool(verified),
        )
        return page

    def _gying_browser_fetch_v1111(
        self,
        session: requests.Session,
        node: str,
        method: str,
        url: str,
        *,
        timeout: int,
        headers: Optional[Dict[str, Any]] = None,
        data: Any = None,
    ) -> requests.Response:
        page = self._gying_browser_bootstrap_v1111(session, node, timeout)
        method = str(method or "GET").upper()
        safe_headers: Dict[str, str] = {}
        for key, value in dict(headers or {}).items():
            if str(key or "").lower() in {"cookie", "host", "content-length", "origin", "referer", "user-agent"}:
                continue
            safe_headers[str(key)] = str(value)
        if method in {"GET", "HEAD"} or data is None:
            body: Optional[str] = None
        elif isinstance(data, str):
            body = data
        elif isinstance(data, (dict, list, tuple)):
            body = urlencode(data, doseq=True)
            safe_headers.setdefault("Content-Type", "application/x-www-form-urlencoded;charset=UTF-8")
        else:
            body = str(data)

        js = r"""
        async (args) => {
          const requestOnce = async () => {
            const opts = {method: args.method, credentials: 'same-origin', headers: args.headers || {}};
            if (args.body !== null && args.method !== 'GET' && args.method !== 'HEAD') opts.body = args.body;
            const response = await fetch(args.url, opts);
            return {
              status: response.status,
              url: response.url,
              text: await response.text(),
              headers: Object.fromEntries(response.headers.entries()),
            };
          };
          let result = await requestOnce();
          let payload = null;
          try { payload = JSON.parse(result.text); } catch (_) {}
          if (payload && Number(payload.refresh || 0) === 1) {
            const overlay = String(payload.overlay || '');
            if (overlay) {
              const absoluteOverlay = new URL(overlay, window.location.href).href;
              if (!Array.from(document.scripts).some(s => s.src === absoluteOverlay)) {
                await new Promise((resolve, reject) => {
                  const script = document.createElement('script');
                  script.src = absoluteOverlay;
                  script.onload = resolve;
                  script.onerror = reject;
                  document.head.appendChild(script);
                });
              }
            }
            if (window.PowOverlay && typeof window.PowOverlay.run === 'function') {
              await window.PowOverlay.run(payload);
              result = await requestOnce();
            }
          }
          return result;
        }
        """

        def evaluate_once() -> requests.Response:
            result = page.evaluate(js, {"url": url, "method": method, "headers": safe_headers, "body": body})
            if not isinstance(result, dict):
                raise RuntimeError("观影浏览器请求未返回有效结果")
            try:
                _sync_browser_cookies_v1111(session, page.context.cookies(), node)
            except Exception:
                pass
            return _browser_response_v1111(result, method, url)

        response = evaluate_once()
        kind = _challenge_kind_v1110(response)
        if kind:
            self._gying_auth_log("INFO", "浏览器验证态需要刷新：节点=%s 类型=%s", canonical_gying_node(node), kind)
            self._gying_browser_bootstrap_v1111(session, node, timeout, force=True)
            response = evaluate_once()
            kind = _challenge_kind_v1110(response)
        if kind:
            raise RuntimeError(f"观影浏览器请求后仍要求验证：{kind}")
        return response

    def _gying_request(
        self,
        session: requests.Session,
        node: str,
        method: str,
        url: str,
        *,
        retry_challenge: bool = True,
        **kwargs: Any,
    ) -> requests.Response:
        timeout = int(kwargs.pop("timeout", int(getattr(self, "_provider_timeout", 15) or 15)) or 15)
        request_kwargs = dict(kwargs)
        canonical = canonical_gying_node(node)
        current_page = getattr(session, "_gying_browser_page_v1111", None)
        current_node = str(getattr(session, "_gying_browser_node_v1111", "") or "")
        if current_page is not None and current_node == canonical:
            return self._gying_browser_fetch_v1111(
                session, node, method, url, timeout=max(timeout, 20),
                headers=request_kwargs.get("headers"), data=request_kwargs.get("data"),
            )

        response = session.request(
            str(method or "GET").upper(), url, timeout=timeout, allow_redirects=True, **request_kwargs
        )
        lowered = str(getattr(response, "text", "") or "").lower()
        if int(getattr(response, "status_code", 0) or 0) in {403, 404} and any(marker in lowered for marker in _BLOCK_MARKERS_V1111):
            raise RuntimeError(f"观影节点当前出口被阻断：HTTP {response.status_code}")
        kind = _challenge_kind_v1110(response)
        if not kind:
            return response
        if not retry_challenge:
            raise RuntimeError(f"观影请求仍要求浏览器验证：{kind}")

        if self._gying_browser_available_v1111():
            self._gying_auth_log("INFO", "观影挑战：节点=%s 类型=%s，切换 MoviePilot 官方 CloakBrowser 请求链", canonical, kind)
            try:
                return self._gying_browser_fetch_v1111(
                    session, node, method, url, timeout=max(timeout, 20),
                    headers=request_kwargs.get("headers"), data=request_kwargs.get("data"),
                )
            except Exception as err:
                self._gying_auth_log(
                    "WARNING", "浏览器验证请求失败：节点=%s 类型=%s；回退 PanSou 算法链",
                    canonical, type(err).__name__,
                )

        return super()._gying_request(
            session, node, method, url, retry_challenge=retry_challenge, timeout=timeout, **request_kwargs
        )

    def _gying_solve_challenge(
        self,
        session: requests.Session,
        node: str,
        response: requests.Response,
    ) -> Dict[str, Any]:
        """旧层直接调用也统一进入浏览器/PanSou v1.10.11，不再掉到 v1.10.8 solver。"""
        if self._gying_browser_available_v1111():
            try:
                self._gying_browser_bootstrap_v1111(
                    session, node, max(20, int(getattr(self, "_provider_timeout", 15) or 15)), force=True
                )
                return {"mode": "cloakbrowser", "success": True}
            except Exception as err:
                self._gying_auth_log(
                    "WARNING", "浏览器 challenge 恢复失败：节点=%s 类型=%s，回退 PanSou solver",
                    canonical_gying_node(node), type(err).__name__,
                )
        kind = _challenge_kind_v1110(response)
        if kind == "refresh_overlay":
            raise RuntimeError("观影动态 refresh 验证需要 MoviePilot 浏览器运行时")
        return dict(self._gying_solve_challenge_v1110(session, node, response, kind=kind or None) or {})


__all__ = ["GuangYaGyingBrowserV1111Mixin"]
