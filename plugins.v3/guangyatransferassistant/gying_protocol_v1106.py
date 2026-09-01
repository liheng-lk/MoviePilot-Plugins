"""v1.10.6 观影 GYING 真实协议适配层。

依据 2026-09-01 浏览器 HAR 收口真实调用链：
- 搜索优先使用 /search?q=...&type=&mode=1，并保留旧 mode=2 兼容回退；
- /res/downurl/{type}/{id} 同时解析 downlist、panlist 与嵌入 Magnet/ED2K；
- downlist.list.k == 0 时使用 list.m 的 BTIH 直接构造 Magnet，不需要真的打开 /bt/{u} 新窗口；
- panlist 保留真实网盘 URL、名称、类型与提取码，迅雷候选可直接拿到 panlist.p；
- downurl JSON 的 login 标志也视为登录失效，不再只看 HTTP 403/登录 HTML；
- 已有明确登录态 Cookie 时优先复用，避免每轮都重新 POST 密码触发图形验证码；
- 密码登录遇站点图形验证码时返回明确状态，不伪装成普通节点故障；
- 对前端 refresh=1 的动态浏览器验证做显式处理，能复用现有 PoW 时自动重试，否则给出可诊断错误。

本层只解析用户正常登录后网页本身返回的资源数据，不绕过账号权限、验证码或访问控制。
"""

from __future__ import annotations

import html
import json
import re
import time
from typing import Any, Dict, Iterable, List, Tuple
from urllib.parse import parse_qs, quote, urlparse

import requests

from .gying_runtime_v193 import _parse_search_payload
from .provider_sources_v192 import _dedupe_candidates, _find_links


_BTIH_RE = re.compile(r"^(?:[0-9A-Fa-f]{40}|[A-Z2-7a-z2-7]{32})$")
_XUNLEI_RE = re.compile(r"https?://pan\.xunlei\.com/s/[^\s\"'<>，。；;]+", re.I)
_CAPTCHA_HINTS = (
    "验证码",
    "图形验证",
    "安全验证",
    "点击验证",
    "captcha",
)
_BAD_CREDENTIAL_HINTS = (
    "用户名或密码",
    "账号或密码",
    "密码错误",
    "账号密码错误",
    "invalid password",
    "user or password",
)
_AUTH_COOKIE_MODES = {"password", "cookie", "cookie_reuse", "configured_cookie"}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return []


def _recursive_dict(payload: Any, key: str) -> Dict[str, Any]:
    if isinstance(payload, dict):
        value = payload.get(key)
        if isinstance(value, dict):
            return dict(value)
        for child in payload.values():
            found = _recursive_dict(child, key)
            if found:
                return found
    elif isinstance(payload, (list, tuple)):
        for child in payload:
            found = _recursive_dict(child, key)
            if found:
                return found
    return {}


def extract_panlist_v1106(payload: Any) -> Dict[str, List[Any]]:
    """读取 HAR 中网页实际使用的 panlist，并保留提取码字段 p。"""
    pan = _recursive_dict(payload, "panlist")
    if not pan:
        return {"url": [], "name": [], "type": [], "p": [], "id": []}
    return {
        "url": _as_list(pan.get("url")),
        "name": _as_list(pan.get("name")),
        "type": _as_list(pan.get("type")),
        "p": _as_list(pan.get("p")),
        "id": _as_list(pan.get("id")),
    }


def extract_downlist_v1106(payload: Any) -> Dict[str, List[Any]]:
    """读取网页 _Downlist 组件实际消费的并行数组。"""
    down = _recursive_dict(payload, "downlist")
    listing = down.get("list") if isinstance(down, dict) else None
    if not isinstance(listing, dict):
        return {"t": [], "m": [], "k": [], "u": [], "s": [], "e": [], "p": [], "n": []}
    return {
        key: _as_list(listing.get(key))
        for key in ("t", "m", "k", "u", "s", "e", "p", "n")
    }


def _parallel_value(rows: Dict[str, List[Any]], key: str, index: int, default: Any = "") -> Any:
    values = rows.get(key) or []
    return values[index] if index < len(values) else default


def _build_magnet(btih: Any, title: str) -> str:
    raw = str(btih or "").strip()
    if not _BTIH_RE.fullmatch(raw):
        return ""
    return f"magnet:?xt=urn:btih:{raw}&dn={quote(str(title or '').strip(), safe='')}"


