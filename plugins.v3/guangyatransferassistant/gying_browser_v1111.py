"""v1.10.11 使用 MoviePilot 官方浏览器门面完成 GYING 验证态。

v1.10.10 已正确复现 PanSou 的平方取模算法，但真实环境仍出现
``POST /res/pow`` HTTP 200 且 ``success != true``。PanSou 自身的排障记录指出，
验证态不仅依赖 Cookie，还依赖同一套浏览器化请求指纹；它用 cloudscraper 保持
挑战页、验证提交和原请求重试处于同一浏览器化会话。

MoviePilot V3 已提供稳定的 ``app.sdk.browser.launch_browser_context``（CloakBrowser）
接口，因此本层优先让站点自己的浏览器脚本完成计算验证，再把合法产生的 Cookie 与
User-Agent 同步回 requests.Session。这样不需要继续猜服务端对 TLS/请求指纹的判定。

另外撤销 v1.10.8 对整个镜像组共享完整 Cookie 的做法：``browser_pow`` 属于短期、
单节点 challenge，跨镜像复用可能把错误 challenge_id 带到另一节点。v1.10.11 恢复
按节点保存/恢复 Cookie，节点切换只切换节点，不搬运 challenge Cookie。

本层不会 OCR、识别或自动点击汉字验证码；账号登录仍由既有自动登录层处理，只有站点
明确要求汉字点击验证时才进入用户人工点选流程。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, urlparse

import requests

try:
    from app.sdk.browser import launch_browser_context
except Exception:  # pragma: no cover - 合同测试环境可能没有 MoviePilot 运行时
    launch_browser_context = None

try:
    from app.sdk.config import settings
except Exception:  # pragma: no cover
    settings = None

from .gying_hardening_v193 import canonical_gying_node
from .gying_pansou_v1110 import GuangYaGyingPanSouV1110Mixin, _challenge_kind_v1110
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
_REGISTRY_ONLY_HOSTS_V1111 = frozenset({
    "www.gying.page", "gying.page",
    "www.gying.si", "gying.si",
    "www.gying.org", "gying.org",
    "www.gying.net", "gying.net",
    "www.gying.in", "gying.in",
    "www.gying.st", "gying.st",
    "www.gyg.la", "gyg.la",
    "www.gyg.si", "gyg.si",
    "www.gyg.st", "gyg.st",
})


class _GyingBrowserSessionV1111(requests.Session):
    """requests Session + 可选的同节点 CloakBrowser 上下文。"""

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
    """把浏览器当前节点 Cookie 同步回 requests，并清掉旧 challenge cookie。"""
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
        if not name or not value:
            continue
        if domain and domain != host and not host.endswith("." + domain):
            continue
        if name.lower() in _EPHEMERAL_COOKIE_NAMES_V1111:
            continue
        try:
            session.cookies.set(name, value, domain=host, path="/")
        except Exception:
            session.cookies.set(name, value)


def _response_from_browser_v1111(result: Dict[str, Any], method: str, url: str) -> requests.Response:
    response = requests.Response()
    response.status_code = int(result.get("status") or 0)
    response.url = str(result.get("url") or url)
    text = str(result.get("text") or "")
    response._content = text.encode("utf-8")
    response.encoding = "utf-8"
    headers = result.get("headers") or {}
    if isinstance(headers, dict):
        response.headers.update({str(k): str(v) for k, v in headers.items()})
    try:
        response.request = requests.Request(method=str(method or "GET").upper(), url=url).prepare()
    except Exception:
        pass
    return response


class GuangYaGyingBrowserV1111Mixin(GuangYaGyingPanSouV1110Mixin):
    """最外层 GYING 传输：浏览器验证优先，算法求解只作无浏览器环境回退。"""

    build_id = "20260902-r22"

    # ------------------------------------------------------------------
    # 节点 / Cookie：注册页不再参与每次业务 failover，browser_pow 严格节点隔离
    # ------------------------------------------------------------------
    @staticmethod
    def _gying_registry_only_v1111(node: str) -> bool:
        host = str(urlparse(canonical_gying_node(node)).hostname or "").lower()
        return host in _REGISTRY_ONLY_HOSTS_V1111

    def _discover_gying_nodes(self, force: bool = False) -> List[str]:
        rows = list(super()._discover_gying_nodes(force=force) or [])
        preferred = canonical_gying_node(str(getattr(self, "_viewing_base_url", "") or ""))
        state = self._gying_state()
        active = canonical_gying_node(str(state.get("active_node") or ""))
        manual = [
            canonical_gying_node(value)
            for value in str(getattr(self, "_viewing_node_urls", "") or "").splitlines()
        ]
        ordered: List[str] = []
        for node in [active, preferred, *manual, *rows]:
            node = canonical_gying_node(node)
            if not node or self._gying_registry_only_v1111(node) or node in ordered:
                continue
            ordered.append(node)
        return ordered[:24]

    def _gying_group_cookie_seed_v1108(self) -> str:
        return ""

    def _gying_sync_cookie_v1108(self, session: requests.Session, node: str) -> None:
        # v1.10.8 的跨镜像共享缓存不再使用。真正持久化仍由 _gying_persist_session 按 node 保存。
        return None

    def _gying_new_session(self, node: str, saved_cookie: str = "") -> requests.Session:
        """构造完全按节点隔离的 Session，仍复用宿主代理配置。"""
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
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-User": "?1",
            "Sec-Fetch-Dest": "document",
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

    # ------------------------------------------------------------------
    # CloakBrowser 会话
    # ------------------------------------------------------------------
    def _gying_browser_available_v1111(self) -> bool:
        return callable(launch_browser_context)

    def _gying_browser_proxy_v1111(self) -> Any:
        if not bool(getattr(self, "_provider_proxy", False)) or settings is None:
            return None
        return getattr(settings, "PROXY", None)

    def _gying_browser_ensure_v1111(
        self,
        session: requests.Session,
        node: str,
        timeout: int,
    ) -> Any:
        if not self._gying_browser_available_v1111():
            raise RuntimeError("MoviePilot 浏览器运行时不可用")
        node = canonical_gying_node(node)
        if not node:
            raise RuntimeError("观影浏览器节点无效")

        current_context = getattr(session, "_gying_browser_context_v1111", None)
        current_page = getattr(session, "_gying_browser_page_v1111", None)
        current_node = str(getattr(session, "_gying_browser_node_v1111", "") or "")
        if current_context is not None and current_page is not None and current_node == node:
            return current_page

        try:
            if current_page is not None:
                current_page.close()
        except Exception:
            pass
        try:
            if current_context is not None:
                current_context.close()
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

        setattr(session, "_gying_browser_context_v1111", context)
        setattr(session, "_gying_browser_page_v1111", page)
        setattr(session, "_gying_browser_node_v1111", node)
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
        """让站点自己的页面脚本完成 PoW/overlay，再同步验证态和 UA。"""
        page = self._gying_browser_ensure_v1111(session, node, timeout)
        node = canonical_gying_node(node)

        # 已经在同一浏览器上下文拿到验证态时不要重复导航；后续登录/search/downurl
        # 全部继续走这个页面上下文，保持与 PanSou cloudscraper 同样的浏览器指纹连续性。
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
        """在同一真实浏览器上下文执行请求，必要时运行站点 refresh overlay。"""
        page = self._gying_browser_bootstrap_v1111(session, node, timeout)
        method = str(method or "GET").upper()
        safe_headers: Dict[str, str] = {}
        for key, value in dict(headers or {}).items():
            lowered = str(key or "").lower()
            if lowered in {"cookie", "host", "content-length", "origin", "referer", "user-agent"}:
                continue
            safe_headers[str(key)] = str(value)

        body: Optional[str]
        if method in {"GET", "HEAD"} or data is None:
            body = None
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
            const opts = {
              method: args.method,
              credentials: 'same-origin',
              headers: args.headers || {},
            };
            if (args.body !== null && args.method !== 'GET' && args.method !== 'HEAD') {
              opts.body = args.body;
            }
            const response = await fetch(args.url, opts);
            const text = await response.text();
            return {
              status: response.status,
              url: response.url,
              text,
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
              const existing = Array.from(document.scripts).some(s => s.src === absoluteOverlay);
              if (!existing) {
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
            result = page.evaluate(
                js,
                {"url": url, "method": method, "headers": safe_headers, "body": body},
            )
            if not isinstance(result, dict):
                raise RuntimeError("观影浏览器请求未返回有效结果")
            try:
                cookies = list(page.context.cookies() or [])
            except Exception:
                cookies = []
            _sync_browser_cookies_v1111(session, cookies, node)
            return _response_from_browser_v1111(result, method, url)

        response = evaluate_once()
        kind = _challenge_kind_v1110(response)
        if kind:
            # 验证态可能刚过期。让浏览器真正重新导航根页运行 challenge JS，再重放一次业务请求。
            self._gying_auth_log("INFO", "浏览器验证态需要刷新：节点=%s 类型=%s", canonical_gying_node(node), kind)
            self._gying_browser_bootstrap_v1111(session, node, timeout, force=True)
            response = evaluate_once()
            kind = _challenge_kind_v1110(response)
        if kind:
            raise RuntimeError(f"观影浏览器请求后仍要求验证：{kind}")
        return response

    # ------------------------------------------------------------------
    # 统一请求：一旦建立浏览器上下文，登录/search/downurl 全部继续走浏览器指纹
    # ------------------------------------------------------------------
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
        current_page = getattr(session, "_gying_browser_page_v1111", None)
        current_node = str(getattr(session, "_gying_browser_node_v1111", "") or "")
        canonical = canonical_gying_node(node)
        if current_page is not None and current_node == canonical:
            return self._gying_browser_fetch_v1111(
                session,
                node,
                method,
                url,
                timeout=max(timeout, 20),
                headers=request_kwargs.get("headers"),
                data=request_kwargs.get("data"),
            )

        response = session.request(
            str(method or "GET").upper(),
            url,
            timeout=timeout,
            allow_redirects=True,
            **request_kwargs,
        )
        text = str(getattr(response, "text", "") or "")
        lowered = text.lower()
        if int(getattr(response, "status_code", 0) or 0) in {403, 404} and any(
            marker in lowered for marker in _BLOCK_MARKERS_V1111
        ):
            raise RuntimeError(f"观影节点当前出口被阻断：HTTP {response.status_code}")

        kind = _challenge_kind_v1110(response)
        if not kind:
            return response
        if not retry_challenge:
            raise RuntimeError(f"观影请求仍要求浏览器验证：{kind}")

        if self._gying_browser_available_v1111():
            self._gying_auth_log(
                "INFO",
                "观影挑战：节点=%s 类型=%s，切换 MoviePilot 官方 CloakBrowser 请求链",
                canonical or str(node or ""),
                kind,
            )
            try:
                return self._gying_browser_fetch_v1111(
                    session,
                    node,
                    method,
                    url,
                    timeout=max(timeout, 20),
                    headers=request_kwargs.get("headers"),
                    data=request_kwargs.get("data"),
                )
            except Exception as err:
                self._gying_auth_log(
                    "WARNING",
                    "浏览器验证请求失败：节点=%s 类型=%s；回退 PanSou 算法链",
                    canonical or str(node or ""),
                    type(err).__name__,
                )

        return super()._gying_request(
            session,
            node,
            method,
            url,
            retry_challenge=retry_challenge,
            timeout=timeout,
            **request_kwargs,
        )

    def _gying_solve_challenge(
        self,
        session: requests.Session,
        node: str,
        response: requests.Response,
    ) -> Dict[str, Any]:
        """兼容旧层直接调用，禁止再次解析到 v1.10.8 旧 remote solver。"""
        if self._gying_browser_available_v1111():
            try:
                self._gying_browser_bootstrap_v1111(
                    session,
                    node,
                    max(20, int(getattr(self, "_provider_timeout", 15) or 15)),
                    force=True,
                )
                return {"mode": "cloakbrowser", "success": True}
            except Exception as err:
                self._gying_auth_log(
                    "WARNING",
                    "浏览器 challenge 恢复失败：节点=%s 类型=%s，回退 PanSou solver",
                    canonical_gying_node(node) or str(node or ""),
                    type(err).__name__,
                )
        kind = _challenge_kind_v1110(response)
        if kind == "refresh_overlay":
            raise RuntimeError("观影动态 refresh 验证需要 MoviePilot 浏览器运行时")
        return dict(self._gying_solve_challenge_v1110(session, node, response, kind=kind or None) or {})


__all__ = ["GuangYaGyingBrowserV1111Mixin"]
