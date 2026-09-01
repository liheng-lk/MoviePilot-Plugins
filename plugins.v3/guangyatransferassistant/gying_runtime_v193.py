"""v1.9.3 完整观影 GYING 运行时。

目标：
- 从发布页与手动节点建立可切换节点池；
- 在同一 requests.Session 内处理 GYING 自定义浏览器 PoW 验证并持久化验证 Cookie；
- 使用真实 /user/login、/search、/res/downurl 接口；
- 统一为 Magnet/ED2K Provider 与迅雷秒传提供同一份搜索结果。

本模块不绕过账号权限，只复现站点公开前端完成的计算型 challenge；账号登录仍需用户
自己的用户名/密码或已经合法取得的 Cookie。验证态和登录态 Cookie 只保存在插件私有数据，
公开 API 仅返回节点/会话状态，不回显 Cookie、密码或挑战明文。
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import time
from http.cookies import SimpleCookie
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote, urlencode, urljoin, urlparse, urlunparse

import requests

from .provider_sources_v192 import _dedupe_candidates, _find_links, _proxy_dict


DEFAULT_GYING_REGISTRIES = "https://www.gying.page\nhttps://gying.si"
DEFAULT_GYING_SEEDS = (
    "https://www.gying.net",
    "https://www.gying.org",
    "https://www.gying.si",
    "https://www.gying.in",
    "https://www.gying.st",
    "https://www.gyg.la",
    "https://www.gyg.si",
    "https://www.gyg.st",
)
_GYING_SEARCH_RE = re.compile(r"(?s)_obj\s*\.\s*search\s*=\s*(\{.*?\})\s*;")
_GYING_CHALLENGE_RE = re.compile(r"(?s)const\s+json\s*=\s*(\{.*?\})\s*;\s*const\s+jss\s*=")
_GYING_URL_RE = re.compile(r"https?://[^\s\"'<>，。；;]+", re.I)
_XUNLEI_URL_RE = re.compile(r"https?://pan\.xunlei\.com/s/[^\s\"'<>，。；;]+", re.I)
_PASSCODE_RE = re.compile(r"(?:提取码|访问码|密码|口令|pass\s*code|passcode|pwd)\s*[:：=]?\s*([A-Za-z0-9]{1,16})", re.I)
_CHALLENGE_MARKERS = (
    "正在确认你是不是机器人",
    "浏览器安全验证",
    "正在进行浏览器计算验证",
    "安全验证",
)
_LOGIN_MARKERS = (
    "_BT.PC.HTML('login')",
    '_BT.PC.HTML("login")',
    "_BT.PC.HTML('nologin')",
    '_BT.PC.HTML("nologin")',
    "未登录，访问受限",
)
_MAINTENANCE_MARKERS = ("站点维护中", "该站点维护中", "站点正在维护")


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _normalize_node_url(value: str) -> str:
    raw = html.unescape(str(value or "").strip()).strip("`\"'()[]{}，。；;")
    if not raw:
        return ""
    if not raw.lower().startswith(("http://", "https://")):
        raw = "https://" + raw
    try:
        parsed = urlparse(raw)
    except Exception:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    if parsed.username or parsed.password:
        return ""
    host = parsed.hostname.strip(".")
    if host.lower() in {"localhost", "localhost.localdomain"} or host.startswith("127.") or host.endswith(".local"):
        return ""
    netloc = parsed.netloc
    return urlunparse((parsed.scheme, netloc, "", "", "", "")).rstrip("/")


def _registry_node_candidate(value: str) -> bool:
    url = _normalize_node_url(value)
    if not url:
        return False
    host = str(urlparse(url).hostname or "")
    lowered = host.lower()
    if any(token in lowered for token in ("gying", "gyg")) or lowered.startswith("xn--"):
        return True
    return any(ord(ch) > 127 for ch in host)


def _cookie_header(session: requests.Session) -> str:
    pairs = []
    for item in session.cookies:
        if item.name and item.value:
            pairs.append(f"{item.name}={item.value}")
    return "; ".join(pairs)


def _apply_cookie_header(session: requests.Session, value: str) -> None:
    raw = str(value or "").strip()
    if not raw:
        return
    cookie = SimpleCookie()
    try:
        cookie.load(raw)
    except Exception:
        cookie = SimpleCookie()
    if cookie:
        for key, morsel in cookie.items():
            session.cookies.set(str(key), str(morsel.value))
        return
    for part in raw.split(";"):
        key, sep, val = part.strip().partition("=")
        if sep and key:
            session.cookies.set(key.strip(), val.strip())


def _is_challenge_text(text: str) -> bool:
    body = str(text or "")
    return any(marker in body for marker in _CHALLENGE_MARKERS)


def _solve_pow_hex(modulus_hex: str, value_hex: str, rounds: int) -> str:
    """复现 GYING worker：y=(y*y)%N，返回不带 0x 的十六进制 y。"""
    rounds = _safe_int(rounds, 0)
    if rounds <= 0 or rounds > 2_000_000:
        raise ValueError("GYING PoW 迭代次数异常")
    try:
        modulus = int(str(modulus_hex or "").removeprefix("0x"), 16)
        value = int(str(value_hex or "").removeprefix("0x"), 16)
    except Exception as err:
        raise ValueError("GYING PoW 参数无效") from err
    if modulus <= 1:
        raise ValueError("GYING PoW 模数无效")
    for _ in range(rounds):
        value = (value * value) % modulus
    return format(value, "x")


def _solve_legacy_nonces(challenges: Iterable[str], salt: str, diff: int) -> List[int]:
    """兼容旧版 challenge/diff/salt：sha256(str(nonce)+salt)。"""
    wanted = [str(item or "").strip().lower() for item in challenges if str(item or "").strip()]
    if not wanted:
        raise ValueError("GYING legacy challenge 为空")
    limit = _safe_int(diff, 0)
    if limit <= 0 or limit > 5_000_000:
        raise ValueError("GYING legacy challenge diff 异常")
    remaining = set(wanted)
    found: Dict[str, int] = {}
    for nonce in range(limit + 1):
        digest = hashlib.sha256(f"{nonce}{salt}".encode("utf-8")).hexdigest().lower()
        if digest in remaining:
            found[digest] = nonce
            remaining.discard(digest)
            if not remaining:
                break
    if remaining:
        raise ValueError("GYING legacy challenge 未找到全部 nonce")
    return [found[item] for item in wanted]


def _parse_search_payload(text: str) -> List[Dict[str, Any]]:
    match = _GYING_SEARCH_RE.search(str(text or ""))
    if not match:
        return []
    try:
        payload = json.loads(match.group(1))
    except Exception:
        return []
    listing = payload.get("l") if isinstance(payload, dict) else None
    if not isinstance(listing, dict):
        return []
    titles = list(listing.get("title") or [])
    years = list(listing.get("year") or [])
    kinds = list(listing.get("d") or [])
    ids = list(listing.get("i") or [])
    infos = list(listing.get("info") or [])
    size = max(len(titles), len(years), len(kinds), len(ids), 0)
    rows: List[Dict[str, Any]] = []
    for index in range(size):
        title = str(titles[index] if index < len(titles) else "").strip()
        kind = str(kinds[index] if index < len(kinds) else "").strip()
        resource_id = str(ids[index] if index < len(ids) else "").strip()
        if not title or not kind or not resource_id:
            continue
        rows.append({
            "title": title,
            "year": years[index] if index < len(years) else "",
            "type": kind,
            "id": resource_id,
            "info": str(infos[index] if index < len(infos) else "").strip(),
        })
    return rows


def _extract_panlist(payload: Any) -> Dict[str, List[Any]]:
    """不同节点偶尔把 panlist 放在顶层或 data/downlist 内，递归找到 name/url 数组。"""
    if isinstance(payload, dict):
        panlist = payload.get("panlist")
        if isinstance(panlist, dict) and isinstance(panlist.get("url"), list):
            return {
                "url": list(panlist.get("url") or []),
                "name": list(panlist.get("name") or []),
                "type": list(panlist.get("type") or []),
            }
        for value in payload.values():
            found = _extract_panlist(value)
            if found.get("url"):
                return found
    elif isinstance(payload, (list, tuple)):
        for value in payload:
            found = _extract_panlist(value)
            if found.get("url"):
                return found
    return {"url": [], "name": [], "type": []}


class GuangYaGyingRuntimeMixin:
    """观影节点选择、challenge、登录、搜索与会话持久化最终实现。"""

    _viewing_registry_urls = DEFAULT_GYING_REGISTRIES
    _viewing_node_urls = ""
    _viewing_auto_switch = True
    _viewing_auto_challenge = True
    _viewing_node_cache_minutes = 360
    _gying_active_node = ""
    _gying_search_cache: Dict[str, Dict[str, Any]] = {}

    def init_plugin(self, config: dict = None) -> None:
        config = dict(config or {})
        self._viewing_registry_urls = str(config.get("viewing_registry_urls") or DEFAULT_GYING_REGISTRIES).strip()
        self._viewing_node_urls = str(config.get("viewing_node_urls") or "").strip()
        self._viewing_auto_switch = bool(config.get("viewing_auto_switch", True))
        self._viewing_auto_challenge = bool(config.get("viewing_auto_challenge", True))
        self._viewing_node_cache_minutes = max(10, min(_safe_int(config.get("viewing_node_cache_minutes"), 360), 1440))
        self._gying_active_node = ""
        self._gying_search_cache = {}
        super().init_plugin(config)

    # ------------------------------------------------------------------
    # 私有状态 / 节点池
    # ------------------------------------------------------------------
    def _gying_state(self) -> Dict[str, Any]:
        state = self.get_data("viewing_session_state") or {}
        if not isinstance(state, dict):
            state = {}
        state.setdefault("schema", 2)
        state.setdefault("active_node", "")
        state.setdefault("discovered_at", 0)
        state.setdefault("nodes", {})
        return state

    def _save_gying_state(self, state: Dict[str, Any]) -> None:
        nodes = state.get("nodes") or {}
        if isinstance(nodes, dict) and len(nodes) > 40:
            ordered = sorted(
                nodes.items(),
                key=lambda pair: float((pair[1] or {}).get("last_ok_ts") or (pair[1] or {}).get("last_checked_ts") or 0),
                reverse=True,
            )[:40]
            state["nodes"] = dict(ordered)
        self.save_data("viewing_session_state", state)

    def _gying_new_session(self, node: str, saved_cookie: str = "") -> requests.Session:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "sec-ch-ua": '"Chromium";v="140", "Google Chrome";v="140", "Not_A Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        })
        proxies = _proxy_dict(bool(getattr(self, "_provider_proxy", False)))
        if proxies:
            session.proxies.update(proxies)
        if saved_cookie:
            _apply_cookie_header(session, saved_cookie)
        if str(getattr(self, "_viewing_cookie", "") or "").strip():
            _apply_cookie_header(session, str(getattr(self, "_viewing_cookie", "") or ""))
        return session

    def _discover_gying_nodes(self, force: bool = False) -> List[str]:
        state = self._gying_state()
        now = time.time()
        cached = list(state.get("discovered_nodes") or [])
        ttl = float(self._viewing_node_cache_minutes) * 60.0
        if cached and not force and now - float(state.get("discovered_at") or 0) < ttl:
            return cached

        rows: List[str] = []
        preferred = _normalize_node_url(str(getattr(self, "_viewing_base_url", "") or ""))
        if preferred:
            rows.append(preferred)
        for raw in self._viewing_node_urls.splitlines():
            node = _normalize_node_url(raw)
            if node:
                rows.append(node)

        session = self._gying_new_session(preferred or "")
        for raw in self._viewing_registry_urls.splitlines():
            registry = _normalize_node_url(raw)
            if not registry:
                continue
            try:
                response = session.get(registry + "/", timeout=min(int(getattr(self, "_provider_timeout", 15) or 15), 20), allow_redirects=True)
                text = html.unescape(str(response.text or ""))
                values = list(_GYING_URL_RE.findall(text))
                values.extend(str(match) for match in re.findall(r"href=[\"']([^\"']+)[\"']", text, flags=re.I))
                for value in values:
                    absolute = urljoin(response.url, value)
                    if _registry_node_candidate(absolute):
                        rows.append(_normalize_node_url(absolute))
            except Exception:
                continue

        rows.extend(DEFAULT_GYING_SEEDS)
        dedup: List[str] = []
        seen = set()
        for value in rows:
            node = _normalize_node_url(value)
            if not node or node in seen:
                continue
            seen.add(node)
            dedup.append(node)
        state["discovered_nodes"] = dedup[:30]
        state["discovered_at"] = now
        self._save_gying_state(state)
        return dedup[:30]

    # ------------------------------------------------------------------
    # Challenge / 会话
    # ------------------------------------------------------------------
    def _gying_solve_challenge(self, session: requests.Session, node: str, response: requests.Response) -> Dict[str, Any]:
        if not self._viewing_auto_challenge:
            raise RuntimeError("观影返回浏览器安全验证；自动计算验证已关闭")
        text = str(response.text or "")
        match = _GYING_CHALLENGE_RE.search(text)
        if match:
            try:
                data = json.loads(match.group(1))
            except Exception as err:
                raise RuntimeError("观影验证数据解析失败") from err
            started = time.monotonic()
            challenge_id = str(data.get("id") or "")
            if data.get("N") and data.get("x") and data.get("t"):
                y = _solve_pow_hex(str(data.get("N")), str(data.get("x")), _safe_int(data.get("t"), 0))
                elapsed = time.monotonic() - started
                if elapsed < 3.0:
                    time.sleep(3.0 - elapsed)
                verify = session.post(
                    response.url,
                    data={"action": "verify", "id": challenge_id, "y": y},
                    headers={"Referer": response.url},
                    timeout=int(getattr(self, "_provider_timeout", 15) or 15) + 15,
                    allow_redirects=True,
                )
                if verify.status_code >= 400:
                    raise RuntimeError(f"观影 PoW 提交失败 HTTP {verify.status_code}")
                return {"mode": "embedded_pow", "success": True}
            challenges = data.get("challenge") or []
            if challenges and data.get("diff") and data.get("salt") is not None:
                nonces = _solve_legacy_nonces(challenges, str(data.get("salt") or ""), _safe_int(data.get("diff"), 0))
                form: List[Tuple[str, str]] = [("action", "verify"), ("id", challenge_id)]
                form.extend(("nonce[]", str(value)) for value in nonces)
                verify = session.post(
                    response.url,
                    data=form,
                    headers={"Referer": response.url},
                    timeout=int(getattr(self, "_provider_timeout", 15) or 15) + 15,
                    allow_redirects=True,
                )
                if verify.status_code >= 400:
                    raise RuntimeError(f"观影 legacy 验证提交失败 HTTP {verify.status_code}")
                return {"mode": "legacy_hash", "success": True}

        # 新版远程 PoW：challenge 页通过 browser_pow 标记，真实 N/x/t 在 /res/pow。
        pow_url = node.rstrip("/") + "/res/pow"
        started = time.monotonic()
        pow_resp = session.get(pow_url, headers={"Referer": response.url}, timeout=int(getattr(self, "_provider_timeout", 15) or 15))
        try:
            data = pow_resp.json()
        except Exception as err:
            raise RuntimeError("观影远程 PoW 参数获取失败") from err
        if not isinstance(data, dict) or not data.get("N") or not data.get("x") or not data.get("t"):
            raise RuntimeError("观影远程 PoW 参数不完整")
        y = _solve_pow_hex(str(data.get("N")), str(data.get("x")), _safe_int(data.get("t"), 0))
        elapsed = time.monotonic() - started
        if elapsed < 3.0:
            time.sleep(3.0 - elapsed)
        verify = session.post(
            pow_url,
            data={"y": y},
            headers={"Referer": response.url},
            timeout=int(getattr(self, "_provider_timeout", 15) or 15) + 15,
            allow_redirects=True,
        )
        try:
            payload = verify.json()
        except Exception:
            payload = {}
        if verify.status_code >= 400 or (isinstance(payload, dict) and payload and payload.get("success") is False):
            raise RuntimeError(f"观影远程 PoW 提交失败 HTTP {verify.status_code}")
        return {"mode": "remote_pow", "success": True, "challenge_id": str((payload or {}).get("challenge_id") or "")}

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
        response = session.request(method.upper(), url, timeout=timeout, allow_redirects=True, **kwargs)
        if retry_challenge and _is_challenge_text(response.text or ""):
            self._gying_solve_challenge(session, node, response)
            response = session.request(method.upper(), url, timeout=timeout, allow_redirects=True, **kwargs)
            if _is_challenge_text(response.text or ""):
                raise RuntimeError("观影浏览器验证已计算，但原请求仍返回验证页；请尝试更换节点/代理")
        return response

    @staticmethod
    def _gying_login_required(response: requests.Response) -> bool:
        text = str(response.text or "")
        return response.status_code == 403 or any(marker in text for marker in _LOGIN_MARKERS)

    def _gying_persist_session(self, node: str, session: requests.Session, **extra: Any) -> None:
        state = self._gying_state()
        nodes = state.setdefault("nodes", {})
        row = dict(nodes.get(node) or {})
        now = time.time()
        row.update({
            "status": str(extra.pop("status", "ok")),
            "cookie": _cookie_header(session),
            "last_checked_ts": now,
            "last_ok_ts": now,
            "updated_at": self._now_text(),
            **extra,
        })
        nodes[node] = row
        state["active_node"] = node
        self._gying_active_node = node
        self._save_gying_state(state)

    def _gying_mark_node(self, node: str, status: str, message: str = "") -> None:
        state = self._gying_state()
        nodes = state.setdefault("nodes", {})
        row = dict(nodes.get(node) or {})
        row.update({
            "status": status,
            "message": str(message or "")[:300],
            "last_checked_ts": time.time(),
            "updated_at": self._now_text(),
        })
        nodes[node] = row
        self._save_gying_state(state)

    def _gying_login(self, session: requests.Session, node: str) -> Dict[str, Any]:
        username = str(getattr(self, "_viewing_username", "") or "").strip()
        password = str(getattr(self, "_viewing_password", "") or "")
        if not (username and password):
            mode = "cookie" if len(session.cookies) else "anonymous"
            return {"success": True, "mode": mode, "message": "复用现有观影 Cookie" if mode == "cookie" else "未配置观影账号"}
        payload = {
            "code": "",
            "siteid": "1",
            "dosubmit": "1",
            "cookietime": "10506240",
            "username": username,
            "password": password,
        }
        login_url = node.rstrip("/") + "/user/login"
        response = self._gying_request(
            session,
            node,
            "POST",
            login_url,
            data=payload,
            headers={"Referer": node.rstrip("/") + "/"},
        )
        try:
            result = response.json()
        except Exception:
            result = {}
        code = (result or {}).get("code") if isinstance(result, dict) else None
        if code not in (200, "200"):
            message = str((result or {}).get("msg") or (result or {}).get("message") or response.text or f"HTTP {response.status_code}")[:300]
            return {"success": False, "mode": "password", "message": f"观影登录失败：{message}", "status": response.status_code}
        try:
            self._gying_request(session, node, "GET", node.rstrip("/") + "/mv/wkMn")
        except Exception:
            pass
        self._gying_persist_session(node, session, status="ok", login_mode="password", login_at=self._now_text())
        return {"success": True, "mode": "password", "message": "观影账号登录成功"}

    def _viewing_session(self) -> Tuple[requests.Session, Dict[str, Any]]:
        if not bool(getattr(self, "_viewing_enabled", False)):
            return self._gying_new_session(""), {"success": False, "mode": "disabled", "message": "观影未启用"}
        state = self._gying_state()
        nodes = self._discover_gying_nodes(force=False)
        active = _normalize_node_url(str(state.get("active_node") or ""))
        preferred = _normalize_node_url(str(getattr(self, "_viewing_base_url", "") or ""))
        ordered: List[str] = []
        for node in (active, preferred, *nodes):
            if node and node not in ordered:
                ordered.append(node)
        if not bool(self._viewing_auto_switch) and preferred:
            ordered = [preferred]
        errors: List[str] = []
        for node in ordered[:12]:
            saved = str(((state.get("nodes") or {}).get(node) or {}).get("cookie") or "")
            session = self._gying_new_session(node, saved_cookie=saved)
            try:
                response = self._gying_request(session, node, "GET", node.rstrip("/") + "/")
                body = str(response.text or "")
                if any(marker in body for marker in _MAINTENANCE_MARKERS):
                    self._gying_mark_node(node, "maintenance", "站点维护中")
                    errors.append(f"{node}: 维护中")
                    continue
                if response.status_code >= 400:
                    self._gying_mark_node(node, "blocked", f"HTTP {response.status_code}")
                    errors.append(f"{node}: HTTP {response.status_code}")
                    continue
                login = self._gying_login(session, node)
                if not login.get("success"):
                    self._gying_mark_node(node, "login_failed", str(login.get("message") or ""))
                    return session, {"node": node, **login}
                self._gying_persist_session(
                    node,
                    session,
                    status="ok",
                    login_mode=str(login.get("mode") or ""),
                    verified=bool(session.cookies.get("browser_verified") or session.cookies.get("browser_pow")),
                )
                return session, {"success": True, "node": node, **login}
            except Exception as err:
                self._gying_mark_node(node, "error", str(err))
                errors.append(f"{node}: {str(err)[:120]}")
                continue
        return self._gying_new_session(preferred or ""), {
            "success": False,
            "mode": "unavailable",
            "node": preferred,
            "message": ("；".join(errors[:4]) or "没有可用观影节点")[:500],
        }

    # ------------------------------------------------------------------
    # 搜索 / downurl（Magnet 与迅雷共用一次结果）
    # ------------------------------------------------------------------
    def _gying_detail(self, session: requests.Session, node: str, resource_type: str, resource_id: str, referer: str) -> Dict[str, Any]:
        url = f"{node.rstrip('/')}/res/downurl/{quote(str(resource_type or '').strip())}/{quote(str(resource_id or '').strip())}"
        response = self._gying_request(session, node, "GET", url, headers={"Referer": referer})
        if self._gying_login_required(response):
            login = self._gying_login(session, node)
            if not login.get("success"):
                raise RuntimeError(str(login.get("message") or "观影登录失效"))
            response = self._gying_request(session, node, "GET", url, headers={"Referer": referer})
        if response.status_code >= 400:
            raise RuntimeError(f"观影 downurl HTTP {response.status_code}")
        try:
            payload = response.json()
        except Exception:
            try:
                payload = json.loads(response.text or "{}")
            except Exception as err:
                raise RuntimeError("观影 downurl 返回非 JSON") from err
        if isinstance(payload, dict) and payload.get("code") in (403, "403"):
            raise RuntimeError("观影 downurl 返回未登录")
        return payload if isinstance(payload, dict) else {}

    def _gying_raw_results(self, keyword: str, force: bool = False) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        keyword = str(keyword or "").strip()
        if not keyword:
            return [], {"success": False, "message": "观影搜索关键词为空"}
        cached = dict(self._gying_search_cache.get(keyword) or {})
        if cached and not force and time.time() - float(cached.get("ts") or 0) < 120:
            return list(cached.get("rows") or []), dict(cached.get("state") or {})
        session, login = self._viewing_session()
        if not login.get("success"):
            return [], {"provider": "viewing", **login}
        node = str(login.get("node") or self._gying_active_node or getattr(self, "_viewing_base_url", "") or "").rstrip("/")
        try:
            search_url = f"{node}/search?q={quote(keyword)}&type=0&mode=2"
            response = self._gying_request(session, node, "GET", search_url, headers={"Referer": node + "/"})
            if self._gying_login_required(response):
                relogin = self._gying_login(session, node)
                if not relogin.get("success"):
                    raise RuntimeError(str(relogin.get("message") or "观影登录失效"))
                response = self._gying_request(session, node, "GET", search_url, headers={"Referer": node + "/"})
            if response.status_code >= 400:
                raise RuntimeError(f"观影搜索 HTTP {response.status_code}")
            cards = _parse_search_payload(response.text or "")
            rows: List[Dict[str, Any]] = []
            for item in cards[: int(getattr(self, "_provider_result_limit", 20) or 20)]:
                try:
                    payload = self._gying_detail(session, node, str(item.get("type") or ""), str(item.get("id") or ""), response.url)
                except Exception:
                    continue
                panlist = _extract_panlist(payload)
                urls = list(panlist.get("url") or [])
                names = list(panlist.get("name") or [])
                types = list(panlist.get("type") or [])
                for index, value in enumerate(urls):
                    rows.append({
                        "url": str(value or ""),
                        "name": str(names[index] if index < len(names) else item.get("title") or "").strip(),
                        "pan_type": types[index] if index < len(types) else None,
                        "search_title": str(item.get("title") or "").strip(),
                        "year": item.get("year"),
                        "resource_type": str(item.get("type") or ""),
                        "resource_id": str(item.get("id") or ""),
                    })
            self._gying_persist_session(node, session, status="ok", login_mode=str(login.get("mode") or ""), last_search_at=self._now_text())
            state = {
                "provider": "viewing",
                "success": True,
                "node": node,
                "login_mode": login.get("mode"),
                "cards": len(cards),
                "resources": len(rows),
                "message": f"观影搜索成功：{len(cards)} 个影视结果，{len(rows)} 条网盘/资源链接",
            }
            self._gying_search_cache[keyword] = {"ts": time.time(), "rows": rows, "state": state}
            return rows, state
        except Exception as err:
            self._gying_mark_node(node, "search_error", str(err))
            return [], {"provider": "viewing", "success": False, "node": node, "login_mode": login.get("mode"), "message": str(err)[:400]}

    def _search_viewing(self, keyword: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        rows, state = self._gying_raw_results(keyword)
        candidates: List[Dict[str, Any]] = []
        for item in rows:
            for row in _find_links(str(item.get("url") or ""), name=str(item.get("name") or item.get("search_title") or ""), provider="viewing"):
                row["search_title"] = str(item.get("search_title") or "")
                candidates.append(row)
        candidates = _dedupe_candidates(candidates)[: int(getattr(self, "_provider_result_limit", 20) or 20)]
        return candidates, {**state, "message": f"观影搜索成功，得到 {len(candidates)} 个 Magnet/ED2K 候选" if state.get("success") else state.get("message")}

    def _search_viewing_xunlei(self, keyword: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        rows, state = self._gying_raw_results(keyword)
        candidates: List[Dict[str, Any]] = []
        for item in rows:
            value = html.unescape(str(item.get("url") or ""))
            for match in _XUNLEI_URL_RE.finditer(value):
                raw_url = match.group(0).rstrip(").]】）}")
                parsed = urlparse(raw_url)
                share_match = re.search(r"^/s/([^/?#]+)", parsed.path or "", re.I)
                if not share_match:
                    continue
                passcode = ""
                query = dict((key, values) for key, values in __import__("urllib.parse", fromlist=["parse_qs"]).parse_qs(parsed.query or "").items())
                for key in ("pwd", "passcode", "pass_code", "code"):
                    values = query.get(key) or []
                    if values and str(values[0] or "").strip():
                        passcode = str(values[0]).strip()
                        break
                if not passcode:
                    nearby = f"{item.get('name') or ''} {value}"
                    code_match = _PASSCODE_RE.search(nearby)
                    if code_match:
                        passcode = code_match.group(1).strip()
                candidates.append({
                    "type": "xunlei",
                    "uri": raw_url,
                    "identity": share_match.group(1).strip(),
                    "share_id": share_match.group(1).strip(),
                    "passcode": passcode,
                    "name": str(item.get("name") or item.get("search_title") or "").strip(),
                    "search_title": str(item.get("search_title") or "").strip(),
                    "provider": "viewing",
                })
        dedup: Dict[str, Dict[str, Any]] = {}
        for row in candidates:
            key = str(row.get("share_id") or "")
            old = dedup.get(key)
            if not old or (not old.get("passcode") and row.get("passcode")):
                dedup[key] = row
        output = list(dedup.values())[: int(getattr(self, "_provider_result_limit", 20) or 20)]
        return output, {**state, "provider": "viewing_xunlei", "message": f"观影找到 {len(output)} 个迅雷分享候选" if state.get("success") else state.get("message")}

    # ------------------------------------------------------------------
    # 对外诊断 API（不返回 Cookie/密码）
    # ------------------------------------------------------------------
    def api_viewing_nodes(self) -> Dict[str, Any]:
        state = self._gying_state()
        rows = []
        for node in self._discover_gying_nodes(force=False):
            saved = dict(((state.get("nodes") or {}).get(node) or {}))
            rows.append({
                "url": node,
                "active": node == str(state.get("active_node") or ""),
                "status": str(saved.get("status") or "unknown"),
                "message": str(saved.get("message") or "")[:200],
                "verified": bool(saved.get("verified")),
                "login_mode": str(saved.get("login_mode") or ""),
                "updated_at": str(saved.get("updated_at") or ""),
            })
        return {"success": True, "active_node": str(state.get("active_node") or ""), "data": rows}

    def api_viewing_nodes_refresh(self) -> Dict[str, Any]:
        nodes = self._discover_gying_nodes(force=True)
        session, status = self._viewing_session()
        del session
        return {"success": bool(status.get("success")), "message": str(status.get("message") or "节点刷新完成"), "active_node": str(status.get("node") or ""), "count": len(nodes), "data": self.api_viewing_nodes().get("data")}

    def api_viewing_session_test(self, keyword: str = "") -> Dict[str, Any]:
        session, status = self._viewing_session()
        del session
        result: Dict[str, Any] = {"success": bool(status.get("success")), "node": str(status.get("node") or ""), "mode": str(status.get("mode") or ""), "message": str(status.get("message") or "")}
        if result["success"] and str(keyword or "").strip():
            rows, search_state = self._gying_raw_results(str(keyword).strip(), force=True)
            result.update({"success": bool(search_state.get("success")), "message": str(search_state.get("message") or ""), "resources": len(rows), "cards": int(search_state.get("cards") or 0)})
        return result

    def api_provider_test(self) -> Dict[str, Any]:
        base = dict(super().api_provider_test() or {})
        providers = [row for row in (base.get("data") or []) if str((row or {}).get("provider") or "") != "viewing"]
        if bool(getattr(self, "_viewing_enabled", False)):
            _, status = self._viewing_session()
            providers.insert(0, {"provider": "viewing", "success": bool(status.get("success")), "node": str(status.get("node") or ""), "mode": str(status.get("mode") or ""), "message": str(status.get("message") or "")})
        return {"success": all(bool(item.get("success")) for item in providers) if providers else True, "data": providers}

    def get_api(self) -> List[Dict[str, Any]]:
        apis = list(super().get_api() or [])
        paths = {str(item.get("path") or "") for item in apis if isinstance(item, dict)}
        extras = [
            {"path": "/viewing/nodes", "endpoint": self.api_viewing_nodes, "methods": ["GET"], "summary": "查看观影节点池"},
            {"path": "/viewing/nodes/refresh", "endpoint": self.api_viewing_nodes_refresh, "methods": ["POST"], "summary": "刷新观影节点并选择可用节点"},
            {"path": "/viewing/session/test", "endpoint": self.api_viewing_session_test, "methods": ["POST"], "summary": "测试观影验证/登录/搜索会话"},
        ]
        apis.extend(item for item in extras if item["path"] not in paths)
        return apis


__all__ = [
    "GuangYaGyingRuntimeMixin",
    "_normalize_node_url",
    "_parse_search_payload",
    "_solve_pow_hex",
    "_solve_legacy_nonces",
]
