"""v1.9.3 迅雷分享秒传完整性收口。

参考用户提供的迅雷->光鸭秒传脚本补齐真实运行中最容易失败的两层：
- captcha_token 与 device/client 是一组运行时身份；没有可复用 token 时尝试 shield/captcha/init；
- 新版 share/detail 可能隐藏 hash，file_info 不可用时用同 parent_id 的 detail(with_audit=false) 补 GCID。

匿名分享接口始终不携带 Authorization；只取得分享元数据/少量 CID 样本并尝试光鸭秒传，
不增加 OSS PUT、本地整文件中转或 MoviePilot 下载器路径。
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from typing import Any, Dict, Optional

from .xunlei_flash_v193 import XUNLEI_CAPTCHA_INIT, XUNLEI_DEFAULT_CLIENT_ID


XUNLEI_BROWSER_CLIENT_ID = "ZUBzD9J_XPXfn7f7"
XUNLEI_BROWSER_CLIENT_VERSION = "1.10.0.2633"
XUNLEI_BROWSER_PACKAGE = "com.xunlei.browser"
XUNLEI_BROWSER_REDIRECT = "xlaccsdk01://xunlei.com/callback?state=harbor"
_XUNLEI_CAPTCHA_SALTS = (
    "uWRwO7gPfdPB/0NfPtfQO+71",
    "F93x+qPluYy6jdgNpq+lwdH1ap6WOM+nfz8/V",
    "0HbpxvpXFsBK5CoTKam",
    "dQhzbhzFRcawnsZqRETT9AuPAJ+wTQso82mRv",
    "SAH98AmLZLRa6DB2u68sGhyiDh15guJpXhBzI",
    "unqfo7Z64Rie9RNHMOB",
    "7yxUdFADp3DOBvXdz0DPuKNVT35wqa5z0DEyEvf",
    "RBG",
    "ThTWPG5eC0UBqlbQ+04nZAptqGCdpv9o55A",
)


def build_xunlei_captcha_signature(
    client_id: str,
    client_version: str,
    package_name: str,
    device_id: str,
    timestamp_ms: Optional[int] = None,
) -> tuple[str, str]:
    """复现迅雷浏览器 captcha_sign：连续九轮 MD5，便于无浏览器环境初始化 token。"""
    timestamp = str(int(timestamp_ms if timestamp_ms is not None else time.time() * 1000))
    content = f"{client_id}{client_version}{package_name}{device_id}{timestamp}"
    for salt in _XUNLEI_CAPTCHA_SALTS:
        content = hashlib.md5((content + salt).encode("utf-8")).hexdigest()  # noqa: S324 - 协议签名，不用于密码学安全
    return timestamp, "1." + content


class GuangYaXunleiHardeningMixin:
    """最终迅雷分享身份、captcha 初始化与 hash 回退层。"""

    build_id = "20260901-r8"
    _xunlei_runtime_client_id = ""
    _xunlei_runtime_device_id = ""
    _xunlei_captcha_status: Dict[str, Any] = {}

    def init_plugin(self, config: dict = None) -> None:
        config = dict(config or {})
        super().init_plugin(config)
        self._xunlei_runtime_client_id = str(getattr(self, "_xunlei_client_id", "") or XUNLEI_DEFAULT_CLIENT_ID).strip()
        self._xunlei_captcha_status = {}

        configured_device = str(getattr(self, "_xunlei_device_id", "") or "").strip()
        if not configured_device:
            try:
                init_payload = json.loads(str(getattr(self, "_xunlei_captcha_init_json", "") or "{}"))
                if isinstance(init_payload, dict):
                    configured_device = str(init_payload.get("device_id") or "").strip()
            except Exception:
                pass

        state = self.get_data("xunlei_runtime_state") or {}
        if not isinstance(state, dict):
            state = {}
        persisted_device = str(state.get("device_id") or "").strip()
        if configured_device:
            runtime_device = configured_device
        elif persisted_device:
            runtime_device = persisted_device
        else:
            runtime_device = secrets.token_hex(16)
        self._xunlei_runtime_device_id = runtime_device
        state.update({"schema": 1, "device_id": runtime_device, "updated_at": self._now_text()})
        self.save_data("xunlei_runtime_state", state)

        # 手工 captcha_token 通常与浏览器 device_id 绑定。没有对应 device 时不要带着一个随机
        # device 去请求；改为清空运行态 token，让下方自动初始化创建一对一致的身份。
        if str(getattr(self, "_xunlei_captcha_token", "") or "").strip() and not configured_device:
            self._xunlei_runtime_captcha_token = ""
            self._xunlei_captcha_status = {
                "mode": "manual_token_missing_device",
                "success": False,
                "message": "已填写迅雷 captcha_token 但没有对应 Device ID，运行时将优先尝试自动初始化",
            }

    def _xunlei_runtime_state_save(self, **values: Any) -> None:
        state = self.get_data("xunlei_runtime_state") or {}
        if not isinstance(state, dict):
            state = {}
        state.update({"schema": 1, "device_id": self._xunlei_runtime_device_id, "updated_at": self._now_text(), **values})
        # 这里只保存诊断和稳定 device；captcha_token 本身不写进公开状态数据。
        state.pop("captcha_token", None)
        self.save_data("xunlei_runtime_state", state)

    def _refresh_xunlei_captcha(self, action: str) -> str:
        # 用户从浏览器复制的 init 请求体最贴近实际浏览器，优先复用父实现。
        if str(getattr(self, "_xunlei_captcha_init_json", "") or "").strip():
            token = str(super()._refresh_xunlei_captcha(action) or "").strip()
            if token:
                self._xunlei_runtime_client_id = str(getattr(self, "_xunlei_client_id", "") or XUNLEI_DEFAULT_CLIENT_ID)
                self._xunlei_captcha_status = {"mode": "configured_init", "success": True, "message": "迅雷 captcha_token 已从配置请求体刷新"}
                self._xunlei_runtime_state_save(captcha_mode="configured_init", captcha_ok=True)
                return token

        # 无浏览器环境下使用公开迅雷浏览器 profile 生成 captcha_sign。先试插件配置 client，
        # 再试已验证可用于匿名分享检查的浏览器 client；成功后后续请求必须沿用同一 client/device。
        profiles = []
        configured_client = str(getattr(self, "_xunlei_client_id", "") or XUNLEI_DEFAULT_CLIENT_ID).strip()
        if configured_client:
            profiles.append(configured_client)
        if XUNLEI_BROWSER_CLIENT_ID not in profiles:
            profiles.append(XUNLEI_BROWSER_CLIENT_ID)

        session = self._xunlei_session()
        last_error = ""
        for client_id in profiles:
            timestamp, signature = build_xunlei_captcha_signature(
                client_id,
                XUNLEI_BROWSER_CLIENT_VERSION,
                XUNLEI_BROWSER_PACKAGE,
                self._xunlei_runtime_device_id,
            )
            payload = {
                "action": str(action or "get:/drive/v1/share"),
                "captcha_token": "",
                "client_id": client_id,
                "device_id": self._xunlei_runtime_device_id,
                "meta": {
                    "timestamp": timestamp,
                    "captcha_sign": signature,
                    "client_version": XUNLEI_BROWSER_CLIENT_VERSION,
                    "package_name": XUNLEI_BROWSER_PACKAGE,
                },
                "redirect_uri": XUNLEI_BROWSER_REDIRECT,
            }
            try:
                response = session.post(
                    XUNLEI_CAPTCHA_INIT,
                    json=payload,
                    headers={
                        "Accept": "application/json;charset=UTF-8",
                        "Content-Type": "application/json",
                        "x-device-id": self._xunlei_runtime_device_id,
                        "x-client-id": client_id,
                        "x-client-version": XUNLEI_BROWSER_CLIENT_VERSION,
                    },
                    timeout=int(getattr(self, "_provider_timeout", 15) or 15),
                )
                body = response.json() if response.content else {}
                token = str((body or {}).get("captcha_token") or "").strip() if isinstance(body, dict) else ""
                verify_url = str((body or {}).get("url") or "").strip() if isinstance(body, dict) else ""
                if token:
                    self._xunlei_runtime_captcha_token = token
                    self._xunlei_runtime_client_id = client_id
                    self._xunlei_captcha_status = {"mode": "signed_init", "success": True, "message": "迅雷 captcha_token 自动初始化成功"}
                    self._xunlei_runtime_state_save(captcha_mode="signed_init", captcha_ok=True, client_profile=client_id)
                    return token
                if verify_url:
                    last_error = "迅雷 captcha/init 要求额外人工验证"
                else:
                    last_error = str((body or {}).get("error_description") or (body or {}).get("error") or f"HTTP {response.status_code}")[:240]
            except Exception as err:
                last_error = str(err)[:240]

        self._xunlei_captcha_status = {"mode": "signed_init", "success": False, "message": last_error or "迅雷 captcha_token 自动初始化失败"}
        self._xunlei_runtime_state_save(captcha_mode="signed_init", captcha_ok=False, captcha_error=last_error[:240])
        return ""

    def _xunlei_headers(self, action: str, *, refresh: bool = False) -> Dict[str, str]:
        token = "" if refresh else str(getattr(self, "_xunlei_runtime_captcha_token", "") or "").strip()
        configured_token = str(getattr(self, "_xunlei_captcha_token", "") or "").strip()
        configured_device = str(getattr(self, "_xunlei_device_id", "") or "").strip()
        if not token and configured_token and configured_device:
            token = configured_token
            self._xunlei_runtime_client_id = str(getattr(self, "_xunlei_client_id", "") or XUNLEI_DEFAULT_CLIENT_ID)
        if not token:
            token = self._refresh_xunlei_captcha(action)

        headers = {
            "Accept": "application/json;charset=UTF-8",
            "Content-Type": "application/json",
            "x-client-id": str(self._xunlei_runtime_client_id or getattr(self, "_xunlei_client_id", "") or XUNLEI_DEFAULT_CLIENT_ID),
            "x-device-id": str(self._xunlei_runtime_device_id or configured_device),
            "x-guid": str(self._xunlei_runtime_device_id or configured_device),
            "x-client-version": XUNLEI_BROWSER_CLIENT_VERSION,
            "Referer": "https://pan.xunlei.com/",
        }
        if token:
            headers["x-captcha-token"] = token
        # 分享链接采用匿名接口，绝不能把用户自己的迅雷 Bearer 带到他人分享请求。
        headers.pop("Authorization", None)
        headers.pop("authorization", None)
        return headers

    @staticmethod
    def _merge_xunlei_file(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(base or {})
        for key in ("gcid", "md5", "cid", "download_url", "size", "name", "path", "parent_id"):
            value = extra.get(key)
            if value not in (None, "", 0):
                merged[key] = value
        return merged

    def _xunlei_detail_hash_fallback(self, share_id: str, pass_code_token: str, row: Dict[str, Any]) -> Dict[str, Any]:
        """参考脚本：同 parent_id 再查 with_audit=false，按 file id 精确补 hash。"""
        file_id = str(row.get("id") or "").strip()
        if not file_id:
            return row
        parent_id = str(row.get("parent_id") or "").strip()
        try:
            body = self._xunlei_get(
                "/drive/v1/share/detail",
                {
                    "share_id": share_id,
                    "parent_id": parent_id,
                    "pass_code_token": pass_code_token,
                    "limit": 200,
                    "with_audit": "false",
                    "usage": "CONSUME",
                },
                action="get:/drive/v1/share/detail",
            )
        except Exception:
            return row
        files = body.get("files") or (body.get("data") or {}).get("files") or []
        if not isinstance(files, list):
            return row
        prefix = str(row.get("path") or "").rsplit("/", 1)[0]
        for raw in files:
            if not isinstance(raw, dict) or str(raw.get("id") or raw.get("file_id") or "") != file_id:
                continue
            normalized = self._xunlei_normalize_file(raw, prefix, parent_id)
            return self._merge_xunlei_file(row, normalized)
        return row

    def _xunlei_file_info(self, share_id: str, pass_code_token: str, row: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(row or {})
        try:
            result = dict(super()._xunlei_file_info(share_id, pass_code_token, result) or result)
        except Exception:
            pass
        if not str(result.get("gcid") or "").strip():
            result = self._xunlei_detail_hash_fallback(share_id, pass_code_token, result)
        return result

    def api_xunlei_runtime_status(self) -> Dict[str, Any]:
        status = dict(self._xunlei_captcha_status or {})
        return {
            "success": True,
            "data": {
                "flash_enabled": bool(getattr(self, "_xunlei_flash_enabled", True)),
                "captcha_ready": bool(getattr(self, "_xunlei_runtime_captcha_token", "")),
                "captcha_mode": str(status.get("mode") or "not_initialized"),
                "captcha_ok": bool(status.get("success")),
                "message": str(status.get("message") or "")[:240],
                "device_ready": bool(self._xunlei_runtime_device_id),
            },
        }

    def get_api(self):
        apis = list(super().get_api() or [])
        if not any(str(item.get("path") or "") == "/xunlei/runtime/status" for item in apis if isinstance(item, dict)):
            apis.append({
                "path": "/xunlei/runtime/status",
                "endpoint": self.api_xunlei_runtime_status,
                "methods": ["GET"],
                "summary": "查看迅雷秒传运行时状态",
            })
        return apis


__all__ = ["GuangYaXunleiHardeningMixin", "build_xunlei_captcha_signature"]
