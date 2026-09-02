"""v1.9.2 外部资源搜索提供器。

补齐两类来源：
- 观影 GYING：可配置站点地址、Cookie，或使用用户名/密码尝试标准表单登录；
- 磁力/ED2K 搜索 API：支持 tg-search、Limitless/通用 JSON 与 Torznab。

搜索结果只作为 ResourceGroup 候选，最终仍经过 MoviePilot 缺集、Episode Resolver、
订阅规则与光鸭 cloudcollection 拆包，不直接下载到本地。
"""

from __future__ import annotations

import json
import re
import time
from html.parser import HTMLParser
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote, urljoin
from xml.etree import ElementTree

import requests

from app.sdk.config import settings

from .episode_resolver_v190 import AUTO_SELECT_CONFIDENCE, reliable_episode_set, resolve_episode
from .legacy import _normalize_media_text
from .source_types_v180 import normalize_source_uri


_LINK_RE = re.compile(r"(magnet:\?[^\s\"'<>]+|ed2k://\|file\|[^\r\n\"'<>]+?\|/)", re.I)
_ACTIVE_SOURCE_STATES = {"new", "dispatching", "submitted", "queued", "waiting", "retry", "completed"}


class _LoginFormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.forms: List[Dict[str, Any]] = []
        self._form: Optional[Dict[str, Any]] = None

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        data = {str(k): str(v or "") for k, v in attrs}
        if tag.lower() == "form":
            self._form = {"action": data.get("action") or "", "method": (data.get("method") or "post").lower(), "inputs": []}
            return
        if tag.lower() == "input" and self._form is not None:
            self._form["inputs"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "form" and self._form is not None:
            self.forms.append(self._form)
            self._form = None


class _GyingSearchParser(HTMLParser):
    """只提取观影搜索卡片里的详情链接和标题，不依赖 BeautifulSoup。"""

    def __init__(self) -> None:
        super().__init__()
        self.items: List[Dict[str, str]] = []
        self._depth = 0
        self._card: Optional[Dict[str, str]] = None
        self._capture_b = False
        self._text: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        data = {str(k): str(v or "") for k, v in attrs}
        classes = set((data.get("class") or "").split())
        if tag.lower() in {"div", "article"} and "v5d" in classes and self._card is None:
            self._card = {"href": "", "title": ""}
            self._depth = 1
            return
        if self._card is None:
            return
        if tag.lower() in {"div", "article"}:
            self._depth += 1
        if tag.lower() == "a" and not self._card.get("href"):
            self._card["href"] = data.get("href") or ""
        if tag.lower() == "b":
            self._capture_b = True
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._capture_b:
            self._text.append(str(data or ""))

    def handle_endtag(self, tag: str) -> None:
        if self._card is None:
            return
        if tag.lower() == "b" and self._capture_b:
            self._capture_b = False
            self._card["title"] = "".join(self._text).strip()
        if tag.lower() in {"div", "article"}:
            self._depth -= 1
            if self._depth <= 0:
                if self._card.get("href"):
                    self.items.append(dict(self._card))
                self._card = None
                self._depth = 0


def _proxy_dict(enabled: bool) -> Optional[Dict[str, str]]:
    if not enabled:
        return None
    proxy = getattr(settings, "PROXY", None)
    if isinstance(proxy, dict):
        return proxy
    if isinstance(proxy, str) and proxy.strip():
        value = proxy.strip()
        return {"http": value, "https": value}
    return None


def _dedupe_candidates(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    seen = set()
    for raw in rows:
        uri = str(raw.get("uri") or "").strip()
        try:
            normalized = normalize_source_uri(uri)
        except Exception:
            continue
        key = (normalized["type"], normalized["identity"])
        if key in seen:
            continue
        seen.add(key)
        output.append({
            **dict(raw),
            "uri": normalized["uri"],
            "type": normalized["type"],
            "identity": normalized["identity"],
            "name": str(raw.get("name") or normalized.get("name") or "").strip()[:300],
        })
    return output


def _find_links(value: Any, *, name: str = "", provider: str = "") -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if isinstance(value, dict):
        label = str(
            value.get("title") or value.get("name") or value.get("filename")
            or value.get("resource_name") or value.get("subject") or name or ""
        )
        for child in value.values():
            rows.extend(_find_links(child, name=label, provider=provider))
        return rows
    if isinstance(value, (list, tuple)):
        for child in value:
            rows.extend(_find_links(child, name=name, provider=provider))
        return rows
    if not isinstance(value, str):
        return rows
    for match in _LINK_RE.finditer(value):
        rows.append({"uri": match.group(1), "name": name, "provider": provider})
    return rows


class GuangYaProviderSourcesMixin:
    """在频道 ResourceGroup 之外补充观影与用户自定义 Magnet API。"""

    _provider_auto_search = True
    _provider_timeout = 15
    _provider_result_limit = 20
    _provider_proxy = False
    _viewing_enabled = False
    _viewing_base_url = "https://www.gying.org"
    _viewing_login_path = "/login"
    _viewing_username = ""
    _viewing_password = ""
    _viewing_cookie = ""
    _magnet_api_sources = ""

    def init_plugin(self, config: dict = None) -> None:
        config = dict(config or {})
        self._provider_auto_search = bool(config.get("provider_auto_search", True))
        self._provider_timeout = max(5, min(int(config.get("provider_timeout") or 15), 60))
        self._provider_result_limit = max(1, min(int(config.get("provider_result_limit") or 20), 100))
        self._provider_proxy = bool(config.get("provider_proxy", False))
        self._viewing_enabled = bool(config.get("viewing_enabled", False))
        self._viewing_base_url = str(config.get("viewing_base_url") or "https://www.gying.org").strip().rstrip("/")
        self._viewing_login_path = str(config.get("viewing_login_path") or "/login").strip() or "/login"
        self._viewing_username = str(config.get("viewing_username") or "").strip()
        self._viewing_password = str(config.get("viewing_password") or "")
        self._viewing_cookie = str(config.get("viewing_cookie") or "").strip()
        self._magnet_api_sources = str(config.get("magnet_api_sources") or "").strip()
        super().init_plugin(config)

    # ------------------------------------------------------------------
    # Provider 配置
    # ------------------------------------------------------------------
    def _provider_api_defs(self) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        for raw in self._magnet_api_sources.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = [part.strip() for part in line.split("|", 3)]
            while len(parts) < 4:
                parts.append("")
            name, kind, url, token = parts
            kind = (kind or "json").lower()
            if kind not in {"json", "tgsearch", "limitless", "torznab"} or not url:
                continue
            rows.append({"name": name or kind, "kind": kind, "url": url.rstrip("/"), "token": token})
        return rows[:20]

    def _provider_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36",
            "Accept": "text/html,application/json,application/xml;q=0.9,*/*;q=0.8",
        })
        proxies = _proxy_dict(self._provider_proxy)
        if proxies:
            session.proxies.update(proxies)
        return session

    def _viewing_session(self) -> Tuple[requests.Session, Dict[str, Any]]:
        session = self._provider_session()
        if self._viewing_cookie:
            session.headers["Cookie"] = self._viewing_cookie
            return session, {"mode": "cookie", "success": True, "message": "使用已配置 Cookie"}
        if not (self._viewing_username and self._viewing_password):
            return session, {"mode": "anonymous", "success": True, "message": "未配置登录凭据，使用匿名访问"}

        login_url = urljoin(self._viewing_base_url + "/", self._viewing_login_path.lstrip("/"))
        try:
            page = session.get(login_url, timeout=self._provider_timeout, allow_redirects=True)
            parser = _LoginFormParser()
            parser.feed(page.text or "")
            form = next((item for item in parser.forms if any((x.get("type") or "").lower() == "password" for x in item.get("inputs") or [])), None)
            if not form:
                return session, {"mode": "password", "success": False, "message": "未识别到标准登录表单，请改用 Cookie"}
            payload: Dict[str, str] = {}
            username_key = ""
            password_key = ""
            for item in form.get("inputs") or []:
                key = str(item.get("name") or "").strip()
                if not key:
                    continue
                typ = str(item.get("type") or "text").lower()
                lowered = key.lower()
                if typ == "password" and not password_key:
                    password_key = key
                    continue
                if typ in {"text", "email"} and not username_key and any(token in lowered for token in ("user", "email", "account", "login")):
                    username_key = key
                    continue
                if typ == "hidden":
                    payload[key] = str(item.get("value") or "")
            if not username_key:
                username_key = "username"
            if not password_key:
                password_key = "password"
            payload[username_key] = self._viewing_username
            payload[password_key] = self._viewing_password
            action = urljoin(page.url, str(form.get("action") or page.url))
            response = session.post(action, data=payload, timeout=self._provider_timeout, allow_redirects=True)
            ok = bool(session.cookies) and response.status_code < 400
            return session, {
                "mode": "password",
                "success": ok,
                "message": "账号密码登录成功" if ok else "登录未取得有效 Cookie；站点可能需要验证码，请改用 Cookie",
                "status": response.status_code,
            }
        except Exception as err:
            return session, {"mode": "password", "success": False, "message": f"登录失败：{err}"[:300]}

    # ------------------------------------------------------------------
    # 观影 GYING
    # ------------------------------------------------------------------
    def _search_viewing(self, keyword: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        if not self._viewing_enabled or not self._viewing_base_url:
            return [], {"provider": "viewing", "enabled": False, "success": True, "message": "未启用"}
        session, login = self._viewing_session()
        if not login.get("success"):
            return [], {"provider": "viewing", "enabled": True, **login}
        try:
            search_url = f"{self._viewing_base_url}/s/1---1/{quote(keyword.strip())}"
            response = session.get(search_url, timeout=self._provider_timeout)
            if response.status_code >= 400:
                raise RuntimeError(f"HTTP {response.status_code}")
            parser = _GyingSearchParser()
            parser.feed(response.text or "")
            candidates: List[Dict[str, Any]] = []
            for item in parser.items[: self._provider_result_limit]:
                href = str(item.get("href") or "").strip()
                title = str(item.get("title") or "").strip()
                if not href:
                    continue
                down_url = urljoin(self._viewing_base_url + "/", f"res/downurl{href}")
                detail = session.get(down_url, timeout=self._provider_timeout, headers={"Referer": response.url})
                if detail.status_code >= 400:
                    continue
                try:
                    payload = detail.json()
                except Exception:
                    try:
                        payload = json.loads(detail.text or "{}")
                    except Exception:
                        continue
                panlist = payload.get("panlist") if isinstance(payload, dict) else None
                urls = list((panlist or {}).get("url") or []) if isinstance(panlist, dict) else []
                names = list((panlist or {}).get("name") or []) if isinstance(panlist, dict) else []
                for index, value in enumerate(urls):
                    label = str(names[index] if index < len(names) else title or "").strip()
                    for row in _find_links(str(value), name=label or title, provider="viewing"):
                        row["search_title"] = title
                        candidates.append(row)
            candidates = _dedupe_candidates(candidates)[: self._provider_result_limit]
            return candidates, {
                "provider": "viewing",
                "enabled": True,
                "success": True,
                "message": f"搜索成功，得到 {len(candidates)} 个 Magnet/ED2K 候选",
                "login_mode": login.get("mode"),
                "cards": len(parser.items),
            }
        except Exception as err:
            return [], {"provider": "viewing", "enabled": True, "success": False, "message": str(err)[:300], "login_mode": login.get("mode")}

    # ------------------------------------------------------------------
    # 通用 Magnet API / Torznab
    # ------------------------------------------------------------------
    def _search_api_provider(self, item: Dict[str, str], keyword: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        name = item["name"]
        kind = item["kind"]
        url = item["url"]
        token = item["token"]
        session = self._provider_session()
        headers: Dict[str, str] = {"Accept": "application/json,application/xml,text/xml,*/*"}
        params: Dict[str, Any] = {}
        if kind == "torznab":
            params = {"t": "search", "q": keyword}
            if token:
                params["apikey"] = token
        else:
            params = {"kw": keyword}
            if kind == "json":
                params = {"q": keyword}
            if token:
                headers["X-API-Key"] = token
                headers["Authorization"] = token
        try:
            response = session.get(url, params=params, headers=headers, timeout=self._provider_timeout)
            if response.status_code >= 400:
                raise RuntimeError(f"HTTP {response.status_code}")
            rows: List[Dict[str, Any]] = []
            if kind == "torznab":
                try:
                    root = ElementTree.fromstring(response.text or "")
                    for node in root.findall(".//item"):
                        title = (node.findtext("title") or "").strip()
                        values = []
                        enclosure = node.find("enclosure")
                        if enclosure is not None and enclosure.attrib.get("url"):
                            values.append(enclosure.attrib.get("url") or "")
                        for child in node.iter():
                            for value in child.attrib.values():
                                if isinstance(value, str):
                                    values.append(value)
                            if child.text:
                                values.append(child.text)
                        for value in values:
                            rows.extend(_find_links(value, name=title, provider=name))
                except Exception:
                    rows.extend(_find_links(response.text or "", provider=name))
            else:
                try:
                    payload = response.json()
                except Exception:
                    payload = response.text or ""
                rows.extend(_find_links(payload, provider=name))
            rows = _dedupe_candidates(rows)[: self._provider_result_limit]
            return rows, {"provider": name, "kind": kind, "success": True, "message": f"得到 {len(rows)} 个候选"}
        except Exception as err:
            return [], {"provider": name, "kind": kind, "success": False, "message": str(err)[:300]}

    def _search_external_providers(self, keyword: str) -> Dict[str, Any]:
        keyword = str(keyword or "").strip()
        if not keyword:
            return {"success": False, "message": "keyword 不能为空", "data": [], "providers": []}
        rows: List[Dict[str, Any]] = []
        states: List[Dict[str, Any]] = []
        viewing_rows, viewing_state = self._search_viewing(keyword)
        rows.extend(viewing_rows)
        states.append(viewing_state)
        for item in self._provider_api_defs():
            found, state = self._search_api_provider(item, keyword)
            rows.extend(found)
            states.append(state)
        rows = _dedupe_candidates(rows)[: self._provider_result_limit]
        return {
            "success": any(state.get("success") for state in states if state.get("enabled", True)),
            "message": f"共得到 {len(rows)} 个 Magnet/ED2K 候选",
            "data": rows,
            "providers": states,
        }

    @staticmethod
    def _provider_candidate_matches(subscribe: Any, row: Dict[str, Any]) -> bool:
        expected = _normalize_media_text(getattr(subscribe, "name", ""))
        raw_actual = " ".join(
            str(value or "").strip()
            for value in (row.get("search_title"), row.get("name"), row.get("label"))
            if str(value or "").strip()
        )
        actual = _normalize_media_text(raw_actual)
        if not expected or not actual:
            return False
        if not (expected in actual or actual in expected):
            return False

        expected_year = str(getattr(subscribe, "year", "") or "").strip()
        actual_years = set(re.findall(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", raw_actual))
        if expected_year and actual_years and expected_year not in actual_years:
            return False

        seasons = {
            int(value)
            for pair in re.findall(r"(?i)(?:\bS(?:eason)?\s*0*(\d{1,2})\b|第\s*0*(\d{1,2})\s*季)", raw_actual)
            for value in pair if value
        }
        is_movie = "movie" in str(getattr(subscribe, "type", "") or "").lower() or "电影" in str(getattr(subscribe, "type", "") or "")
        if is_movie and seasons:
            return False
        try:
            expected_season = int(getattr(subscribe, "season", 0) or 0)
        except (TypeError, ValueError):
            expected_season = 0
        if not is_movie and expected_season > 0 and seasons and expected_season not in seasons:
            return False
        return True

    def _provider_keyword(self, subscribe: Any) -> str:
        parts = [str(getattr(subscribe, "name", "") or "").strip()]
        year = str(getattr(subscribe, "year", "") or "").strip()
        if year:
            parts.append(year)
        season = getattr(subscribe, "season", None)
        try:
            season_no = int(season or 0)
        except (TypeError, ValueError):
            season_no = 0
        if season_no > 0:
            parts.append(f"S{season_no:02d}")
        return " ".join(part for part in parts if part)

    def _dispatch_provider_candidate(self, subscribe: Any, uncovered: set[int]) -> Optional[Dict[str, Any]]:
        result = self._search_external_providers(self._provider_keyword(subscribe))
        sid = int(getattr(subscribe, "id", 0) or 0)
        is_movie = self._is_movie_subscription(subscribe)
        for candidate in result.get("data") or []:
            if not self._provider_candidate_matches(subscribe, candidate):
                continue
            source_type = str(candidate.get("type") or "")
            target: set[int] = set()
            if not is_movie:
                if source_type == "magnet":
                    target = set(uncovered)
                else:
                    parsed = resolve_episode(str(candidate.get("name") or ""), season_hint=getattr(subscribe, "season", None))
                    target = reliable_episode_set(parsed, float(getattr(self, "_episode_auto_confidence", AUTO_SELECT_CONFIDENCE) or AUTO_SELECT_CONFIDENCE)).intersection(uncovered)
                    if not target:
                        continue
            existing = self._existing_source(sid, source_type, str(candidate.get("identity") or ""))
            if existing and str(existing.get("state") or "") in _ACTIVE_SOURCE_STATES:
                continue
            row = self._upsert_source(
                sid,
                str(candidate.get("uri") or ""),
                label=str(candidate.get("name") or candidate.get("search_title") or "")[:120],
                origin=f"provider:{candidate.get('provider') or 'api'}",
                auto_dispatch=True,
                resource_group_id=f"provider:{candidate.get('provider') or 'api'}:{int(time.time())}",
                target_episodes=sorted(target),
                source_label=str(candidate.get("provider") or "外部搜索")[:120],
                candidate_rank=1 if source_type == "magnet" else 2,
            )
            self._spawn_source_dispatch(str(row.get("id") or ""))
            return {
                "source_id": str(row.get("id") or ""),
                "type": source_type,
                "episodes": sorted(target),
                "provider": str(candidate.get("provider") or ""),
            }
        return None

    def _dispatch_channel_external_candidates(self, subscribe: Any) -> Dict[str, Any]:
        result = dict(super()._dispatch_channel_external_candidates(subscribe) or {})
        if not self._provider_auto_search:
            return result
        sid = int(getattr(subscribe, "id", 0) or 0)
        if not sid:
            return result
        plan = dict(self.api_resource_plan(sid).get("data") or {})
        is_movie = self._is_movie_subscription(subscribe)
        uncovered = set(int(value) for value in (plan.get("uncovered") or []) if int(value or 0) > 0)
        if not is_movie and not uncovered:
            return result
        if result.get("actions"):
            return result
        if not self._viewing_enabled and not self._provider_api_defs():
            return result
        action = self._dispatch_provider_candidate(subscribe, uncovered)
        if not action:
            return result
        actions = list(result.get("actions") or []) + [action]
        return {**result, "success": True, "actions": actions, "provider_actions": [action], "message": "频道候选未覆盖，已从外部资源提供器补充候选"}

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------
    def api_provider_search(self, keyword: str = "") -> Dict[str, Any]:
        result = self._search_external_providers(keyword)
        # API 不返回观影 Cookie、账号、密码或接口密钥。
        return result

    def api_provider_test(self) -> Dict[str, Any]:
        providers = []
        if self._viewing_enabled:
            session, login = self._viewing_session()
            state = {"provider": "viewing", **login}
            if login.get("success"):
                try:
                    response = session.get(self._viewing_base_url + "/", timeout=self._provider_timeout)
                    state["success"] = response.status_code < 400
                    state["status"] = response.status_code
                    state["message"] = "观影连接正常" if state["success"] else f"观影 HTTP {response.status_code}"
                except Exception as err:
                    state["success"] = False
                    state["message"] = str(err)[:300]
            providers.append(state)
        for item in self._provider_api_defs():
            providers.append({"provider": item["name"], "kind": item["kind"], "configured": True, "success": True, "message": "配置已解析；使用搜索接口进行实际连通测试"})
        return {"success": all(item.get("success") for item in providers) if providers else True, "data": providers}

    def get_api(self) -> List[Dict[str, Any]]:
        apis = list(super().get_api() or [])
        existing = {str(item.get("path") or "") for item in apis if isinstance(item, dict)}
        extras = [
            {"path": "/providers/search", "endpoint": self.api_provider_search, "methods": ["GET"], "summary": "搜索观影/磁力API候选"},
            {"path": "/providers/test", "endpoint": self.api_provider_test, "methods": ["POST"], "summary": "测试观影登录和外部来源配置"},
        ]
        apis.extend(item for item in extras if item["path"] not in existing)
        return apis


__all__ = ["GuangYaProviderSourcesMixin"]
