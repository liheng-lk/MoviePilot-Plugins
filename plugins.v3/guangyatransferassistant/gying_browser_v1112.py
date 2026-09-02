"""v1.10.12 GYING CloakBrowser 同会话传输层。

v1.10.11 已证明远程 PoW 数学本身能够完成，但纯 requests.Session 在
challenge -> /res/pow -> login -> search -> downurl 链上仍可能被服务端视为不同浏览器。
本层按 PanSou 的已验证经验收口为真正的浏览器会话：

- 通过 MoviePilot 官方 ``app.sdk.browser.launch_browser_context`` 启动 CloakBrowser；
- 每个“内容节点 + 账号”固定一个单线程浏览器上下文，避免同步浏览器对象跨线程使用；
- GET/POST 统一在页面上下文内 ``fetch(..., credentials='include')``，登录/搜索/downurl
  不再切回 requests；
- remote/embedded/legacy PoW 的提交同样走该浏览器上下文；Python 仅负责计算；
- requests.Session 仅保留为既有调用合同和 Cookie 持久化影子，不再承担主网络链；
- CloakBrowser SDK/运行资源不可用时，才回退 v1.10.11 PanSou requests 链。

``browser_pow``、``browser_verified``、``vrg_sc``、``vrg_go`` 属于浏览器/节点验证态，
不会从旧 requests Cookie 注入新 CloakBrowser，也不会进入跨镜像共享 Cookie。
登录 Cookie 仍可按节点持久化和恢复。

不会记录 Cookie、账号密码、PoW N/x/y、验证码内容或点击坐标。
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode, urlparse

import requests
from requests.structures import CaseInsensitiveDict

from .gying_hardening_v193 import canonical_gying_node
from .gying_pansou_v1110 import (
    _BLOCK_MARKERS_V1110,
    _challenge_kind_v1110,
    _json_v1110,
    _truthy_success_v1110,
)
from .gying_pow_v1111 import GuangYaGyingPowV1111Mixin
from .gying_runtime_v193 import (
    _GYING_CHALLENGE_RE,
    _safe_int,
    _solve_legacy_nonces,
    _solve_pow_hex,
)


_MIN_POW_SECONDS_V1112 = 3.15
_BROWSER_WAIT_SECONDS_V1112 = 6.5
_BROWSER_MAX_SESSIONS_V1112 = 4
_BROWSER_TTL_SECONDS_V1112 = 15 * 60
_BROWSER_BOUND_COOKIES_V1112 = frozenset(
    {
        "browser_pow",
        "browser_verified",
        "vrg_sc",
        "vrg_go",
    }
)
_BROWSER_MANAGED_HEADERS_V1112 = frozenset(
    {
        "origin",
        "user-agent",
        "cookie",
        "host",
        "connection",
        "content-length",
        "accept-encoding",
        "sec-fetch-dest",
        "sec-fetch-mode",
        "sec-fetch-site",
        "sec-fetch-user",
        "sec-ch-ua",
        "sec-ch-ua-mobile",
        "sec-ch-ua-platform",
    }
)

_FETCH_SCRIPT_V1112 = r"""
async (payload) => {
    const options = {
        method: payload.method,
        credentials: 'include',
        redirect: 'follow',
        cache: 'no-store',
        headers: payload.headers || {}
    };
    if (payload.referrer) {
        options.referrer = payload.referrer;
    }
    if (payload.body !== null && payload.body !== undefined
        && payload.method !== 'GET' && payload.method !== 'HEAD') {
        options.body = payload.body;
    }
    const response = await fetch(payload.url, options);
    const text = await response.text();
    const headers = {};
    response.headers.forEach((value, key) => {
        headers[key] = value;
    });
    return {
        status: response.status,
        url: response.url,
        text: text,
        headers: headers
    };
}
"""


class _GyingBrowserUnavailableV1112(RuntimeError):
    """仅表示浏览器 SDK/运行资源无法启动；此异常允许安全回退 requests。"""


def _response_v1112(
    url: str,
    status: int,
    text: str,
    headers: Optional[Dict[str, Any]] = None,
) -> requests.Response:
    response = requests.Response()
    response.status_code = int(status or 0)
    response.url = str(url or "")
    response.headers = CaseInsensitiveDict(
        {str(key): str(value) for key, value in dict(headers or {}).items()}
    )
    response.encoding = "utf-8"
    response._content = str(text or "").encode("utf-8")
    return response


def _cookie_seed_v1112(cookie_header: str) -> str:
    """只恢复登录/业务 Cookie；浏览器绑定验证态必须由新 context 自己建立。"""
    rows: List[str] = []
    for raw in str(cookie_header or "").split(";"):
        item = raw.strip()
        if not item or "=" not in item:
            continue
        name, value = item.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name or not value or name.lower() in _BROWSER_BOUND_COOKIES_V1112:
            continue
        rows.append(f"{name}={value}")
    return "; ".join(rows)


def _cookie_rows_v1112(cookie_header: str, node: str) -> List[Dict[str, str]]:
    base = (canonical_gying_node(node) or str(node or "").rstrip("/")).rstrip("/") + "/"
    rows: List[Dict[str, str]] = []
    for raw in _cookie_seed_v1112(cookie_header).split(";"):
        item = raw.strip()
        if not item or "=" not in item:
            continue
        name, value = item.split("=", 1)
        if name.strip() and value.strip():
            rows.append({"name": name.strip(), "value": value.strip(), "url": base})
    return rows


def _cookie_header_without_browser_state_v1112(session: requests.Session) -> str:
    rows: List[str] = []
    seen = set()
    for cookie in list(session.cookies):
        name = str(getattr(cookie, "name", "") or "").strip()
        value = str(getattr(cookie, "value", "") or "").strip()
        lowered = name.lower()
        if (
            not name
            or not value
            or lowered in _BROWSER_BOUND_COOKIES_V1112
            or lowered in seen
        ):
            continue
        rows.append(f"{name}={value}")
        seen.add(lowered)
    return "; ".join(rows)


def _same_origin_v1112(left: str, right: str) -> bool:
    try:
        a = urlparse(str(left or ""))
        b = urlparse(str(right or ""))
    except Exception:
        return False
    return (
        a.scheme.lower(),
        (a.hostname or "").lower(),
        a.port,
    ) == (
        b.scheme.lower(),
        (b.hostname or "").lower(),
        b.port,
    )


def _status_from_navigation_v1112(navigation: Any) -> int:
    value = getattr(navigation, "status", 200)
    try:
        value = value() if callable(value) else value
        return int(value or 200)
    except Exception:
        return 200


class GuangYaGyingBrowserV1112Mixin(GuangYaGyingPowV1111Mixin):
    """用 MoviePilot 官方 CloakBrowser 贯穿 GYING 的完整 HTTP 会话。"""

    build_id = "20260902-r23"

    def init_plugin(self, config: dict = None) -> None:
        try:
            self._gying_browser_close_all_v1112()
        except Exception:
            pass
        self._gying_browser_registry_v1112: Dict[str, Dict[str, Any]] = {}
        self._gying_browser_registry_lock_v1112 = threading.RLock()
        self._gying_browser_fallback_logged_v1112 = False
        return super().init_plugin(dict(config or {}))

    def stop_service(self) -> None:
        try:
            self._gying_browser_close_all_v1112()
        finally:
            return super().stop_service()

    def _gying_new_session(self, node: str, saved_cookie: str = "") -> requests.Session:
        session = super()._gying_new_session(node, saved_cookie=saved_cookie)
        for cookie in list(session.cookies):
            if str(getattr(cookie, "name", "") or "").lower() not in _BROWSER_BOUND_COOKIES_V1112:
                continue
            try:
                session.cookies.clear(cookie.domain, cookie.path, cookie.name)
            except Exception:
                try:
                    session.cookies.set(cookie.name, None)
                except Exception:
                    pass
        return session

    def _gying_sync_cookie_v1108(self, session: requests.Session, node: str) -> None:
        """跨镜像共享只保留业务 Cookie，绝不共享浏览器验证态。"""
        checker = getattr(self, "_gying_is_mirror_v1108", None)
        if not callable(checker) or not checker(node):
            return
        header = _cookie_header_without_browser_state_v1112(session)
        with getattr(self, "_gying_transport_lock_v1108", threading.RLock()):
            self._gying_shared_cookie_v1108 = header

    def _gying_browser_key_v1112(self, node: str) -> str:
        canonical = canonical_gying_node(node) or str(node or "").rstrip("/")
        host = str(urlparse(canonical).hostname or canonical).lower()
        username = str(getattr(self, "_viewing_username", "") or "").strip()
        account = hashlib.sha256(username.encode("utf-8")).hexdigest()[:12] if username else "anonymous"
        return f"guangya-gying:{host}:{account}"

    def _gying_browser_close_row_v1112(self, row: Dict[str, Any]) -> None:
        executor = row.get("executor")
        if not executor:
            return

        def closer() -> None:
            page = row.get("page")
            context = row.get("context")
            try:
                if page:
                    page.close()
            except Exception:
                pass
            try:
                if context:
                    context.close()
            except Exception:
                pass
            row["page"] = None
            row["context"] = None

        try:
            future = executor.submit(closer)
            future.result(timeout=12)
        except Exception:
            pass
        try:
            executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass

    def _gying_browser_close_all_v1112(self) -> None:
        registry = getattr(self, "_gying_browser_registry_v1112", None)
        if not isinstance(registry, dict):
            return
        lock = getattr(self, "_gying_browser_registry_lock_v1112", threading.RLock())
        with lock:
            rows = list(registry.values())
            registry.clear()
        for row in rows:
            self._gying_browser_close_row_v1112(row)

    def _gying_browser_prune_v1112(self) -> None:
        registry = getattr(self, "_gying_browser_registry_v1112", None)
        if not isinstance(registry, dict):
            return
        lock = getattr(self, "_gying_browser_registry_lock_v1112", threading.RLock())
        now = time.monotonic()
        victims: List[Dict[str, Any]] = []
        with lock:
            for key, row in list(registry.items()):
                if now - float(row.get("last_used") or 0) > _BROWSER_TTL_SECONDS_V1112:
                    victims.append(registry.pop(key))
            while len(registry) > _BROWSER_MAX_SESSIONS_V1112:
                oldest_key = min(
                    registry,
                    key=lambda value: float((registry.get(value) or {}).get("last_used") or 0),
                )
                victims.append(registry.pop(oldest_key))
        for row in victims:
            self._gying_browser_close_row_v1112(row)

    def _gying_browser_row_v1112(self, node: str) -> Dict[str, Any]:
        self._gying_browser_prune_v1112()
        key = self._gying_browser_key_v1112(node)
        registry = getattr(self, "_gying_browser_registry_v1112", None)
        if not isinstance(registry, dict):
            self._gying_browser_registry_v1112 = {}
            registry = self._gying_browser_registry_v1112
        lock = getattr(self, "_gying_browser_registry_lock_v1112", threading.RLock())
        with lock:
            row = registry.get(key)
            if row:
                row["last_used"] = time.monotonic()
                return row
            row = {
                "key": key,
                "node": canonical_gying_node(node) or str(node or "").rstrip("/"),
                "executor": ThreadPoolExecutor(
                    max_workers=1,
                    thread_name_prefix="gying-cloakbrowser",
                ),
                "context": None,
                "page": None,
                "ready": False,
                "last_used": time.monotonic(),
            }
            registry[key] = row
            return row

    def _gying_browser_submit_v1112(
        self,
        row: Dict[str, Any],
        callback,
        *args: Any,
    ) -> Any:
        executor = row.get("executor")
        if not executor:
            raise _GyingBrowserUnavailableV1112("CloakBrowser 会话执行器不存在")
        row["last_used"] = time.monotonic()
        try:
            return executor.submit(callback, *args).result()
        except _GyingBrowserUnavailableV1112:
            raise

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

        try:
            context = launch_browser_context(headless=True)
            page = context.new_page()
            if hasattr(page, "set_default_timeout"):
                page.set_default_timeout(max(int(timeout), 5) * 1000)
        except Exception as err:
            raise _GyingBrowserUnavailableV1112(
                f"CloakBrowser 启动失败：{type(err).__name__}"
            ) from err

        row["context"] = context
        row["page"] = page

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

    @staticmethod
    def _gying_browser_context_cookies_v1112(row: Dict[str, Any]) -> List[Dict[str, Any]]:
        context = row.get("context")
        if not context:
            return []
        try:
            cookies = context.cookies()
        except Exception:
            return []
        return [dict(item or {}) for item in list(cookies or []) if isinstance(item, dict)]

    def _gying_browser_sync_shadow_v1112(
        self,
        row: Dict[str, Any],
        session: requests.Session,
        node: str,
    ) -> None:
        cookies = self._gying_browser_context_cookies_v1112(row)
        if not cookies:
            return
        try:
            session.cookies.clear()
        except Exception:
            pass
        for cookie in cookies:
            name = str(cookie.get("name") or "").strip()
            value = str(cookie.get("value") or "")
            if not name:
                continue
            domain = str(cookie.get("domain") or "").strip()
            path = str(cookie.get("path") or "/") or "/"
            try:
                if domain:
                    session.cookies.set(name, value, domain=domain, path=path)
                else:
                    session.cookies.set(name, value)
            except Exception:
                try:
                    session.cookies.set(name, value)
                except Exception:
                    pass
        self._gying_sync_cookie_v1108(session, node)

    @staticmethod
    def _gying_browser_has_cookie_v1112(row: Dict[str, Any], name: str) -> bool:
        target = str(name or "").lower()
        return any(
            str(item.get("name") or "").lower() == target
            and bool(str(item.get("value") or ""))
            for item in GuangYaGyingBrowserV1112Mixin._gying_browser_context_cookies_v1112(row)
        )

    @staticmethod
    def _gying_browser_prepare_request_v1112(
        method: str,
        url: str,
        kwargs: Dict[str, Any],
    ) -> Tuple[str, Dict[str, str], Optional[str], str]:
        method = str(method or "GET").upper()
        request_url = str(url or "")
        params = kwargs.get("params")
        if params:
            prepared = requests.Request(method=method, url=request_url, params=params).prepare()
            request_url = str(prepared.url or request_url)

        raw_headers = dict(kwargs.get("headers") or {})
        headers: Dict[str, str] = {}
        referrer = ""
        for key, value in raw_headers.items():
            key_text = str(key or "").strip()
            lowered = key_text.lower()
            if not key_text or value is None:
                continue
            if lowered == "referer":
                referrer = str(value or "").strip()
                continue
            if lowered in _BROWSER_MANAGED_HEADERS_V1112 or lowered.startswith("sec-"):
                continue
            headers[key_text] = str(value)

        body: Optional[str] = None
        if method not in {"GET", "HEAD"}:
            if kwargs.get("json") is not None:
                body = json.dumps(kwargs.get("json"), ensure_ascii=False, separators=(",", ":"))
                headers.setdefault("Content-Type", "application/json;charset=UTF-8")
            elif kwargs.get("data") is not None:
                data = kwargs.get("data")
                if isinstance(data, (str, bytes)):
                    body = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
                else:
                    body = urlencode(data, doseq=True)
                headers.setdefault(
                    "Content-Type",
                    "application/x-www-form-urlencoded;charset=UTF-8",
                )

        if referrer and not _same_origin_v1112(referrer, request_url):
            referrer = ""
        return request_url, headers, body, referrer

    def _gying_browser_fetch_v1112(
        self,
        row: Dict[str, Any],
        method: str,
        url: str,
        kwargs: Dict[str, Any],
    ) -> requests.Response:
        page = row.get("page")
        if not page:
            raise _GyingBrowserUnavailableV1112("CloakBrowser 页面尚未建立")
        request_url, headers, body, referrer = self._gying_browser_prepare_request_v1112(
            method, url, kwargs
        )
        try:
            payload = page.evaluate(
                _FETCH_SCRIPT_V1112,
                {
                    "method": str(method or "GET").upper(),
                    "url": request_url,
                    "headers": headers,
                    "body": body,
                    "referrer": referrer,
                },
            )
        except Exception as err:
            raise RuntimeError(f"CloakBrowser 页面请求失败：{type(err).__name__}") from err
        if not isinstance(payload, dict):
            raise RuntimeError("CloakBrowser 页面请求未返回有效响应")
        return _response_v1112(
            str(payload.get("url") or request_url),
            _safe_int(payload.get("status"), 0),
            str(payload.get("text") or ""),
            dict(payload.get("headers") or {}),
        )

    def _gying_browser_navigation_response_v1112(
        self,
        row: Dict[str, Any],
        url: str,
        timeout: int,
    ) -> requests.Response:
        page = row.get("page")
        if not page:
            raise _GyingBrowserUnavailableV1112("CloakBrowser 页面尚未建立")
        try:
            navigation = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=max(int(timeout), 5) * 1000,
            )
            content = page.content()
            current_url = str(getattr(page, "url", "") or url)
        except Exception as err:
            raise RuntimeError(f"CloakBrowser 导航失败：{type(err).__name__}") from err
        return _response_v1112(
            current_url,
            _status_from_navigation_v1112(navigation),
            str(content or ""),
        )

    def _gying_browser_wait_site_solver_v1112(
        self,
        row: Dict[str, Any],
        response: requests.Response,
    ) -> requests.Response:
        kind = _challenge_kind_v1110(response)
        if not kind:
            return response
        page = row.get("page")
        if not page:
            return response
        deadline = time.monotonic() + _BROWSER_WAIT_SECONDS_V1112
        latest = response
        while time.monotonic() < deadline:
            if self._gying_browser_has_cookie_v1112(row, "browser_verified"):
                break
            time.sleep(0.25)
            try:
                latest = _response_v1112(
                    str(getattr(page, "url", "") or response.url),
                    int(getattr(response, "status_code", 200) or 200),
                    str(page.content() or ""),
                )
            except Exception:
                break
            if not _challenge_kind_v1110(latest):
                break
        return latest

    def _gying_browser_solve_v1112(
        self,
        row: Dict[str, Any],
        node: str,
        response: requests.Response,
        kind: str,
        timeout: int,
    ) -> None:
        if not bool(getattr(self, "_viewing_auto_challenge", True)):
            raise RuntimeError("观影返回浏览器安全验证；自动计算验证已关闭")
        node = canonical_gying_node(node) or str(node or "").rstrip("/")

        if kind == "refresh_overlay":
            if self._gying_browser_has_cookie_v1112(row, "browser_pow"):
                kind = "remote_pow"
            else:
                home = self._gying_browser_navigation_response_v1112(
                    row, node.rstrip("/") + "/", timeout
                )
                home = self._gying_browser_wait_site_solver_v1112(row, home)
                home_kind = _challenge_kind_v1110(home)
                if not home_kind:
                    return
                kind = home_kind
                response = home

        if kind == "remote_pow":
            pow_url = node.rstrip("/") + "/res/pow"
            challenge = self._gying_browser_fetch_v1112(
                row,
                "GET",
                pow_url,
                {"headers": {"Accept": "application/json,text/plain,*/*"}},
            )
            if int(challenge.status_code or 0) != 200:
                raise RuntimeError(f"观影获取 PoW 参数失败：HTTP {challenge.status_code}")
            data = _json_v1110(challenge)
            if not data.get("N") or not data.get("x") or _safe_int(data.get("t"), 0) <= 0:
                raise RuntimeError("观影 PoW 参数无效")

            started = time.monotonic()
            y = _solve_pow_hex(
                str(data.get("N")),
                str(data.get("x")),
                _safe_int(data.get("t"), 0),
            )
            elapsed = time.monotonic() - started
            if elapsed < _MIN_POW_SECONDS_V1112:
                time.sleep(_MIN_POW_SECONDS_V1112 - elapsed)

            verified = self._gying_browser_fetch_v1112(
                row,
                "POST",
                pow_url,
                {
                    "data": {"y": y},
                    "headers": {"Accept": "application/json,text/plain,*/*"},
                },
            )
            if int(verified.status_code or 0) >= 400:
                raise RuntimeError(f"观影 PoW 提交失败：HTTP {verified.status_code}")
            result = _json_v1110(verified)
            explicit_false = (
                "success" in result
                and not _truthy_success_v1110(result.get("success"))
                and result.get("code") not in (200, "200")
            )
            if explicit_false:
                message = str(result.get("msg") or result.get("message") or "").strip()[:120]
                raise RuntimeError(f"观影 PoW 被服务器拒绝：{message or '未返回原因'}")
            self._gying_auth_log(
                "INFO",
                "CloakBrowser PoW：同一浏览器上下文已提交，节点=%s browser_verified=%s，准备重试原请求",
                node,
                self._gying_browser_has_cookie_v1112(row, "browser_verified"),
            )
            return

        match = _GYING_CHALLENGE_RE.search(str(getattr(response, "text", "") or ""))
        if not match:
            raise RuntimeError("观影挑战页缺少可计算参数")
        try:
            data = json.loads(match.group(1))
        except Exception as err:
            raise RuntimeError("观影挑战参数解析失败") from err

        if kind == "embedded_pow":
            if not data.get("id") or not data.get("N") or not data.get("x"):
                raise RuntimeError("观影内嵌 PoW 参数无效")
            started = time.monotonic()
            y = _solve_pow_hex(
                str(data.get("N")),
                str(data.get("x")),
                _safe_int(data.get("t"), 0),
            )
            elapsed = time.monotonic() - started
            if elapsed < _MIN_POW_SECONDS_V1112:
                time.sleep(_MIN_POW_SECONDS_V1112 - elapsed)
            verify = self._gying_browser_fetch_v1112(
                row,
                "POST",
                str(getattr(response, "url", "") or node + "/"),
                {
                    "data": {
                        "action": "verify",
                        "id": str(data.get("id") or ""),
                        "y": y,
                    }
                },
            )
            if int(verify.status_code or 0) >= 400:
                raise RuntimeError(f"观影内嵌 PoW 提交失败：HTTP {verify.status_code}")
            return

        if kind == "legacy_hash":
            challenges = list(data.get("challenge") or [])
            nonces = _solve_legacy_nonces(
                challenges,
                str(data.get("salt") or ""),
                _safe_int(data.get("diff"), 0),
            )
            form: List[Tuple[str, str]] = [
                ("action", "verify"),
                ("id", str(data.get("id") or "")),
            ]
            form.extend(("nonce[]", str(value)) for value in nonces)
            verify = self._gying_browser_fetch_v1112(
                row,
                "POST",
                str(getattr(response, "url", "") or node + "/"),
                {"data": form},
            )
            if int(verify.status_code or 0) >= 400:
                raise RuntimeError(f"观影 legacy 验证提交失败：HTTP {verify.status_code}")
            return

        raise RuntimeError(f"观影暂不支持的挑战类型：{kind}")

    def _gying_browser_bootstrap_v1112(
        self,
        row: Dict[str, Any],
        node: str,
        session: requests.Session,
        timeout: int,
    ) -> None:
        self._gying_browser_ensure_context_v1112(row, node, session, timeout)
        if row.get("ready"):
            self._gying_browser_sync_shadow_v1112(row, session, node)
            return

        node = canonical_gying_node(node) or str(node or "").rstrip("/")
        self._gying_auth_log(
            "INFO",
            "CloakBrowser：节点=%s，建立同指纹浏览器会话",
            node,
        )
        home = self._gying_browser_navigation_response_v1112(
            row,
            node.rstrip("/") + "/",
            timeout,
        )
        kind = _challenge_kind_v1110(home)
        if kind:
            waited = self._gying_browser_wait_site_solver_v1112(row, home)
            kind = _challenge_kind_v1110(waited)
            if kind:
                self._gying_auth_log(
                    "INFO",
                    "CloakBrowser：站点脚本未在等待窗口内完成验证，节点=%s 类型=%s；改由同浏览器上下文提交",
                    node,
                    kind,
                )
                self._gying_browser_solve_v1112(row, node, waited, kind, timeout)
                confirmed = self._gying_browser_navigation_response_v1112(
                    row,
                    node.rstrip("/") + "/",
                    timeout,
                )
                confirmed = self._gying_browser_wait_site_solver_v1112(row, confirmed)
                if _challenge_kind_v1110(confirmed):
                    raise RuntimeError("观影 CloakBrowser 验证后根页仍返回挑战")
        row["ready"] = True
        self._gying_browser_sync_shadow_v1112(row, session, node)

    def _gying_browser_request_in_thread_v1112(
        self,
        row: Dict[str, Any],
        session: requests.Session,
        node: str,
        method: str,
        url: str,
        timeout: int,
        retry_challenge: bool,
        kwargs: Dict[str, Any],
    ) -> requests.Response:
        self._gying_browser_bootstrap_v1112(row, node, session, timeout)

        attempts = 2 if retry_challenge else 1
        solved_kind = ""
        for attempt in range(attempts):
            response = self._gying_browser_fetch_v1112(row, method, url, kwargs)
            self._gying_browser_sync_shadow_v1112(row, session, node)

            text = str(response.text or "")
            lowered = text.lower()
            if int(response.status_code or 0) in {403, 404} and any(
                marker in lowered for marker in _BLOCK_MARKERS_V1110
            ):
                raise RuntimeError(f"观影节点当前出口被阻断：HTTP {response.status_code}")

            kind = _challenge_kind_v1110(response)
            if not kind:
                if solved_kind:
                    self._gying_auth_log(
                        "INFO",
                        "CloakBrowser PoW：原请求重试成功，节点=%s 类型=%s",
                        canonical_gying_node(node) or str(node or ""),
                        solved_kind,
                    )
                return response

            if not retry_challenge or attempt + 1 >= attempts:
                raise RuntimeError("观影 CloakBrowser 验证后原请求仍返回挑战页")

            solved_kind = kind
            self._gying_browser_solve_v1112(
                row,
                node,
                response,
                kind,
                timeout,
            )
            self._gying_browser_sync_shadow_v1112(row, session, node)

        raise RuntimeError("观影 CloakBrowser 请求重试次数已耗尽")

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
        canonical = canonical_gying_node(node) or str(node or "").rstrip("/")
        if not canonical or not _same_origin_v1112(canonical + "/", str(url or "")):
            return super()._gying_request(
                session,
                node,
                method,
                url,
                retry_challenge=retry_challenge,
                **kwargs,
            )

        timeout = int(
            kwargs.pop(
                "timeout",
                int(getattr(self, "_provider_timeout", 15) or 15),
            )
            or 15
        )
        kwargs.pop("allow_redirects", None)
        row = self._gying_browser_row_v1112(canonical)
        try:
            return self._gying_browser_submit_v1112(
                row,
                self._gying_browser_request_in_thread_v1112,
                row,
                session,
                canonical,
                str(method or "GET").upper(),
                str(url or ""),
                timeout,
                bool(retry_challenge),
                dict(kwargs),
            )
        except _GyingBrowserUnavailableV1112 as err:
            if not bool(getattr(self, "_gying_browser_fallback_logged_v1112", False)):
                self._gying_browser_fallback_logged_v1112 = True
                self._gying_auth_log(
                    "WARNING",
                    "CloakBrowser 当前不可用，GYING 暂时回退 PanSou requests 链：%s",
                    str(err)[:160],
                )
            return super()._gying_request(
                session,
                canonical,
                method,
                url,
                retry_challenge=retry_challenge,
                timeout=timeout,
                **kwargs,
            )

    def api_viewing_auth_start(self, force: bool = False) -> Dict[str, Any]:
        if force:
            self._gying_browser_close_all_v1112()
        return dict(super().api_viewing_auth_start(force=bool(force)) or {})


__all__ = [
    "GuangYaGyingBrowserV1112Mixin",
    "_cookie_seed_v1112",
    "_response_v1112",
]
