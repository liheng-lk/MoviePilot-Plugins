"""v1.9.3 GYING 完整性收口。

在完整 GYING 运行时与故障切换层之前增加最后一层安全/兼容补丁：
- 中文 IDN 与 punycode 统一成同一节点身份，避免重复验证/重复冷却；
- 把当前可访问的中文内容节点作为备用种子，但不写死为唯一入口；
- 手工 Cookie 只发送到与其绑定的首选节点，避免节点切换时跨域携带登录态；
- GYING 搜索在“标题+年份+季”零结果时自动退化到纯标题关键词；
- Provider 候选如果同时有年份信息，年份必须与 MoviePilot 订阅一致；
- 对 Angie/伪 404 等出口阻断做显式失败，让 Failover 立即换节点。
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List
from urllib.parse import urlparse, urlunparse

import requests

from .gying_runtime_v193 import _apply_cookie_header
from .legacy import _normalize_media_text
from .provider_sources_v192 import _proxy_dict


CURRENT_CONTENT_SEEDS = (
    "https://www.星际穿越.com",
)
LEGACY_GYING_DEFAULT = "https://www.gying.org"
_BLOCK_PAGE_MARKERS = (
    "Angie",
    "request forbidden",
    "access denied",
)


def canonical_gying_node(value: str) -> str:
    """把中文域名和 punycode 统一成 ASCII 节点身份，同时丢弃路径/凭据。"""
    raw = str(value or "").strip().strip("`\"'()[]{}，。；;")
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
    lowered = host.lower()
    if lowered in {"localhost", "localhost.localdomain"} or lowered.startswith("127.") or lowered.endswith(".local"):
        return ""
    try:
        ascii_host = host.encode("idna").decode("ascii").lower()
    except Exception:
        return ""
    port = parsed.port
    netloc = ascii_host if port is None else f"{ascii_host}:{port}"
    return urlunparse((parsed.scheme.lower(), netloc, "", "", "", "")).rstrip("/")


def gying_keyword_variants(keyword: str) -> List[str]:
    """GYING 对附加年份/季号并不稳定；只在零结果时按从严到宽顺序降级。"""
    original = " ".join(str(keyword or "").split())
    if not original:
        return []
    rows = [original]
    current = re.sub(r"\s+S\d{1,2}\s*$", "", original, flags=re.I).strip()
    if current and current not in rows:
        rows.append(current)
    current = re.sub(r"\s+(?:19|20)\d{2}\s*$", "", current, flags=re.I).strip()
    if current and current not in rows:
        rows.append(current)
    return rows[:3]


class GuangYaGyingHardeningMixin:
    """最终 GYING 节点身份、Cookie 边界和搜索降级策略。"""

    build_id = "20260901-r8"

    def init_plugin(self, config: dict = None) -> None:
        config = dict(config or {})
        super().init_plugin(config)
        preferred = canonical_gying_node(str(getattr(self, "_viewing_base_url", "") or ""))
        # v1.9.2 曾把 gying.org 作为固定默认值；现在它只是换址入口时，不应每轮都被当成
        # 首选内容节点。自动切换开启时把这个旧默认迁移为空，让节点池自行选择。
        if bool(getattr(self, "_viewing_auto_switch", True)) and preferred == canonical_gying_node(LEGACY_GYING_DEFAULT):
            preferred = ""
        self._viewing_base_url = preferred

    def _gying_state(self) -> Dict[str, Any]:
        state = dict(super()._gying_state() or {})
        changed = False
        active = canonical_gying_node(str(state.get("active_node") or ""))
        if active != str(state.get("active_node") or ""):
            state["active_node"] = active
            changed = True

        old_nodes = state.get("nodes") or {}
        if isinstance(old_nodes, dict):
            migrated: Dict[str, Dict[str, Any]] = {}
            for raw_node, raw_row in old_nodes.items():
                node = canonical_gying_node(str(raw_node or ""))
                if not node:
                    changed = True
                    continue
                row = dict(raw_row or {}) if isinstance(raw_row, dict) else {}
                old = migrated.get(node)
                if old:
                    old_ok = float(old.get("last_ok_ts") or 0)
                    new_ok = float(row.get("last_ok_ts") or 0)
                    if new_ok >= old_ok:
                        migrated[node] = row
                    changed = True
                else:
                    migrated[node] = row
                if node != str(raw_node or ""):
                    changed = True
            state["nodes"] = migrated

        discovered = []
        for raw in list(state.get("discovered_nodes") or []):
            node = canonical_gying_node(str(raw or ""))
            if node and node not in discovered:
                discovered.append(node)
            if node != str(raw or ""):
                changed = True
        state["discovered_nodes"] = discovered
        if changed:
            self._save_gying_state(state)
        return state

    def _discover_gying_nodes(self, force: bool = False) -> List[str]:
        base = list(super()._discover_gying_nodes(force=force) or [])
        state = self._gying_state()
        rows: List[str] = []
        for raw in (
            str(state.get("active_node") or ""),
            str(getattr(self, "_viewing_base_url", "") or ""),
            *str(getattr(self, "_viewing_node_urls", "") or "").splitlines(),
            *CURRENT_CONTENT_SEEDS,
            *base,
        ):
            node = canonical_gying_node(str(raw or ""))
            if node and node not in rows:
                rows.append(node)
        if rows != list(state.get("discovered_nodes") or []):
            state["discovered_nodes"] = rows[:30]
            state["discovered_at"] = time.time()
            self._save_gying_state(state)
        return rows[:30]

    def _gying_new_session(self, node: str, saved_cookie: str = "") -> requests.Session:
        """配置 Cookie 只跟随首选节点；运行时持久 Cookie 仍按 node 单独恢复。"""
        node = canonical_gying_node(node)
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "sec-ch-ua": '\"Chromium\";v=\"140\", \"Google Chrome\";v=\"140\", \"Not_A Brand\";v=\"99\"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '\"Windows\"',
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
        return session

    def _gying_request(self, session: requests.Session, node: str, method: str, url: str, **kwargs: Any) -> requests.Response:
        response = super()._gying_request(session, node, method, url, **kwargs)
        text = str(response.text or "")
        lowered = text.lower()
        if response.status_code in {403, 404} and any(marker.lower() in lowered for marker in _BLOCK_PAGE_MARKERS):
            raise RuntimeError(f"观影节点当前出口被阻断：HTTP {response.status_code}")
        return response

    def _gying_raw_results(self, keyword: str, force: bool = False):
        variants = gying_keyword_variants(keyword)
        if not variants:
            return super()._gying_raw_results(keyword, force=force)
        last_rows = []
        last_state: Dict[str, Any] = {"success": False, "message": "观影搜索失败"}
        for index, variant in enumerate(variants):
            rows, state = super()._gying_raw_results(variant, force=force)
            last_rows, last_state = rows, dict(state or {})
            if not state.get("success"):
                return rows, state
            if int(state.get("cards") or 0) > 0 or rows:
                if variant != variants[0]:
                    last_state["query_fallback"] = variant
                    last_state["message"] = f"{last_state.get('message') or '观影搜索成功'} · 已自动使用纯标题查询"
                return rows, last_state
        return last_rows, last_state

    @staticmethod
    def _provider_candidate_matches(subscribe: Any, row: Dict[str, Any]) -> bool:
        expected = _normalize_media_text(getattr(subscribe, "name", ""))
        actual = _normalize_media_text(row.get("search_title") or row.get("name") or "")
        if not expected or not actual or not (expected in actual or actual in expected):
            return False
        try:
            expected_year = int(getattr(subscribe, "year", 0) or 0)
        except (TypeError, ValueError):
            expected_year = 0
        try:
            actual_year = int(row.get("year") or 0)
        except (TypeError, ValueError):
            actual_year = 0
        if expected_year and actual_year and expected_year != actual_year:
            return False
        return True


__all__ = ["GuangYaGyingHardeningMixin", "canonical_gying_node", "gying_keyword_variants"]