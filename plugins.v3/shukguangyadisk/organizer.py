"""光鸭云盘自动整理监控。

职责边界：本模块只负责目录发现、稳定性等待、任务状态编排和可观测性。媒体识别、
分类策略、目标目录、重命名、整理方式、覆盖、刮削与整理历史仍全部交给 MoviePilot
原生 TransferDispatcher / TransferChain。插件不维护第二套媒体库规则。
"""

from __future__ import annotations

import datetime
import hashlib
import threading
import time
from collections import deque
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

from apscheduler.triggers.interval import IntervalTrigger

from app.application.directory import DirectoryHelper
from app.monitor.dispatcher import TransferDispatcher
from app.sdk.logging import logger

from .models import GuangYaOrganizerResponse
from .organizer_history import inspect_moviepilot_history
from .organizer_state import OrganizerStateStore


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
    _monitor_inflight_lease = 1800

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
    _organize_state_lock: Optional[threading.RLock] = None
    _organize_state_store: Optional[OrganizerStateStore] = None

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

    def _state(self) -> OrganizerStateStore:
        if self._organize_state_store is None:
            self._organize_state_lock = self._organize_state_lock or threading.RLock()
            self._organize_state_store = OrganizerStateStore(
                read=self.get_data,
                write=self.save_data,
                key=self._monitor_state_key,
                lock=self._organize_state_lock,
            )
        return self._organize_state_store

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
        self._organize_state_lock = self._organize_state_lock or threading.RLock()
        self._organize_state_store = OrganizerStateStore(
            read=self.get_data,
            write=self.save_data,
            key=self._monitor_state_key,
            lock=self._organize_state_lock,
        )
        migration = self._organize_state_store.migrate_from_v322(
            monitor_path=self._organize_monitor_path
        )
        self._organize_monitor_initialized = True
        logger.info(
            "【光鸭云盘助手】【自动整理】恢复设置: enabled=%s path=%s interval=%ss stability=%ss batch=%s recursive=%s state=%s",
            self._organize_monitor_enabled,
            self._organize_monitor_path,
            self._organize_monitor_interval,
            self._organize_monitor_stability,
            self._organize_monitor_batch_size,
            self._organize_monitor_recursive,
            migration,
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

    def _is_monitored_path(self, value: Any) -> bool:
        """终态事件只归属当前监控根，避免手动整理污染自动监控状态。"""
        try:
            path = PurePosixPath(self._organize_normalize_path(value))
            root = PurePosixPath(self._organize_monitor_path)
            return root != PurePosixPath("/") and (path == root or path.is_relative_to(root))
        except (TypeError, ValueError):
            return False

    def _scan_cloud_files(self, root_path: str) -> Tuple[List[Any], bool]:
        """只枚举文件，不在插件内识别媒体或计算分类目录。"""
        if not self._guangya_api:
            raise RuntimeError("光鸭云盘尚未登录或存储未初始化")
        root = self._guangya_api.get_item(Path(root_path))
        if not root or root.type != "dir":
            raise RuntimeError(f"监控目录不存在: {root_path}")

        files: List[Any] = []
        queue = deque([root])
        visited = 0
        truncated = False
        while queue:
            current = queue.popleft()
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
        lock = self._organize_state_lock or threading.RLock()
        self._organize_state_lock = lock
        with lock:
            history = list(self.get_data(self._monitor_history_key) or [])
            history.append(row)
            self.save_data(self._monitor_history_key, history[-self._monitor_history_limit:])

    def _save_monitor_status(self, **kwargs: Any) -> Dict[str, Any]:
        lock = self._organize_state_lock or threading.RLock()
        self._organize_state_lock = lock
        with lock:
            status = dict(self.get_data(self._monitor_status_key) or {})
            status.update(kwargs)
            self.save_data(self._monitor_status_key, status)
            return status

    def _dispatch_to_moviepilot(self, item: Any) -> bool:
        """默认整理入口：MoviePilot 原生 TransferDispatcher。"""
        return bool(self._get_organize_dispatcher().handle_file(
            storage=self._disk_name,
            event_path=Path(str(item.path or "")),
            file_size=int(getattr(item, "size", 0) or 0),
            file_modify_time=float(getattr(item, "modify_time", 0) or 0),
            fileid=str(getattr(item, "fileid", "") or "") or None,
        ))

    def _history_row(
        self,
        *,
        now_text: str,
        item: Any,
        path: str,
        result: str,
        message: str,
    ) -> Dict[str, Any]:
        return {
            "time": now_text,
            "path": path,
            "name": str(getattr(item, "name", "") or Path(path).name),
            "size": int(getattr(item, "size", 0) or 0),
            "result": result,
            "message": message,
        }

    def _preflight_history(self, item: Any, path: str) -> Dict[str, Any]:
        """在显式 TransferChain 路径前也统一执行 MP 历史闸，避免绕过宿主去重。"""
        return inspect_moviepilot_history(
            storage=self._disk_name,
            path=Path(path),
            file_size=int(getattr(item, "size", 0) or 0),
            file_modify_time=float(getattr(item, "modify_time", 0) or 0),
            fileid=str(getattr(item, "fileid", "") or "") or None,
        )

    def run_organize_monitor_scan(self, manual: bool = False) -> Dict[str, Any]:
        """执行发现→稳定→MP历史预检→入队；最终成功/失败由 MoviePilot 事件回写。"""
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
            inventory_paths = {
                self._organize_normalize_path(getattr(item, "path", "")) for item in files
            }
            state = self._state()
            state.reconcile_inventory(inventory_paths, truncated=truncated)

            now = time.time()
            ready: List[Tuple[Any, str, str]] = []
            waiting = inflight = retry_wait = completed = ignored = blocked = 0
            changed = 0
            for item in files:
                path = self._organize_normalize_path(getattr(item, "path", ""))
                fp = self._fingerprint(item)
                phase = state.classify(
                    path=path,
                    fingerprint=fp,
                    now=now,
                    stability_seconds=self._organize_monitor_stability,
                    inflight_lease_seconds=self._monitor_inflight_lease,
                )
                if phase == "completed":
                    completed += 1
                    continue
                if phase == "ignored":
                    ignored += 1
                    continue
                if phase == "blocked":
                    blocked += 1
                    continue
                changed += 1
                if phase == "stabilizing":
                    waiting += 1
                elif phase == "inflight":
                    inflight += 1
                elif phase == "retry_wait":
                    retry_wait += 1
                elif phase == "ready":
                    ready.append((item, path, fp))

            ready.sort(key=lambda row: float(getattr(row[0], "modify_time", 0) or 0))
            ready = ready[:self._organize_monitor_batch_size]

            submitted = deferred = failed = unsupported = history_completed = newly_blocked = 0
            errors: List[str] = []
            for item, path, fp in ready:
                event_path = Path(path)
                if not dispatcher.is_transfer_candidate_path(event_path):
                    unsupported += 1
                    state.mark_ignored(path=path, fingerprint=fp)
                    self._append_monitor_history(self._history_row(
                        now_text=now_text,
                        item=item,
                        path=path,
                        result="ignored",
                        message="MoviePilot 当前媒体/字幕/音频扩展名规则不处理该文件",
                    ))
                    continue

                preflight = self._preflight_history(item, path)
                decision = str(preflight.get("decision") or "unknown")
                preflight_message = str(preflight.get("message") or "")
                if decision == "completed":
                    history_completed += 1
                    state.mark_completed(path=path, fingerprint=fp)
                    self._append_monitor_history(self._history_row(
                        now_text=now_text,
                        item=item,
                        path=path,
                        result="history_completed",
                        message=preflight_message,
                    ))
                    continue
                if decision == "blocked":
                    newly_blocked += 1
                    state.mark_blocked(
                        path=path,
                        fingerprint=fp,
                        reason=preflight_message,
                        now=time.time(),
                    )
                    self._append_monitor_history(self._history_row(
                        now_text=now_text,
                        item=item,
                        path=path,
                        result="blocked",
                        message=f"{preflight_message}；10 分钟后自动重新检查，也可手动解除等待",
                    ))
                    continue
                if decision == "unknown":
                    deferred += 1
                    retry = state.mark_deferred(
                        path=path,
                        fingerprint=fp,
                        now=time.time(),
                        reason=preflight_message or "MoviePilot 整理历史暂不可用",
                    )
                    self._append_monitor_history(self._history_row(
                        now_text=now_text,
                        item=item,
                        path=path,
                        result="deferred",
                        message=f"{preflight_message}；{int(retry.get('delay') or 0)} 秒后重试",
                    ))
                    continue

                attempts = state.mark_submitting(
                    path=path,
                    fingerprint=fp,
                    now=time.time(),
                    metadata={
                        "name": str(getattr(item, "name", "") or Path(path).name),
                        "size": int(getattr(item, "size", 0) or 0),
                        "history_action": preflight.get("action"),
                    },
                )
                if attempts == 0:
                    continue
                try:
                    accepted = self._dispatch_to_moviepilot(item)
                    if accepted:
                        submitted += 1
                        self._append_monitor_history(self._history_row(
                            now_text=now_text,
                            item=item,
                            path=path,
                            result="queued",
                            message=f"已进入 MoviePilot 整理链，等待最终回执（第 {attempts} 次）",
                        ))
                    else:
                        deferred += 1
                        retry = state.mark_deferred(
                            path=path,
                            fingerprint=fp,
                            now=time.time(),
                            reason="MoviePilot 预检允许提交，但当前未接收入队：可能为 TTL 去重或并发门控",
                        )
                        self._append_monitor_history(self._history_row(
                            now_text=now_text,
                            item=item,
                            path=path,
                            result="deferred",
                            message=f"MoviePilot 暂未接收入队，{int(retry.get('delay') or 0)} 秒后自动重试",
                        ))
                except Exception as err:
                    failed += 1
                    errors.append(f"{path}: {err}")
                    retry = state.mark_failed(
                        path=path,
                        fingerprint=fp,
                        now=time.time(),
                        reason=str(err),
                    )
                    logger.error(
                        "【光鸭云盘助手】【自动整理】提交 MP 整理链失败: %s - %s；%s 秒后重试",
                        path,
                        err,
                        int(retry.get("delay") or 0),
                    )

            state.set_metadata(monitor_path=self._organize_monitor_path, updated_at=now_text)
            state_counts = state.stats()
            status = self._save_monitor_status(
                running=self._organize_monitor_enabled,
                last_scan=now_text,
                monitor_path=self._organize_monitor_path,
                inventory=len(files),
                changed=changed,
                waiting=waiting,
                inflight=state_counts["inflight"],
                retry_wait=state_counts["retry_wait"],
                completed=state_counts["completed"],
                ignored=state_counts["ignored"],
                blocked=state_counts["blocked"],
                submitted=submitted,
                history_completed=history_completed,
                deferred=deferred,
                unsupported=unsupported,
                newly_blocked=newly_blocked,
                failed=failed,
                truncated=truncated,
                duration_ms=int((time.time() - started) * 1000),
                errors=errors[:10],
                state_schema=OrganizerStateStore.schema_version,
            )
            message = (
                f"扫描完成：文件 {len(files)}，待处理 {changed}，提交 MP {submitted}，"
                f"整理中 {state_counts['inflight']}，历史已完成 {history_completed}，"
                f"重试等待 {state_counts['retry_wait']}，受 MP 门控 {state_counts['blocked']}，"
                f"等待稳定 {waiting}，忽略 {unsupported}，提交异常 {failed}"
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
            storage_names_getter = getattr(self, "_storage_names", None)
            storage_names = storage_names_getter() if callable(storage_names_getter) else {self._disk_name}
            source_dirs = [item for item in dirs if str(getattr(item, "storage", "") or "") in storage_names]
            return {
                "directory_count": len(dirs),
                "organize_enabled_count": len(enabled),
                "guangya_directory_count": len(source_dirs),
                "message": "分类、命名、目标目录、整理方式、覆盖与刮削均使用 MoviePilot 当前内置目录配置",
            }
        except Exception as err:
            return {
                "directory_count": 0,
                "organize_enabled_count": 0,
                "guangya_directory_count": 0,
                "message": f"读取 MoviePilot 目录配置失败: {err}",
            }

    def _organizer_selfcheck(self) -> Dict[str, Any]:
        self.init_organizer_monitor()
        from .organizer_runtime import organizer_runtime_bound_to

        checks = {
            "plugin_enabled": bool(self._enabled),
            "storage_ready": bool(self._guangya_api),
            "runtime_bridge": organizer_runtime_bound_to(self),
            "monitor_path_selected": self._organize_monitor_path != "/",
            "state_schema": OrganizerStateStore.schema_version,
        }
        try:
            if self._guangya_api and self._organize_monitor_path != "/":
                folder = self._guangya_api.get_item(Path(self._organize_monitor_path))
                checks["monitor_path_exists"] = bool(folder and folder.type == "dir")
            else:
                checks["monitor_path_exists"] = False
        except Exception as err:
            checks["monitor_path_exists"] = False
            checks["monitor_path_error"] = str(err)
        checks.update({f"state_{k}": v for k, v in self._state().stats().items()})
        critical = ("plugin_enabled", "storage_ready", "runtime_bridge", "monitor_path_selected", "monitor_path_exists")
        healthy = all(bool(checks.get(name)) for name in critical) if self._organize_monitor_enabled else bool(checks["runtime_bridge"])
        return {"healthy": healthy, "checks": checks, "mp": self._moviepilot_directory_summary()}

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
                self._state().reset_for_monitor_path(path)
            else:
                self._state().set_metadata(monitor_path=path)
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
        status.update({f"state_{k}": v for k, v in self._state().stats().items()})
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

    def api_organize_monitor_selfcheck(self) -> Dict[str, Any]:
        report = self._organizer_selfcheck()
        return {"success": True, "message": "自动整理自检完成", "data": report}

    def api_organize_monitor_unblock(self, payload: dict = None) -> Dict[str, Any]:
        count = self._state().clear_blocked()
        return {
            "success": True,
            "message": f"已解除 {count} 个 MoviePilot 门控等待项；下一次扫描会重新预检",
            "data": {"unblocked": count},
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
            {"path": "/organize/monitor/selfcheck", "endpoint": self.api_organize_monitor_selfcheck, "auth": "bear", "methods": ["GET"], "summary": "自动整理运行时自检", "response_model": GuangYaOrganizerResponse},
            {"path": "/organize/monitor/unblock", "endpoint": self.api_organize_monitor_unblock, "auth": "bear", "methods": ["POST"], "summary": "重新检查被 MoviePilot 门控的文件", "response_model": GuangYaOrganizerResponse},
        ]
