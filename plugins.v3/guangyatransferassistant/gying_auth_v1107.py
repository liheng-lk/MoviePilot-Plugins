"""v1.10.7 观影人工汉字验证码与会话恢复层。

依据用户提供的 2026-09-02 观影前端代码：
- POST /res/captcha/2 with webp=1 -> {type, img, text}
- 用户按 text 顺序点击画布，提交 do=check & info=x,y-...;width;height
- check 返回 code == 200 后，同一 captchainfo 直接作为 /user/login 的 code
- 所有请求继续复用同一个 requests.Session；站点 refresh=1 / 浏览器计算验证允许连续恢复最多 3 次

本层不会自动识别或点击汉字验证码。验证码图片和提示文字只回传给当前 MoviePilot
页面，点击动作由用户本人完成。Cookie、账号密码、PoW 参数和点击坐标不会写入公开状态或日志。
"""

from __future__ import annotations

import base64
import json
import re
import secrets
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests

from .gying_hardening_v193 import canonical_gying_node
from .gying_runtime_v193 import (
    GuangYaGyingRuntimeMixin,
    _is_challenge_text,
    _normalize_node_url,
)


_JSON_IMAGE_TYPE_RE = re.compile(r"^[A-Za-z0-9.+-]{1,24}$")
_CAPTCHA_WIDTH = 315
_CAPTCHA_HEIGHT = 180
_CAPTCHA_GRID = 15
_CAPTCHA_TTL_SECONDS = 180
_AUTH_COOKIE_MODES_V1107 = {
    "manual_captcha",
    "password",
    "cookie",
    "cookie_reuse",
    "configured_cookie",
}
_LANDING_MARKERS_V1107 = (
    "当前网址将在不久后失效",
    "获取新网址",
    "地址发布页",
)
_MAINTENANCE_MARKERS_V1107 = (
    "站点维护中",
    "该站点维护中",
    "站点正在维护",
)
_BLOCK_PAGE_MARKERS_V1107 = (
    "Angie",
    "request forbidden",
    "access denied",
)
_CURRENT_FRONTEND_SEEDS_V1107 = (
    "https://www.肖申克的救赎.com",
    "https://www.阿甘正传.com",
    "https://www.盗梦空间.com",
    "https://www.星际穿越.com",
)


def _safe_json(response: requests.Response) -> Dict[str, Any]:
    try:
        payload = response.json()
    except Exception:
        try:
            payload = json.loads(str(getattr(response, "text", "") or "{}"))
        except Exception:
            payload = {}
    return payload if isinstance(payload, dict) else {}


def _json_refresh_required(response: requests.Response) -> bool:
    payload = _safe_json(response)
    try:
        return int(payload.get("refresh") or 0) == 1
    except (TypeError, ValueError):
        return False


def _looks_like_content_node(response: requests.Response) -> bool:
    text = str(getattr(response, "text", "") or "")
    if any(marker in text for marker in _LANDING_MARKERS_V1107):
        return False
    if any(marker in text for marker in _MAINTENANCE_MARKERS_V1107):
        return False
    return int(getattr(response, "status_code", 0) or 0) < 400


def _captcha_info(points: List[Tuple[int, int]], width: int, height: int) -> str:
    if not points:
        return ""
    return f"{'-'.join(f'{x},{y}' for x, y in points)};{int(width)};{int(height)}"


