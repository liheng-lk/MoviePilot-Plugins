"""v1.10.11 修复真实 GYING 远程 PoW 提交时序与验真策略。

真实日志表明 v1.10.10 在 ``POST /res/pow`` 返回 HTTP 200 时仍会直接判定
“未被服务器确认”。复核 PanSou 当前实现后确认两个兼容点：

1. 最少 3 秒的计时必须从拿到 N/x/t 后、真正开始平方取模计算时开始，而不能把
   ``GET /res/pow`` 的网络耗时算进 3 秒窗口；
2. PoW 是否最终通过，应以“同一 Session 重试原请求后不再返回 challenge”为最终依据。
   ``success=true`` / ``browser_verified`` 是强确认信号，但 HTTP 200 且响应体字段漂移时
   不能在重试原请求之前提前判死刑。

本层还把真正参与内容请求的节点收敛到已确认的 IDN 内容镜像，发布页/换址页仍可用于
发现地址，但不再进入每次搜索的 12 节点慢轮询。

本版本不要求、也不主动建议为观影配置代理；网络可直连时直接使用 MoviePilot 当前网络出口。
不会记录 Cookie、N/x/y、账号密码或验证码坐标；人工汉字验证码行为保持不变。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

from .gying_hardening_v193 import canonical_gying_node
from .gying_pansou_v1110 import (
    GuangYaGyingPanSouV1110Mixin,
    _challenge_kind_v1110,
    _json_v1110,
    _truthy_success_v1110,
)
from .gying_runtime_v193 import _safe_int, _solve_pow_hex
from .gying_transport_v1108 import _GYING_MIRRORS_V1108


_MIN_REMOTE_POW_SECONDS_V1111 = 3.15
_MAX_CONTENT_NODES_V1111 = 10


def _has_cookie_v1111(session: requests.Session, name: str) -> bool:
    target = str(name or "").lower()
    return any(
        str(getattr(cookie, "name", "") or "").lower() == target
        and bool(str(getattr(cookie, "value", "") or ""))
        for cookie in list(session.cookies)
    )


def _is_content_candidate_v1111(node: str) -> bool:
    """内容节点目前均为 IDN/punycode 镜像；gying/gyg 仅作为发布/换址入口。"""
    canonical = canonical_gying_node(node)
    if not canonical:
        return False
    host = str(urlparse(canonical).hostname or "").lower()
    if not host:
        return False
    return host.startswith("xn--") or ".xn--" in host


class GuangYaGyingPowV1111Mixin(GuangYaGyingPanSouV1110Mixin):
    """PanSou 链路补丁：正确计时、原请求最终验真、内容节点收敛。"""

    build_id = "20260902-r22"

    def _discover_gying_nodes(self, force: bool = False) -> List[str]:
        """只把真实内容镜像交给 failover；发布页仍由旧发现层负责刷新缓存。"""
        state: Dict[str, Any]
        try:
            state = dict(self._gying_state() or {})
        except Exception:
            state = {}

        candidates: List[str] = []
        for raw in (
            str(state.get("active_node") or ""),
            str(getattr(self, "_gying_active_node", "") or ""),
            str(getattr(self, "_viewing_base_url", "") or ""),
        ):
            node = canonical_gying_node(raw)
            if node and _is_content_candidate_v1111(node):
                candidates.append(node)

        for raw in list(state.get("discovered_nodes") or []):
            node = canonical_gying_node(str(raw or ""))
            if node and _is_content_candidate_v1111(node):
                candidates.append(node)

        # 强制刷新时才调用旧发现层访问发布页；普通搜索不再每次轮询发布域名。
        if force:
            try:
                for raw in list(super()._discover_gying_nodes(force=True) or []):
                    node = canonical_gying_node(str(raw or ""))
                    if node and _is_content_candidate_v1111(node):
                        candidates.append(node)
            except Exception:
                pass

        for raw in _GYING_MIRRORS_V1108:
            node = canonical_gying_node(raw)
            if node and _is_content_candidate_v1111(node):
                candidates.append(node)

        output: List[str] = []
        seen = set()
        for node in candidates:
            if node in seen:
                continue
            seen.add(node)
            output.append(node)
            if len(output) >= _MAX_CONTENT_NODES_V1111:
                break
        return output

    def _gying_solve_challenge_v1110(
        self,
        session: requests.Session,
        node: str,
        response: requests.Response,
        kind: Optional[str] = None,
    ) -> Dict[str, Any]:
        """修复 remote_pow；内嵌/legacy 继续复用 v1.10.10。"""
        kind = str(kind or _challenge_kind_v1110(response) or "")
        if kind != "remote_pow":
            return dict(super()._gying_solve_challenge_v1110(session, node, response, kind=kind) or {})

        if not bool(getattr(self, "_viewing_auto_challenge", True)):
            raise RuntimeError("观影返回浏览器安全验证；自动计算验证已关闭")

        node = canonical_gying_node(node) or str(node or "").rstrip("/")
        if not node:
            raise RuntimeError("观影 PoW 节点无效")

        timeout = min(max(int(getattr(self, "_provider_timeout", 15) or 15), 5), 20)
        pow_url = node.rstrip("/") + "/res/pow"
        self._gying_auth_log(
            "INFO",
            "PanSou PoW：节点=%s，挑战页已确认，browser_pow=%s，开始读取参数",
            node,
            _has_cookie_v1111(session, "browser_pow"),
        )

        challenge = session.get(
            pow_url,
            headers={"Referer": str(getattr(response, "url", "") or node + "/")},
            timeout=timeout,
            allow_redirects=True,
        )
        sync_cookie = getattr(self, "_gying_sync_cookie_v1108", None)
        if callable(sync_cookie):
            try:
                sync_cookie(session, node)
            except Exception:
                pass
        if int(getattr(challenge, "status_code", 0) or 0) != 200:
            raise RuntimeError(f"观影获取 PoW 参数失败：HTTP {int(getattr(challenge, 'status_code', 0) or 0)}")

        data = _json_v1110(challenge)
        if not data.get("N") or not data.get("x") or _safe_int(data.get("t"), 0) <= 0:
            raise RuntimeError("观影 PoW 参数无效")

        # PanSou 从真正开始 bigint 迭代时计时。网络 GET 耗时不能算入服务器要求的最短计算窗口。
        solve_started = time.monotonic()
        y = _solve_pow_hex(str(data.get("N")), str(data.get("x")), _safe_int(data.get("t"), 0))
        solve_elapsed = time.monotonic() - solve_started
        if solve_elapsed < _MIN_REMOTE_POW_SECONDS_V1111:
            time.sleep(_MIN_REMOTE_POW_SECONDS_V1111 - solve_elapsed)

        verified = session.post(
            pow_url,
            data={"y": y},
            headers={
                "Origin": node,
                "Referer": str(getattr(response, "url", "") or node + "/"),
                "Accept": "application/json,text/plain,*/*",
            },
            timeout=timeout + 15,
            allow_redirects=True,
        )
        if callable(sync_cookie):
            try:
                sync_cookie(session, node)
            except Exception:
                pass

        status = int(getattr(verified, "status_code", 0) or 0)
        if status >= 400:
            raise RuntimeError(f"观影 PoW 提交失败：HTTP {status}")

        result = _json_v1110(verified)
        success_value = result.get("success") if "success" in result else None
        code_value = result.get("code") if "code" in result else None
        try:
            code_ok = int(code_value) == 200
        except (TypeError, ValueError):
            code_ok = False
        server_ack = (
            _truthy_success_v1110(success_value)
            or code_ok
            or _has_cookie_v1111(session, "browser_verified")
        )

        # 真实环境已有 HTTP 200 但 JSON 字段与文档不一致的情况。
        # 不在这里提前判死刑，最终由 _gying_request 对原请求的重试结果判定验证是否真正通过。
        if server_ack:
            self._gying_auth_log(
                "INFO",
                "PanSou PoW：提交已取得确认信号，节点=%s browser_verified=%s，准备重试原请求",
                node,
                _has_cookie_v1111(session, "browser_verified"),
            )
        else:
            message = str(result.get("msg") or result.get("message") or "").strip()
            self._gying_auth_log(
                "WARNING",
                "PanSou PoW：提交 HTTP 200 但未给出明确确认字段，节点=%s 响应提示=%s；继续以原请求验真",
                node,
                message[:80] if message else "无",
            )

        return {
            "mode": "remote_pow_pansou_v1111",
            "success": True,
            "server_ack": bool(server_ack),
            "browser_verified": _has_cookie_v1111(session, "browser_verified"),
        }

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
        """不改变网络出口；仅复用下层 PoW/原请求验真状态机。"""
        return super()._gying_request(
            session,
            node,
            method,
            url,
            retry_challenge=retry_challenge,
            **kwargs,
        )


__all__ = ["GuangYaGyingPowV1111Mixin", "_has_cookie_v1111", "_is_content_candidate_v1111"]
