"""115 网盘助手 MoviePilot V3 插件入口。

首轮提供稳定登录态、二维码登录、目录浏览与基础文件操作 API；MoviePilot
StorageChain 合同将在同分支继续补齐。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.plugins import _PluginBase
from app.sdk.logging import logger

from .auth import QrToken, create_qr_token, exchange_qr_cookie, extract_cookie, poll_qr_status
from .models import P115Item
from .p115_client import P115ClientConfig, P115Gateway


class P115Disk(_PluginBase):
    plugin_name = "115网盘助手"
    plugin_desc = "MoviePilot V3 115网盘助手，支持扫码登录、目录浏览、文件操作和115转存底层能力。"
    plugin_icon = ""
    plugin_version = "0.1.1"
    plugin_author = "liheng-lk"
    author_url = "https://github.com/liheng-lk/MoviePilot-Plugins"
    plugin_config_prefix = "p115disk_"
    plugin_order = 20
    auth_level = 2

    QR_DATA_KEY = "p115_qr_login_v1"

    _enabled: bool = False
    _cookies: str = ""
    _cookies_file: str = ""
    _page_size: int = 500
    _qr_app: str = "qandroid"

    def __init__(self):
        super().__init__()
        self._gateway: Optional[P115Gateway] = None

    def init_plugin(self, config: dict = None) -> None:
        config = config or {}
        self._enabled = bool(config.get("enabled", False))
        self._cookies = str(config.get("cookies") or "").strip().rstrip(";")
        self._cookies_file = str(config.get("cookies_file") or "").strip()
        self._qr_app = str(config.get("qr_app") or "qandroid").strip() or "qandroid"
        try:
            self._page_size = max(50, min(int(config.get("page_size") or 500), 1150))
        except (TypeError, ValueError):
            self._page_size = 500
        self._gateway = None
        if not self._enabled:
            return
        if not (self._cookies or self._cookies_file):
            logger.info("【115网盘助手】尚未登录，等待扫码或 Cookie 配置")
            return
        try:
            self._gateway = P115Gateway(
                P115ClientConfig(cookies=self._cookies, cookies_file=self._cookies_file, app=self._qr_app)
            )
            logger.info("【115网盘助手】初始化完成")
        except Exception as err:
            logger.error("【115网盘助手】初始化失败: %s", err)

    def get_state(self) -> bool:
        return bool(self._enabled)

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    @staticmethod
    def get_service() -> List[Dict[str, Any]]:
        return []

    def get_form(self) -> Tuple[Optional[List[dict]], Dict[str, Any]]:
        return None, {
            "enabled": self._enabled,
            "cookies": self._cookies,
            "cookies_file": self._cookies_file,
            "page_size": self._page_size,
            "qr_app": self._qr_app,
        }

    def get_page(self) -> Optional[List[dict]]:
        return None

    def stop_service(self) -> None:
        self._gateway = None

    def _ensure_gateway(self) -> P115Gateway:
        if not self._enabled:
            raise RuntimeError("115网盘助手未启用")
        if self._gateway is None:
            self._gateway = P115Gateway(
                P115ClientConfig(
                    cookies=self._cookies,
                    cookies_file=self._cookies_file,
                    app=self._qr_app,
                )
            )
        return self._gateway

    def _current_config(self) -> Dict[str, Any]:
        return {
            "enabled": self._enabled,
            "cookies": self._cookies,
            "cookies_file": self._cookies_file,
            "page_size": self._page_size,
            "qr_app": self._qr_app,
        }

    def api_config(self) -> Dict[str, Any]:
        return {
            "success": True,
            "data": {
                "enabled": self._enabled,
                "cookies_file": self._cookies_file,
                "page_size": self._page_size,
                "qr_app": self._qr_app,
                "has_cookies": bool(self._cookies or self._cookies_file),
            },
        }

    def api_save_config(self, payload: dict) -> Dict[str, Any]:
        config = {
            "enabled": bool(payload.get("enabled", self._enabled)),
            "cookies": str(payload.get("cookies") or self._cookies or "").strip().rstrip(";"),
            "cookies_file": str(payload.get("cookies_file") or self._cookies_file or "").strip(),
            "page_size": int(payload.get("page_size") or self._page_size or 500),
            "qr_app": str(payload.get("qr_app") or self._qr_app or "qandroid").strip(),
        }
        self.update_config(config)
        self.init_plugin(config)
        return {"success": True, "message": "配置已保存", "data": self.api_config()["data"]}

    def api_qr_start(self, payload: dict = None) -> Dict[str, Any]:
        try:
            token = create_qr_token()
            app = str((payload or {}).get("app") or self._qr_app or "qandroid").strip()
            self.save_data(
                self.QR_DATA_KEY,
                {
                    "uid": token.uid,
                    "time": token.time,
                    "sign": token.sign,
                    "qrcode": token.qrcode,
                    "app": app,
                },
            )
            return {
                "success": True,
                "message": "请使用115手机APP扫码并确认登录",
                "data": {**token.public_dict(), "app": app},
            }
        except Exception as err:
            logger.exception("【115网盘助手】获取二维码失败: %s", err)
            return {"success": False, "message": str(err), "data": None}

    def api_qr_poll(self, payload: dict = None) -> Dict[str, Any]:
        try:
            saved = self.get_data(self.QR_DATA_KEY) or {}
            if not isinstance(saved, dict) or not saved.get("uid"):
                return {"success": False, "message": "没有待扫码会话，请重新获取二维码", "data": None}
            token = QrToken(
                uid=str(saved.get("uid") or ""),
                time=str(saved.get("time") or ""),
                sign=str(saved.get("sign") or ""),
                qrcode=str(saved.get("qrcode") or ""),
            )
            status_resp = poll_qr_status(token)
            status_data = status_resp.get("data") if isinstance(status_resp.get("data"), dict) else {}
            status = int(status_data.get("status") if status_data.get("status") is not None else -99)
            message = str(status_data.get("msg") or status_resp.get("message") or "")

            if status != 2:
                state_name = {
                    0: "waiting_scan",
                    1: "scanned_waiting_confirm",
                    -1: "expired",
                    -2: "canceled",
                }.get(status, "waiting")
                return {
                    "success": True,
                    "message": message or state_name,
                    "data": {"status": status, "state": state_name, "logged_in": False},
                }

            app = str((payload or {}).get("app") or saved.get("app") or self._qr_app or "qandroid").strip()
            login_resp = exchange_qr_cookie(token.uid, app=app)
            cookie = extract_cookie(login_resp)
            config = self._current_config()
            config.update({"enabled": True, "cookies": cookie, "qr_app": app})
            self.update_config(config)
            self.save_data(self.QR_DATA_KEY, {})
            self.init_plugin(config)
            return {
                "success": True,
                "message": "115扫码登录成功",
                "data": {"status": 2, "state": "logged_in", "logged_in": True, "app": app},
            }
        except Exception as err:
            logger.exception("【115网盘助手】扫码登录轮询失败: %s", err)
            return {"success": False, "message": str(err), "data": None}

    def api_status(self) -> Dict[str, Any]:
        try:
            data = self._ensure_gateway().user_info()
            return {"success": True, "data": data}
        except Exception as err:
            return {"success": False, "message": str(err), "data": None}

    @staticmethod
    def _extract_items(resp: Dict[str, Any]) -> list[dict]:
        candidates = [resp.get("data"), resp.get("files"), resp.get("list")]
        for candidate in candidates:
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, dict)]
            if isinstance(candidate, dict):
                for key in ("data", "files", "list"):
                    value = candidate.get(key)
                    if isinstance(value, list):
                        return [item for item in value if isinstance(item, dict)]
        return []

    def api_browse(self, cid: int = 0, offset: int = 0, limit: int = 0) -> Dict[str, Any]:
        try:
            resp = self._ensure_gateway().list_files(
                int(cid or 0), offset=int(offset or 0), limit=int(limit or self._page_size)
            )
            items = [P115Item.from_raw(raw) for raw in self._extract_items(resp)]
            return {
                "success": True,
                "data": [
                    {
                        "file_id": item.file_id,
                        "parent_id": item.parent_id,
                        "name": item.name,
                        "type": item.type,
                        "size": item.size,
                        "pickcode": item.pickcode,
                        "sha1": item.sha1,
                        "modify_time": item.modify_time,
                    }
                    for item in items
                ],
                "raw_count": len(items),
            }
        except Exception as err:
            logger.exception("【115网盘助手】浏览失败: %s", err)
            return {"success": False, "message": str(err), "data": []}

    def api_mkdir(self, payload: dict) -> Dict[str, Any]:
        try:
            gateway = self._ensure_gateway()
            resp = gateway.mkdir(str(payload.get("name") or "").strip(), int(payload.get("pid") or 0))
            return {"success": gateway._ok(resp), "data": resp}
        except Exception as err:
            return {"success": False, "message": str(err)}

    def api_rename(self, payload: dict) -> Dict[str, Any]:
        try:
            gateway = self._ensure_gateway()
            resp = gateway.rename(int(payload.get("file_id")), str(payload.get("name") or "").strip())
            return {"success": gateway._ok(resp), "data": resp}
        except Exception as err:
            return {"success": False, "message": str(err)}

    def api_move(self, payload: dict) -> Dict[str, Any]:
        try:
            gateway = self._ensure_gateway()
            resp = gateway.move(payload.get("file_ids") or [], int(payload.get("pid") or 0))
            return {"success": gateway._ok(resp), "data": resp}
        except Exception as err:
            return {"success": False, "message": str(err)}

    def api_delete(self, payload: dict) -> Dict[str, Any]:
        try:
            gateway = self._ensure_gateway()
            resp = gateway.delete(payload.get("file_ids") or [])
            return {"success": gateway._ok(resp), "data": resp}
        except Exception as err:
            return {"success": False, "message": str(err)}

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {"path": "/config", "endpoint": self.api_config, "methods": ["GET"], "auth": "bear", "summary": "读取115网盘助手配置"},
            {"path": "/config", "endpoint": self.api_save_config, "methods": ["POST"], "auth": "bear", "summary": "保存115网盘助手配置"},
            {"path": "/login/qrcode", "endpoint": self.api_qr_start, "methods": ["POST"], "auth": "bear", "summary": "获取115登录二维码"},
            {"path": "/login/poll", "endpoint": self.api_qr_poll, "methods": ["POST"], "auth": "bear", "summary": "轮询115扫码登录状态"},
            {"path": "/status", "endpoint": self.api_status, "methods": ["GET"], "auth": "bear", "summary": "检查115登录状态"},
            {"path": "/browse", "endpoint": self.api_browse, "methods": ["GET"], "auth": "bear", "summary": "浏览115目录"},
            {"path": "/mkdir", "endpoint": self.api_mkdir, "methods": ["POST"], "auth": "bear", "summary": "创建115目录"},
            {"path": "/rename", "endpoint": self.api_rename, "methods": ["POST"], "auth": "bear", "summary": "重命名115文件"},
            {"path": "/move", "endpoint": self.api_move, "methods": ["POST"], "auth": "bear", "summary": "移动115文件"},
            {"path": "/delete", "endpoint": self.api_delete, "methods": ["POST"], "auth": "bear", "summary": "删除115文件"},
        ]