def extract_resource_rows_v1106(payload: Any, item: Dict[str, Any]) -> List[Dict[str, Any]]:
    """把一次 downurl 响应统一为可缓存的原始资源行。"""
    title = str(item.get("title") or "").strip()
    common = {
        "search_title": title,
        "year": item.get("year"),
        "resource_type": str(item.get("type") or "").strip(),
        "resource_id": str(item.get("id") or "").strip(),
    }
    output: List[Dict[str, Any]] = []

    pan = extract_panlist_v1106(payload)
    for index, value in enumerate(pan.get("url") or []):
        url = html.unescape(str(value or "").strip())
        if not url:
            continue
        output.append({
            **common,
            "url": url,
            "name": str(_parallel_value(pan, "name", index, title) or title).strip(),
            "pan_type": _parallel_value(pan, "type", index, None),
            "passcode": str(_parallel_value(pan, "p", index, "") or "").strip(),
            "pan_id": str(_parallel_value(pan, "id", index, "") or "").strip(),
            "resource_kind": "pan",
        })

    down = extract_downlist_v1106(payload)
    size = max((len(value) for value in down.values()), default=0)
    for index in range(size):
        kind = _safe_int(_parallel_value(down, "k", index, -1), -1)
        if kind != 0:
            continue
        row_title = str(_parallel_value(down, "t", index, title) or title).strip()
        uri = _build_magnet(_parallel_value(down, "m", index, ""), row_title)
        if not uri:
            continue
        output.append({
            **common,
            "url": uri,
            "name": row_title,
            "resource_kind": "magnet",
            "bt_detail_id": str(_parallel_value(down, "u", index, "") or "").strip(),
            "size_text": str(_parallel_value(down, "s", index, "") or "").strip(),
            "seeds": _safe_int(_parallel_value(down, "e", index, -1), -1),
            "source_label": str(_parallel_value(down, "p", index, "") or "").strip(),
        })

    # 为未来字段漂移兜底：如果 downurl 直接嵌入完整 Magnet/ED2K，也一起收进统一候选。
    for found in _find_links(payload, name=title, provider="viewing"):
        uri = str(found.get("uri") or "").strip()
        if not uri:
            continue
        output.append({
            **common,
            "url": uri,
            "name": str(found.get("name") or title).strip(),
            "resource_kind": str(found.get("type") or "embedded"),
        })

    deduped: List[Dict[str, Any]] = []
    seen = set()
    for row in output:
        key = (str(row.get("url") or "").strip(), str(row.get("passcode") or "").strip())
        if not key[0] or key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _json_refresh_required(response: requests.Response) -> bool:
    text = str(getattr(response, "text", "") or "").strip()
    if not text or not text.startswith("{"):
        return False
    try:
        payload = response.json()
    except Exception:
        try:
            payload = json.loads(text)
        except Exception:
            return False
    return isinstance(payload, dict) and _safe_int(payload.get("refresh"), 0) == 1


def _login_message(payload: Any, response: requests.Response) -> str:
    if isinstance(payload, dict):
        for key in ("msg", "message", "error"):
            value = str(payload.get(key) or "").strip()
            if value:
                return value[:300]
    return str(getattr(response, "text", "") or f"HTTP {getattr(response, 'status_code', 0)}")[:300]


def _captcha_required(payload: Any, message: str) -> bool:
    lowered = str(message or "").lower()
    if any(token.lower() in lowered for token in _CAPTCHA_HINTS):
        return True
    if isinstance(payload, dict):
        for key in ("captcha", "need_captcha", "captcha_required"):
            if payload.get(key):
                return True
    return False


def _bad_credentials(message: str) -> bool:
    lowered = str(message or "").lower()
    return any(token.lower() in lowered for token in _BAD_CREDENTIAL_HINTS)