def _extract_node_values(payload: Any) -> List[str]:
    rows: List[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for child in value.values():
                visit(child)
            return
        if isinstance(value, (list, tuple, set)):
            for child in value:
                visit(child)
            return
        text = str(value or "").strip()
        if not text:
            return
        if text.startswith(("http://", "https://")):
            rows.append(text)
            return
        if "." in text and " " not in text and len(text) <= 255:
            rows.append("https://" + text)

    visit(payload)
    return rows


class GuangYaGyingAuthV1107Mixin:
    """人工点击验证码、PoW 连续恢复、会话验证与 MoviePilot 交互 UI。"""

    build_id = "20260902-r18"

    def init_plugin(self, config: dict = None) -> None:
        super().init_plugin(dict(config or {}))
        self._gying_auth_sessions: Dict[str, Dict[str, Any]] = {}
        self._gying_auth_active_id = ""
        self._gying_auth_lock = threading.RLock()

    # ------------------------------------------------------------------
    # 日志 / 临时会话
    # ------------------------------------------------------------------
    def _gying_auth_log(self, level: str, message: str, *args: Any) -> None:
        writer = getattr(self, "_gying_obs_log", None)
        if callable(writer):
            try:
                writer(level, message, *args)
                return
            except Exception:
                pass
        fallback = getattr(self, "_plugin_log", None)
        if callable(fallback):
            fallback(level, "【光鸭转存助手】【观影】" + message, *args)

    def _gying_auth_cleanup(self) -> None:
        store = getattr(self, "_gying_auth_sessions", None)
        if not isinstance(store, dict):
            self._gying_auth_sessions = {}
            return
        now = time.time()
        expired = []
        for auth_id, row in list(store.items()):
            updated = float((row or {}).get("updated_ts") or (row or {}).get("created_ts") or 0)
            if not updated or now - updated > _CAPTCHA_TTL_SECONDS:
                expired.append(auth_id)
        for auth_id in expired:
            row = store.pop(auth_id, None) or {}
            session = row.get("session")
            try:
                if session:
                    session.close()
            except Exception:
                pass
            if str(getattr(self, "_gying_auth_active_id", "") or "") == auth_id:
                self._gying_auth_active_id = ""
        if len(store) > 4:
            ordered = sorted(
                store.items(),
                key=lambda pair: float((pair[1] or {}).get("updated_ts") or 0),
                reverse=True,
            )
            for auth_id, row in ordered[4:]:
                store.pop(auth_id, None)
                try:
                    session = (row or {}).get("session")
                    if session:
                        session.close()
                except Exception:
                    pass

    def _gying_auth_get(self, auth_id: str) -> Optional[Dict[str, Any]]:
        with getattr(self, "_gying_auth_lock", threading.RLock()):
            self._gying_auth_cleanup()
            row = (getattr(self, "_gying_auth_sessions", {}) or {}).get(str(auth_id or ""))
            if isinstance(row, dict):
                row["updated_ts"] = time.time()
                return row
        return None

    def _gying_auth_public(self, row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(row, dict):
            return {"stage": "idle", "active": False}
        captcha = dict(row.get("captcha") or {})
        stage = str(row.get("stage") or "idle")
        data: Dict[str, Any] = {
            "active": True,
            "auth_id": str(row.get("auth_id") or ""),
            "stage": stage,
            "node": str(row.get("node") or ""),
            "message": str(row.get("message") or "")[:300],
            "clicked": len(list(row.get("points") or [])),
            "required": len(str(captcha.get("text") or "")),
            "expires_in": max(
                0,
                int(
                    _CAPTCHA_TTL_SECONDS
                    - (time.time() - float(row.get("updated_ts") or row.get("created_ts") or time.time()))
                ),
            ),
        }
        if stage == "captcha" and captcha:
            image_type = str(captcha.get("type") or "webp")
            image = str(captcha.get("img") or "")
            data["captcha"] = {
                "type": image_type,
                "image": f"data:image/{image_type};base64,{image}" if image else "",
                "text": str(captcha.get("text") or ""),
                "width": int(captcha.get("width") or _CAPTCHA_WIDTH),
                "height": int(captcha.get("height") or _CAPTCHA_HEIGHT),
            }
        return data

    # ------------------------------------------------------------------
    # 节点发现：保留旧节点池，再读取 /urlop/，并吸收当前站点前端公布的内容域名
    # ------------------------------------------------------------------
    def _discover_gying_nodes(self, force: bool = False) -> List[str]:
        rows = list(super()._discover_gying_nodes(force=force) or [])
        registry_rows = []
        for raw in str(getattr(self, "_viewing_registry_urls", "") or "").splitlines():
            node = canonical_gying_node(raw)
            if node:
                registry_rows.append(node)
        session = self._gying_new_session("")
        timeout = min(int(getattr(self, "_provider_timeout", 15) or 15), 20)
        for registry in registry_rows[:6]:
            try:
                response = session.get(
                    registry.rstrip("/") + "/urlop/",
                    timeout=timeout,
                    allow_redirects=True,
                    headers={"Accept": "application/json,text/plain,*/*"},
                )
                payload = _safe_json(response)
                for value in _extract_node_values(payload):
                    node = canonical_gying_node(value)
                    if node and node not in rows:
                        rows.append(node)
            except Exception:
                continue
        try:
            session.close()
        except Exception:
            pass
        for value in _CURRENT_FRONTEND_SEEDS_V1107:
            node = canonical_gying_node(value)
            if node and node not in rows:
                rows.append(node)
        state = self._gying_state()
        state["discovered_nodes"] = rows[:40]
        state["discovered_at"] = time.time()
        self._save_gying_state(state)
        return rows[:40]

    # ------------------------------------------------------------------
    # PoW：一次原请求最多连续恢复 3 次，只有原请求恢复正常才记录“确认通过”
    # ------------------------------------------------------------------
    def _gying_solve_challenge(
        self,
        session: requests.Session,
        node: str,
        response: requests.Response,
    ) -> Dict[str, Any]:
        label = str(node or "")
        self._gying_auth_log("INFO", "检测到浏览器 PoW：节点=%s，开始计算提交", label)
        started = time.monotonic()
        result = GuangYaGyingRuntimeMixin._gying_solve_challenge(self, session, node, response)
        self._gying_auth_log(
            "INFO",
            "PoW计算提交完成：节点=%s 模式=%s 耗时=%.2fs，等待原请求确认",
            label,
            str((result or {}).get("mode") or "unknown"),
            time.monotonic() - started,
        )
        return dict(result or {})

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
        max_pow = 3 if retry_challenge else 0
        solved = 0
        for attempt in range(max_pow + 1):
            response = session.request(
                str(method or "GET").upper(),
                url,
                timeout=timeout,
                allow_redirects=True,
                **kwargs,
            )
            text = str(response.text or "")
            lowered = text.lower()
            if response.status_code in {403, 404} and any(
                marker.lower() in lowered for marker in _BLOCK_PAGE_MARKERS_V1107
            ):
                raise RuntimeError(f"观影节点当前出口被阻断：HTTP {response.status_code}")
            challenge = _is_challenge_text(text) or _json_refresh_required(response)
            if not challenge:
                if solved:
                    self._gying_auth_log(
                        "INFO",
                        "浏览器计算验证确认通过：节点=%s 连续挑战=%s",
                        str(node or ""),
                        solved,
                    )
                return response
            if attempt >= max_pow:
                break
            solved += 1
            self._gying_solve_challenge(session, node, response)
        raise RuntimeError(
            f"观影浏览器验证连续 {solved or 1} 次计算后原请求仍要求验证；"
            "请稍后重试或检查当前出口/节点"
        )

    # ------------------------------------------------------------------
    # 登录状态：当前站点已确认点击验证码，账号密码模式不再先 POST code=''
    # ------------------------------------------------------------------
    def _gying_authenticated_probe(self, session: requests.Session, node: str) -> bool:
        node = str(node or "").rstrip("/")
        if not node:
            return False
        url = f"{node}/search?q={quote('肖申克的救赎')}&type=&mode=1"
        try:
            response = self._gying_request(
                session,
                node,
                "GET",
                url,
                headers={"Referer": node + "/", "Accept": "text/html,*/*"},
            )
        except Exception:
            return False
        text = str(response.text or "")
        if self._gying_login_required(response):
            return False
        if "未登录，访问受限" in text or "_BT.PC.HTML('nologin')" in text or '_BT.PC.HTML("nologin")' in text:
            return False
        return int(response.status_code or 0) < 400

    def _gying_login_password(self, session: requests.Session, node: str) -> Dict[str, Any]:
        username = str(getattr(self, "_viewing_username", "") or "").strip()
        password = str(getattr(self, "_viewing_password", "") or "")
        if not (username and password):
            return {
                "success": False,
                "mode": "credentials_missing",
                "manual_login_required": True,
                "message": "观影登录态已失效，且未配置用户名/密码",
            }
        return {
            "success": False,
            "mode": "captcha_required",
            "manual_login_required": True,
            "message": "观影账号需要汉字点击验证码；请在插件页“观影人工认证”中按提示点击",
        }

    def _gying_login(self, session: requests.Session, node: str) -> Dict[str, Any]:
        try:
            row = dict(((self._gying_state().get("nodes") or {}).get(node) or {}))
        except Exception:
            row = {}
        login_mode = str(row.get("login_mode") or "")
        if (
            len(session.cookies)
            and bool(row.get("authenticated"))
            and login_mode in _AUTH_COOKIE_MODES_V1107
        ):
            if self._gying_authenticated_probe(session, node):
                return {
                    "success": True,
                    "mode": "cookie_reuse" if login_mode == "manual_captcha" else login_mode,
                    "message": "复用已验证的观影登录会话",
                }
            row["authenticated"] = False
            row["status"] = "login_expired"
            state = self._gying_state()
            state.setdefault("nodes", {})[node] = row
            self._save_gying_state(state)

        result = dict(super()._gying_login(session, node) or {})
        if not result.get("success") and str(result.get("mode") or "") == "captcha_required":
            result["manual_login_required"] = True
            result["message"] = "观影账号需要汉字点击验证码；请在插件页“观影人工认证”中按提示点击"
        return result

    # ------------------------------------------------------------------
    # 验证码 / 人工登录
    # ------------------------------------------------------------------
    def _gying_request_captcha(self, session: requests.Session, node: str) -> Dict[str, Any]:
        url = str(node or "").rstrip("/") + "/res/captcha/2"
        response = self._gying_request(
            session,
            node,
            "POST",
            url,
            data={"webp": "1"},
            headers={
                "Origin": str(node or "").rstrip("/"),
                "Referer": str(node or "").rstrip("/") + "/user/login",
                "Accept": "*/*",
            },
        )
        payload = _safe_json(response)
        image_type = str(payload.get("type") or "").strip().lower()
        image = str(payload.get("img") or "").strip()
        text = str(payload.get("text") or "").strip()
        if not image_type or not _JSON_IMAGE_TYPE_RE.fullmatch(image_type):
            raise RuntimeError("观影验证码返回的图片类型无效")
        if not image or len(image) > 2_000_000:
            raise RuntimeError("观影验证码图片为空或过大")
        try:
            base64.b64decode(image, validate=True)
        except Exception as err:
            raise RuntimeError("观影验证码图片不是有效 Base64") from err
        if not text or len(text) > 8:
            raise RuntimeError("观影验证码点击文字为空或异常")
        return {
            "type": image_type,
            "img": image,
            "text": text,
            "width": _CAPTCHA_WIDTH,
            "height": _CAPTCHA_HEIGHT,
        }

    def _gying_verify_captcha(self, row: Dict[str, Any]) -> Dict[str, Any]:
        session = row.get("session")
        node = str(row.get("node") or "")
        captcha = dict(row.get("captcha") or {})
        points = list(row.get("points") or [])
        width = int(captcha.get("width") or _CAPTCHA_WIDTH)
        height = int(captcha.get("height") or _CAPTCHA_HEIGHT)
        info = _captcha_info(points, width, height)
        if not isinstance(session, requests.Session) or not node or not info:
            raise RuntimeError("观影人工验证码会话已失效")
        response = self._gying_request(
            session,
            node,
            "POST",
            node.rstrip("/") + "/res/captcha/2",
            data={"do": "check", "info": info},
            headers={
                "Origin": node.rstrip("/"),
                "Referer": node.rstrip("/") + "/user/login",
                "Accept": "*/*",
            },
        )
        payload = _safe_json(response)
        return {"success": payload.get("code") in (200, "200"), "info": info}

    def _gying_finish_manual_login(self, row: Dict[str, Any], info: str) -> Dict[str, Any]:
        session = row.get("session")
        node = str(row.get("node") or "")
        username = str(getattr(self, "_viewing_username", "") or "").strip()
        password = str(getattr(self, "_viewing_password", "") or "")
        if not isinstance(session, requests.Session) or not node:
            return {"success": False, "mode": "expired", "message": "观影人工登录会话已失效"}
        if not (username and password):
            return {
                "success": False,
                "mode": "credentials_missing",
                "message": "未配置观影用户名/密码，无法完成登录",
            }
        login_url = node.rstrip("/") + "/user/login"
        response = self._gying_request(
            session,
            node,
            "POST",
            login_url,
            data={
                "code": str(info or ""),
                "siteid": "1",
                "dosubmit": "1",
                "cookietime": "10506240",
                "username": username,
                "password": password,
            },
            headers={
                "Origin": node.rstrip("/"),
                "Referer": login_url,
                "Accept": "*/*",
            },
        )
        payload = _safe_json(response)
        if payload.get("code") not in (200, "200"):
            message = str(payload.get("msg") or payload.get("message") or "站点未返回登录成功")[:260]
            return {"success": False, "mode": "login_failed", "message": f"观影登录失败：{message}"}
        if not self._gying_authenticated_probe(session, node):
            return {
                "success": False,
                "mode": "login_unverified",
                "message": "观影登录接口返回成功，但受限搜索仍显示未登录",
            }
        self._gying_persist_session(
            node,
            session,
            status="ok",
            login_mode="manual_captcha",
            authenticated=True,
            verified=bool(
                session.cookies.get("browser_verified")
                or session.cookies.get("browser_pow")
            ),
            login_at=self._now_text(),
        )
        self._gying_auth_log("INFO", "人工登录完成：节点=%s，会话已验证并保存", node)
        return {
            "success": True,
            "mode": "manual_captcha",
            "node": node,
            "message": "观影登录成功，会话已保存；站点公告/最新网址弹窗不阻塞资源检索",
        }

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
            old_id = str(getattr(self, "_gying_auth_active_id", "") or "")
            old = (getattr(self, "_gying_auth_sessions", {}) or {}).pop(old_id, None) if old_id else None
            if old:
                try:
                    old_session = old.get("session")
                    if old_session:
                        old_session.close()
                except Exception:
                    pass
            self._gying_auth_active_id = ""

        state = self._gying_state()
        node_order = []
        chooser = getattr(self, "_gying_node_order", None)
        if callable(chooser):
            try:
                node_order = list(chooser() or [])
            except Exception:
                node_order = []
        if not node_order:
            node_order = list(self._discover_gying_nodes(force=False) or [])
        errors: List[str] = []
        for raw_node in node_order[:12]:
            node = canonical_gying_node(raw_node) or _normalize_node_url(raw_node)
            if not node:
                continue
            saved = "" if force else str(((state.get("nodes") or {}).get(node) or {}).get("cookie") or "")
            session = self._gying_new_session(node, saved_cookie=saved)
            try:
                home = self._gying_request(
                    session,
                    node,
                    "GET",
                    node.rstrip("/") + "/",
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
                        login_mode="manual_captcha",
                        authenticated=True,
                        verified=bool(
                            session.cookies.get("browser_verified")
                            or session.cookies.get("browser_pow")
                        ),
                    )
                    try:
                        session.close()
                    except Exception:
                        pass
                    return {
                        "success": True,
                        "stage": "authenticated",
                        "node": node,
                        "message": "现有观影会话仍有效，无需再次验证码",
                    }

                self._gying_request(
                    session,
                    node,
                    "GET",
                    node.rstrip("/") + "/user/login",
                    headers={"Referer": node.rstrip("/") + "/"},
                )
                captcha = self._gying_request_captcha(session, node)
                auth_id = secrets.token_urlsafe(18)
                row = {
                    "auth_id": auth_id,
                    "session": session,
                    "node": node,
                    "stage": "captcha",
                    "captcha": captcha,
                    "points": [],
                    "created_ts": time.time(),
                    "updated_ts": time.time(),
                    "message": "请按提示顺序点击汉字；点满后自动校验并登录",
                }
                with getattr(self, "_gying_auth_lock", threading.RLock()):
                    self._gying_auth_sessions[auth_id] = row
                    self._gying_auth_active_id = auth_id
                self._gying_auth_log(
                    "INFO",
                    "人工登录：验证码已生成，节点=%s，需要点击=%s个",
                    node,
                    len(str(captcha.get("text") or "")),
                )
                return {"success": True, **self._gying_auth_public(row)}
            except Exception as err:
                errors.append(f"{node}: {str(err)[:120]}")
                try:
                    session.close()
                except Exception:
                    pass
                continue
        return {
            "success": False,
            "stage": "unavailable",
            "message": ("；".join(errors[:5]) or "没有可用于人工登录的观影内容节点")[:500],
        }

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------
    def api_viewing_auth_start(self, force: bool = False) -> Dict[str, Any]:
        return self._gying_auth_start(bool(force))

    def api_viewing_auth_status(self, auth_id: str = "") -> Dict[str, Any]:
        target = str(auth_id or getattr(self, "_gying_auth_active_id", "") or "")
        row = self._gying_auth_get(target) if target else None
        if row:
            return {"success": True, **self._gying_auth_public(row)}
        state = self._gying_state()
        active = str(state.get("active_node") or "")
        saved = dict(((state.get("nodes") or {}).get(active) or {})) if active else {}
        authenticated = bool(saved.get("authenticated")) and str(saved.get("login_mode") or "") in _AUTH_COOKIE_MODES_V1107
        return {
            "success": True,
            "active": False,
            "stage": "authenticated" if authenticated else "idle",
            "node": active,
            "message": "观影会话已认证" if authenticated else "等待人工认证",
        }

    def api_viewing_auth_click(
        self,
        auth_id: str = "",
        x: int = -1,
        y: int = -1,
    ) -> Dict[str, Any]:
        row = self._gying_auth_get(auth_id)
        if not row or str(row.get("stage") or "") != "captcha":
            return {"success": False, "stage": "expired", "message": "验证码会话已过期，请重新开始认证"}
        captcha = dict(row.get("captcha") or {})
        width = int(captcha.get("width") or _CAPTCHA_WIDTH)
        height = int(captcha.get("height") or _CAPTCHA_HEIGHT)
        try:
            px, py = int(x), int(y)
        except (TypeError, ValueError):
            return {"success": False, "stage": "captcha", "message": "点击坐标无效"}
        if px < 0 or py < 0 or px >= width or py >= height:
            return {"success": False, "stage": "captcha", "message": "点击位置超出验证码范围"}
        required = len(str(captcha.get("text") or ""))
        points = list(row.get("points") or [])
        if len(points) >= required:
            points = []
        points.append((px, py))
        row["points"] = points
        row["updated_ts"] = time.time()
        if len(points) < required:
            return {
                "success": True,
                "stage": "captcha",
                "message": f"已记录第 {len(points)}/{required} 个点击",
                "clicked": len(points),
                "required": required,
            }

        self._gying_auth_log("INFO", "人工登录：收到完整点击序列，开始校验")
        try:
            checked = self._gying_verify_captcha(row)
        except Exception as err:
            row["points"] = []
            row["message"] = f"验证码校验请求失败：{str(err)[:180]}"
            return {"success": False, **self._gying_auth_public(row)}
        if not checked.get("success"):
            try:
                row["captcha"] = self._gying_request_captcha(row["session"], str(row.get("node") or ""))
                row["points"] = []
                row["message"] = "未点中正确区域，已刷新验证码，请重新点击"
                row["updated_ts"] = time.time()
            except Exception as err:
                row["points"] = []
                row["message"] = f"验证码错误，刷新失败：{str(err)[:180]}"
            self._gying_auth_log("WARNING", "人工登录：验证码点击错误，已请求刷新")
            return {"success": False, **self._gying_auth_public(row)}

        result = self._gying_finish_manual_login(row, str(checked.get("info") or ""))
        if result.get("success"):
            row["stage"] = "authenticated"
            row["points"] = []
            row["captcha"] = {}
            row["message"] = str(result.get("message") or "")
            row["updated_ts"] = time.time()
            return {"success": True, **self._gying_auth_public(row), **result}
        row["stage"] = "login_failed"
        row["points"] = []
        row["message"] = str(result.get("message") or "观影登录失败")
        row["updated_ts"] = time.time()
        return {"success": False, **self._gying_auth_public(row), **result}

    def api_viewing_auth_undo(self, auth_id: str = "") -> Dict[str, Any]:
        row = self._gying_auth_get(auth_id)
        if not row or str(row.get("stage") or "") != "captcha":
            return {"success": False, "message": "没有可撤销的验证码会话"}
        points = list(row.get("points") or [])
        if points:
            points.pop()
        row["points"] = points
        row["updated_ts"] = time.time()
        return {
            "success": True,
            "stage": "captcha",
            "message": f"已撤销，当前 {len(points)}/{len(str((row.get('captcha') or {}).get('text') or ''))}",
            "clicked": len(points),
        }

    def api_viewing_auth_refresh(self, auth_id: str = "") -> Dict[str, Any]:
        row = self._gying_auth_get(auth_id)
        if not row or str(row.get("stage") or "") != "captcha":
            return {"success": False, "message": "验证码会话已过期，请重新开始认证"}
        try:
            row["captcha"] = self._gying_request_captcha(row["session"], str(row.get("node") or ""))
            row["points"] = []
            row["updated_ts"] = time.time()
            row["message"] = "验证码已刷新"
            return {"success": True, **self._gying_auth_public(row)}
        except Exception as err:
            return {"success": False, "message": f"刷新验证码失败：{str(err)[:240]}"}

    def api_viewing_auth_cancel(self, auth_id: str = "") -> Dict[str, Any]:
        target = str(auth_id or getattr(self, "_gying_auth_active_id", "") or "")
        row = None
        with getattr(self, "_gying_auth_lock", threading.RLock()):
            row = (getattr(self, "_gying_auth_sessions", {}) or {}).pop(target, None)
            if str(getattr(self, "_gying_auth_active_id", "") or "") == target:
                self._gying_auth_active_id = ""
        try:
            if row and row.get("session"):
                row["session"].close()
        except Exception:
            pass
        return {"success": True, "stage": "idle", "message": "已取消观影人工认证"}

    def get_api(self) -> List[Dict[str, Any]]:
        apis = list(super().get_api() or [])
        paths = {str(item.get("path") or "") for item in apis if isinstance(item, dict)}
        extras = [
            {"path": "/viewing/auth/start", "endpoint": self.api_viewing_auth_start, "methods": ["POST"], "summary": "开始观影人工汉字验证码登录"},
            {"path": "/viewing/auth/status", "endpoint": self.api_viewing_auth_status, "methods": ["GET"], "summary": "查看观影人工认证状态"},
            {"path": "/viewing/auth/click", "endpoint": self.api_viewing_auth_click, "methods": ["POST"], "summary": "提交一次人工验证码点击"},
            {"path": "/viewing/auth/undo", "endpoint": self.api_viewing_auth_undo, "methods": ["POST"], "summary": "撤销上一次人工验证码点击"},
            {"path": "/viewing/auth/refresh", "endpoint": self.api_viewing_auth_refresh, "methods": ["POST"], "summary": "刷新观影汉字验证码"},
            {"path": "/viewing/auth/cancel", "endpoint": self.api_viewing_auth_cancel, "methods": ["POST"], "summary": "取消观影人工认证"},
        ]
        apis.extend(item for item in extras if item["path"] not in paths)
        return apis

    # ------------------------------------------------------------------
    # MoviePilot 控制台：用 15px 透明网格覆盖 315x180 验证码。
    # 用户点击的是图片位置；每个格子的中心坐标作为固定 API 参数回传。
    # ------------------------------------------------------------------
    @staticmethod
    def _gying_auth_api_button(
        text: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        icon: str = "",
        color: str = "primary",
        variant: str = "tonal",
    ) -> Dict[str, Any]:
        props: Dict[str, Any] = {
            "size": "small",
            "variant": variant,
            "color": color,
            "class": "mr-2 mb-2",
            "style": "border-radius:11px;min-height:36px;font-weight:650;",
        }
        if icon:
            props["prepend-icon"] = icon
        event: Dict[str, Any] = {
            "api": f"plugin/GuangYaTransferAssistant{path}",
            "method": "post",
        }
        if params:
            event["params"] = dict(params)
        return {
            "component": "VBtn",
            "props": props,
            "text": text,
            "events": {"click": event},
        }

    def _gying_auth_grid(self, auth_id: str, image: str, width: int, height: int) -> Dict[str, Any]:
        cells: List[Dict[str, Any]] = [
            {
                "component": "VImg",
                "props": {
                    "src": image,
                    "width": width,
                    "height": height,
                    "cover": True,
                    "style": f"position:absolute;left:0;top:0;width:{width}px;height:{height}px;",
                },
            }
        ]
        for top in range(0, height, _CAPTCHA_GRID):
            for left in range(0, width, _CAPTCHA_GRID):
                cell_w = min(_CAPTCHA_GRID, width - left)
                cell_h = min(_CAPTCHA_GRID, height - top)
                x = min(width - 1, left + cell_w // 2)
                y = min(height - 1, top + cell_h // 2)
                cells.append({
                    "component": "VBtn",
                    "props": {
                        "variant": "text",
                        "ripple": False,
                        "aria-label": f"验证码位置 {x},{y}",
                        "style": (
                            f"position:absolute;left:{left}px;top:{top}px;"
                            f"width:{cell_w}px;height:{cell_h}px;min-width:0;padding:0;"
                            "border-radius:0;background:transparent;box-shadow:none;"
                            "border:1px solid rgba(var(--v-border-color),.025);"
                        ),
                    },
                    "events": {
                        "click": {
                            "api": "plugin/GuangYaTransferAssistant/viewing/auth/click",
                            "method": "post",
                            "params": {"auth_id": auth_id, "x": x, "y": y},
                        }
                    },
                })
        return {
            "component": "VSheet",
            "props": {
                "style": (
                    f"position:relative;width:{width}px;height:{height}px;max-width:100%;"
                    "overflow:hidden;border-radius:14px;border:1px solid "
                    "rgba(var(--v-border-color),.14);margin:0 auto;"
                ),
            },
            "content": cells,
        }

    def _gying_auth_panel(self) -> Dict[str, Any]:
        status = self.api_viewing_auth_status()
        stage = str(status.get("stage") or "idle")
        node = str(status.get("node") or "未选择")
        content: List[Dict[str, Any]] = [
            {
                "component": "div",
                "props": {"class": "d-flex flex-wrap align-center mb-3"},
                "content": [
                    {
                        "component": "VChip",
                        "props": {
                            "size": "small",
                            "variant": "tonal",
                            "color": "success" if stage == "authenticated" else ("warning" if stage == "captcha" else "info"),
                            "class": "mr-2 mb-2",
                        },
                        "text": "已认证" if stage == "authenticated" else ("等待点击" if stage == "captcha" else "需要认证"),
                    },
                    {
                        "component": "VChip",
                        "props": {"size": "small", "variant": "outlined", "class": "mr-2 mb-2"},
                        "text": f"节点 {node}",
                    },
                ],
            }
        ]
        if stage == "captcha":
            captcha = dict(status.get("captcha") or {})
            auth_id = str(status.get("auth_id") or "")
            text = str(captcha.get("text") or "")
            width = int(captcha.get("width") or _CAPTCHA_WIDTH)
            height = int(captcha.get("height") or _CAPTCHA_HEIGHT)
            content.extend([
                {
                    "component": "VAlert",
                    "props": {
                        "type": "info",
                        "variant": "tonal",
                        "density": "compact",
                        "class": "mb-3",
                        "style": "border-radius:12px;",
                        "text": "请依次点击：" + "、".join(f"“{char}”" for char in text),
                    },
                },
                self._gying_auth_grid(auth_id, str(captcha.get("image") or ""), width, height),
                {
                    "component": "div",
                    "props": {
                        "class": "mt-3 mb-2",
                        "style": "font-size:12px;line-height:1.6;opacity:.72;",
                    },
                    "text": (
                        f"已记录 {int(status.get('clicked') or 0)}/{int(status.get('required') or 0)}。"
                        "每次点击会回传对应位置；点满后自动校验并登录。点击错误时会刷新验证码。"
                    ),
                },
                {
                    "component": "div",
                    "props": {"class": "d-flex flex-wrap"},
                    "content": [
                        self._gying_auth_api_button(
                            "撤销一次",
                            "/viewing/auth/undo",
                            params={"auth_id": auth_id},
                            icon="mdi-undo",
                            variant="outlined",
                        ),
                        self._gying_auth_api_button(
                            "刷新验证码",
                            "/viewing/auth/refresh",
                            params={"auth_id": auth_id},
                            icon="mdi-refresh",
                            color="info",
                            variant="outlined",
                        ),
                        self._gying_auth_api_button(
                            "取消认证",
                            "/viewing/auth/cancel",
                            params={"auth_id": auth_id},
                            icon="mdi-close",
                            color="secondary",
                            variant="text",
                        ),
                    ],
                },
            ])
        elif stage == "authenticated":
            content.extend([
                {
                    "component": "VAlert",
                    "props": {
                        "type": "success",
                        "variant": "tonal",
                        "density": "compact",
                        "style": "border-radius:12px;",
                        "text": str(status.get("message") or "观影会话已认证，可直接参与资源检索。"),
                    },
                },
                {
                    "component": "div",
                    "props": {"class": "d-flex flex-wrap mt-3"},
                    "content": [
                        self._gying_auth_api_button(
                            "重新认证",
                            "/viewing/auth/start",
                            params={"force": True},
                            icon="mdi-account-key-outline",
                            color="warning",
                            variant="outlined",
                        ),
                    ],
                },
            ])
        else:
            content.extend([
                {
                    "component": "VAlert",
                    "props": {
                        "type": "info",
                        "variant": "tonal",
                        "density": "compact",
                        "style": "border-radius:12px;",
                        "text": (
                            "当前观影站点登录会触发汉字点击验证码。插件不会自动识别验证码；"
                            "点击“开始人工认证”后，在这里按提示亲自点击即可。"
                        ),
                    },
                },
                {
                    "component": "div",
                    "props": {"class": "d-flex flex-wrap mt-3"},
                    "content": [
                        self._gying_auth_api_button(
                            "开始人工认证",
                            "/viewing/auth/start",
                            icon="mdi-account-key-outline",
                            color="primary",
                        ),
                    ],
                },
            ])
        return {
            "component": "VCard",
            "props": {
                "variant": "flat",
                "class": "mb-4",
                "style": (
                    "border:1px solid rgba(var(--v-theme-primary),.16);border-radius:18px;"
                    "box-shadow:0 10px 30px rgba(15,23,42,.06);overflow:hidden;"
                ),
            },
            "content": [{
                "component": "VCardText",
                "content": [
                    {
                        "component": "div",
                        "props": {"class": "d-flex align-center mb-3"},
                        "content": [
                            {
                                "component": "VAvatar",
                                "props": {
                                    "size": 36,
                                    "color": "primary",
                                    "variant": "tonal",
                                    "style": "border-radius:12px;",
                                },
                                "content": [{"component": "VIcon", "props": {"icon": "mdi-account-key-outline", "size": 20}}],
                            },
                            {
                                "component": "div",
                                "props": {"class": "ml-3"},
                                "content": [
                                    {
                                        "component": "div",
                                        "props": {"style": "font-size:17px;font-weight:700;"},
                                        "text": "观影人工认证",
                                    },
                                    {
                                        "component": "div",
                                        "props": {"style": "font-size:12px;opacity:.62;line-height:1.5;"},
                                        "text": "PoW 自动恢复；汉字点击由你本人完成；成功后复用同一 Session 并持久化登录态。",
                                    },
                                ],
                            },
                        ],
                    },
                    *content,
                ],
            }],
        }

    def get_page(self):
        pages = list(super().get_page() or [])
        try:
            panel = self._gying_auth_panel()
            insert_at = 3 if len(pages) >= 3 else len(pages)
            pages.insert(insert_at, panel)
        except Exception as err:
            self._gying_auth_log("WARNING", "人工认证面板构建失败：%s", err)
        return pages


__all__ = ["GuangYaGyingAuthV1107Mixin", "_captcha_info"]
