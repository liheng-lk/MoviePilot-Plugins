"""MoviePilot 原生整理队列观测与光鸭旧积压恢复。

本层只使用 MoviePilot 已公开的 TransferChain 队列视图与 remove_from_queue 边界，
并复用宿主 global_vars.stop_transfer 取消语义。它不会访问或清空 ``_queue``、不会
停止/重启 worker，也不会碰非光鸭来源任务。
"""

from __future__ import annotations

import time
from pathlib import PurePosixPath
from typing import Any, Dict, Iterable, List, Set

from app.chain.transfer import TransferChain
from app.runtime.config import global_vars
from app.sdk.logging import logger

from .models import GuangYaOrganizerResponse


class GuangYaQueueRecoveryMixin:
    """观测 MoviePilot 原生队列，并提供显式的光鸭积压恢复入口。"""

    _queue_recovery_pause_seconds = 120
    _queue_recovery_pause_until: float = 0.0

    @staticmethod
    def _queue_obj_get(obj: Any, name: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    def _queue_storage_names(self) -> Set[str]:
        names: Set[str] = {
            str(getattr(self, "_disk_name", "") or ""),
            str(getattr(self, "_legacy_disk_name", "") or ""),
        }
        getter = getattr(self, "_storage_names", None)
        if callable(getter):
            try:
                names.update(str(value or "") for value in (getter() or []))
            except Exception:
                pass
        return {name for name in names if name}

    def _queue_path_is_current_monitor(self, value: Any) -> bool:
        try:
            monitor = self._organize_normalize_path(self._organize_monitor_path)
            if monitor == "/":
                return False
            path = self._organize_normalize_path(value)
            return PurePosixPath(path) == PurePosixPath(monitor) or PurePosixPath(path).is_relative_to(PurePosixPath(monitor))
        except Exception:
            return False

    def _native_guangya_queue_rows(self, *, monitor_only: bool = False) -> List[Dict[str, Any]]:
        """读取 MoviePilot 正式队列视图，绝不读取 TransferChain 私有 queue。"""
        rows: List[Dict[str, Any]] = []
        storage_names = self._queue_storage_names()
        try:
            jobs = TransferChain().get_queue_tasks() or []
        except Exception as err:
            logger.warning("【光鸭云盘助手】【队列恢复】读取 MoviePilot 整理队列失败: %s", err)
            return rows

        for job in jobs:
            media = self._queue_obj_get(job, "media")
            media_title = str(
                self._queue_obj_get(media, "title_year")
                or self._queue_obj_get(media, "title")
                or ""
            )
            season = self._queue_obj_get(job, "season")
            for task in self._queue_obj_get(job, "tasks", []) or []:
                fileitem = self._queue_obj_get(task, "fileitem")
                if not fileitem:
                    continue
                storage = str(self._queue_obj_get(fileitem, "storage", "") or "")
                if storage not in storage_names:
                    continue
                path = str(self._queue_obj_get(fileitem, "path", "") or "")
                if not path:
                    continue
                if monitor_only and not self._queue_path_is_current_monitor(path):
                    continue
                rows.append({
                    "fileitem": fileitem,
                    "storage": storage,
                    "path": path,
                    "name": str(self._queue_obj_get(fileitem, "name", "") or PurePosixPath(path).name),
                    "state": str(self._queue_obj_get(task, "state", "waiting") or "waiting"),
                    "media_title": media_title,
                    "season": season,
                })
        return rows

    def _native_queue_snapshot(self) -> Dict[str, Any]:
        """返回当前光鸭在 MoviePilot 原生整理队列里的真实占用。"""
        try:
            jobs = TransferChain().get_queue_tasks() or []
        except Exception as err:
            return {
                "available": False,
                "error": str(err),
                "total": 0,
                "guangya_total": 0,
                "guangya_active": 0,
                "guangya_waiting": 0,
                "guangya_running": 0,
                "guangya_failed": 0,
                "guangya_completed": 0,
                "monitor_active": 0,
                "sample": [],
            }

        total = 0
        storage_names = self._queue_storage_names()
        rows: List[Dict[str, Any]] = []
        state_counts: Dict[str, int] = {}
        monitor_active = 0
        for job in jobs:
            media = self._queue_obj_get(job, "media")
            media_title = str(
                self._queue_obj_get(media, "title_year")
                or self._queue_obj_get(media, "title")
                or ""
            )
            for task in self._queue_obj_get(job, "tasks", []) or []:
                total += 1
                fileitem = self._queue_obj_get(task, "fileitem")
                if not fileitem:
                    continue
                storage = str(self._queue_obj_get(fileitem, "storage", "") or "")
                if storage not in storage_names:
                    continue
                path = str(self._queue_obj_get(fileitem, "path", "") or "")
                state = str(self._queue_obj_get(task, "state", "waiting") or "waiting")
                state_counts[state] = state_counts.get(state, 0) + 1
                if state in {"waiting", "running"} and self._queue_path_is_current_monitor(path):
                    monitor_active += 1
                if len(rows) < 20:
                    rows.append({
                        "path": path,
                        "name": str(self._queue_obj_get(fileitem, "name", "") or PurePosixPath(path).name),
                        "state": state,
                        "media_title": media_title,
                    })

        guangya_total = sum(state_counts.values())
        waiting = int(state_counts.get("waiting", 0))
        running = int(state_counts.get("running", 0))
        return {
            "available": True,
            "error": "",
            "total": total,
            "guangya_total": guangya_total,
            "guangya_active": waiting + running,
            "guangya_waiting": waiting,
            "guangya_running": running,
            "guangya_failed": int(state_counts.get("failed", 0)),
            "guangya_completed": int(state_counts.get("completed", 0)),
            "monitor_active": monitor_active,
            "sample": rows,
        }

    def _queue_recovery_remaining(self) -> int:
        return max(int(self._queue_recovery_pause_until - time.time()), 0)

    def _backpressure_snapshot(self, now: float | None = None) -> Dict[str, Any]:
        """把 MoviePilot 原生队列占用纳入背压，避免旧队列未记入插件 state 时继续灌入。"""
        snapshot = dict(super()._backpressure_snapshot(now=now))
        native = self._native_queue_snapshot()
        native_active = int(native.get("monitor_active") or native.get("guangya_active") or 0)
        plugin_inflight = int(snapshot.get("inflight") or 0)
        occupied = max(plugin_inflight, native_active)
        limit = max(int(snapshot.get("max_inflight") or 1), 1)
        recovery_remaining = self._queue_recovery_remaining()

        snapshot["plugin_inflight"] = plugin_inflight
        snapshot["native_guangya_active"] = native_active
        snapshot["native_guangya_waiting"] = int(native.get("guangya_waiting") or 0)
        snapshot["native_guangya_running"] = int(native.get("guangya_running") or 0)
        snapshot["native_guangya_total"] = int(native.get("guangya_total") or 0)
        snapshot["native_queue_total"] = int(native.get("total") or 0)
        snapshot["native_queue_available"] = bool(native.get("available"))
        snapshot["inflight"] = occupied
        snapshot["native_backlog"] = max(native_active - limit, 0)
        snapshot["recovery_required"] = snapshot["native_backlog"] > 0
        snapshot["recovery_paused"] = recovery_remaining > 0
        snapshot["recovery_pause_remaining"] = recovery_remaining

        if recovery_remaining > 0:
            snapshot["slots"] = 0
        elif not snapshot.get("stalled"):
            snapshot["slots"] = max(limit - occupied, 0)
        return snapshot

    def _save_monitor_status(self, **kwargs: Any) -> Dict[str, Any]:
        snapshot = self._backpressure_snapshot()
        kwargs.update({
            "native_queue_total": snapshot.get("native_queue_total", 0),
            "native_guangya_total": snapshot.get("native_guangya_total", 0),
            "native_guangya_active": snapshot.get("native_guangya_active", 0),
            "native_guangya_waiting": snapshot.get("native_guangya_waiting", 0),
            "native_guangya_running": snapshot.get("native_guangya_running", 0),
            "native_backlog": snapshot.get("native_backlog", 0),
            "queue_recovery_required": snapshot.get("recovery_required", False),
            "queue_recovery_paused": snapshot.get("recovery_paused", False),
            "queue_recovery_pause_remaining": snapshot.get("recovery_pause_remaining", 0),
        })
        return super()._save_monitor_status(**kwargs)

    def organize_monitor_tick(self) -> None:
        if self._queue_recovery_remaining() > 0:
            self._save_monitor_status(
                dispatch_paused=True,
                dispatch_pause_reason="正在释放旧光鸭整理队列，暂停新增任务",
            )
            return
        return super().organize_monitor_tick()

    def run_organize_monitor_scan(self, manual: bool = False) -> Dict[str, Any]:
        remaining = self._queue_recovery_remaining()
        if remaining > 0:
            return {
                "success": False,
                "message": f"正在释放旧光鸭整理队列，约 {remaining} 秒后恢复扫描提交",
                "data": {"queue_recovery_paused": True, "queue_recovery_pause_remaining": remaining},
            }
        return super().run_organize_monitor_scan(manual=manual)

    def api_organize_monitor_status(self) -> Dict[str, Any]:
        response = super().api_organize_monitor_status()
        if isinstance(response, dict):
            data = response.setdefault("data", {})
            data["native_queue"] = self._native_queue_snapshot()
        return response

    def _organizer_selfcheck(self) -> Dict[str, Any]:
        result = dict(super()._organizer_selfcheck() or {})
        checks = result.setdefault("checks", {})
        native = self._native_queue_snapshot()
        checks.update({
            "native_queue_available": bool(native.get("available")),
            "native_queue_total": int(native.get("total") or 0),
            "native_guangya_total": int(native.get("guangya_total") or 0),
            "native_guangya_waiting": int(native.get("guangya_waiting") or 0),
            "native_guangya_running": int(native.get("guangya_running") or 0),
            "native_monitor_active": int(native.get("monitor_active") or 0),
            "queue_recovery_required": int(native.get("monitor_active") or 0) > max(int(checks.get("dispatch_max_inflight") or 1), 1),
            "queue_recovery_pause_remaining": self._queue_recovery_remaining(),
        })
        result["native_queue"] = native
        return result

    def _reopen_queue_paths(self, paths: Iterable[str]) -> int:
        state = self._state()
        method = getattr(state, "reopen_paths", None)
        if callable(method):
            return int(method(paths) or 0)

        normalized = {self._organize_normalize_path(path) for path in paths if path}
        def _apply(raw: Dict[str, Any]) -> int:
            changed = 0
            for path in normalized:
                for name in ("blocked", "stabilizing", "inflight", "retry"):
                    if path in raw.get(name, {}):
                        raw[name].pop(path, None)
                        changed += 1
            return changed
        return int(state.mutate(_apply) or 0)

    def api_organize_monitor_recover_queue(self, payload: dict = None) -> Dict[str, Any]:
        """显式取消旧光鸭排队任务；默认只处理当前监控目录的 waiting 项。"""
        payload = payload or {}
        if payload.get("confirm") is not True:
            return {"success": False, "message": "需要 confirm=true 才会清理旧光鸭整理队列"}

        include_running = bool(payload.get("include_running", False))
        monitor_only = bool(payload.get("monitor_only", True))
        if monitor_only and self._organize_monitor_path == "/":
            return {"success": False, "message": "当前未选择具体监控目录，拒绝批量取消以避免影响手工光鸭任务"}

        rows = self._native_guangya_queue_rows(monitor_only=monitor_only)
        allowed_states = {"waiting"}
        if include_running:
            allowed_states.add("running")
        targets = [row for row in rows if row.get("state") in allowed_states]
        if not targets:
            return {
                "success": True,
                "message": "当前没有符合条件的旧光鸭排队任务",
                "data": {"cancelled": 0, "reopened": 0, "native_queue": self._native_queue_snapshot()},
            }

        chain = TransferChain()
        cancelled = 0
        failed: List[str] = []
        paths: List[str] = []
        seen = set()
        for row in targets:
            path = str(row.get("path") or "")
            storage = str(row.get("storage") or "")
            key = (storage, path)
            if not path or key in seen:
                continue
            seen.add(key)
            fileitem = row.get("fileitem")
            try:
                # 与 MoviePilot 官方 DELETE /transfer/queue 使用同一公开取消语义。
                chain.remove_from_queue(fileitem)
                global_vars.stop_transfer(path)
                cancelled += 1
                paths.append(path)
            except Exception as err:
                failed.append(f"{path}: {err}")

        reopened = self._reopen_queue_paths(paths)
        self._queue_recovery_pause_until = time.time() + self._queue_recovery_pause_seconds
        self._organize_monitor_last_tick = 0.0
        writer = getattr(self, "_write_pending_groups", None)
        if callable(writer):
            try:
                writer([])
            except Exception:
                pass

        native_after = self._native_queue_snapshot()
        self._save_monitor_status(
            queue_recovery_cancelled=cancelled,
            queue_recovery_reopened=reopened,
            queue_recovery_failed=len(failed),
            queue_recovery_last_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            queue_recovery_errors=failed[:10],
            dispatch_paused=True,
            dispatch_pause_reason="已取消旧光鸭排队任务，等待 MoviePilot worker 快速释放已取消队列项",
        )
        logger.warning(
            "【光鸭云盘助手】【队列恢复】取消旧光鸭任务=%s 重新开放状态=%s 失败=%s include_running=%s monitor_only=%s",
            cancelled,
            reopened,
            len(failed),
            include_running,
            monitor_only,
        )
        message = (
            f"已向 MoviePilot 取消 {cancelled} 个旧光鸭{'等待/运行' if include_running else '等待'}任务，"
            f"重新开放 {reopened} 个插件状态；暂停新增 {self._queue_recovery_pause_seconds} 秒让官方队列释放。"
        )
        if failed:
            message += f" 其中 {len(failed)} 个取消失败，请查看状态错误。"
        return {
            "success": not failed,
            "message": message,
            "data": {
                "cancelled": cancelled,
                "reopened": reopened,
                "failed": len(failed),
                "pause_seconds": self._queue_recovery_pause_seconds,
                "native_queue": native_after,
            },
        }

    def get_organizer_api(self) -> List[Dict[str, Any]]:
        apis = list(super().get_organizer_api())
        apis.append({
            "path": "/organize/monitor/recover-queue",
            "endpoint": self.api_organize_monitor_recover_queue,
            "auth": "bear",
            "methods": ["POST"],
            "summary": "清理当前监控目录的旧光鸭整理队列积压",
            "response_model": GuangYaOrganizerResponse,
        })
        return apis


__all__ = ["GuangYaQueueRecoveryMixin"]
