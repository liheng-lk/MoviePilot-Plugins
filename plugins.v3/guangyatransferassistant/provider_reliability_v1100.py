"""v1.10.0 外部资源搜索可靠性与统一搜索视图。

解决两个长期体验问题：
- 通用 Magnet/ED2K 接口不再只假定一个查询参数；按 provider 类型在 q/kw/keyword/search
  之间做有限、可诊断的兼容尝试，并统一 Bearer/X-API-Key 认证头；
- “观影搜索”不再只展示 Magnet/ED2K。统一搜索同时返回观影迅雷分享、观影 Magnet/ED2K
  以及外部 API 候选，让 UI 和自动分流看到同一套真实来源。

v1.10.3 修复 v1.10.0 重构时的方法名漂移：新版控制台与统一搜索调用
``_parse_provider_defs``，而 v1.9.2 的真实配置解析入口仍叫 ``_provider_api_defs``。
增加兼容桥接后，状态页、资源来源检测和统一搜索重新使用同一份 Magnet/ED2K 配置定义。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple
from urllib.parse import quote
from xml.etree import ElementTree

import requests

from .provider_sources_v192 import _dedupe_candidates, _find_links, _proxy_dict


class GuangYaProviderReliabilityV1100Mixin:
    """最终外部 Provider 搜索、探测和统一搜索 API。"""

    build_id = "20260901-r11"

    def _parse_provider_defs(self) -> List[Dict[str, str]]:
        """兼容 v1.10 控制台命名，复用 v1.9.2 唯一的 Provider 配置解析入口。"""
        parser = getattr(self, "_provider_api_defs", None)
        if not callable(parser):
            return []
        rows = parser() or []
        return [dict(row) for row in rows if isinstance(row, dict)]

    @staticmethod
    def _provider_query_variants(kind: str, keyword: str) -> List[Tuple[str, Dict[str, str]]]:
        kind = str(kind or "json").strip().lower()
        keyword = str(keyword or "").strip()
        if kind == "torznab":
            return [("q", {"t": "search", "q": keyword})]
        if kind == "tgsearch":
            keys = ("kw", "q", "keyword", "search")
        elif kind == "limitless":
            keys = ("keyword", "kw", "q", "search")
        else:
            keys = ("q", "keyword", "kw", "search")
        return [(key, {key: keyword}) for key in keys]

    @staticmethod
    def _provider_headers(token: str) -> Dict[str, str]:
        headers = {"Accept": "application/json, application/xml, text/xml, text/plain, */*"}
        raw = str(token or "").strip()
        if not raw:
            return headers
        lowered = raw.lower()
        if lowered.startswith("bearer ") or lowered.startswith("basic "):
            headers["Authorization"] = raw
            return headers
        if lowered.startswith("x-api-key:"):
            headers["X-API-Key"] = raw.split(":", 1)[1].strip()
            return headers
        # 大多数自建搜索 API 接受二者之一；同时携带可避免旧版本把裸 token 放进
        # Authorization 而导致 401。响应和日志中从不回显 token。
        headers["X-API-Key"] = raw
        headers["Authorization"] = f"Bearer {raw}"
        return headers

    @staticmethod
    def _provider_response_candidates(response: requests.Response, *, kind: str, name: str) -> List[Dict[str, Any]]:
        kind = str(kind or "json").strip().lower()
        candidates: List[Dict[str, Any]] = []
        content_type = str(response.headers.get("Content-Type") or "").lower()

        if kind == "torznab" or "xml" in content_type:
            try:
                root = ElementTree.fromstring(response.text or "")
            except Exception:
                root = None
            if root is not None:
                for item in root.findall(".//item"):
                    title = str(item.findtext("title") or "").strip()
                    payloads: List[Any] = [title, item.findtext("link"), item.findtext("guid")]
                    for enclosure in item.findall("enclosure"):
                        payloads.append(enclosure.attrib.get("url"))
                    for attr in item.findall("{*}attr"):
                        attr_name = str(attr.attrib.get("name") or "").lower()
                        if attr_name in {"magneturl", "magnet", "downloadurl", "download"}:
                            payloads.append(attr.attrib.get("value"))
                    for payload in payloads:
                        candidates.extend(_find_links(payload, name=title, provider=name))
                return _dedupe_candidates(candidates)

        payload: Any
        try:
            payload = response.json()
        except Exception:
            text = str(response.text or "")
            try:
                payload = json.loads(text)
            except Exception:
                payload = text
        return _dedupe_candidates(_find_links(payload, provider=name))

    def _search_api_provider(self, item: Dict[str, str], keyword: str):
        name = str(item.get("name") or "API").strip() or "API"
        kind = str(item.get("kind") or "json").strip().lower()
        url = str(item.get("url") or "").strip()
        token = str(item.get("token") or "").strip()
        if not url:
            return [], {"provider": name, "kind": kind, "success": False, "message": "接口地址为空", "attempts": []}

        session = requests.Session()
        proxies = _proxy_dict(bool(getattr(self, "_provider_proxy", False)))
        if proxies:
            session.proxies.update(proxies)
        headers = self._provider_headers(token)
        timeout = int(getattr(self, "_provider_timeout", 15) or 15)
        variants = self._provider_query_variants(kind, keyword)
        attempts: List[Dict[str, Any]] = []
        had_http_success = False
        last_error = ""

        for key, params in variants[:4]:
            request_url = url
            request_params = dict(params)
            # 兼容直接把关键词写进 URL 的 API 模板。
            if any(marker in request_url for marker in ("{keyword}", "{query}", "{q}")):
                encoded = quote(str(keyword or "").strip(), safe="")
                request_url = request_url.replace("{keyword}", encoded).replace("{query}", encoded).replace("{q}", encoded)
                request_params = {}
            if kind == "torznab" and token:
                request_params["apikey"] = token
            try:
                response = session.get(
                    request_url,
                    params=request_params,
                    headers=headers,
                    timeout=timeout,
                    allow_redirects=True,
                )
                status = int(response.status_code or 0)
                if status >= 400:
                    message = f"HTTP {status}"
                    attempts.append({"param": key, "status": status, "count": 0, "ok": False, "message": message})
                    last_error = message
                    # 401/403 多半是认证问题，换查询参数没有意义。
                    if status in {401, 403}:
                        break
                    continue
                had_http_success = True
                rows = self._provider_response_candidates(response, kind=kind, name=name)
                attempts.append({"param": key, "status": status, "count": len(rows), "ok": True})
                if rows:
                    limit = int(getattr(self, "_provider_result_limit", 20) or 20)
                    rows = _dedupe_candidates(rows)[:limit]
                    return rows, {
                        "provider": name,
                        "kind": kind,
                        "success": True,
                        "count": len(rows),
                        "query_param": key,
                        "message": f"{name} 搜索成功，得到 {len(rows)} 个 Magnet/ED2K 候选",
                        "attempts": attempts,
                    }
            except Exception as err:
                last_error = str(err)[:240]
                attempts.append({"param": key, "status": 0, "count": 0, "ok": False, "message": last_error})

        if had_http_success:
            return [], {
                "provider": name,
                "kind": kind,
                "success": True,
                "count": 0,
                "message": f"{name} 接口可访问，但本次没有 Magnet/ED2K 候选",
                "attempts": attempts,
            }
        return [], {
            "provider": name,
            "kind": kind,
            "success": False,
            "count": 0,
            "message": last_error or f"{name} 请求失败",
            "attempts": attempts,
        }

    def _unified_provider_search(self, keyword: str) -> Dict[str, Any]:
        keyword = str(keyword or "").strip()
        if not keyword:
            return {"success": False, "keyword": "", "message": "搜索关键词不能为空", "data": [], "xunlei": [], "states": []}

        candidates: List[Dict[str, Any]] = []
        xunlei: List[Dict[str, Any]] = []
        states: List[Dict[str, Any]] = []

        if bool(getattr(self, "_viewing_enabled", False)):
            viewing_rows, viewing_state = self._search_viewing(keyword)
            xunlei_rows, xunlei_state = self._search_viewing_xunlei(keyword)
            candidates.extend(viewing_rows or [])
            xunlei.extend(xunlei_rows or [])
            states.extend([dict(viewing_state or {}), dict(xunlei_state or {})])

        for item in self._parse_provider_defs():
            rows, state = self._search_api_provider(item, keyword)
            candidates.extend(rows or [])
            states.append(dict(state or {}))

        candidates = _dedupe_candidates(candidates)[: max(1, int(getattr(self, "_provider_result_limit", 20) or 20) * 3)]
        xunlei_by_id: Dict[str, Dict[str, Any]] = {}
        for row in xunlei:
            share_id = str(row.get("share_id") or row.get("identity") or "").strip()
            if not share_id:
                continue
            previous = xunlei_by_id.get(share_id)
            if not previous or (not previous.get("passcode") and row.get("passcode")):
                xunlei_by_id[share_id] = dict(row)
        xunlei = list(xunlei_by_id.values())[: max(1, int(getattr(self, "_provider_result_limit", 20) or 20))]

        magnet_count = sum(1 for row in candidates if str(row.get("type") or "") == "magnet")
        ed2k_count = sum(1 for row in candidates if str(row.get("type") or "") == "ed2k")
        healthy = any(bool(state.get("success")) for state in states)
        message = f"搜索完成：迅雷 {len(xunlei)} · Magnet {magnet_count} · ED2K {ed2k_count}"
        return {
            "success": healthy,
            "keyword": keyword,
            "message": message,
            "data": candidates,
            "xunlei": xunlei,
            "counts": {"xunlei": len(xunlei), "magnet": magnet_count, "ed2k": ed2k_count},
            "states": states,
        }

    def api_provider_search(self, keyword: str = "") -> Dict[str, Any]:
        return self._unified_provider_search(keyword)

    def api_provider_test(self) -> Dict[str, Any]:
        states: List[Dict[str, Any]] = []
        keyword = "test"
        selected = set(int(value) for value in (getattr(self, "_selected_subscriptions", []) or []) if int(value or 0) > 0)
        if selected:
            for subscribe in self._list_subscriptions(None):
                if int(getattr(subscribe, "id", 0) or 0) in selected:
                    keyword = self._provider_keyword(subscribe) or str(getattr(subscribe, "name", "") or "test")
                    break

        if bool(getattr(self, "_viewing_enabled", False)):
            try:
                _, login = self._viewing_session()
                states.append({
                    "provider": "viewing",
                    "success": bool(login.get("success")),
                    "node": str(login.get("node") or ""),
                    "login_mode": str(login.get("mode") or ""),
                    "message": str(login.get("message") or "")[:300],
                })
            except Exception as err:
                states.append({"provider": "viewing", "success": False, "message": str(err)[:300]})
        else:
            states.append({"provider": "viewing", "success": True, "enabled": False, "message": "未启用"})

        for item in self._parse_provider_defs():
            _, state = self._search_api_provider(item, keyword)
            states.append(dict(state or {}))

        overall = all(bool(item.get("success")) for item in states if item.get("enabled") is not False)
        result = {"success": overall, "keyword": keyword, "providers": states, "message": "资源来源检测完成" if overall else "部分资源来源不可用，请查看 providers"}
        self.save_data("provider_test_last", result)
        return result

    def api_provider_search_selected(self) -> Dict[str, Any]:
        selected = set(int(value) for value in (getattr(self, "_selected_subscriptions", []) or []) if int(value or 0) > 0)
        if not selected:
            result = {"success": False, "message": "尚未选择固定走光鸭的 MoviePilot 订阅", "items": []}
            self.save_data("provider_search_last", result)
            return result

        items: List[Dict[str, Any]] = []
        for subscribe in self._list_subscriptions(None):
            sid = int(getattr(subscribe, "id", 0) or 0)
            if sid not in selected:
                continue
            keyword = self._provider_keyword(subscribe) or str(getattr(subscribe, "name", "") or "")
            search = self._unified_provider_search(keyword)
            counts = dict(search.get("counts") or {})
            previews: List[Dict[str, Any]] = []
            for row in (search.get("xunlei") or [])[:3]:
                previews.append({"type": "xunlei", "name": str(row.get("name") or row.get("search_title") or "")[:160]})
            for row in (search.get("data") or [])[:5]:
                previews.append({"type": str(row.get("type") or ""), "name": str(row.get("name") or row.get("search_title") or "")[:160]})
            items.append({
                "subscribe_id": sid,
                "name": str(getattr(subscribe, "name", "") or ""),
                "year": str(getattr(subscribe, "year", "") or ""),
                "keyword": keyword,
                "success": bool(search.get("success")),
                "counts": counts,
                "message": str(search.get("message") or "")[:300],
                "preview": previews,
            })
            if len(items) >= 12:
                break

        total = {
            "xunlei": sum(int((item.get("counts") or {}).get("xunlei") or 0) for item in items),
            "magnet": sum(int((item.get("counts") or {}).get("magnet") or 0) for item in items),
            "ed2k": sum(int((item.get("counts") or {}).get("ed2k") or 0) for item in items),
        }
        result = {
            "success": any(bool(item.get("success")) for item in items),
            "message": f"已搜索 {len(items)} 个固定转存订阅：迅雷 {total['xunlei']} · Magnet {total['magnet']} · ED2K {total['ed2k']}",
            "counts": total,
            "items": items,
            "updated_at": self._now_text(),
        }
        self.save_data("provider_search_last", result)
        return result

    def get_api(self):
        apis = list(super().get_api() or [])
        paths = {str(item.get("path") or "") for item in apis if isinstance(item, dict)}
        if "/providers/search/selected" not in paths:
            apis.append({
                "path": "/providers/search/selected",
                "endpoint": self.api_provider_search_selected,
                "methods": ["POST"],
                "summary": "搜索已选择订阅的观影/迅雷/Magnet/ED2K 候选",
            })
        return apis


__all__ = ["GuangYaProviderReliabilityV1100Mixin"]
