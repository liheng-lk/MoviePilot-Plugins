"""v1.10.9 观影自动登录优先层。

公开维护中的 GYING 接入并不会默认要求人工汉字验证码：它们先完成浏览器计算验证，
随后以 code="" 直接 POST /user/login；只有站点明确返回验证码要求时才需要人工处理。

本层把这一行为恢复为默认路径：
- 正常搜索/测试会话自动尝试账号密码登录；
- “建立观影会话”按钮也先在后台自动登录，不再一上来就请求点击验证码；
- 只有服务端明确返回 captcha/点击验证提示时，才进入既有 315x180 人工点选流程；
- API 启动异常转换为普通 JSON 错误，避免 MoviePilot 前端只显示“服务器无响应”；
- 不自动识别/OCR/代点验证码，不记录账号、密码、Cookie 或点击坐标。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List

import requests

from .gying_auth_v1107 import _looks_like_content_node, _safe_json
from .gying_hardening_v193 import canonical_gying_node
from .gying_ui_v1109 import GuangYaGyingUiV1109Mixin


_CAPTCHA_HINTS_V1109 = (
    "验证码",
    "图形验证",
    "点击验证",
    "captcha",
)
_BAD_CREDENTIAL_HINTS_V1109 = (
    "用户名或密码",
    "账号或密码",
    "密码错误",
    "账号密码错误",
    "invalid password",
    "user or password",
)


def _message_v1109(payload: Dict[str, Any], fallback: str = "") -> str:
    return str(
        payload.get("msg")
        or payload.get("message")
        or payload.get("error")
        or fallback
        or ""
    ).strip()[:260]


def _contains_hint_v1109(message: str, hints: tuple[str, ...]) -> bool:
    lowered = str(message or "").lower()
    return any(str(token or "").lower() in lowered for token in hints)


class GuangYaGyingAutoLoginV1109Mixin(GuangYaGyingUiV1109Mixin):
    """最终 MRO 最外层：自动密码登录优先，人工验证码只做真实服务端回退。"""

    build_id = "20260902-r20"

    def _gying_login_password(self, session: requests.Session, node: str) -> Dict[str, Any]:
        username = str(getattr(self, "_viewing_username", "") or "").strip()
        password = str(getattr(self, "_viewing_password", "") or "")
        if not (username and password):
            return {
                "success": False,
                "mode": "credentials_missing",
                "manual_login_required": False,
                "message": "观影登录态已失效，且未配置用户名/密码",
            }

        node = canonical_gying_node(node) or str(node or "").rstrip("/")
        if not node:
            return {
                "success": False,
                "mode": "node_missing",
                "manual_login_required": False,
                "message": "观影内容节点无效",
            }

        login_url = node.rstrip("/") + "/user/login"
        timeout = min(max(int(getattr(self, "_provider_timeout", 15) or 15), 5), 15)
        self._gying_auth_log("INFO", "自动登录：节点=%s，开始建立登录会话", node)
        try:
            self._gying_request(
                session,
                node,
                "GET",
                login_url,
                timeout=timeout,
                headers={
                    "Referer": node.rstrip("/") + "/",
                    "Accept": "text/html,*/*",
                },
            )
            response = self._gying_request(
                session,
                node,
                "POST",
                login_url,
                timeout=timeout,
                data={
                    "code": "",
                    "siteid": "1",
                    "dosubmit": "1",
                    "cookietime": "10506240",
                    "username": username,
                    "password": password,
                },
                headers={
                    "Origin": node.rstrip("/"),
                    "Referer": login_url,
                    "Accept": "application/json,text/plain,*/*",
                },
            )
        except Exception as err:
            self._gying_auth_log(
                "WARNING",
                "自动登录请求失败：节点=%s 类型=%s",
                node,
                type(err).__name__,
            )
            return {
                "success": False,
                "mode": "transport_error",
                "manual_login_required": False,
                "message": f"观影自动登录请求失败：{str(err)[:180]}",
            }

        payload = _safe_json(response)
        code = payload.get("code") if isinstance(payload, dict) else None
        try:
            code_ok = int(code) == 200
        except (TypeError, ValueError):
            code_ok = str(code or "") == "200"

        if not code_ok:
            message = _message_v1109(payload, str(getattr(response, "text", "") or ""))
            if _contains_hint_v1109(message, _CAPTCHA_HINTS_V1109):
                self._gying_auth_log("INFO", "自动登录：节点=%s 明确要求人工验证码，切换人工回退", node)
                return {
                    "success": False,
                    "mode": "captcha_required",
                    "manual_login_required": True,
                    "message": "站点明确要求汉字点击验证码，将切换到人工点选",
                }
            if _contains_hint_v1109(message, _BAD_CREDENTIAL_HINTS_V1109):
                self._gying_auth_log("WARNING", "自动登录：节点=%s 账号或密码校验失败", node)
                return {
                    "success": False,
                    "mode": "bad_credentials",
                    "manual_login_required": False,
                    "message": "观影用户名或密码错误",
                }
            return {
                "success": False,
                "mode": "login_failed",
                "manual_login_required": False,
                "message": f"观影自动登录失败：{message or ('HTTP ' + str(getattr(response, 'status_code', 0)))}",
            }

        try:
            self._gying_request(
                session,
                node,
                "GET",
                node.rstrip("/") + "/mv/wkMn",
                timeout=timeout,
                headers={"Referer": node.rstrip("/") + "/"},
            )
        except Exception as err:
            self._gying_auth_log(
                "INFO",
                "自动登录暖机未完成：节点=%s 类型=%s，继续受限搜索验真",
                node,
                type(err).__name__,
            )

        if not self._gying_authenticated_probe(session, node):
            return {
                "success": False,
                "mode": "login_unverified",
                "manual_login_required": False,
                "message": "观影登录接口返回成功，但受限搜索仍显示未登录",
            }

        self._gying_persist_session(
            node,
            session,
            status="ok",
            login_mode="password",
            authenticated=True,
            verified=bool(session.cookies.get("browser_verified")),
            login_at=self._now_text(),
        )
        sync_cookie = getattr(self, "_gying_sync_cookie_v1108", None)
        if callable(sync_cookie):
            try:
                sync_cookie(session, node)
            except Exception:
                pass
        self._gying_auth_log("INFO", "自动登录成功：节点=%s，会话已保存并通过受限搜索验真", node)
        return {
            "success": True,
            "mode": "password",
            "node": node,
            "message": "观影已自动登录并通过受限搜索验真",
        }

    def _gying_auth_worker_run_v1108(self, auth_id: str, force: bool) -> None:
        errors: List[str] = []
        try:
            self._gying_auth_update_v1108(
                auth_id,
                stage="discovering",
                message="正在发现观影内容节点并尝试自动登录…",
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
                    message=f"正在连接 {node} 并自动建立登录会话…",
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
                        sync_cookie = getattr(self, "_gying_sync_cookie_v1108", None)
                        if callable(sync_cookie):
                            sync_cookie(session, node)
                        session.close()
                        self._gying_auth_update_v1108(
                            auth_id,
                            stage="authenticated",
                            node=node,
                            session=None,
                            captcha={},
                            points=[],
                            message="现有观影会话仍有效，无需重新登录",
                        )
                        return

                    self._gying_auth_update_v1108(
                        auth_id,
                        stage="login_page",
                        node=node,
                        message="正在自动提交账号密码登录…",
                    )
                    login = dict(self._gying_login_password(session, node) or {})
                    if login.get("success"):
                        session.close()
                        self._gying_auth_update_v1108(
                            auth_id,
                            stage="authenticated",
                            node=node,
                            session=None,
                            captcha={},
                            points=[],
                            message=str(login.get("message") or "观影已自动登录"),
                        )
                        return

                    mode = str(login.get("mode") or "")
                    if mode == "bad_credentials":
                        session.close()
                        self._gying_auth_update_v1108(
                            auth_id,
                            stage="login_failed",
                            node=node,
                            session=None,
                            captcha={},
                            points=[],
                            message=str(login.get("message") or "观影用户名或密码错误"),
                        )
                        return
                    if mode != "captcha_required":
                        errors.append(f"{node}: {str(login.get('message') or mode or '自动登录失败')[:120]}")
                        session.close()
                        continue

                    self._gying_auth_update_v1108(
                        auth_id,
                        stage="login_page",
                        node=node,
                        message="站点明确要求点击验证，正在获取汉字验证码…",
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
                        message="站点要求人工验证：请按提示顺序点击汉字",
                    )
                    self._gying_auth_log(
                        "INFO",
                        "自动登录回退：验证码已生成，节点=%s，需要点击=%s个",
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
                message=("；".join(errors[:5]) or "没有可用于观影自动登录的内容节点")[:500],
            )

    def api_viewing_auth_start(self, force: bool = False) -> Dict[str, Any]:
        try:
            if not isinstance(getattr(self, "_gying_auth_sessions", None), dict):
                self._gying_auth_sessions = {}
            if not hasattr(self, "_gying_auth_lock"):
                self._gying_auth_lock = threading.RLock()
            if not hasattr(self, "_gying_auth_active_id"):
                self._gying_auth_active_id = ""
            result = super().api_viewing_auth_start(force=bool(force))
            return dict(result or {})
        except Exception as err:
            self._gying_auth_log(
                "ERROR",
                "观影会话启动异常：类型=%s",
                type(err).__name__,
            )
            return {
                "success": False,
                "stage": "error",
                "message": f"观影会话启动失败：{type(err).__name__}，请查看插件日志",
            }


__all__ = ["GuangYaGyingAutoLoginV1109Mixin"]
