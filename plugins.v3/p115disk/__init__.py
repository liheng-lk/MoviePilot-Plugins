"""115 网盘助手 MoviePilot V3 插件入口。

首轮先提供稳定登录态、目录浏览与基础文件操作 API；MoviePilot StorageChain 合同将在同分支继续补齐。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.plugins import _PluginBase
from app.sdk.logging import logger

from .models import P115Item
from .p115_client import P115ClientConfig, P115Gateway


class P115Disk(_PluginBase):
    plugin_name = "115网盘助手"
    plugin_desc = "MoviePilot V3 115网盘助手，提供目录浏览、文件操作和115转存底层能力。"
    plugin_icon = ""
    plugin_version = "0.1.0"
    plugin_author = "liheng-lk"
    author_url = "https://github.com/liheng-lk/MoviePilot-Plugins"
    plugin_config_prefix = "p115disk_"
    plugin_order = 20
    auth_level = 2

    _enabled: bool = False
    _cookies: str = ""
    _cookies_file: str = ""
    _page_size: int = 500

    def __init__(self):
        super().__init__()
        self._gateway: Optional[P115Gateway] = None

    def init_plugin(self, config: dict = None) -> None:
        config = config or {}
        self._enabled = bool(config.get("enabled", False))
        self._cookies = str(config.get("cookies") or "").strip()
        self._cookies_file = str(config.get("cookies_file") or "").strip()
        try:
            self._page_size = max(50, min(int(config.get("page_size") or 500), 1150))
        except (TypeError, ValueError):
            self._page_size = 500
        self._gateway = None
        if not self._enabled:
            return
        try:
            self._gateway = P115Gateway(
                P115ClientConfig(cookies=self._cookies, cookies_file=self._cookies_file)
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
                P115ClientConfig(cookies=self._cookies, cookies_file=self._cookies_file)
            )
        return self._gateway

    def api_config(self) -> Dict[str, Any]:
        return {
            "success": True,
            "data": {
                "enabled": self._enabled,
                "cookies_file": self._cookies_file,
                "page_size": self._page_size,
                "has_cookies": bool(self._cookies or self._cookies_file),
            },
        }

    def api_save_config(self, payload: dict) -> Dict[str, Any]:
        config = {
            "enabled": bool(payload.get("enabled", self._enabled)),
            "cookies": str(payload.get("cookies") or self._cookies or "").strip(),
            "cookies_file": str(payload.get("cookies_file") or self._cookies_file or "").strip(),
            "page_size": int(payload.get("page_size") or self._page_size or 500),
        }
        self.update_config(config)
        self.init_plugin(config)
        return {"success": True, "message": "配置已保存", "data": self.api_config()["data"]}

    def api_status(self) -> Dict[str, Any]:
        try:
            data = self._ensure_gateway().user_info()
            return {"success": True, "data": data}
        except Exception as err:
            return {"success": False, "message": str(err), "data": None}

    @staticmethod
    def _extract_items(resp: Dict[str, Any]) -> list[dict]:
        candidates = [
            resp.get("data"),
            resp.get("files"),
            resp.get("list"),
        ]
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
            resp = self._ensure_gateway().mkdir(str(payload.get("name") or "").strip(), int(payload.get("pid") or 0))
            return {"success": self._gateway._ok(resp), "data": resp}
        except Exception as err:
            return {"success": False, "message": str(err)}

    def api_rename(self, payload: dict) -> Dict[str, Any]:
        try:
            resp = self._ensure_gateway().rename(int(payload.get("file_id")), str(payload.get("name") or "").strip())
            return {"success": self._gateway._ok(resp), "data": resp}
        except Exception as err:
            return {"success": False, "message": str(err)}

    def api_move(self, payload: dict) -> Dict[str, Any]:
        try:
            resp = self._ensure_gateway().move(payload.get("file_ids") or [], int(payload.get("pid") or 0))
            return {"success": self._gateway._ok(resp), "data": resp}
        except Exception as err:
            return {"success": False, "message": str(err)}

    def api_delete(self, payload: dict) -> Dict[str, Any]:
        try:
            resp = self._ensure_gateway().delete(payload.get("file_ids") or [])
            return {"success": self._gateway._ok(resp), "data": resp}
        except Exception as err:
            return {"success": False, "message": str(err)}

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {"path": "/config", "endpoint": self.api_config, "methods": ["GET"], "auth": "bear", "summary": "读取115网盘助手配置"},
            {"path": "/config", "endpoint": self.api_save_config, "methods": ["POST"], "auth": "bear", "summary": "保存115网盘助手配置"},
            {"path": "/status", "endpoint": self.api_status, "methods": ["GET"], "auth": "bear", "summary": "检查115登录状态"},
            {"path": "/browse", "endpoint": self.api_browse, "methods": ["GET"], "auth": "bear", "summary": "浏览115目录"},
            {"path": "/mkdir", "endpoint": self.api_mkdir, "methods": ["POST"], "auth": "bear", "summary": "创建115目录"},
            {"path": "/rename", "endpoint": self.api_rename, "methods": ["POST"], "auth": "bear", "summary": "重命名115文件"},
            {"path": "/move", "endpoint": self.api_move, "methods": ["POST"], "auth": "bear", "summary": "移动115文件"},
            {"path": "/delete", "endpoint": self.api_delete, "methods": ["POST"], "auth": "bear", "summary": "删除115文件"},
        ]