class GuangYaGyingProtocolV1106Mixin:
    """HAR 对齐后的搜索、downurl、登录态与资源解析实现。"""

    build_id = "20260902-r17"

    def _gying_state(self) -> Dict[str, Any]:
        """在 Hardening/Failover 读取前先把历史数值状态规整，避免旧坏值拖垮节点选择。"""
        state = dict(super()._gying_state() or {})
        state["discovered_at"] = _safe_float(state.get("discovered_at"), 0.0)
        nodes = state.get("nodes") or {}
        clean_nodes: Dict[str, Dict[str, Any]] = {}
        if isinstance(nodes, dict):
            for key, raw in nodes.items():
                row = dict(raw) if isinstance(raw, dict) else {}
                row["last_ok_ts"] = _safe_float(row.get("last_ok_ts"), 0.0)
                row["last_checked_ts"] = _safe_float(row.get("last_checked_ts"), 0.0)
                clean_nodes[str(key)] = row
        state["nodes"] = clean_nodes
        discovered = state.get("discovered_nodes")
        state["discovered_nodes"] = [str(value) for value in discovered if str(value or "").strip()] if isinstance(discovered, list) else []
        return state

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
        response = super()._gying_request(
            session,
            node,
            method,
            url,
            retry_challenge=retry_challenge,
            **kwargs,
        )
        if not retry_challenge or not _json_refresh_required(response):
            return response
        try:
            self._gying_solve_challenge(session, node, response)
        except Exception as err:
            raise RuntimeError(
                "观影要求动态浏览器验证，自动 PoW 未完成；可在浏览器登录后复制该节点 Cookie 到插件"
            ) from err
        retried = super()._gying_request(
            session,
            node,
            method,
            url,
            retry_challenge=False,
            **kwargs,
        )
        if _json_refresh_required(retried):
            raise RuntimeError("观影动态浏览器验证已执行，但原请求仍要求 refresh 验证")
        return retried

    def _configured_cookie_available(self, session: requests.Session, node: str) -> bool:
        configured = str(getattr(self, "_viewing_cookie", "") or "").strip()
        if not configured or not len(session.cookies):
            return False
        preferred = str(getattr(self, "_viewing_base_url", "") or "").rstrip("/")
        return not preferred or str(node or "").rstrip("/") == preferred

    def _saved_authenticated_cookie(self, session: requests.Session, node: str) -> bool:
        if not len(session.cookies):
            return False
        try:
            row = dict(((self._gying_state().get("nodes") or {}).get(node) or {}))
        except Exception:
            row = {}
        return str(row.get("login_mode") or "") in _AUTH_COOKIE_MODES

    def _gying_login_password(self, session: requests.Session, node: str) -> Dict[str, Any]:
        username = str(getattr(self, "_viewing_username", "") or "").strip()
        password = str(getattr(self, "_viewing_password", "") or "")
        if not (username and password):
            return {
                "success": False,
                "mode": "credentials_missing",
                "message": "观影登录态已失效，且未配置用户名/密码；请更新 Cookie 或配置账号",
            }

        login_url = node.rstrip("/") + "/user/login"
        try:
            self._gying_request(
                session,
                node,
                "GET",
                login_url,
                headers={"Referer": node.rstrip("/") + "/"},
            )
        except Exception:
            # 登录页预热失败不直接判死，POST 仍可能可用。
            pass

        response = self._gying_request(
            session,
            node,
            "POST",
            login_url,
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
                "Accept": "*/*",
            },
        )
        try:
            result = response.json()
        except Exception:
            try:
                result = json.loads(response.text or "{}")
            except Exception:
                result = {}

        code = result.get("code") if isinstance(result, dict) else None
        if code in (200, "200"):
            self._gying_persist_session(
                node,
                session,
                status="ok",
                login_mode="password",
                login_at=self._now_text(),
            )
            return {"success": True, "mode": "password", "message": "观影账号登录成功"}

        message = _login_message(result, response)
        if _captcha_required(result, message):
            return {
                "success": False,
                "mode": "captcha_required",
                "message": "观影账号需要网页图形验证码；请在浏览器完成登录后把该节点 Cookie 填入插件",
                "status": int(response.status_code or 0),
            }
        if _bad_credentials(message):
            return {
                "success": False,
                "mode": "password",
                "message": f"观影登录失败：{message}",
                "status": int(response.status_code or 0),
            }
        return {
            "success": False,
            "mode": "password_pending",
            "message": f"观影登录未完成：{message or '站点未返回成功状态；可能要求网页验证码'}",
            "status": int(response.status_code or 0),
        }

    def _gying_login(self, session: requests.Session, node: str) -> Dict[str, Any]:
        if self._configured_cookie_available(session, node):
            return {"success": True, "mode": "configured_cookie", "message": "复用已配置观影 Cookie"}
        if self._saved_authenticated_cookie(session, node):
            return {"success": True, "mode": "cookie_reuse", "message": "复用上次成功登录的观影 Cookie"}

        username = str(getattr(self, "_viewing_username", "") or "").strip()
        password = str(getattr(self, "_viewing_password", "") or "")
        if username and password:
            return self._gying_login_password(session, node)
        return {"success": True, "mode": "anonymous", "message": "未配置观影账号/Cookie，先尝试公开访问"}

    @staticmethod
    def _downurl_login_flag(payload: Any) -> bool:
        return isinstance(payload, dict) and bool(payload.get("login"))

    def _decode_downurl_response(self, response: requests.Response) -> Dict[str, Any]:
        try:
            payload = response.json()
        except Exception:
            try:
                payload = json.loads(response.text or "{}")
            except Exception as err:
                raise RuntimeError("观影 downurl 返回非 JSON") from err
        return payload if isinstance(payload, dict) else {}

    def _gying_detail(
        self,
        session: requests.Session,
        node: str,
        resource_type: str,
        resource_id: str,
        referer: str,
    ) -> Dict[str, Any]:
        url = (
            f"{node.rstrip('/')}/res/downurl/"
            f"{quote(str(resource_type or '').strip())}/{quote(str(resource_id or '').strip())}"
        )
        response = self._gying_request(
            session,
            node,
            "GET",
            url,
            headers={"Referer": referer},
        )
        payload = self._decode_downurl_response(response)
        needs_login = self._gying_login_required(response) or self._downurl_login_flag(payload)
        if needs_login:
            login = self._gying_login_password(session, node)
            if not login.get("success"):
                raise RuntimeError(str(login.get("message") or "观影登录失效"))
            response = self._gying_request(
                session,
                node,
                "GET",
                url,
                headers={"Referer": referer},
            )
            payload = self._decode_downurl_response(response)

        if response.status_code >= 400:
            raise RuntimeError(f"观影 downurl HTTP {response.status_code}")
        if self._downurl_login_flag(payload) or payload.get("code") in (403, "403"):
            raise RuntimeError("观影 downurl 仍处于未登录状态；请更新 Cookie 或在网页重新登录")

        code = payload.get("code")
        has_resources = bool(extract_panlist_v1106(payload).get("url")) or bool(
            extract_downlist_v1106(payload).get("m")
        )
        if code not in (None, 200, "200") and not has_resources:
            message = str(payload.get("msg") or payload.get("message") or "downurl 返回失败状态")[:300]
            raise RuntimeError(f"观影 downurl 失败：{message}")
        return payload

    def _gying_raw_results(self, keyword: str, force: bool = False) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        keyword = " ".join(str(keyword or "").split())
        if not keyword:
            return [], {"provider": "viewing", "success": False, "message": "观影搜索关键词为空"}

        cached = dict(self._gying_search_cache.get(keyword) or {})
        if cached and not force and time.time() - _safe_float(cached.get("ts"), 0.0) < 120:
            return list(cached.get("rows") or []), dict(cached.get("state") or {})

        session, login = self._viewing_session()
        if not login.get("success"):
            return [], {"provider": "viewing", **dict(login or {})}
        node = str(
            login.get("node")
            or getattr(self, "_gying_active_node", "")
            or getattr(self, "_viewing_base_url", "")
            or ""
        ).rstrip("/")
        if not node:
            return [], {"provider": "viewing", "success": False, "message": "观影没有可用内容节点"}

        try:
            query = quote(keyword, safe="")
            search_variants = [
                ("browser", f"{node}/search?q={query}&type=&mode=1"),
                ("legacy", f"{node}/search?q={query}&type=0&mode=2"),
            ]
            cards: List[Dict[str, Any]] = []
            response: requests.Response | None = None
            search_mode = "browser"
            for mode, search_url in search_variants:
                current = self._gying_request(
                    session,
                    node,
                    "GET",
                    search_url,
                    headers={"Referer": node + "/"},
                )
                if self._gying_login_required(current):
                    relogin = self._gying_login_password(session, node)
                    if not relogin.get("success"):
                        raise RuntimeError(str(relogin.get("message") or "观影登录失效"))
                    current = self._gying_request(
                        session,
                        node,
                        "GET",
                        search_url,
                        headers={"Referer": node + "/"},
                    )
                if current.status_code >= 400:
                    if mode == "browser":
                        continue
                    raise RuntimeError(f"观影搜索 HTTP {current.status_code}")
                parsed = _parse_search_payload(current.text or "")
                response = current
                search_mode = mode
                if parsed:
                    cards = parsed
                    break

            if response is None:
                raise RuntimeError("观影搜索没有得到有效响应")

            rows: List[Dict[str, Any]] = []
            limit = max(1, min(_safe_int(getattr(self, "_provider_result_limit", 20), 20), 100))
            for item in cards[:limit]:
                resource_type = str(item.get("type") or "").strip()
                resource_id = str(item.get("id") or "").strip()
                if not resource_type or not resource_id:
                    continue
                detail_referer = f"{node}/{quote(resource_type)}/{quote(resource_id)}"
                try:
                    payload = self._gying_detail(
                        session,
                        node,
                        resource_type,
                        resource_id,
                        detail_referer,
                    )
                except Exception as err:
                    logger = getattr(self, "_gying_obs_log", None)
                    if callable(logger):
                        logger(
                            "WARNING",
                            "资源详情跳过：标题=%s 类型=%s 错误=%s",
                            str(item.get("title") or "-")[:80],
                            resource_type[:24],
                            str(err)[:180],
                        )
                    continue
                rows.extend(extract_resource_rows_v1106(payload, item))

            deduped: List[Dict[str, Any]] = []
            seen = set()
            for row in rows:
                key = (str(row.get("url") or "").strip(), str(row.get("passcode") or "").strip())
                if not key[0] or key in seen:
                    continue
                seen.add(key)
                deduped.append(row)

            pan_count = sum(1 for row in deduped if row.get("resource_kind") == "pan")
            magnet_count = sum(1 for row in deduped if str(row.get("url") or "").lower().startswith("magnet:?"))
            ed2k_count = sum(1 for row in deduped if str(row.get("url") or "").lower().startswith("ed2k://|file|"))
            xunlei_count = sum(1 for row in deduped if "pan.xunlei.com/s/" in str(row.get("url") or "").lower())

            self._gying_persist_session(
                node,
                session,
                status="ok",
                login_mode=str(login.get("mode") or ""),
                last_search_at=self._now_text(),
            )
            state = {
                "provider": "viewing",
                "success": True,
                "node": node,
                "login_mode": login.get("mode"),
                "cards": len(cards),
                "resources": len(deduped),
                "pan_resources": pan_count,
                "magnet_resources": magnet_count,
                "ed2k_resources": ed2k_count,
                "xunlei_resources": xunlei_count,
                "search_mode": search_mode,
                "message": (
                    f"观影搜索成功：影视 {len(cards)} · 网盘 {pan_count} · 迅雷 {xunlei_count} · "
                    f"Magnet {magnet_count} · ED2K {ed2k_count}"
                ),
            }
            self._gying_search_cache[keyword] = {"ts": time.time(), "rows": deduped, "state": state}
            return deduped, state
        except Exception as err:
            self._gying_mark_node(node, "search_error", str(err))
            return [], {
                "provider": "viewing",
                "success": False,
                "node": node,
                "login_mode": login.get("mode"),
                "message": str(err)[:400],
            }

    def _search_viewing_xunlei(self, keyword: str):
        output, state = super()._search_viewing_xunlei(keyword)
        raw_rows, _ = self._gying_raw_results(keyword)
        passcodes: Dict[str, str] = {}
        for item in raw_rows:
            url = html.unescape(str(item.get("url") or ""))
            match = _XUNLEI_RE.search(url)
            if not match:
                continue
            parsed = urlparse(match.group(0).rstrip(").]】）}"))
            share = re.search(r"^/s/([^/?#]+)", parsed.path or "", re.I)
            if not share:
                continue
            code = str(item.get("passcode") or "").strip()
            if not code:
                query = parse_qs(parsed.query or "")
                for key in ("pwd", "passcode", "pass_code", "code"):
                    values = query.get(key) or []
                    if values and str(values[0] or "").strip():
                        code = str(values[0]).strip()
                        break
            if code:
                passcodes[share.group(1).strip()] = code
        for row in output or []:
            share_id = str((row or {}).get("share_id") or (row or {}).get("identity") or "").strip()
            if share_id and not str((row or {}).get("passcode") or "").strip() and share_id in passcodes:
                row["passcode"] = passcodes[share_id]
        return output, state


__all__ = [
    "GuangYaGyingProtocolV1106Mixin",
    "extract_panlist_v1106",
    "extract_downlist_v1106",
    "extract_resource_rows_v1106",
]
