"""115 转存助手 MoviePilot V3 插件入口。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.plugins import _PluginBase
from app.sdk.logging import logger

from .dispatcher import TransferDispatcher
from .models import TaskState
from .p115_provider import P115TransferProvider
from .resource import normalize_resource
from .task_store import TaskStore


class P115TransferAssistant(_PluginBase):
    plugin_name = "115转存助手"
    plugin_desc = "115分享、Magnet、ED2K 三来源转存，支持任务去重、状态恢复和安全文件选择。"
    plugin_icon = ""
    plugin_version = "0.1.0"
    plugin_author = "liheng-lk"
    author_url = "https://github.com/liheng-lk/MoviePilot-Plugins"
    plugin_config_prefix = "p115transferassistant_"
    plugin_order = 21
    auth_level = 2

    _enabled: bool = False
    _cookies: str = ""
    _cookies_file: str = ""
    _target_cid: int = 0

    def __init__(self):
        super().__init__()
        self._provider: Optional[P115TransferProvider] = None
        self._store: Optional[TaskStore] = None
        self._dispatcher: Optional[TransferDispatcher] = None

    def init_plugin(self, config: dict = None) -> None:
        config = config or {}
        self._enabled = bool(config.get("enabled", False))
        self._cookies = str(config.get("cookies") or "").strip()
        self._cookies_file = str(config.get("cookies_file") or "").strip()
        try:
            self._target_cid = int(config.get("target_cid") or 0)
        except (TypeError, ValueError):
            self._target_cid = 0

        self._store = TaskStore(self.get_data, self.save_data)
        self._provider = None
        self._dispatcher = None
        if not self._enabled:
            return
        try:
            self._provider = P115TransferProvider(self._cookies, self._cookies_file)
            self._dispatcher = TransferDispatcher(self._provider, self._store)
            logger.info("【115转存助手】初始化完成，目标 CID=%s", self._target_cid)
        except Exception as err:
            logger.error("【115转存助手】初始化失败: %s", err)

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
            "target_cid": self._target_cid,
        }

    def get_page(self) -> Optional[List[dict]]:
        return None

    def stop_service(self) -> None:
        self._provider = None
        self._dispatcher = None

    def _ensure_runtime(self) -> TransferDispatcher:
        if not self._enabled:
            raise RuntimeError("115转存助手未启用")
        if not self._store:
            self._store = TaskStore(self.get_data, self.save_data)
        if not self._provider:
            self._provider = P115TransferProvider(self._cookies, self._cookies_file)
        if not self._dispatcher:
            self._dispatcher = TransferDispatcher(self._provider, self._store)
        return self._dispatcher

    def api_config(self) -> Dict[str, Any]:
        return {
            "success": True,
            "data": {
                "enabled": self._enabled,
                "cookies_file": self._cookies_file,
                "target_cid": self._target_cid,
                "has_cookies": bool(self._cookies or self._cookies_file),
            },
        }

    def api_save_config(self, payload: dict) -> Dict[str, Any]:
        config = {
            "enabled": bool(payload.get("enabled", self._enabled)),
            "cookies": str(payload.get("cookies") or self._cookies or "").strip(),
            "cookies_file": str(payload.get("cookies_file") or self._cookies_file or "").strip(),
            "target_cid": int(payload.get("target_cid") or self._target_cid or 0),
        }
        self.update_config(config)
        self.init_plugin(config)
        return {"success": True, "message": "配置已保存", "data": self.api_config()["data"]}

    def api_tasks(self) -> Dict[str, Any]:
        store = self._store or TaskStore(self.get_data, self.save_data)
        return {"success": True, "data": [task.to_dict() for task in store.list()]}

    def api_submit(self, payload: dict) -> Dict[str, Any]:
        try:
            uri = str(payload.get("uri") or "").strip()
            resource = normalize_resource(uri)
            dispatcher = self._ensure_runtime()
            task = dispatcher.build_task(
                resource,
                target_cid=int(payload.get("target_cid") or self._target_cid or 0),
                subscribe_id=payload.get("subscribe_id"),
                tmdb_id=payload.get("tmdb_id"),
                media_type=str(payload.get("media_type") or ""),
                season=payload.get("season"),
                target_episodes=payload.get("target_episodes") or [],
                wanted=payload.get("wanted") or [],
            )
            share_file_ids = payload.get("share_file_ids") or []
            if bool(payload.get("dispatch", True)):
                task = dispatcher.dispatch(task, share_file_ids=share_file_ids)
            return {"success": True, "data": task.to_dict()}
        except Exception as err:
            logger.exception("【115转存助手】提交资源失败: %s", err)
            return {"success": False, "message": str(err), "data": None}

    def api_retry(self, payload: dict) -> Dict[str, Any]:
        task_id = str(payload.get("task_id") or "").strip()
        store = self._store or TaskStore(self.get_data, self.save_data)
        task = store.get(task_id)
        if not task:
            return {"success": False, "message": "任务不存在"}
        if task.state not in {TaskState.FAILED_RETRYABLE, TaskState.NEEDS_REVIEW}:
            return {"success": False, "message": f"当前状态不可重试: {task.state}"}
        task.error_message = ""
        store.transition(task, TaskState.RESOLVED)
        task = self._ensure_runtime().dispatch(task, share_file_ids=payload.get("share_file_ids") or [])
        return {"success": True, "data": task.to_dict()}

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/config",
                "endpoint": self.api_config,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "读取115转存助手配置",
            },
            {
                "path": "/config",
                "endpoint": self.api_save_config,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "保存115转存助手配置",
            },
            {
                "path": "/tasks",
                "endpoint": self.api_tasks,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "读取115转存任务",
            },
            {
                "path": "/submit",
                "endpoint": self.api_submit,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "提交115分享/Magnet/ED2K",
            },
            {
                "path": "/retry",
                "endpoint": self.api_retry,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "重试115转存任务",
            },
        ]
