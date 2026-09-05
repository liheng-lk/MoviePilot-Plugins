"""115 转存助手 MoviePilot V3 插件入口。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.plugins import _PluginBase
from app.sdk.logging import logger

from .dispatcher import TransferDispatcher
from .episode_fence import EpisodeFence
from .episode_matcher import episode_intersection
from .models import SourceType, TaskState, TransferTask
from .p115_provider import P115TransferProvider
from .resource import NormalizedResource, normalize_resource
from .share_resolver import resolve_share_files
from .task_store import TaskStore


class P115TransferAssistant(_PluginBase):
    plugin_name = "115转存助手"
    plugin_desc = "115分享、Magnet、ED2K 三来源转存，支持缺集选择、任务去重、状态恢复和集级栅栏。"
    plugin_icon = ""
    plugin_version = "0.1.1"
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
        self._fence: Optional[EpisodeFence] = None
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
        self._fence = EpisodeFence(self.get_data, self.save_data)
        self._provider = None
        self._dispatcher = None
        if not self._enabled:
            return
        try:
            self._provider = P115TransferProvider(self._cookies, self._cookies_file)
            self._dispatcher = TransferDispatcher(self._provider, self._store, self._fence)
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
        if not self._fence:
            self._fence = EpisodeFence(self.get_data, self.save_data)
        if not self._provider:
            self._provider = P115TransferProvider(self._cookies, self._cookies_file)
        if not self._dispatcher:
            self._dispatcher = TransferDispatcher(self._provider, self._store, self._fence)
        return self._dispatcher

    def _reserve_for_dispatch(self, task: TransferTask) -> bool:
        """在真正发往 115 前占用目标集；全部被占用时直接短路。"""
        if not task.target_episodes or not task.tmdb_id or task.season is None:
            return True
        if not self._fence:
            self._fence = EpisodeFence(self.get_data, self.save_data)
        accepted, blocked = self._fence.reserve(
            task_id=task.task_id,
            tmdb_id=task.tmdb_id,
            season=task.season,
            episodes=task.target_episodes,
        )
        task.extra["blocked_episodes"] = blocked
        task.extra["deduplicated_by_fence"] = bool(blocked)
        task.reserved_episodes = accepted
        task.target_episodes = accepted
        if self._store:
            self._store.save(task)
        if accepted:
            return True
        task.state = TaskState.RESOLVED
        task.error_message = "目标集已被其它任务占用或已完成，未重复提交"
        if self._store:
            self._store.save(task)
        return False

    @staticmethod
    def _share_result_payload(result: Any) -> Dict[str, Any]:
        return {
            "file_ids": list(result.file_ids),
            "resolved_episodes": list(result.resolved_episodes),
            "missing_episodes": list(result.missing_episodes),
            "ambiguous": dict(result.ambiguous),
            "reason": result.reason,
            "files": [
                {
                    "file_id": item.file_id,
                    "name": item.name,
                    "path": item.path,
                    "size": item.size,
                    "episodes": list(item.episodes),
                    "kind": item.kind,
                }
                for item in result.files
            ],
        }

    def _resolve_share(self, task: TransferTask) -> list[int]:
        if not self._provider:
            raise RuntimeError("115 Provider 尚未初始化")
        result = resolve_share_files(
            self._provider.client,
            share_code=task.share_code,
            receive_code=task.receive_code,
            target_episodes=task.target_episodes,
            season=task.season,
            media_type=task.media_type,
        )
        task.extra["share_resolution"] = self._share_result_payload(result)
        task.extra["share_file_ids"] = list(result.file_ids)
        if self._store:
            self._store.save(task)
        if not result.safe:
            raise ValueError(result.reason or "115 分享未能形成安全文件选择")
        return list(result.file_ids)

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

    def _build_task_from_payload(
        self,
        dispatcher: TransferDispatcher,
        resource: NormalizedResource,
        payload: dict,
    ) -> TransferTask:
        raw_targets = sorted({int(v) for v in (payload.get("target_episodes") or []) if int(v) > 0})
        season = payload.get("season")

        # ED2K 是单文件入口。存在缺集目标时，先用文件名把它收窄到真实对应集，
        # 绝不能拿一个 E03 文件去占用 E03-E10 的全部缺口。
        if resource.source_type == SourceType.ED2K and raw_targets:
            matched = list(
                episode_intersection(
                    resource.filename,
                    raw_targets,
                    expected_season=int(season) if season is not None else None,
                )
            )
            if matched:
                raw_targets = matched

        task = dispatcher.build_task(
            resource,
            target_cid=int(payload.get("target_cid") or self._target_cid or 0),
            subscribe_id=payload.get("subscribe_id"),
            tmdb_id=payload.get("tmdb_id"),
            media_type=str(payload.get("media_type") or ""),
            season=season,
            target_episodes=raw_targets,
            wanted=payload.get("wanted") or [],
        )
        if resource.filename:
            task.extra["source_filename"] = resource.filename
        if resource.source_type == SourceType.ED2K and payload.get("target_episodes") and not raw_targets:
            task.extra["requested_episodes"] = payload.get("target_episodes") or []
        if self._store:
            self._store.save(task)
        return task

    def api_submit(self, payload: dict) -> Dict[str, Any]:
        try:
            uri = str(payload.get("uri") or "").strip()
            resource = normalize_resource(uri)
            dispatcher = self._ensure_runtime()
            task = self._build_task_from_payload(dispatcher, resource, payload)

            # 已经在途/完成的同一物理资源直接幂等返回，不发第二次请求。
            if task.state in {TaskState.TRANSFERRING, TaskState.TRANSFERRED, TaskState.COMPLETED}:
                return {"success": True, "data": task.to_dict()}

            should_dispatch = bool(payload.get("dispatch", True))
            explicit_share_ids = [int(v) for v in (payload.get("share_file_ids") or [])]

            # ED2K 有缺集上下文但文件名无法确认对应集时，拒绝提交。
            requested_targets = [int(v) for v in (payload.get("target_episodes") or []) if int(v) > 0]
            if resource.source_type == SourceType.ED2K and requested_targets and not task.target_episodes:
                task = dispatcher.fail(
                    task,
                    TaskState.NEEDS_REVIEW,
                    "ED2K 文件名无法高置信匹配当前缺集",
                    release=False,
                )
                return {"success": True, "data": task.to_dict()}

            if should_dispatch and not self._reserve_for_dispatch(task):
                return {"success": True, "data": task.to_dict()}

            share_file_ids = explicit_share_ids
            if resource.source_type == SourceType.SHARE115 and not share_file_ids:
                try:
                    share_file_ids = self._resolve_share(task)
                except Exception as err:
                    task = dispatcher.fail(task, TaskState.NEEDS_REVIEW, str(err))
                    return {"success": True, "data": task.to_dict()}

            if not should_dispatch:
                task = self._store.transition(task, TaskState.RESOLVED) if self._store else task
                return {"success": True, "data": task.to_dict()}

            task = dispatcher.dispatch(task, share_file_ids=share_file_ids)
            return {"success": True, "data": task.to_dict()}
        except Exception as err:
            logger.exception("【115转存助手】提交资源失败: %s", err)
            return {"success": False, "message": str(err), "data": None}

    def api_retry(self, payload: dict) -> Dict[str, Any]:
        task_id = str(payload.get("task_id") or "").strip()
        store = self._store or TaskStore(self.get_data, self.save_data)
        self._store = store
        task = store.get(task_id)
        if not task:
            return {"success": False, "message": "任务不存在"}
        if task.state not in {TaskState.FAILED_RETRYABLE, TaskState.NEEDS_REVIEW, TaskState.RESOLVED}:
            return {"success": False, "message": f"当前状态不可重试: {task.state}"}

        dispatcher = self._ensure_runtime()
        task.error_message = ""
        store.transition(task, TaskState.RESOLVED)
        if not self._reserve_for_dispatch(task):
            return {"success": True, "data": task.to_dict()}

        share_file_ids = [int(v) for v in (payload.get("share_file_ids") or task.extra.get("share_file_ids") or [])]
        if task.source_type == SourceType.SHARE115.value and not share_file_ids:
            try:
                share_file_ids = self._resolve_share(task)
            except Exception as err:
                task = dispatcher.fail(task, TaskState.NEEDS_REVIEW, str(err))
                return {"success": True, "data": task.to_dict()}

        task = dispatcher.dispatch(task, share_file_ids=share_file_ids)
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
