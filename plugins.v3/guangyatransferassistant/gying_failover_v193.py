"""GYING 节点健康与自动故障切换。

放在 GuangYaGyingRuntimeMixin 前面，复用后者的节点发现、PoW、登录和持久化实现，
只负责避免“发布页/换址页 HTTP 200 被误当内容站”以及一个坏节点长期粘住。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple

import requests

from .gying_runtime_v193 import _normalize_node_url


_BAD_NODE_STATES = {"maintenance", "landing", "blocked", "error", "search_error"}
_LANDING_MARKERS = (
    "当前网址将在不久后失效",
    "获取新网址",
    "地址发布页",
)


class GuangYaGyingFailoverMixin:
    """最终节点选择权：优先最近成功节点，失败节点短暂冷却并自动切换。"""

    _gying_node_cooldown_seconds = 600

    @staticmethod
    def _gying_bad_credentials(message: str) -> bool:
        text = str(message or "").lower()
        return any(token in text for token in ("用户名或密码", "密码错误", "账号密码错误", "user or password", "invalid password"))

    def _gying_node_order(self) -> List[str]:
        state = self._gying_state()
        node_state = state.get("nodes") or {}
        active = _normalize_node_url(str(state.get("active_node") or ""))
        preferred = _normalize_node_url(str(getattr(self, "_viewing_base_url", "") or ""))
        discovered = list(self._discover_gying_nodes(force=False))
        all_nodes: List[str] = []
        for node in (active, preferred, *discovered):
            node = _normalize_node_url(node)
            if node and node not in all_nodes:
                all_nodes.append(node)
        if not bool(getattr(self, "_viewing_auto_switch", True)) and preferred:
            return [preferred]

        now = time.time()
        good: List[str] = []
        cooling: List[str] = []
        for node in all_nodes:
            row = dict(node_state.get(node) or {})
            status = str(row.get("status") or "")
            age = now - float(row.get("last_checked_ts") or 0)
            if status in _BAD_NODE_STATES and age < self._gying_node_cooldown_seconds:
                cooling.append(node)
            else:
                good.append(node)
        # 最近成功节点排最前；冷却节点只在其它节点都不可用时再试。
        good.sort(key=lambda node: float((node_state.get(node) or {}).get("last_ok_ts") or 0), reverse=True)
        return good + cooling

    def _viewing_session(self) -> Tuple[requests.Session, Dict[str, Any]]:
        if not bool(getattr(self, "_viewing_enabled", False)):
            return self._gying_new_session(""), {"success": False, "mode": "disabled", "message": "观影未启用"}
        state = self._gying_state()
        errors: List[str] = []
        for node in self._gying_node_order()[:12]:
            saved = str(((state.get("nodes") or {}).get(node) or {}).get("cookie") or "")
            session = self._gying_new_session(node, saved_cookie=saved)
            try:
                response = self._gying_request(session, node, "GET", node.rstrip("/") + "/")
                body = str(response.text or "")
                if any(marker in body for marker in ("站点维护中", "该站点维护中", "站点正在维护")):
                    self._gying_mark_node(node, "maintenance", "站点维护中")
                    errors.append(f"{node}: 维护中")
                    continue
                if any(marker in body for marker in _LANDING_MARKERS):
                    self._gying_mark_node(node, "landing", "换址/发布页，不是内容节点")
                    errors.append(f"{node}: 换址页")
                    continue
                if response.status_code >= 400:
                    self._gying_mark_node(node, "blocked", f"HTTP {response.status_code}")
                    errors.append(f"{node}: HTTP {response.status_code}")
                    continue
                login = self._gying_login(session, node)
                if not login.get("success"):
                    message = str(login.get("message") or "观影登录失败")
                    self._gying_mark_node(node, "login_failed", message)
                    if self._gying_bad_credentials(message):
                        return session, {"node": node, **login}
                    errors.append(f"{node}: {message[:120]}")
                    continue
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
        preferred = _normalize_node_url(str(getattr(self, "_viewing_base_url", "") or ""))
        return self._gying_new_session(preferred or ""), {
            "success": False,
            "mode": "unavailable",
            "node": preferred,
            "message": ("；".join(errors[:5]) or "没有可用观影节点")[:500],
        }

    def _gying_raw_results(self, keyword: str, force: bool = False):
        """搜索失败时把当前节点放入冷却并立即尝试下一个节点，最多三次。"""
        if not bool(getattr(self, "_viewing_auto_switch", True)):
            return super()._gying_raw_results(keyword, force=force)
        last_rows = []
        last_state: Dict[str, Any] = {"success": False, "message": "观影搜索失败"}
        for attempt in range(3):
            rows, state = super()._gying_raw_results(keyword, force=True if attempt else force)
            last_rows, last_state = rows, dict(state or {})
            if state.get("success"):
                return rows, state
            failed_node = _normalize_node_url(str(state.get("node") or ""))
            if not failed_node:
                break
            self._gying_mark_node(failed_node, "search_error", str(state.get("message") or "搜索失败"))
            store = self._gying_state()
            if str(store.get("active_node") or "") == failed_node:
                store["active_node"] = ""
                self._save_gying_state(store)
            self._gying_search_cache.pop(str(keyword or "").strip(), None)
        return last_rows, last_state


__all__ = ["GuangYaGyingFailoverMixin"]
