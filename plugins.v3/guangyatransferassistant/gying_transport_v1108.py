"""v1.10.8 观影请求层稳定性与异步人工认证。

本层参考近期仍在维护的观影接入实现，解决 v1.10.7 的两个运行态问题：
1. “开始人工认证”不再在一次 MoviePilot API 请求中串行探测多个节点/PoW，改为立即
   返回 auth_id 后由后台线程完成节点探测，避免前端先报“服务器无响应”；
2. PoW 判定不再使用宽泛“安全验证”文本。正常数据页出现 ``_obj.`` 时优先判正常，
   JSON 仅在 code=419 或 refresh=1 且消息明确要求验证时触发计算。

另外把观影确认的 8 个中文镜像视为同一后端的受控镜像组：仅在这个固定白名单内部复用
运行时 Cookie；发布/换址页以及其它域名绝不继承登录 Cookie。网络指纹统一为移动端，
与 315x180 汉字点击验证码尺寸保持一致。

本层不会自动识别、OCR 或代点汉字验证码；验证码仍由用户本人在 MoviePilot 页面完成。
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, List, Optional

import requests

from .gying_auth_v1107 import _looks_like_content_node
from .gying_hardening_v193 import canonical_gying_node
from .gying_runtime_v193 import _apply_cookie_header, _solve_pow_hex


_GYING_MIRRORS_V1108 = (
    "https://www.教父.com",
    "https://www.星际穿越.com",
    "https://www.楚门的世界.com",
    "https://www.泰坦尼克号.com",
    "https://www.盗梦空间.com",
    "https://www.肖申克的救赎.com",
    "https://www.阿甘正传.com",
    "https://www.黑客帝国.com",
)
_GYING_MIRROR_SET_V1108 = frozenset(
    canonical_gying_node(value) for value in _GYING_MIRRORS_V1108 if canonical_gying_node(value)
)
_MOBILE_UA_V1108 = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1"
)
_BLOCK_PAGE_MARKERS_V1108 = ("angie", "request forbidden", "access denied")
_CHALLENGE_TEXT_MARKERS_V1108 = (
    "浏览器验证已过期",
    "浏览器安全验证",
    "正在进行浏览器计算验证",
    "正在确认你是不是机器人",
    "pow.worker",
)
_ASYNC_STAGES_V1108 = {"connecting", "discovering", "probing", "login_page"}


def _response_json_v1108(response: requests.Response) -> Dict[str, Any]:
    try:
        payload = response.json()
    except Exception:
        try:
            payload = json.loads(str(getattr(response, "text", "") or "{}"))
        except Exception:
            payload = {}
    return payload if isinstance(payload, dict) else {}


def _challenge_required_v1108(response: requests.Response) -> bool:
    """按真实站点语义判 PoW；正常 _obj. 数据页永远优先于静态脚本关键字。"""
    text = str(getattr(response, "text", "") or "")
    if "_obj." in text:
        return False
    status = int(getattr(response, "status_code", 0) or 0)
    if status == 419:
        return True
    payload = _response_json_v1108(response)
    try:
        if int(payload.get("code") or 0) == 419:
            return True
    except (TypeError, ValueError):
        pass
    try:
        refresh = int(payload.get("refresh") or 0) == 1
    except (TypeError, ValueError):
        refresh = False
    message = str(payload.get("msg") or payload.get("message") or "")
    if refresh and "验证" in message:
        return True
    return any(marker in text for marker in _CHALLENGE_TEXT_MARKERS_V1108)


def _cookie_header_v1108(session: requests.Session) -> str:
    rows: List[str] = []
    seen = set()
    for cookie in list(session.cookies):
        name = str(getattr(cookie, "name", "") or "").strip()
        value = str(getattr(cookie, "value", "") or "").strip()
        if name and value and name not in seen:
            rows.append(f"{name}={value}")
            seen.add(name)
    return "; ".join(rows)


def _drop_cookie_v1108(session: requests.Session, name: str) -> None:
    target = str(name or "").lower()
    for cookie in list(session.cookies):
        if str(getattr(cookie, "name", "") or "").lower() != target:
            continue
        try:
            session.cookies.clear(cookie.domain, cookie.path, cookie.name)
        except Exception:
            try:
                session.cookies.set(cookie.name, None)
            except Exception:
                pass


class GuangYaGyingTransportV1108Mixin:
    """放在最终插件 MRO 最外侧的观影传输与异步认证层。"""

    build_id = "20260902-r19"

    def init_plugin(self, config: dict = None) -> None:
        super().init_plugin(dict(config or {}))
        self._gying_transport_lock_v1108 = threading.RLock()
        self._gying_shared_cookie_v1108 = ""
        self._gying_auth_worker_v1108: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # 镜像节点 / Cookie / 移动端指纹
    # ------------------------------------------------------------------
    @staticmethod
    def _gying_is_mirror_v1108(node: str) -> bool:
        return canonical_gying_node(node) in _GYING_MIRROR_SET_V1108

    def _discover_gying_nodes(self, force: bool = False) -> List[str]:
        rows = list(super()._discover_gying_nodes(force=force) or [])
        for raw in _GYING_MIRRORS_V1108:
            node = canonical_gying_node(raw)
            if node and node not in rows:
                rows.append(node)
        return rows[:40]

    def _gying_group_cookie_seed_v1108(self) -> str:
        cached = str(getattr(self, "_gying_shared_cookie_v1108", "") or "").strip()
        if cached:
            return cached
        try:
            state = self._gying_state()
            nodes = dict(state.get("nodes") or {})
        except Exception:
            return ""
        ranked = []
        for raw_node, raw_row in nodes.items():
            node = canonical_gying_node(str(raw_node or ""))
            row = dict(raw_row or {}) if isinstance(raw_row, dict) else {}
            cookie = str(row.get("cookie") or "").strip()
            if node in _GYING_MIRROR_SET_V1108 and cookie:
                ranked.append((float(row.get("last_ok_ts") or 0), cookie))
        if not ranked:
            return ""
        ranked.sort(key=lambda item: item[0], reverse=True)
        return ranked[0][1]

    def _gying_sync_cookie_v1108(self, session: requests.Session, node: str) -> None:
        if not self._gying_is_mirror_v1108(node):
            return
        header = _cookie_header_v1108(session)
        if header:
            with getattr(self, "_gying_transport_lock_v1108", threading.RLock()):
                self._gying_shared_cookie_v1108 = header

    def _gying_new_session(self, node: str, saved_cookie: str = "") -> requests.Session:
        canonical = canonical_gying_node(node)
        seed = str(saved_cookie or "").strip()
        if canonical in _GYING_MIRROR_SET_V1108 and not seed:
            seed = self._gying_group_cookie_seed_v1108()
        session = super()._gying_new_session(canonical or node, saved_cookie=seed)
        session.headers.update({
            "User-Agent": _MOBILE_UA_V1108,
            "Accept": "text/html,application/xhtml+xml,application/json,text/plain,*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        for key in ("sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform"):
            session.headers.pop(key, None)
        shared = str(getattr(self, "_gying_shared_cookie_v1108", "") or "").strip()
        if canonical in _GYING_MIRROR_SET_V1108 and shared:
            _apply_cookie_header(session, shared)
        return session

    # ------------------------------------------------------------------
    # 精确 PoW 检测 + 远程 PoW 必须 success=true
    # ------------------------------------------------------------------
    def _gying_solve_challenge(
        self,
        session: requests.Session,
        node: str,
        response: requests.Response,
    ) -> Dict[str, Any]:
        text = str(getattr(response, "text", "") or "")
        # 老内嵌 challenge 保留既有实现；当前内容站的 /res/pow 使用下面的严格路径。
        if "const json" in text or "nonce[]" in text:
            return dict(super()._gying_solve_challenge(session, node, response) or {})
        if not bool(getattr(self, "_viewing_auto_challenge", True)):
            raise RuntimeError("观影返回浏览器安全验证；自动计算验证已关闭")
        node = canonical_gying_node(node) or str(node or "").rstrip("/")
        pow_url = node.rstrip("/") + "/res/pow"
        timeout = min(max(int(getattr(self, "_provider_timeout", 15) or 15), 5), 20)
        started = time.monotonic()
        self._gying_auth_log("INFO", "检测到浏览器 PoW：节点=%s，开始计算提交", node)
        challenge = session.get(
            pow_url,
            headers={"Referer": str(getattr(response, "url", "") or node + "/")},
            timeout=timeout,
            allow_redirects=True,
        )
        self._gying_sync_cookie_v1108(session, node)
        payload = _response_json_v1108(challenge)
        n_hex = str(payload.get("N") or "")
        x_hex = str(payload.get("x") or "")
        rounds = payload.get("t")
        if not n_hex or not x_hex or rounds is None:
            raise RuntimeError("观影远程 PoW 参数不完整")
        try:
            rounds_int = int(rounds)
        except (TypeError, ValueError) as err:
            raise RuntimeError("观影远程 PoW 轮数无效") from err
        y = _solve_pow_hex(n_hex, x_hex, rounds_int)
        elapsed = time.monotonic() - started
        if elapsed < 3.0:
            time.sleep(3.0 - elapsed)
        verified = session.post(
            pow_url,
            data={"y": y},
            headers={
                "Origin": node,
                "Referer": str(getattr(response, "url", "") or node + "/"),
            },
            timeout=timeout + 15,
            allow_redirects=True,
        )
        self._gying_sync_cookie_v1108(session, node)
        result = _response_json_v1108(verified)
        accepted = result.get("success") in (True, 1, "1", "true", "True")
        if int(getattr(verified, "status_code", 0) or 0) >= 400 or not accepted:
            raise RuntimeError(
                f"观影远程 PoW 未被服务器确认：HTTP {int(getattr(verified, 'status_code', 0) or 0)}"
            )
        _drop_cookie_v1108(session, "browser_pow")
        self._gying_sync_cookie_v1108(session, node)
        self._gying_auth_log(
            "INFO",
            "PoW计算提交完成：节点=%s 耗时=%.2fs，等待原请求确认",
            node,
            time.monotonic() - started,
        )
        return {"mode": "remote_pow", "success": True}

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
        timeout = kwargs.pop("timeout", int(getattr(self, "_provider_timeout", 15) or 15))
        max_pow = 2 if retry_challenge else 0
        solved = 0
        for attempt in range(max_pow + 1):
            response = session.request(
                str(method or "GET").upper(),
                url,
                timeout=timeout,
                allow_redirects=True,
                **kwargs,
            )
            self._gying_sync_cookie_v1108(session, node)
            text = str(getattr(response, "text", "") or "")
            lowered = text.lower()
            if int(getattr(response, "status_code", 0) or 0) in {403, 404} and any(
                marker in lowered for marker in _BLOCK_PAGE_MARKERS_V1108
            ):
                raise RuntimeError(f"观影节点当前出口被阻断：HTTP {response.status_code}")
            if not _challenge_required_v1108(response):
                if solved:
                    self._gying_auth_log(
                        "INFO",
                        "浏览器计算验证确认通过：节点=%s 连续挑战=%s",
                        canonical_gying_node(node) or str(node or ""),
                        solved,
                    )
                return response
            if attempt >= max_pow:
                break
            solved += 1
            self._gying_solve_challenge(session, node, response)
        raise RuntimeError(
            f"观影浏览器验证连续 {solved or 1} 次计算后原请求仍要求验证；请稍后重试或检查当前出口/节点"
        )

    # ------------------------------------------------------------------
    # 人工认证改后台执行：API 立即返回，不再被 8~12 个节点串行探测拖超时
    # ------------------------------------------------------------------
    def _gying_auth_is_current_v1108(self, auth_id: str) -> bool:
        return bool(auth_id) and str(getattr(self, "_gying_auth_active_id", "") or "") == auth_id and bool(
            (getattr(self, "_gying_auth_sessions", {}) or {}).get(auth_id)
        )

    def _gying_auth_update_v1108(self, auth_id: str, **values: Any) -> Optional[Dict[str, Any]]:
        with getattr(self, "_gying_auth_lock", threading.RLock()):
            row = (getattr(self, "_gying_auth_sessions", {}) or {}).get(auth_id)
            if not isinstance(row, dict):
                return None
            row.update(values)
            row["updated_ts"] = time.time()
            return row

    def _gying_auth_worker_run_v1108(self, auth_id: str, force: bool) -> None:
        errors: List[str] = []
        try:
            self._gying_auth_update_v1108(
                auth_id,
                stage="discovering",
                message="正在发现并排序观影内容节点…",
            )
            chooser = getattr(self, "_gying_node_order", None)
            try:
                node_order = list(chooser() or []) if callable(chooser) else []
            except Exception:
                node_order = []
            if not node_order:
                node_order = list(self._discover_gying_nodes(force=False) or [])
            state = self._gying_state()
            for raw_node in node_order[:12]:
                if not self._gying_auth_is_current_v1108(auth_id):
                    return
                node = canonical_gying_node(raw_node)
                if not node:
                    continue
                self._gying_auth_update_v1108(
                    auth_id,
                    stage="probing",
                    node=node,
                    message=f"正在连接观影节点 {node}…",
                )
                saved = "" if force else str(((state.get("nodes") or {}).get(node) or {}).get("cookie") or "")
                session = self._gying_new_session(node, saved_cookie=saved)
                try:
                    home = self._gying_request(
                        session,
                        node,
                        "GET",
                        node.rstrip("/") + "/",
                        timeout=min(int(getattr(self, "_provider_timeout", 15) or 15), 10),
                        headers={"Accept": "text/html,*/*"},
                    )
                    if not _looks_like_content_node(home):
                        errors.append(f"{node}: 非内容节点")
                        session.close()
                        continue
                    if not force and self._gying_authenticated_probe(session, node):
                        self._gying_persist_session(
                            node,
                            session,
                            status="ok",
                            login_mode="cookie_reuse",
                            authenticated=True,
                            verified=bool(session.cookies.get("browser_verified")),
                        )
                        self._gying_sync_cookie_v1108(session, node)
                        session.close()
                        self._gying_auth_update_v1108(
                            auth_id,
                            stage="authenticated",
                            node=node,
                            session=None,
                            captcha={},
                            points=[],
                            message="现有观影会话仍有效，无需再次验证码",
                        )
                        return
                    self._gying_auth_update_v1108(
                        auth_id,
                        stage="login_page",
                        node=node,
                        message="已连接内容节点，正在准备登录验证码…",
                    )
                    self._gying_request(
                        session,
                        node,
                        "GET",
                        node.rstrip("/") + "/user/login",
                        timeout=min(int(getattr(self, "_provider_timeout", 15) or 15), 10),
                        headers={"Referer": node.rstrip("/") + "/"},
                    )
                    captcha = self._gying_request_captcha(session, node)
                    if not self._gying_auth_is_current_v1108(auth_id):
                        session.close()
                        return
                    row = self._gying_auth_update_v1108(
                        auth_id,
                        stage="captcha",
                        node=node,
                        session=session,
                        captcha=captcha,
                        points=[],
                        message="请按提示顺序点击汉字；点满后自动校验并登录",
                    )
                    self._gying_auth_log(
                        "INFO",
                        "人工登录：验证码已生成，节点=%s，需要点击=%s个",
                        node,
                        len(str(captcha.get("text") or "")),
                    )
                    if row is None:
                        session.close()
                    return
                except Exception as err:
                    errors.append(f"{node}: {str(err)[:120]}")
                    try:
                        session.close()
                    except Exception:
                        pass
                    continue
        except Exception as err:
            errors.append(str(err)[:180])
        if self._gying_auth_is_current_v1108(auth_id):
            self._gying_auth_update_v1108(
                auth_id,
                stage="unavailable",
                session=None,
                captcha={},
                points=[],
                message=("；".join(errors[:5]) or "没有可用于人工登录的观影内容节点")[:500],
            )

    def _gying_auth_start(self, force: bool = False) -> Dict[str, Any]:
        if not bool(getattr(self, "_viewing_enabled", False)):
            return {"success": False, "stage": "disabled", "message": "观影未启用"}
        username = str(getattr(self, "_viewing_username", "") or "").strip()
        password = str(getattr(self, "_viewing_password", "") or "")
        if not (username and password):
            return {
                "success": False,
                "stage": "credentials_missing",
                "message": "请先在插件配置中填写观影用户名和密码",
            }
        with getattr(self, "_gying_auth_lock", threading.RLock()):
            self._gying_auth_cleanup()
            active_id = str(getattr(self, "_gying_auth_active_id", "") or "")
            active = (getattr(self, "_gying_auth_sessions", {}) or {}).get(active_id) if active_id else None
            if isinstance(active, dict) and str(active.get("stage") or "") in _ASYNC_STAGES_V1108 and not force:
                return {"success": True, **self._gying_auth_public(active)}
            if active_id:
                old = (getattr(self, "_gying_auth_sessions", {}) or {}).pop(active_id, None)
                try:
                    if old and old.get("session"):
                        old["session"].close()
                except Exception:
                    pass
            import secrets

            auth_id = secrets.token_urlsafe(18)
            now = time.time()
            row = {
                "auth_id": auth_id,
                "session": None,
                "node": "",
                "stage": "connecting",
                "captcha": {},
                "points": [],
                "created_ts": now,
                "updated_ts": now,
                "message": "认证任务已启动；节点探测与 PoW 在后台执行，不会阻塞 MoviePilot 页面",
            }
            self._gying_auth_sessions[auth_id] = row
            self._gying_auth_active_id = auth_id
        worker = threading.Thread(
            target=self._gying_auth_worker_run_v1108,
            args=(auth_id, bool(force)),
            daemon=True,
            name="GuangYa-GYING-Auth",
        )
        self._gying_auth_worker_v1108 = worker
        worker.start()
        self._gying_auth_log("INFO", "人工登录：后台认证任务已启动")
        return {"success": True, **self._gying_auth_public(row)}


__all__ = [
    "GuangYaGyingTransportV1108Mixin",
    "_challenge_required_v1108",
    "_GYING_MIRRORS_V1108",
]
