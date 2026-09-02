"""v1.10.10 对齐 PanSou 的 GYING 挑战与重试语义。

这一层针对 v1.10.9 线上出现的“PoW 未被服务器确认”做收口：

- 挑战识别按 PanSou 当前公开实现收紧：必须同时出现验证文案和真实 PoW/worker
  特征，或存在内嵌 ``const json={...}; const jss=...``；正常 ``_obj.`` 页面优先放行。
- ``refresh=1`` 是观影网页自己的动态 overlay 中间件协议，不能直接等价成远程
  ``/res/pow``。遇到它时先回到同节点根页建立/恢复 ``browser_pow`` 挑战，再按
  PanSou 的挑战页流程计算，之后重试原请求。
- 远程 PoW 完全按 PanSou 公开协议：GET ``/res/pow`` 取 N/x/t，计算至少 3 秒，
  POST form ``y=<hex>``，响应必须 ``success=true``，随后由“原请求重试成功”作为
  最终验证依据。
- 不主动删除 ``browser_pow``；Cookie 生命周期交给服务端 Set-Cookie/cookie jar，
  与 PanSou 的 cloudscraper 行为一致。

不执行远端 overlay JavaScript，不使用 OCR/浏览器自动化，也不记录 Cookie、PoW 参数、
验证码或账号密码。
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

import requests

from .gying_hardening_v193 import canonical_gying_node
from .gying_runtime_v193 import _GYING_CHALLENGE_RE, _safe_int, _solve_pow_hex


_VERIFY_TEXT_V1110 = (
    "正在确认你是不是机器人",
    "浏览器安全验证",
    "安全验证",
    "正在进行浏览器计算验证",
)
_REMOTE_SIG_V1110 = (
    "powSolve-",
    "pow.worker-",
    "const jss=",
    "/res/pow",
)
_BLOCK_MARKERS_V1110 = ("angie", "request forbidden", "access denied")


def _json_v1110(response: requests.Response) -> Dict[str, Any]:
    try:
        data = response.json()
    except Exception:
        try:
            data = json.loads(str(getattr(response, "text", "") or "{}"))
        except Exception:
            data = {}
    return data if isinstance(data, dict) else {}


def _challenge_kind_v1110(response: requests.Response) -> str:
    """返回 embedded_pow / legacy_hash / remote_pow / refresh_overlay / 空字符串。"""
    text = str(getattr(response, "text", "") or "")
    # 数据页里可能引用验证静态资源；PanSou 的核心经验是不能因此误判。
    if "_obj." in text:
        return ""

    match = _GYING_CHALLENGE_RE.search(text)
    if match:
        try:
            data = json.loads(match.group(1))
        except Exception:
            data = {}
        if isinstance(data, dict):
            if data.get("id") and data.get("N") and data.get("x") and _safe_int(data.get("t"), 0) > 0:
                return "embedded_pow"
            if data.get("id") and data.get("challenge") and data.get("salt") is not None and _safe_int(data.get("diff"), 0) > 0:
                return "legacy_hash"

    has_verify_text = any(token in text for token in _VERIFY_TEXT_V1110)
    if has_verify_text and any(token in text for token in _REMOTE_SIG_V1110):
        return "remote_pow"

    payload = _json_v1110(response)
    try:
        refresh = int(payload.get("refresh") or 0) == 1
    except (TypeError, ValueError):
        refresh = False
    if refresh:
        # 真实网页由 refreshMiddleware -> data.overlay -> PowOverlay.run(data) 处理。
        # 它不是“看到 refresh 就 POST /res/pow”的同义词。
        return "refresh_overlay"
    return ""


def _truthy_success_v1110(value: Any) -> bool:
    return value in (True, 1, "1", "true", "True")


class GuangYaGyingPanSouV1110Mixin:
    """最外层观影请求覆盖：复刻 PanSou 已验证的 challenge -> solve -> retry 模型。"""

    build_id = "20260902-r21"

    def _gying_solve_challenge_v1110(
        self,
        session: requests.Session,
        node: str,
        response: requests.Response,
        kind: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not bool(getattr(self, "_viewing_auto_challenge", True)):
            raise RuntimeError("观影返回浏览器安全验证；自动计算验证已关闭")

        kind = str(kind or _challenge_kind_v1110(response) or "")
        node = canonical_gying_node(node) or str(node or "").rstrip("/")
        if not node:
            raise RuntimeError("观影 PoW 节点无效")

        if kind in {"embedded_pow", "legacy_hash"}:
            # 旧运行时已经正确实现 action=verify/id/y 与 nonce[]，继续复用。
            result = dict(super()._gying_solve_challenge(session, node, response) or {})
            sync_cookie = getattr(self, "_gying_sync_cookie_v1108", None)
            if callable(sync_cookie):
                try:
                    sync_cookie(session, node)
                except Exception:
                    pass
            return result

        if kind != "remote_pow":
            raise RuntimeError("观影当前响应不是可直接提交 /res/pow 的挑战页")

        timeout = min(max(int(getattr(self, "_provider_timeout", 15) or 15), 5), 20)
        pow_url = node.rstrip("/") + "/res/pow"
        started = time.monotonic()
        has_pow_cookie = any(str(getattr(item, "name", "") or "") == "browser_pow" for item in session.cookies)
        self._gying_auth_log(
            "INFO",
            "PanSou PoW：节点=%s，挑战页已确认，browser_pow=%s，开始读取参数",
            node,
            bool(has_pow_cookie),
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
        y = _solve_pow_hex(str(data.get("N")), str(data.get("x")), _safe_int(data.get("t"), 0))
        elapsed = time.monotonic() - started
        if elapsed < 3.0:
            time.sleep(3.0 - elapsed)

        # PanSou submitChallengeVerification 只提交 form，不主动清理 browser_pow。
        verified = session.post(
            pow_url,
            data={"y": y},
            headers={"Referer": str(getattr(response, "url", "") or node + "/")},
            timeout=timeout + 15,
            allow_redirects=True,
        )
        if callable(sync_cookie):
            try:
                sync_cookie(session, node)
            except Exception:
                pass
        result = _json_v1110(verified)
        if int(getattr(verified, "status_code", 0) or 0) >= 400 or not _truthy_success_v1110(result.get("success")):
            message = str(result.get("msg") or result.get("message") or "").strip()[:120]
            suffix = f"：{message}" if message else ""
            raise RuntimeError(
                f"观影 PoW 未被服务器确认：HTTP {int(getattr(verified, 'status_code', 0) or 0)}{suffix}"
            )

        has_verified_cookie = any(
            str(getattr(item, "name", "") or "") == "browser_verified" for item in session.cookies
        )
        self._gying_auth_log(
            "INFO",
            "PanSou PoW：服务器已确认提交，节点=%s browser_verified=%s，准备重试原请求",
            node,
            bool(has_verified_cookie),
        )
        return {
            "mode": "remote_pow_pansou",
            "success": True,
            "challenge_id_present": bool(str(result.get("challenge_id") or "")),
        }

    def _gying_refresh_bootstrap_v1110(
        self,
        session: requests.Session,
        node: str,
        response: requests.Response,
        timeout: int,
    ) -> bool:
        """把网页 refresh=1 转回可验证的根页 challenge，而不是误投 /res/pow。"""
        node = canonical_gying_node(node) or str(node or "").rstrip("/")
        payload = _json_v1110(response)
        self._gying_auth_log(
            "INFO",
            "PanSou PoW：收到网页 refresh=1，先回根页建立挑战；overlay=%s",
            bool(str(payload.get("overlay") or "")),
        )
        bootstrap = session.get(
            node.rstrip("/") + "/",
            timeout=timeout,
            allow_redirects=True,
            headers={"Accept": "text/html,*/*"},
        )
        sync_cookie = getattr(self, "_gying_sync_cookie_v1108", None)
        if callable(sync_cookie):
            try:
                sync_cookie(session, node)
            except Exception:
                pass
        kind = _challenge_kind_v1110(bootstrap)
        if kind in {"embedded_pow", "legacy_hash", "remote_pow"}:
            self._gying_solve_challenge_v1110(session, node, bootstrap, kind=kind)
            return True
        if any(str(getattr(item, "name", "") or "") == "browser_verified" for item in session.cookies):
            return True
        # 根页没有 challenge 时仍允许原请求再试一次；若仍 refresh，外层会明确失败。
        return int(getattr(bootstrap, "status_code", 0) or 0) < 400

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
        timeout = int(kwargs.pop("timeout", int(getattr(self, "_provider_timeout", 15) or 15)) or 15)
        attempts = 2 if retry_challenge else 1
        solved_kind = ""
        for attempt in range(attempts):
            response = session.request(
                str(method or "GET").upper(),
                url,
                timeout=timeout,
                allow_redirects=True,
                **kwargs,
            )
            sync_cookie = getattr(self, "_gying_sync_cookie_v1108", None)
            if callable(sync_cookie):
                try:
                    sync_cookie(session, node)
                except Exception:
                    pass

            text = str(getattr(response, "text", "") or "")
            lowered = text.lower()
            if int(getattr(response, "status_code", 0) or 0) in {403, 404} and any(
                marker in lowered for marker in _BLOCK_MARKERS_V1110
            ):
                raise RuntimeError(f"观影节点当前出口被阻断：HTTP {response.status_code}")

            kind = _challenge_kind_v1110(response)
            if not kind:
                if solved_kind:
                    self._gying_auth_log(
                        "INFO",
                        "PanSou PoW：原请求重试成功，节点=%s 类型=%s",
                        canonical_gying_node(node) or str(node or ""),
                        solved_kind,
                    )
                return response

            if not retry_challenge or attempt + 1 >= attempts:
                if kind == "refresh_overlay":
                    raise RuntimeError("观影动态 refresh 验证重试后仍未恢复")
                raise RuntimeError("观影机器人验证完成后原请求仍返回挑战页")

            if kind == "refresh_overlay":
                solved_kind = "refresh_overlay"
                if not self._gying_refresh_bootstrap_v1110(session, node, response, timeout):
                    raise RuntimeError("观影动态 refresh 验证无法建立 browser_pow 挑战")
                continue

            solved_kind = kind
            self._gying_solve_challenge_v1110(session, node, response, kind=kind)

        raise RuntimeError("观影请求重试次数已耗尽")


__all__ = ["GuangYaGyingPanSouV1110Mixin", "_challenge_kind_v1110"]
