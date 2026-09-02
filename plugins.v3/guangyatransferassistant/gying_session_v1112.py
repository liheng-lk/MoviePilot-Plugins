"""v1.10.12 观影验证会话隔离与真实浏览器兜底。

v1.10.11 实机日志暴露出三个同时存在的问题：

1. v1.10.8 的镜像共享 Cookie 会把 ``browser_pow`` / ``browser_verified`` 这类
   短期挑战 Cookie 带到其它镜像或下一次 Session；当服务器已经再次下发挑战页时，
   旧 ``browser_verified`` 仍会让本地误判“提交已取得确认信号”。
2. 某些旧调用链仍直接调用 ``_gying_solve_challenge``，会绕回 v1.10.8 的严格
   ``success=true`` solver，于是同一轮日志里同时出现新旧两种 PoW 错误。
3. 热更新后旧插件实例的观影后台线程没有统一套用运行所有权门禁，会与新实例并发探测，
   因而仍能看到已经被新版本排除的 gying/gyg 发布页。

本层修复以上问题，并仅在“算法 PoW 已提交但同一原请求仍反复挑战”时，按 MoviePilot V3
官方 ``app.sdk.browser.launch_browser_context`` 启动 CloakBrowser 做一次同节点浏览器兜底。
浏览器只执行站点自身 PoW/overlay JavaScript，不识别、不点击人工汉字验证码；成功后仅把
Cookie 写回当前 requests.Session，并继续走原有登录/搜索/downurl 解析。

不使用代理，不记录 Cookie 值、PoW 参数、账号密码或验证码坐标。
"""

from __future__ import annotations

import time
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

import requests

from .gying_autologin_v1109 import GuangYaGyingAutoLoginV1109Mixin
from .gying_hardening_v193 import canonical_gying_node
from .gying_pansou_v1110 import _challenge_kind_v1110
from .gying_pow_v1111 import _has_cookie_v1111, _is_content_candidate_v1111
from .gying_transport_v1108 import _cookie_header_v1108, _drop_cookie_v1108


_CHALLENGE_COOKIE_NAMES_V1112 = frozenset({"browser_pow", "browser_verified"})
_MAX_CONTENT_NODES_V1112 = 10
_BROWSER_WAIT_SECONDS_V1112 = 14.0


def _sanitize_cookie_header_v1112(header: str) -> str:
    """跨镜像共享时剔除短期 PoW Cookie，不改变其它登录 Cookie。"""
    rows: List[str] = []
    seen = set()
    for part in str(header or "").split(";"):
        token = str(part or "").strip()
        if not token or "=" not in token:
            continue
        name, value = token.split("=", 1)
        clean = name.strip()
        if not clean or clean.lower() in _CHALLENGE_COOKIE_NAMES_V1112 or clean.lower() in seen:
            continue
        rows.append(f"{clean}={value.strip()}")
        seen.add(clean.lower())
    return "; ".join(rows)


def _browser_page_is_normal_v1112(text: str, url: str = "") -> bool:
    """判断 CloakBrowser 当前页是否已经离开纯 PoW gate。"""
    body = str(text or "")
    lowered = body.lower()
    if "_obj." in body:
        return True
    if "name=\"username\"" in lowered and "name=\"password\"" in lowered:
        return True
    if "name='username'" in lowered and "name='password'" in lowered:
        return True
    if "/user/login" in str(url or "") and ("username" in lowered and "password" in lowered):
        return True
    verify_text = any(token in body for token in (
        "正在确认你是不是机器人",
        "浏览器安全验证",
        "正在进行浏览器计算验证",
    ))
    remote_sig = any(token in body for token in ("powSolve-", "pow.worker-", "const jss=", "/res/pow"))
    return not (verify_text and remote_sig)


