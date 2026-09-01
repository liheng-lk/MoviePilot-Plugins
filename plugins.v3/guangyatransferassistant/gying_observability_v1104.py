"""v1.10.4 观影 GYING 可观测性层。

观影链路此前主要把最终结果写入 ``viewing_session_state``，节点发现、PoW、登录、搜索、
downurl 和故障切换缺少统一插件日志。这里仅补可观测性，不改变节点选择、认证、搜索、
迅雷秒传或 Magnet/ED2K 业务决策。

日志和公开状态只记录节点、阶段、结果计数与错误摘要；Cookie、密码、Token、PoW 参数、
迅雷提取码不会写入日志或公开状态。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

from .gying_runtime_v193 import _extract_panlist


class GuangYaGyingObservabilityV1104Mixin:
    """给最终 GYING 调用链补齐可判断的过程日志与最近运行状态。"""

    build_id = "20260901-r15"

    @staticmethod
    def _gying_node_label(value: Any) -> str:
        raw = str(value or "").strip()
        if not raw:
            return "-"
        try:
            parsed = urlparse(raw if "://" in raw else "https://" + raw)
            if parsed.hostname:
                port = f":{parsed.port}" if parsed.port else ""
                return f"{parsed.scheme or 'https'}://{parsed.hostname}{port}"
        except Exception:
            pass
        return "-"

    def _gying_obs_log(self, level: str, message: str, *args: Any) -> None:
        writer = getattr(self, "_plugin_log", None)
        if not callable(writer):
            return
        try:
            writer(level, "【光鸭转存助手】【观影】" + message, *args)
        except Exception:
            pass

    def _gying_obs_record(
        self,
        stage: str,
        *,
        success: bool | None = None,
        node: str = "",
        message: str = "",
        **extra: Any,
    ) -> None:
        try:
            old = self.get_data("viewing_observability_state") or {}
            state = dict(old) if isinstance(old, dict) else {}
            state.update({
                "stage": str(stage or "")[:40],
                "success": success,
                "node": self._gying_node_label(node),
                "message": str(message or "")[:300],
                "updated_at": self._now_text(),
                "updated_ts": time.time(),
            })
            for key in ("mode", "cards", "resources", "magnet", "ed2k", "xunlei", "nodes"):
                if key in extra:
                    value = extra.get(key)
                    if isinstance(value, (str, int, float, bool)) or value is None:
                        state[key] = value
            self.save_data("viewing_observability_state", state)
        except Exception:
            pass

    def init_plugin(self, config: dict = None) -> None:
        super().init_plugin(config)
        enabled = bool(getattr(self, "_viewing_enabled", False))
        self._gying_obs_log(
            "INFO",
            "运行时初始化：启用=%s 自动切节点=%s 自动PoW=%s 首选节点=%s",
            enabled,
            bool(getattr(self, "_viewing_auto_switch", True)),
            bool(getattr(self, "_viewing_auto_challenge", True)),
            self._gying_node_label(getattr(self, "_viewing_base_url", "")),
        )
        self._gying_obs_record("init", success=True if enabled else None, node=getattr(self, "_viewing_base_url", ""), message="观影已启用" if enabled else "观影未启用")

    def _discover_gying_nodes(self, force: bool = False) -> List[str]:
        started = time.monotonic()
        try:
            rows = list(super()._discover_gying_nodes(force=force) or [])
        except Exception as err:
            self._gying_obs_log("WARNING", "节点发现失败：%s", str(err)[:240])
            self._gying_obs_record("discover", success=False, message=str(err))
            raise
        if force:
            self._gying_obs_log("INFO", "节点刷新完成：候选=%s 耗时=%.2fs", len(rows), time.monotonic() - started)
        self._gying_obs_record("discover", success=bool(rows), node=rows[0] if rows else "", message=f"发现 {len(rows)} 个候选节点", nodes=len(rows))
        return rows

    def _gying_solve_challenge(self, session, node: str, response):
        label = self._gying_node_label(node)
        started = time.monotonic()
        self._gying_obs_log("INFO", "检测到浏览器 PoW：节点=%s，开始计算验证", label)
        self._gying_obs_record("pow", success=None, node=node, message="开始计算浏览器 PoW")
        try:
            result = dict(super()._gying_solve_challenge(session, node, response) or {})
        except Exception as err:
            self._gying_obs_log("WARNING", "PoW失败：节点=%s 错误=%s", label, str(err)[:240])
            self._gying_obs_record("pow", success=False, node=node, message=str(err))
            raise
        mode = str(result.get("mode") or "unknown")
        self._gying_obs_log("INFO", "PoW通过：节点=%s 模式=%s 耗时=%.2fs", label, mode, time.monotonic() - started)
        self._gying_obs_record("pow", success=True, node=node, message="浏览器 PoW 已通过", mode=mode)
        return result

    def _gying_login(self, session, node: str) -> Dict[str, Any]:
        label = self._gying_node_label(node)
        configured = bool(str(getattr(self, "_viewing_username", "") or "").strip() and str(getattr(self, "_viewing_password", "") or ""))
        self._gying_obs_log("INFO", "登录检查：节点=%s 账号登录=%s 现有Cookie=%s", label, configured, bool(len(session.cookies)))
        try:
            result = dict(super()._gying_login(session, node) or {})
        except Exception as err:
            self._gying_obs_log("WARNING", "登录调用异常：节点=%s 错误=%s", label, str(err)[:240])
            self._gying_obs_record("login", success=False, node=node, message=str(err))
            raise
        ok = bool(result.get("success"))
        mode = str(result.get("mode") or "")
        message = str(result.get("message") or "")[:240]
        self._gying_obs_log("INFO" if ok else "WARNING", "登录结果：节点=%s 成功=%s 模式=%s 信息=%s", label, ok, mode or "-", message or "-")
        self._gying_obs_record("login", success=ok, node=node, message=message, mode=mode)
        return result

    def _gying_mark_node(self, node: str, status: str, message: str = "") -> None:
        super()._gying_mark_node(node, status, message)
        status = str(status or "")
        if status and status != "ok":
            self._gying_obs_log("WARNING", "节点状态：节点=%s 状态=%s 信息=%s", self._gying_node_label(node), status, str(message or "")[:200] or "-")
            self._gying_obs_record("node", success=False, node=node, message=f"{status}: {str(message or '')[:220]}")

    def _viewing_session(self) -> Tuple[Any, Dict[str, Any]]:
        if not bool(getattr(self, "_viewing_enabled", False)):
            self._gying_obs_log("INFO", "会话检查跳过：观影未启用")
        started = time.monotonic()
        try:
            session, status = super()._viewing_session()
        except Exception as err:
            self._gying_obs_log("WARNING", "会话建立异常：%s", str(err)[:240])
            self._gying_obs_record("session", success=False, message=str(err))
            raise
        status = dict(status or {})
        ok = bool(status.get("success"))
        node = str(status.get("node") or "")
        mode = str(status.get("mode") or "")
        message = str(status.get("message") or "")[:240]
        self._gying_obs_log(
            "INFO" if ok else "WARNING",
            "会话结果：成功=%s 节点=%s 模式=%s 耗时=%.2fs 信息=%s",
            ok,
            self._gying_node_label(node),
            mode or "-",
            time.monotonic() - started,
            message or "-",
        )
        self._gying_obs_record("session", success=ok, node=node, message=message or ("会话可用" if ok else "会话不可用"), mode=mode)
        return session, status

    def _gying_detail(self, session, node: str, resource_type: str, resource_id: str, referer: str) -> Dict[str, Any]:
        try:
            payload = dict(super()._gying_detail(session, node, resource_type, resource_id, referer) or {})
        except Exception as err:
            self._gying_obs_log("WARNING", "downurl失败：节点=%s 类型=%s 错误=%s", self._gying_node_label(node), str(resource_type or "-")[:24], str(err)[:220])
            raise
        panlist = _extract_panlist(payload)
        count = len(list(panlist.get("url") or []))
        self._gying_obs_log("INFO", "downurl成功：节点=%s 类型=%s 资源链接=%s", self._gying_node_label(node), str(resource_type or "-")[:24], count)
        return payload

    def _gying_raw_results(self, keyword: str, force: bool = False):
        clean_keyword = " ".join(str(keyword or "").split())[:120]
        started = time.monotonic()
        self._gying_obs_log("INFO", "搜索开始：关键词=%s 强制刷新=%s", clean_keyword or "-", bool(force))
        try:
            rows, state = super()._gying_raw_results(keyword, force=force)
        except Exception as err:
            self._gying_obs_log("WARNING", "搜索异常：关键词=%s 错误=%s", clean_keyword or "-", str(err)[:240])
            self._gying_obs_record("search", success=False, message=str(err))
            raise
        state = dict(state or {})
        ok = bool(state.get("success"))
        node = str(state.get("node") or "")
        cards = int(state.get("cards") or 0)
        resources = len(rows or [])
        message = str(state.get("message") or "")[:240]
        self._gying_obs_log(
            "INFO" if ok else "WARNING",
            "搜索结果：成功=%s 节点=%s 影视卡片=%s 原始资源=%s 耗时=%.2fs 信息=%s",
            ok,
            self._gying_node_label(node),
            cards,
            resources,
            time.monotonic() - started,
            message or "-",
        )
        self._gying_obs_record("search", success=ok, node=node, message=message, cards=cards, resources=resources, mode=str(state.get("login_mode") or ""))
        return rows, state

    def _search_viewing(self, keyword: str):
        rows, state = super()._search_viewing(keyword)
        magnet = sum(1 for row in rows or [] if str((row or {}).get("type") or "") == "magnet")
        ed2k = sum(1 for row in rows or [] if str((row or {}).get("type") or "") == "ed2k")
        self._gying_obs_log("INFO", "候选提取：Magnet=%s ED2K=%s", magnet, ed2k)
        self._gying_obs_record("candidates", success=bool((state or {}).get("success")), node=str((state or {}).get("node") or ""), message=f"Magnet {magnet} · ED2K {ed2k}", magnet=magnet, ed2k=ed2k)
        return rows, state

    def _search_viewing_xunlei(self, keyword: str):
        rows, state = super()._search_viewing_xunlei(keyword)
        count = len(rows or [])
        self._gying_obs_log("INFO", "迅雷候选提取：数量=%s", count)
        self._gying_obs_record("xunlei", success=bool((state or {}).get("success")), node=str((state or {}).get("node") or ""), message=f"迅雷候选 {count}", xunlei=count)
        return rows, state

    def api_viewing_nodes_refresh(self) -> Dict[str, Any]:
        self._gying_obs_log("INFO", "人工操作：刷新观影节点")
        result = dict(super().api_viewing_nodes_refresh() or {})
        self._gying_obs_log("INFO" if result.get("success") else "WARNING", "节点刷新结果：成功=%s 当前节点=%s 候选=%s 信息=%s", bool(result.get("success")), self._gying_node_label(result.get("active_node")), int(result.get("count") or 0), str(result.get("message") or "")[:200] or "-")
        return result

    def api_viewing_session_test(self, keyword: str = "") -> Dict[str, Any]:
        self._gying_obs_log("INFO", "人工操作：测试观影会话%s", "并搜索" if str(keyword or "").strip() else "")
        try:
            result = dict(super().api_viewing_session_test(keyword=keyword) or {})
        except TypeError:
            result = dict(super().api_viewing_session_test(keyword) or {})
        ok = bool(result.get("success"))
        node = str(result.get("node") or "")
        message = str(result.get("message") or "")[:240]
        self._gying_obs_log("INFO" if ok else "WARNING", "人工测试结果：成功=%s 节点=%s 模式=%s cards=%s resources=%s 信息=%s", ok, self._gying_node_label(node), str(result.get("mode") or "-")[:40], int(result.get("cards") or 0), int(result.get("resources") or 0), message or "-")
        self._gying_obs_record("test", success=ok, node=node, message=message or ("测试通过" if ok else "测试失败"), mode=str(result.get("mode") or ""), cards=int(result.get("cards") or 0), resources=int(result.get("resources") or 0))
        return result


__all__ = ["GuangYaGyingObservabilityV1104Mixin"]
