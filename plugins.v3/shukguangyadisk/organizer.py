"""光鸭云盘自动整理监控。

本模块只负责发现光鸭监控目录中的新增/变化文件；媒体识别、目录匹配、分类、
重命名、整理方式、覆盖、刮削和整理历史全部交给 MoviePilot 自带监控/整理链。
插件不维护第二套分类规则或命名规则。
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
    """监控光鸭目录并把变化文件直接送入 MoviePilot 原生整理链。"""

    _monitor_config_key = "organize_monitor_config"
    _monitor_state_key = "organize_monitor_state"
    _monitor_history_key = "organize_monitor_history"
    _monitor_status_key = "organize_monitor_status"

    _monitor_default_interval = 60
    _monitor_min_interval = 30
    _monitor_default_stability = 30
    _monitor_default_batch_size = 100
    _monitor_inventory_cap = 5000
    _monitor_history_limit = 100

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
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(parsed, maximum))

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
        saved = self.get_data(self._monitor_config_key) or {}
        config = self._default_monitor_config()
        if isinstance(saved, dict):
            config.update(saved)
        config["enabled"] = bool(config.get("enabled"))
        config["path"] = self._organize_normalize_path(config.get("path") or "/")
        config["interval"] = self._bounded_int(
            config.get("interval"), self._monitor_default_interval, self._monitor_min_interval, 3600
        )
        config["stability"] = self._bounded_int(
            config.get("stability"), self._monitor_default_stability, 0, 3600
        )
        config["batch_size"] = self._bounded_int(
            config.get("batch_size"), self._monitor_default_batch_size, 1, 500
        )
        config["recursive"] = bool(config.get("recursive", True))
        return config

    def init_organizer_monitor(self) -> None:
        """从插件持久化数据恢复监控设置；不依赖前端 localStorage。"""
        config = self._load_monitor_config()
        self._organize_monitor_enabled = config["enabled"]
        self._organize_monitor_path = config["path"]
        self._organize_monitor_interval = config["interval"]
        self._organize_monitor_stability = config["stability"]
        self._organize_monitor_batch_size = config["batch_size"]
        self._organize_monitor_recursive = config["recursive"]
        self._organize_monitor_last_tick = 0.0
        self._organize_dispatcher = None
        if self._organize_scan_lock is None:
            self._organize_scan_lock = threading.Lock()
        logger.info(
            "【光鸭云盘助手】【自动整理】配置恢复: enabled=%s path=%s interval=%ss stability=%ss batch=%s recursive=%s",
            self._organize_monitor_enabled,
            self._organize_monitor_path,
            self._organize_monitor_interval,
            self._organize_monitor_stability,
            self._organize_monitor_batch_size,
            self._organize_monitor_recursive,
        )

    def _monitor_config_payload(self) -> Dict[str, Any]:
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
        """枚举监控目录。这里只发现文件，不做任何媒体分类。"""
        if not self._guangya_api:
            raise RuntimeError("光鸭云盘尚未登录或存储未初始化")
        root = self._guangya_api.get_item(Path(root_path))
        if not root or root.type != "dir":
            raise RuntimeError(f"监控目录不存在: {root_path}")

        files: List[Any] = []
        queue: List[Any] = [root]
        visited_nodes = 0
        truncated = False
        while queue:
            current = queue.pop(0)
            children = self._guangya_api.list(current) or []
            for child in children:
                visited_nodes += 1
                if visited_nodes > self._monitor_inventory_cap:
                    truncated = True
                    queue.clear()
                    break
                name = str(getattr(child, "name", "") or "")
                if name.startswith("."):
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
        """直接走 MP TransferDispatcher -> TransferChain；插件不计算目标目录或文件名。"""
        dispatcher = self._get_organize_dispatcher()
        event_path = Path(str(item.path or ""))
        return bool(dispatcher.handle_file(
            storage=self._disk_name,
            event_path=event_path,
            file_size=int(getattr(item, "size", 0) or 0),
            file_modify_time=float(getattr(item, "modify_time", 0) or 0),
            fileid=str(getattr(item, "fileid", "") or "") or None,
        ))

    def run_organize_monitor_scan(self, manual: bool = False) -> Dict[str, Any]:
        """扫描一次监控目录，将稳定的新文件交给 MoviePilot 原生整理链。"""
        if not manual and not self._organize_monitor_enabled:
            return {"success": True, "message": "自动整理监控未启用", "data": {"disabled": True}}
        if not self._enabled or not self._guangya_api:
            return {"success": False, "message": "光鸭云盘未启用或未登录"}
        if self._organize_monitor_path == "/":
            return {"success": False, "message": "请先选择具体监控目录，禁止直接监控根目录"}

        scan_lock = self._organize_scan_lock or threading.Lock()
        self._organize_scan_lock = scan_lock
        if not scan_lock.acquire(blocking=False):
            return {"success": False, "message": "已有自动整理扫描正在运行，请稍后再试"}

        started = time.time()
        now_text = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            dispatcher = self._get_organize_dispatcher()
            try:
                dispatcher.retry_pending()
            except Exception as err:
                logger.debug("【光鸭云盘助手】【自动整理】MP 待重试队列检查失败: %s", err)

            files, truncated = self._scan_cloud_files(self._organize_monitor_path)
            state = dict(self.get_data(self._monitor_state_key) or {})
            seen: Dict[str, str] = dict(state.get("seen") or {})
            pending: Dict[str, Dict[str, Any]] = dict(state.get("pending") or {})
            inventory_paths = set()
            candidates: List[Tuple[Any, str, str]] = []

            for item in files:
                path = self._organize_normalize_path(getattr(item, "path", ""))
                inventory_paths.add(path)
                fingerprint = self._fingerprint(item)
                if seen.get(path) == fingerprint:
                    pending.pop(path, None)
                    continue
                candidates.append((item, path, fingerprint))

            # 完整扫描时才清理已消失路径；扫描被上限截断时保留旧状态防止重复整理。
            if not truncated:
                seen = {path: fp for path, fp in seen.items() if path in inventory_paths}
                pending = {path: row for path, row in pending.items() if path in inventory_paths}

            ready: List[Tuple[Any, str, str]] = []
            waiting = 0
            now = time.time()
            for item, path, fingerprint in candidates:
                old = pending.get(path) or {}
                if old.get("fingerprint") != fingerprint:
                    pending[path] = {"fingerprint": fingerprint, "first_seen": now}
                    if self._organize_monitor_stability > 0:
                        waiting += 1
                        continue
                first_seen = float((pending.get(path) or {}).get("first_seen") or now)
                if now - first_seen < self._organize_monitor_stability:
                    waiting += 1
                    continue
                ready.append((item, path, fingerprint))

            ready.sort(key=lambda row: float(getattr(row[0], "modify_time", 0) or 0))
            ready = ready[:self._organize_monitor_batch_size]

            submitted = 0
            gated = 0
            failed = 0
            errors: List[str] = []
            for item, path, fingerprint in ready:
                try:
                    accepted = self._dispatch_to_moviepilot(item)
                    # accepted=False 由 MP 自己的扩展名、历史、去重或重试门控决定；
                    # 这同样是一个确定的 MP 处理结果，不在插件里另写判定规则。
                    if accepted:
                        submitted += 1
                        action = "已提交 MoviePilot 整理链"
                    else:
                        gated += 1
                        action = "MoviePilot 门控跳过/去重"
                    seen[path] = fingerprint
                    pending.pop(path, None)
                    self._append_monitor_history({
                        "time": now_text,
                        "path": path,
                        "name": str(getattr(item, "name", "") or Path(path).name),
                        "size": int(getattr(item, "size", 0) or 0),
                        "result": "submitted" if accepted else "gated",
                        "message": action,
                    })
                except Exception as err:
                    failed += 1
                    errors.append(f"{path}: {err}")
                    logger.error("【光鸭云盘助手】【自动整理】提交 MoviePilot 整理链失败: %s - %s", path, err)

            state = {
                "seen": seen,
                "pending": pending,
                "monitor_path": self._organize_monitor_path,
                "updated_at": now_text,
            }
            self.save_data(self._monitor_state_key, state)
            duration_ms = int((time.time() - started) * 1000)
            status = self._save_monitor_status(
                running=True,
                last_scan=now_text,
                monitor_path=self._organize_monitor_path,
                inventory=len(files),
                changed=len(candidates),
                waiting=waiting,
                submitted=submitted,
                gated=gated,
                failed=failed,
                truncated=truncated,
                duration_ms=duration_ms,
                errors=errors[:10],
            )
            message = (
                f"扫描完成：发现 {len(files)} 个文件，变化 {len(candidates)}，"
                f"提交 MP {submitted}，MP 门控 {gated}，等待稳定 {waiting}，失败 {failed}"
            )
            logger.info("【光鸭云盘助手】【自动整理】%s", message)
            return {"success": failed == 0, "message": message, "data": status}
        except Exception as err:
            logger.exception("【光鸭云盘助手】【自动整理】扫描失败: %s", err)
            status = self._save_monitor_status(
                running=True,
                last_scan=now_text,
                monitor_path=self._organize_monitor_path,
                failed=1,
                errors=[str(err)],
            )
            return {"success": False, "message": f"自动整理扫描失败: {err}", "data": status}
        finally:
            scan_lock.release()

    def organize_monitor_tick(self) -> None:
        """固定 30 秒心跳；实际扫描周期读取用户持久化设置，无需重载插件服务。"""
        if not self._organize_monitor_enabled:
            return
        now = time.monotonic()
        if self._organize_monitor_last_tick and (
            now - self._organize_monitor_last_tick < self._organize_monitor_interval
        ):
            return
        self._organize_monitor_last_tick = now
        self.run_organize_monitor_scan(manual=False)

    def get_organizer_services(self) -> List[Dict[str, Any]]:
        """服务始终注册，启停由持久化 monitor.enabled 控制，保存后立即生效。"""
        return [{
            "id": "ShukGuangYaDiskAutoMonitor",
            "name": "光鸭云盘自动整理监控",
            "trigger": IntervalTrigger(seconds=self._monitor_min_interval),
            "func": self.organize_monitor_tick,
            "kwargs": {},
        }]

    def api_organize_monitor_config(self) -> Dict[str, Any]:
        return {
            "success": True,
            "message": "自动整理设置已读取",
            "data": {
                "config": self._monitor_config_payload(),
                "mp": self._moviepilot_directory_summary(),
            },
        }

    def api_organize_monitor_save(self, payload: dict) -> Dict[str, Any]:
        payload = payload or {}
        try:
            old_path = self._organize_monitor_path
            path = self._organize_normalize_path(payload.get("path", old_path))
            enabled = bool(payload.get("enabled", self._organize_monitor_enabled))
            if enabled and path == "/":
                return {"success": False, "message": "启用自动整理前必须选择具体监控目录"}
            if self._guangya_api and path != "/":
                item = self._guangya_api.get_item(Path(path))
                if not item or item.type != "dir":
                    return {"success": False, "message": f"监控目录不存在: {path}"}

            config = {
                "enabled": enabled,
                "path": path,
                "interval": self._bounded_int(
                    payload.get("interval", self._organize_monitor_interval),
                    self._monitor_default_interval,
                    self._monitor_min_interval,
                    3600,
                ),
                "stability": self._bounded_int(
                    payload.get("stability", self._organize_monitor_stability),
                    self._monitor_default_stability,
                    0,
                    3600,
                ),
                "batch_size": self._bounded_int(
                    payload.get("batch_size", self._organize_monitor_batch_size),
                    self._monitor_default_batch_size,
                    1,
                    500,
                ),
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
            self._save_monitor_status(
                running=self._organize_monitor_enabled,
                monitor_path=self._organize_monitor_path,
            )
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

    def _moviepilot_directory_summary(self) -> Dict[str, Any]:
        """只展示 MP 已配置目录数量，绝不把规则复制到插件配置。"""
        try:
            dirs = DirectoryHelper().get_dirs() or []
            enabled = [item for item in dirs if getattr(item, "monitor_type", None)]
            return {
                "directory_count": len(dirs),
                "organize_enabled_count": len(enabled),
                "message": "分类、命名、目标目录、整理方式、覆盖与刮削均使用 MoviePilot 当前内置目录配置",
            }
        except Exception as err:
            return {
                "directory_count": 0,
                "organize_enabled_count": 0,
                "message": f"读取 MoviePilot 目录配置失败: {err}",
            }

    def api_organize_policies(self) -> Dict[str, Any]:
        """兼容旧前端接口：只返回 MP 状态，不再提供插件侧策略选择。"""
        summary = self._moviepilot_directory_summary()
        return {
            "success": True,
            "message": summary["message"],
            "data": {"policies": [], "managed_by": "MoviePilot", "summary": summary},
        }

    def api_organize_folders(self, payload: dict) -> Dict[str, Any]:
        """浏览光鸭目录，仅用于选择监控目录。"""
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
            logger.warning("【光鸭云盘助手】【自动整理】浏览目录失败: %s", err)
            return {"success": False, "message": f"浏览目录失败: {err}"}

    def get_organizer_api(self) -> List[Dict[str, Any]]:
        """自动整理 API；不再暴露插件自建分类/目标/移动复制策略。"""
        return [
            {"path": "/organize/policies", "endpoint": self.api_organize_policies, "auth": "bear", "methods": ["GET"], "summary": "查看 MoviePilot 内置整理配置状态", "response_model": GuangYaOrganizerResponse},
            {"path": "/organize/folders", "endpoint": self.api_organize_folders, "auth": "bear", "methods": ["POST"], "summary": "浏览光鸭目录选择监控目录", "response_model": GuangYaOrganizerResponse},
            {"path": "/organize/monitor/config", "endpoint": self.api_organize_monitor_config, "auth": "bear", "methods": ["GET"], "summary": "读取自动整理监控设置", "response_model": GuangYaOrganizerResponse},
            {"path": "/organize/monitor/config", "endpoint": self.api_organize_monitor_save, "auth": "bear", "methods": ["POST"], "summary": "保存自动整理监控设置", "response_model": GuangYaOrganizerResponse},
            {"path": "/organize/monitor/scan", "endpoint": self.api_organize_monitor_scan, "auth": "bear", "methods": ["POST"], "summary": "立即扫描监控目录并交给 MoviePilot 整理", "response_model": GuangYaOrganizerResponse},
            {"path": "/organize/monitor/status", "endpoint": self.api_organize_monitor_status, "auth": "bear", "methods": ["GET"], "summary": "读取自动整理运行状态与最近记录", "response_model": GuangYaOrganizerResponse},
        ]