def _response_from_browser_v1112(text: str, url: str, status: int = 200) -> requests.Response:
    """把浏览器最终 HTML 包装成既有解析器可消费的 requests.Response。"""
    response = requests.Response()
    response.status_code = int(status or 200)
    response.url = str(url or "")
    response.encoding = "utf-8"
    response._content = str(text or "").encode("utf-8", errors="replace")
    response.request = requests.Request("GET", response.url or "https://localhost/").prepare()
    return response


class GuangYaGyingSessionV1112Mixin(GuangYaGyingAutoLoginV1109Mixin):
    """最终观影会话层：挑战 Cookie 节点隔离、旧 solver 封口、CloakBrowser 兜底。"""

    build_id = "20260902-r23"

    @staticmethod
    def _gying_runtime_current_v1112(instance: Any) -> bool:
        checker = getattr(instance, "_runtime_is_current", None)
        if not callable(checker) or not hasattr(instance, "_runtime_generation"):
            return True
        try:
            return bool(checker())
        except Exception:
            return False

    def _gying_auth_is_current_v1108(self, auth_id: str) -> bool:
        if not self._gying_runtime_current_v1112(self):
            return False
        return bool(super()._gying_auth_is_current_v1108(auth_id))

    def _gying_sync_cookie_v1108(self, session: requests.Session, node: str) -> None:
        """镜像组只共享普通登录 Cookie；PoW challenge Cookie 永不跨节点传播。"""
        is_mirror = getattr(self, "_gying_is_mirror_v1108", None)
        if callable(is_mirror) and not bool(is_mirror(node)):
            return
        header = _sanitize_cookie_header_v1112(_cookie_header_v1108(session))
        lock = getattr(self, "_gying_transport_lock_v1108", None)
        if lock is None:
            self._gying_shared_cookie_v1108 = header
            return
        with lock:
            self._gying_shared_cookie_v1108 = header

    def _gying_new_session(self, node: str, saved_cookie: str = "") -> requests.Session:
        """每个新 Session 都重新建立 browser_pow/browser_verified，杜绝旧挑战污染。"""
        session = super()._gying_new_session(node, saved_cookie=saved_cookie)
        for name in _CHALLENGE_COOKIE_NAMES_V1112:
            _drop_cookie_v1108(session, name)
        # v1.10.8 运行时共享缓存也可能来自旧插件实例；同步为剔除挑战 Cookie 的版本。
        shared = _sanitize_cookie_header_v1112(str(getattr(self, "_gying_shared_cookie_v1108", "") or ""))
        self._gying_shared_cookie_v1108 = shared
        return session

    def _gying_node_order(self) -> List[str]:
        """业务请求只接受真实 IDN 内容节点；发布/换址域只能参与显式节点刷新。"""
        rows: List[str] = []
        try:
            source = list(super()._gying_node_order() or [])
        except Exception:
            source = []
        for raw in source:
            node = canonical_gying_node(str(raw or ""))
            if node and _is_content_candidate_v1111(node) and node not in rows:
                rows.append(node)
        if not rows:
            try:
                for raw in list(self._discover_gying_nodes(force=False) or []):
                    node = canonical_gying_node(str(raw or ""))
                    if node and _is_content_candidate_v1111(node) and node not in rows:
                        rows.append(node)
            except Exception:
                pass
        return rows[:_MAX_CONTENT_NODES_V1112]

    def _gying_solve_challenge_v1110(
        self,
        session: requests.Session,
        node: str,
        response: requests.Response,
        kind: Optional[str] = None,
    ) -> Dict[str, Any]:
        kind = str(kind or _challenge_kind_v1110(response) or "")
        if kind == "remote_pow" and _has_cookie_v1111(session, "browser_verified"):
            # 如果服务器已经返回新的 challenge，现存 verified 标记就不能再被当成提交成功证据。
            _drop_cookie_v1108(session, "browser_verified")
            self._gying_auth_log(
                "INFO",
                "PanSou PoW：挑战页出现时检测到旧 browser_verified，已丢弃并重新建立本节点验证态",
            )
        return dict(super()._gying_solve_challenge_v1110(session, node, response, kind=kind) or {})

    def _gying_solve_challenge(
        self,
        session: requests.Session,
        node: str,
        response: requests.Response,
    ) -> Dict[str, Any]:
        """封死旧 v1.10.8 remote solver；所有可识别挑战统一进入 v1.10.11+ 链。"""
        kind = str(_challenge_kind_v1110(response) or "")
        if kind in {"remote_pow", "embedded_pow", "legacy_hash"}:
            return self._gying_solve_challenge_v1110(session, node, response, kind=kind)
        if kind == "refresh_overlay":
            timeout = min(max(int(getattr(self, "_provider_timeout", 15) or 15), 5), 20)
            ok = bool(self._gying_refresh_bootstrap_v1110(session, node, response, timeout))
            if ok:
                return {"mode": "refresh_overlay", "success": True}
            raise RuntimeError("观影动态 refresh 验证无法建立 browser_pow 挑战")
        return dict(super()._gying_solve_challenge(session, node, response) or {})

    @staticmethod
    def _browser_cookie_rows_v1112(session: requests.Session, node: str) -> List[Dict[str, Any]]:
        """准备注入浏览器的 Cookie；挑战 Cookie 不从 requests 侧复用。"""
        host = str(urlparse(canonical_gying_node(node) or str(node or "")).hostname or "").lower()
        rows: List[Dict[str, Any]] = []
        for cookie in list(session.cookies):
            name = str(getattr(cookie, "name", "") or "").strip()
            value = str(getattr(cookie, "value", "") or "")
            if not name or not value or name.lower() in _CHALLENGE_COOKIE_NAMES_V1112:
                continue
            domain = str(getattr(cookie, "domain", "") or "").lstrip(".").lower()
            if domain and host and not (host == domain or host.endswith("." + domain)):
                continue
            rows.append({"name": name, "value": value, "url": (canonical_gying_node(node) or node).rstrip("/") + "/"})
        return rows

    @staticmethod
    def _import_browser_cookies_v1112(session: requests.Session, cookies: Iterable[Dict[str, Any]]) -> Tuple[int, bool]:
        """从 CloakBrowser 回写 Cookie；只返回数量/验证标记，不暴露值。"""
        imported = 0
        verified = False
        for raw in cookies or []:
            row = dict(raw or {})
            name = str(row.get("name") or "").strip()
            value = str(row.get("value") or "")
            if not name or not value:
                continue
            domain = str(row.get("domain") or "").strip() or None
            path = str(row.get("path") or "/").strip() or "/"
            try:
                session.cookies.set(name, value, domain=domain, path=path)
            except Exception:
                try:
                    session.cookies.set(name, value)
                except Exception:
                    continue
            imported += 1
            if name.lower() == "browser_verified":
                verified = True
        return imported, verified

    def _gying_browser_fallback_v1112(
        self,
        session: requests.Session,
        node: str,
        url: str,
        timeout: int,
    ) -> Optional[requests.Response]:
        """用 MoviePilot 官方 CloakBrowser 执行站点自身 challenge，再把会话回写到 requests。"""
        node = canonical_gying_node(node) or str(node or "").rstrip("/")
        if not node or not _is_content_candidate_v1111(node):
            return None
        try:
            from app.sdk.browser import launch_browser_context
        except Exception as err:
            self._gying_auth_log("WARNING", "观影浏览器兜底不可用：SDK导入失败 类型=%s", type(err).__name__)
            return None

        context = None
        page = None
        try:
            self._gying_auth_log("INFO", "观影浏览器兜底：节点=%s，启动 MoviePilot CloakBrowser 重新建立验证态", node)
            context = launch_browser_context(headless=True)
            add_cookies = getattr(context, "add_cookies", None)
            seed_rows = self._browser_cookie_rows_v1112(session, node)
            if callable(add_cookies) and seed_rows:
                add_cookies(seed_rows)
            page = context.new_page()
            if hasattr(page, "set_default_timeout"):
                page.set_default_timeout(max(5000, int(timeout) * 1000))
            target = str(url or node.rstrip("/") + "/")
            nav = page.goto(target, wait_until="domcontentloaded", timeout=max(5000, int(timeout) * 1000))
            deadline = time.monotonic() + min(_BROWSER_WAIT_SECONDS_V1112, max(6.0, float(timeout)))
            final_text = ""
            final_url = target
            while time.monotonic() < deadline:
                try:
                    final_text = str(page.content() or "")
                    final_url = str(getattr(page, "url", "") or target)
                except Exception:
                    final_text = ""
                if final_text and _browser_page_is_normal_v1112(final_text, final_url):
                    break
                time.sleep(0.5)

            cookie_rows = list(context.cookies() or [])
            imported, verified = self._import_browser_cookies_v1112(session, cookie_rows)
            try:
                user_agent = str(page.evaluate("navigator.userAgent") or "").strip()
                if user_agent:
                    session.headers["User-Agent"] = user_agent
            except Exception:
                pass
            self._gying_sync_cookie_v1108(session, node)

            status = int(getattr(nav, "status", 200) or 200) if nav is not None else 200
            normal = bool(final_text) and _browser_page_is_normal_v1112(final_text, final_url)
            self._gying_auth_log(
                "INFO" if normal else "WARNING",
                "观影浏览器兜底：节点=%s 完成，正常页=%s browser_verified=%s 导入Cookie数=%s",
                node,
                normal,
                verified,
                imported,
            )
            if normal:
                return _response_from_browser_v1112(final_text, final_url, status=status)
            return None
        except Exception as err:
            self._gying_auth_log(
                "WARNING",
                "观影浏览器兜底失败：节点=%s 类型=%s",
                node,
                type(err).__name__,
            )
            return None
        finally:
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
        if not self._gying_runtime_current_v1112(self):
            raise RuntimeError("观影任务所属插件实例已被热更新替代")
        timeout = int(kwargs.get("timeout", int(getattr(self, "_provider_timeout", 15) or 15)) or 15)
        try:
            return super()._gying_request(
                session,
                node,
                method,
                url,
                retry_challenge=retry_challenge,
                **kwargs,
            )
        except RuntimeError as err:
            message = str(err or "")
            if not retry_challenge or not any(token in message for token in (
                "原请求仍返回挑战页",
                "PoW 未被服务器确认",
                "远程 PoW 未被服务器确认",
                "动态 refresh 验证重试后仍未恢复",
            )):
                raise

            # 算法链已经失败后才启用真实浏览器，不让普通请求承担浏览器启动开销。
            fallback = self._gying_browser_fallback_v1112(session, node, url, timeout)
            if fallback is not None and str(method or "GET").upper() == "GET":
                return fallback
            if fallback is not None:
                # POST 请求无法用 page.goto 原样复现，先用浏览器建立验证态后再让原链重试一次。
                return super()._gying_request(
                    session,
                    node,
                    method,
                    url,
                    retry_challenge=False,
                    **kwargs,
                )
            raise

    def _viewing_session(self):
        if not self._gying_runtime_current_v1112(self):
            return requests.Session(), {
                "success": False,
                "mode": "stale_instance",
                "message": "旧版观影后台任务已被新插件实例终止",
            }
        return super()._viewing_session()

    def _gying_raw_results(self, keyword: str, force: bool = False):
        if not self._gying_runtime_current_v1112(self):
            return [], {
                "success": False,
                "mode": "stale_instance",
                "message": "旧版观影搜索任务已被新插件实例终止",
            }
        return super()._gying_raw_results(keyword, force=force)


__all__ = [
    "GuangYaGyingSessionV1112Mixin",
    "_sanitize_cookie_header_v1112",
    "_browser_page_is_normal_v1112",
]
