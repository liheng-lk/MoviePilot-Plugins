"""光鸭云盘自动整理监控。

职责边界：本模块只负责“发现监控目录中的新增/变化文件”。媒体识别、分类策略、
目标目录、重命名、整理方式、覆盖、刮削、历史去重和失败重试全部交给 MoviePilot
原生 TransferDispatcher / TransferChain。插件不维护第二套分类或命名规则。
"""

from __future__ import annotations

import datetime
import hashlib
import threading
import time
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

from apscheduler.triggers.interval import IntervalTrigger

from app.application.directory import DirectoryHelper
from app.monitor.dispatcher import TransferDispatcher
from app.sdk.logging import logger

from .models import GuangYaOrganizerResponse


class GuangYaOrganizerMixin:
    """光鸭远程目录轮询监控 + MoviePilot 原生整理链适配。"""

    _monitor_config_key = "organize_monitor_config"
    _monitor_state_key = "organize_monitor_state"
    _monitor_history_key = "organize_monitor_history"
    _monitor_status_key = "organize_monitor_status"

    _monitor_heartbeat = 30
    _monitor_default_interval = 60
    _monitor_default_stability = 30
    _monitor_default_batch_size = 100
    _monitor_inventory_cap = 5000
    _monitor_history_limit = 100

    _organize_monitor_initialized: bool = False
    _organize_monitor_enabled: bool = False
    _organize_monitor_path: str = "/"
    _organize_monitor_interval: int = _monitor_default_interval
    _organize_monitor_stability: int = _monitor_default_stability
    _organize_monitor_batch_size: int = _monitor_default_batch_size
    _organize_monitor_recursive: bool = True
    _organize_monitor_last_tick: float = 0.0
    _organize_dispatcher: Optional[TransferDispatcher] = None
    _organize_scan_lock: Optional[threading.Lock] = None

    @staticmethod
    def _organize_normalize_path(value: Any) -> str:
        raw = str(value or "").strip().replace("\\", "/")
        if not raw:
            return "/"
        if not raw.startswith("/"):
            raw = "/" + raw
        path = PurePosixPath(raw)
        if ".." in path.parts:
            raise ValueError("监控目录不能包含 ..")
        normalized = "/" + "/".join(part for part in path.parts if part != "/")
        return normalized.rstrip("/") or "/"

    @staticmethod
    def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(value, maximum))

    def _default_monitor_config(self) -> Dict[str, Any]:
        return {
            "enabled": False,
            "path": "/",
            "interval": self._monitor_default_interval,
            "stability": self._monitor_default_stability,
            "batch_size": self._monitor_default_batch_size,
            "recursive": True,
        }

    def _load_monitor_config(self) -> Dict[str, Any]:
        config = self._default_monitor_config()
        saved = self.get_data(self._monitor_config_key) or {}
        if isinstance(saved, dict):
            config.update(saved)
        config["enabled"] = bool(config.get("enabled"))
        config["path"] = self._organize_normalize_path(config.get("path") or "/")
        config["interval"] = self._bounded_int(config.get("interval"), 60, 30, 3600)
        config["stability"] = self._bounded_int(config.get("stability"), 30, 0, 3600)
        config["batch_size"] = self._bounded_int(config.get("batch_size"), 100, 1, 500)
        config["recursive"] = bool(config.get("recursive", True))
        return config

    def init_organizer_monitor(self, force: bool = False) -> None:
        """从插件后端持久化数据恢复设置，而不是依赖浏览器 localStorage。"""
        if self._organize_monitor_initialized and not force:
            return
        config = self._load_monitor_config()
        self._organize_monitor_enabled = config["enabled"]
        self._organize_monitor_path = config["path"]
        self._organize_monitor_interval = config["interval"]
        self._organize_monitor_stability = config["stability"]
        self._organize_monitor_batch_size = config["batch_size"]
        self._organize_monitor_recursive = config["recursive"]
        self._organize_monitor_last_tick = 0.0
        self._organize_dispatcher = None
        self._organize_scan_lock = self._organize_scan_lock or threading.Lock()
        self._organize_monitor_initialized = True
        logger.info(
            "【光鸭云盘助手】【自动整理】恢复设置: enabled=%s path=%s interval=%ss stability=%ss batch=%s recursive=%s",
            self._organize_monitor_enabled,
            self._organize_monitor_path,
            self._organize_monitor_interval,
            self._organize_monitor_stability,
            self._organize_monitor_batch_size,
            self._organize_monitor_recursive,
        )

    def get_service(self) -> List[Dict[str, Any]]:
        """始终注册轻量心跳；保存启停设置后无需重启插件即可生效。"""
        self.init_organizer_monitor()
        base_getter = getattr(super(), "get_service", None)
        services = list(base_getter() or []) if callable(base_getter) else []
        services.append({
            "id": "ShukGuangYaDiskAutoMonitor",
            "name": "光鸭云盘自动整理监控",
            "trigger": IntervalTrigger(seconds=self._monitor_heartbeat),
            "func": self.organize_monitor_tick,
            "kwargs": {},
        })
        return services

    def _monitor_config_payload(self) -> Dict[str, Any]:
        self.init_organizer_monitor()
        return {
            "enabled": self._organize_monitor_enabled,
            "path": self._organize_monitor_path,
            "interval": self._organize_monitor_interval,
            "stability": self._organize_monitor_stability,
            "batch_size": self._organize_monitor_batch_size,
            "recursive": self._organize_monitor_recursive,
        }

    def _get_organize_dispatcher(self) -> TransferDispatcher:
        if self._organize_dispatcher is None:
            self._organize_dispatcher = TransferDispatcher()
        return self._organize_dispatcher

    @staticmethod
    def _fingerprint(item: Any) -> str:
        raw = "|".join([
            str(getattr(item, "fileid", "") or ""),
            str(getattr(item, "size", 0) or 0),
            str(getattr(item, "modify_time", 0) or 0),
        ])
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def _scan_cloud_files(self, root_path: str) -> Tuple[List[Any], bool]:
        """只枚举文件，不在插件内识别媒体或计算分类目录。"""
        if not self._guangya_api:
            raise RuntimeError("光鸭云盘尚未登录或存储未初始化")
        root = self._guangya_api.get_item(Path(root_path))
        if not root or root.type != "dir":
            raise RuntimeError(f"监控目录不存在: {root_path}")

        files: List[Any] = []
        queue: List[Any] = [root]
        visited = 0
        truncated = False
        while queue:
            current = queue.pop(0)
            for child in self._guangya_api.list(current) or []:
                visited += 1
                if visited > self._monitor_inventory_cap:
                    truncated = True
                    queue.clear()
                    break
                if str(getattr(child, "name", "") or "").startswith("."):
                    continue
                if child.type == "dir":
                    if self._organize_monitor_recursive:
                        queue.append(child)
                elif child.type == "file":
                    files.append(child)
        return files, truncated

    def _append_monitor_history(self, row: Dict[str, Any]) -> None:
        history = list(self.get_data(self._monitor_history_key) or [])
        history.append(row)
        self.save_data(self._monitor_history_key, history[-self._monitor_history_limit:])

    def _save_monitor_status(self, **kwargs: Any) -> Dict[str, Any]:
        status = dict(self.get_data(self._monitor_status_key) or {})
        status.update(kwargs)
        self.save_data(self._monitor_status_key, status)
        return status

    def _dispatch_to_moviepilot(self, item: Any) -> bool:
        """唯一整理入口：MoviePilot 原生 TransferDispatcher。"""
        return bool(self._get_organize_dispatcher().handle_file(
            storage=self._disk_name,
            event_path=Path(str(item.path or "")),
            file_size=int(getattr(item, "size", 0) or 0),
            file_modify_time=float(getattr(item, "modify_time", 0) or 0),
            fileid=str(getattr(item, "fileid", "") or "") or None,
        ))

    def run_organize_monitor_scan(self, manual: bool = False) -> Dict[str, Any]:
        self.init_organizer_monitor()
        if not manual and not self._organize_monitor_enabled:
            return {"success": True, "message": "自动整理监控未启用", "data": {"disabled": True}}
        if not self._enabled or not self._guangya_api:
            return {"success": False, "message": "光鸭云盘未启用或未登录"}
        if self._organize_monitor_path == "/":
            return {"success": False, "message": "请先选择具体监控目录，禁止直接监控根目录"}

        lock = self._organize_scan_lock or threading.Lock()
        self._organize_scan_lock = lock
        if not lock.acquire(blocking=False):
            return {"success": False, "message": "已有自动整理扫描正在运行，请稍后再试"}

        started = time.time()
        now_text = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            dispatcher = self._get_organize_dispatcher()
            try:
                dispatcher.retry_pending()
            except Exception as err:
                logger.debug("【光鸭云盘助手】【自动整理】MP 待重试检查失败: %s", err)

            files, truncated = self._scan_cloud_files(self._organize_monitor_path)
            state = dict(self.get_data(self._monitor_state_key) or {})
            seen: Dict[str, str] = dict(state.get("seen") or {})
            pending: Dict[str, Dict[str, Any]] = dict(state.get("pending") or {})
            inventory_paths = set()
            changed: List[Tuple[Any, str, str]] = []

            for item in files:
                path = self._organize_normalize_path(getattr(item, "path", ""))
                inventory_paths.add(path)
                fp = self._fingerprint(item)
                if seen.get(path) == fp:
                    pending.pop(path, None)
                    continue
                changed.append((item, path, fp))

            if not truncated:
                seen = {path: fp for path, fp in seen.items() if path in inventory_paths}
                pending = {path: row for path, row in pending.items() if path in inventory_paths}

            now = time.time()
            waiting = 0
            ready: List[Tuple[Any, str, str]] = []
            for item, path, fp in changed:
                previous = pending.get(path) or {}
                if previous.get("fingerprint") != fp:
                    pending[path] = {"fingerprint": fp, "first_seen": now}
                    previous = pending[path]
                if now - float(previous.get("first_seen") or now) < self._organize_monitor_stability:
                    waiting += 1
                    continue
                ready.append((item, path, fp))

            ready.sort(key=lambda row: float(getattr(row[0], "modify_time", 0) or 0))
            ready = ready[:self._organize_monitor_batch_size]

            submitted = gated = failed = 0
            errors: List[str] = []
            for item, path, fp in ready:
                try:
                    accepted = self._dispatch_to_moviepilot(item)
                    if accepted:
                        submitted += 1
                        result, message = "submitted", "已提交 MoviePilot 原生整理链"
                    else:
                        gated += 1
                        result, message = "gated", "MoviePilot 原生历史/去重/扩展名门控未入队"
                    # accepted=False 也属于 MP 已给出的确定门控结果；插件不二次发明判定规则。
                    seen[path] = fp
                    pending.pop(path, None)
                    self._append_monitor_history({
                        "time": now_text,
                        "path": path,
                        "name": str(getattr(item, "name", "") or Path(path).name),
                        "size": int(getattr(item, "size", 0) or 0),
                        "result": result,
                        "message": message,
                    })
                except Exception as err:
                    failed += 1
                    errors.append(f"{path}: {err}")
                    logger.error("【光鸭云盘助手】【自动整理】提交 MP 整理链失败: %s - %s", path, err)

            self.save_data(self._monitor_state_key, {
                "seen": seen,
                "pending": pending,
                "monitor_path": self._organize_monitor_path,
                "updated_at": now_text,
            })
            status = self._save_monitor_status(
                running=self._organize_monitor_enabled,
                last_scan=now_text,
                monitor_path=self._organize_monitor_path,
                inventory=len(files),
                changed=len(changed),
                waiting=waiting,
                submitted=submitted,
                gated=gated,
                failed=failed,
                truncated=truncated,
                duration_ms=int((time.time() - started) * 1000),
                errors=errors[:10],
            )
            message = (
                f"扫描完成：文件 {len(files)}，变化 {len(changed)}，提交 MP {submitted}，"
                f"MP 门控 {gated}，等待稳定 {waiting}，失败 {failed}"
            )
            logger.info("【光鸭云盘助手】【自动整理】%s", message)
            return {"success": failed == 0, "message": message, "data": status}
        except Exception as err:
            logger.exception("【光鸭云盘助手】【自动整理】扫描失败: %s", err)
            status = self._save_monitor_status(
                running=self._organize_monitor_enabled,
                last_scan=now_text,
                monitor_path=self._organize_monitor_path,
                failed=1,
                errors=[str(err)],
            )
            return {"success": False, "message": f"自动整理扫描失败: {err}", "data": status}
        finally:
            lock.release()

    def organize_monitor_tick(self) -> None:
        """30 秒心跳；真正扫描周期由用户设置控制。"""
        self.init_organizer_monitor()
        if not self._organize_monitor_enabled:
            return
        now = time.monotonic()
        if self._organize_monitor_last_tick and now - self._organize_monitor_last_tick < self._organize_monitor_interval:
            return
        self._organize_monitor_last_tick = now
        self.run_organize_monitor_scan(manual=False)

    def _moviepilot_directory_summary(self) -> Dict[str, Any]:
        try:
            dirs = DirectoryHelper().get_dirs() or []
            enabled = [item for item in dirs if getattr(item, "monitor_type", None)]
            return {
                "directory_count": len(dirs),
                "organize_enabled_count": len(enabled),
                "message": "分类、命名、目标目录、整理方式、覆盖与刮削均使用 MoviePilot 当前内置目录配置",
            }
        except Exception as err:
            return {"directory_count": 0, "organize_enabled_count": 0, "message": f"读取 MoviePilot 目录配置失败: {err}"}

    def api_organize_monitor_config(self) -> Dict[str, Any]:
        return {"success": True, "data": {"config": self._monitor_config_payload(), "mp": self._moviepilot_directory_summary()}}

    def api_organize_monitor_save(self, payload: dict) -> Dict[str, Any]:
        self.init_organizer_monitor()
        payload = payload or {}
        try:
            old_path = self._organize_monitor_path
            path = self._organize_normalize_path(payload.get("path", old_path))
            enabled = bool(payload.get("enabled", self._organize_monitor_enabled))
            if enabled and path == "/":
                return {"success": False, "message": "启用自动整理前必须选择具体监控目录"}
            if self._guangya_api and path != "/":
                folder = self._guangya_api.get_item(Path(path))
                if not folder or folder.type != "dir":
                    return {"success": False, "message": f"监控目录不存在: {path}"}

            config = {
                "enabled": enabled,
                "path": path,
                "interval": self._bounded_int(payload.get("interval", self._organize_monitor_interval), 60, 30, 3600),
                "stability": self._bounded_int(payload.get("stability", self._organize_monitor_stability), 30, 0, 3600),
                "batch_size": self._bounded_int(payload.get("batch_size", self._organize_monitor_batch_size), 100, 1, 500),
                "recursive": bool(payload.get("recursive", self._organize_monitor_recursive)),
            }
            self.save_data(self._monitor_config_key, config)
            self._organize_monitor_enabled = config["enabled"]
            self._organize_monitor_path = config["path"]
            self._organize_monitor_interval = config["interval"]
            self._organize_monitor_stability = config["stability"]
            self._organize_monitor_batch_size = config["batch_size"]
            self._organize_monitor_recursive = config["recursive"]
            self._organize_monitor_last_tick = 0.0
            if old_path != path:
                self.save_data(self._monitor_state_key, {})
            self._save_monitor_status(running=enabled, monitor_path=path)
            return {
                "success": True,
                "message": "自动整理设置已保存，监控状态立即生效",
                "data": {"config": config, "mp": self._moviepilot_directory_summary()},
            }
        except Exception as err:
            return {"success": False, "message": f"保存自动整理设置失败: {err}"}

    def api_organize_monitor_scan(self, payload: dict = None) -> Dict[str, Any]:
        return self.run_organize_monitor_scan(manual=True)

    def api_organize_monitor_status(self) -> Dict[str, Any]:
        self.init_organizer_monitor()
        status = dict(self.get_data(self._monitor_status_key) or {})
        status.setdefault("running", self._organize_monitor_enabled)
        status.setdefault("monitor_path", self._organize_monitor_path)
        history = list(self.get_data(self._monitor_history_key) or [])[-20:][::-1]
        return {
            "success": True,
            "data": {
                "config": self._monitor_config_payload(),
                "status": status,
                "history": history,
                "mp": self._moviepilot_directory_summary(),
            },
        }

    def api_organize_policies(self) -> Dict[str, Any]:
        """兼容 v3.1.0 旧入口；不再让插件选择/复制 MP 分类策略。"""
        summary = self._moviepilot_directory_summary()
        return {"success": True, "message": summary["message"], "data": {"policies": [], "managed_by": "MoviePilot", "summary": summary}}

    def api_organize_folders(self, payload: dict) -> Dict[str, Any]:
        """只浏览目录供选择“监控目录”。"""
        if not self._guangya_api:
            return {"success": False, "message": "光鸭云盘尚未登录或存储未初始化"}
        try:
            path = self._organize_normalize_path((payload or {}).get("path") or "/")
            folder = self._guangya_api.get_item(Path(path))
            if not folder or folder.type != "dir":
                return {"success": False, "message": f"目录不存在: {path}"}
            rows = []
            for item in self._guangya_api.list(folder) or []:
                if item.type != "dir" or str(item.name or "").startswith("."):
                    continue
                rows.append({
                    "name": item.name,
                    "path": self._organize_normalize_path(item.path),
                    "fileid": str(item.fileid or ""),
                    "modify_time": int(item.modify_time or 0),
                })
            parent = "/" if path == "/" else self._organize_normalize_path(str(PurePosixPath(path).parent))
            return {"success": True, "data": {"path": path, "parent": parent, "folders": rows}}
        except Exception as err:
            return {"success": False, "message": f"浏览目录失败: {err}"}

    def get_organizer_api(self) -> List[Dict[str, Any]]:
        self.init_organizer_monitor()
        return [
            {"path": "/organize/policies", "endpoint": self.api_organize_policies, "auth": "bear", "methods": ["GET"], "summary": "查看 MoviePilot 内置整理状态", "response_model": GuangYaOrganizerResponse},
            {"path": "/organize/folders", "endpoint": self.api_organize_folders, "auth": "bear", "methods": ["POST"], "summary": "浏览光鸭监控目录", "response_model": GuangYaOrganizerResponse},
            {"path": "/organize/monitor/config", "endpoint": self.api_organize_monitor_config, "auth": "bear", "methods": ["GET"], "summary": "读取自动整理监控设置", "response_model": GuangYaOrganizerResponse},
            {"path": "/organize/monitor/config", "endpoint": self.api_organize_monitor_save, "auth": "bear", "methods": ["POST"], "summary": "保存自动整理监控设置", "response_model": GuangYaOrganizerResponse},
            {"path": "/organize/monitor/scan", "endpoint": self.api_organize_monitor_scan, "auth": "bear", "methods": ["POST"], "summary": "立即扫描并交给 MoviePilot 整理", "response_model": GuangYaOrganizerResponse},
            {"path": "/organize/monitor/status", "endpoint": self.api_organize_monitor_status, "auth": "bear", "methods": ["GET"], "summary": "自动整理状态与最近记录", "response_model": GuangYaOrganizerResponse},
        ]
