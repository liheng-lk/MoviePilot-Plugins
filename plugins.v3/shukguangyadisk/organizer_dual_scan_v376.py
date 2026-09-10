"""v3.7.6：自动整理显式“增量监控 + 持久全量兜底”双通道。

本层只负责编排扫描触发与可观测性，MoviePilot 继续负责媒体识别、分类、命名、目标目录、
冲突和真实整理执行。
"""
from __future__ import annotations

import datetime
import time
import uuid
from typing import Any, Dict, Sequence

from app.sdk.logging import logger

from .models import GuangYaOrganizerResponse
from .organizer import GuangYaOrganizerMixin as _BaseOrganizerMixin
from .organizer_monitor_v366 import GuangYaOrganizerMonitorV366Mixin as _MonitorMixin

_FULL_SESSION_KEY = "organize_v376_full_scan_session"
_FULL_LAST_KEY = "organize_v376_full_scan_last"
_FULL_SCAN_INTERVAL = 1800.0
_FULL_STEP_MIN_GAP = 2.0
_STAGE_TOTAL = 6
_INSTALL_FLAG = "_v376_dual_scan_installed"


def _new_scan_id(mode: str) -> str:
    prefix = "FULL" if mode == "full" else "INC"
    return f"{prefix}-{datetime.datetime.now().strftime('%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"


def _norm(plugin: Any, value: Any) -> str:
    return plugin._v360_norm(value)


def _load_full(plugin: Any) -> Dict[str, Any]:
    raw = plugin.get_data(_FULL_SESSION_KEY) or {}
    if not isinstance(raw, dict):
        return {}
    root = _norm(plugin, getattr(plugin, "_organize_monitor_path", ""))
    if _norm(plugin, raw.get("monitor_path")) != root:
        return {}
    return dict(raw)


def _save_full(plugin: Any, session: Dict[str, Any]) -> None:
    row = dict(session or {})
    row["updated_at"] = time.time()
    plugin.save_data(_FULL_SESSION_KEY, row)


def _trace(plugin: Any, stage: int, title: str, message: str, *, level: str = "info") -> None:
    scan_id = str(getattr(plugin, "_v376_active_scan_id", "") or "NO-SCAN")
    mode = str(getattr(plugin, "_v376_active_scan_mode", "") or "incremental")
    trigger = str(getattr(plugin, "_v376_active_scan_trigger", "") or "")
    getattr(logger, level, logger.info)(
        "【光鸭云盘助手】【整理】【%s】【%s/%s %s】%s",
        scan_id, stage, _STAGE_TOTAL, title, message,
    )
    try:
        plugin._save_monitor_status(
            scan_id=scan_id,
            scan_mode=mode,
            scan_mode_label="全量" if mode == "full" else "增量",
            scan_trigger=trigger,
            scan_stage=title,
            scan_stage_no=stage,
            scan_stage_total=_STAGE_TOTAL,
            scan_message=message,
            scan_updated_at=time.time(),
        )
    except Exception:
        pass


def _set_context(plugin: Any, scan_id: str, mode: str, trigger: str):
    old = (
        str(getattr(plugin, "_v376_active_scan_id", "") or ""),
        str(getattr(plugin, "_v376_active_scan_mode", "") or ""),
        str(getattr(plugin, "_v376_active_scan_trigger", "") or ""),
    )
    plugin._v376_active_scan_id = scan_id
    plugin._v376_active_scan_mode = mode
    plugin._v376_active_scan_trigger = trigger
    return old


def _restore_context(plugin: Any, old) -> None:
    plugin._v376_active_scan_id, plugin._v376_active_scan_mode, plugin._v376_active_scan_trigger = old


def _full_due(plugin: Any) -> bool:
    raw = plugin.get_data(_FULL_LAST_KEY) or {}
    if not isinstance(raw, dict):
        return True
    root = _norm(plugin, getattr(plugin, "_organize_monitor_path", ""))
    if _norm(plugin, raw.get("monitor_path")) != root:
        return True
    now = time.time()
    if float(raw.get("suppressed_until") or 0) > now:
        return False
    completed = float(raw.get("completed_at") or 0)
    return completed <= 0 or now - completed >= _FULL_SCAN_INTERVAL


def install_dual_scan_v376() -> None:
    """只覆盖 monitor/API 触发面；所有媒体业务规则仍走既有链路。"""
    if bool(getattr(_MonitorMixin, _INSTALL_FLAG, False)):
        return

    original_schedule = _MonitorMixin._v360_schedule_resource
    original_run = _MonitorMixin.run_organize_monitor_scan
    original_tick = _MonitorMixin.organize_monitor_tick
    original_status = _MonitorMixin.api_organize_monitor_status
    original_get_api = _BaseOrganizerMixin.get_organizer_api

    def schedule_wrapped(self, group_path: str, files: Sequence[Any]) -> Dict[str, Any]:
        scan_id = str(getattr(self, "_v376_active_scan_id", "") or "")
        if scan_id:
            _trace(self, 4, "判定", f"资源={_norm(self, group_path)} 主媒体={len(self._v360_primary_files(files))}")
        result = dict(original_schedule(self, group_path, files) or {})
        if scan_id and result.get("scheduled"):
            _trace(self, 5, "入队", f"资源={_norm(self, group_path)} submitted={int(result.get('submitted') or 0)}")
        return result

    def run_incremental(self, trigger: str = "monitor") -> Dict[str, Any]:
        scan_id = _new_scan_id("incremental")
        old = _set_context(self, scan_id, "incremental", trigger)
        started = time.time()
        try:
            _trace(self, 1, "触发", f"来源={trigger}，执行增量检查")
            _trace(self, 2, "准备", f"目录={_norm(self, getattr(self, '_organize_monitor_path', ''))}；pending→known→discovery")
            result = dict(original_run(self, manual=(trigger == "manual")) or {})
            data = dict(result.get("data") or {})
            if data.get("priority_revisit") and not data.get("scheduled") and not any(data.get(k) for k in ("busy", "handoff", "scan_busy")):
                result = dict(original_run(self, manual=True) or {})
                data = dict(result.get("data") or {})
            if data.get("known_scan"):
                detail = f"known={int(data.get('known_checked') or 0)}/{int(data.get('known_total') or 0)} changed={int(data.get('known_changed') or 0)}"
            elif data.get("priority_revisit"):
                detail = f"pending={data.get('path') or '-'} scheduled={int(bool(data.get('scheduled')))}"
            else:
                detail = f"dirs={int(data.get('dirs_scanned') or 0)} files={int(data.get('files_seen') or 0)} remain={int(data.get('remaining_dirs') or 0)}"
            _trace(self, 3, "发现", detail)
            elapsed = round(time.time() - started, 3)
            self._save_monitor_status(incremental_last_at=time.time(), incremental_last_scan_id=scan_id, incremental_last_duration=elapsed)
            _trace(self, 6, "完成", f"增量轮次结束，耗时={elapsed}s")
            data.update({"scan_id": scan_id, "scan_mode": "incremental"})
            result["data"] = data
            return result
        except Exception as err:
            _trace(self, 6, "失败", f"增量扫描异常: {err}", level="error")
            return {"success": False, "message": f"增量扫描失败: {err}", "data": {"scan_id": scan_id}}
        finally:
            _restore_context(self, old)

    def run_full_step(self, trigger: str = "resume") -> Dict[str, Any]:
        session = _load_full(self)
        if not session.get("active"):
            return {"success": True, "message": "当前没有运行中的全量扫描", "data": {"full_scan_active": False}}
        scan_id = str(session.get("scan_id") or _new_scan_id("full"))
        old = _set_context(self, scan_id, "full", str(session.get("trigger") or trigger))
        try:
            result = dict(original_run(self, manual=True) or {})
            data = dict(result.get("data") or {})
            if any(data.get(k) for k in ("busy", "handoff", "scan_busy")):
                reason = "worker_busy" if data.get("busy") else "handoff" if data.get("handoff") else "scan_busy"
                session.update({"paused": True, "pause_reason": reason})
                _save_full(self, session)
                self._save_monitor_status(full_scan_active=True, full_scan_id=scan_id, full_scan_paused=True, full_scan_pause_reason=reason)
                return {"success": True, "message": "全量扫描已暂停，Worker 空闲后自动继续", "data": {**data, "scan_id": scan_id, "full_scan_active": True, "full_scan_paused": True}}

            page_dirs = int(data.get("dirs_scanned") or 0)
            page_files = int(data.get("files_seen") or 0)
            page_resources = int(data.get("resource_dirs") or 0)
            if page_dirs or page_files or page_resources or "cycle_complete" in data:
                session["pages"] = int(session.get("pages") or 0) + 1
            session["paused"] = False
            session["pause_reason"] = ""
            session["dirs_scanned"] = int(session.get("dirs_scanned") or 0) + page_dirs
            session["files_seen"] = int(session.get("files_seen") or 0) + page_files
            session["resource_dirs"] = int(session.get("resource_dirs") or 0) + page_resources
            if data.get("scheduled"):
                session["scheduled_resources"] = int(session.get("scheduled_resources") or 0) + 1
            if "remaining_dirs" in data:
                session["remaining_dirs"] = int(data.get("remaining_dirs") or 0)
            _trace(self, 3, "发现", f"全量页={int(session.get('pages') or 0)} 本页目录={page_dirs} 累计目录={int(session.get('dirs_scanned') or 0)} 剩余={int(session.get('remaining_dirs') or 0)}")

            if data.get("cycle_complete"):
                completed_at = time.time()
                session.update({"active": False, "completed_at": completed_at, "remaining_dirs": 0})
                self.save_data(_FULL_LAST_KEY, {"monitor_path": _norm(self, getattr(self, "_organize_monitor_path", "")), "completed_at": completed_at, "scan_id": scan_id, "suppressed_until": 0})
                marker = getattr(self, "_v366_mark_baseline_complete", None)
                if callable(marker):
                    marker()
                _trace(self, 6, "完成", f"全量遍历完成：页={int(session.get('pages') or 0)} 目录={int(session.get('dirs_scanned') or 0)} 文件={int(session.get('files_seen') or 0)}")
            _save_full(self, session)
            self._save_monitor_status(
                full_scan_active=bool(session.get("active")), full_scan_id=scan_id,
                full_scan_paused=bool(session.get("paused")), full_scan_pages=int(session.get("pages") or 0),
                full_scan_dirs=int(session.get("dirs_scanned") or 0), full_scan_files=int(session.get("files_seen") or 0),
                full_scan_resources=int(session.get("resource_dirs") or 0), full_scan_remaining_dirs=int(session.get("remaining_dirs") or 0),
            )
            data.update({"scan_id": scan_id, "scan_mode": "full", "full_scan_active": bool(session.get("active")), "full_scan_pages": int(session.get("pages") or 0), "full_scan_remaining_dirs": int(session.get("remaining_dirs") or 0)})
            result["data"] = data
            result["message"] = "全量扫描已完整遍历监控目录" if not session.get("active") else "全量扫描正在进行，将自动续页"
            return result
        except Exception as err:
            session["last_error"] = str(err)
            _save_full(self, session)
            _trace(self, 6, "失败", f"全量扫描异常，断点保留: {err}", level="error")
            return {"success": False, "message": f"全量扫描失败，断点已保留: {err}", "data": {"scan_id": scan_id, "full_scan_active": True}}
        finally:
            _restore_context(self, old)

    def start_full(self, trigger: str = "manual") -> Dict[str, Any]:
        self.init_organizer_monitor()
        root = _norm(self, getattr(self, "_organize_monitor_path", "/"))
        if root == "/":
            return {"success": False, "message": "请先选择具体监控目录，禁止直接扫描根目录"}
        if not getattr(self, "_enabled", False) or not getattr(self, "_guangya_api", None):
            return {"success": False, "message": "光鸭云盘未启用或未登录"}
        current = _load_full(self)
        if current.get("active"):
            return run_full_step(self, "manual-resume")
        cursor = self._v360_load_cursor(root)
        cycle = max(int(cursor.get("cycle") or 1), 1)
        self._v360_save_cursor(self._v360_new_cursor(root, cycle=cycle))
        scan_id = _new_scan_id("full")
        session = {"active": True, "scan_id": scan_id, "monitor_path": root, "trigger": trigger, "started_at": time.time(), "pages": 0, "dirs_scanned": 0, "files_seen": 0, "resource_dirs": 0, "scheduled_resources": 0, "remaining_dirs": 1, "paused": False}
        _save_full(self, session)
        old = _set_context(self, scan_id, "full", trigger)
        try:
            _trace(self, 1, "触发", f"来源={trigger}，启动完整目录树扫描")
            _trace(self, 2, "准备", f"目录={root}；游标已重置，直到 cycle_complete 才结束")
        finally:
            _restore_context(self, old)
        return run_full_step(self, trigger)

    def stop_full(self, trigger: str = "manual") -> Dict[str, Any]:
        session = _load_full(self)
        if not session.get("active"):
            return {"success": True, "message": "当前没有运行中的全量扫描", "data": {"full_scan_active": False}}
        stopped_at = time.time()
        session.update({"active": False, "stopped_at": stopped_at, "stopped_by": trigger})
        _save_full(self, session)
        self.save_data(_FULL_LAST_KEY, {"monitor_path": _norm(self, getattr(self, "_organize_monitor_path", "")), "suppressed_until": stopped_at + _FULL_SCAN_INTERVAL, "stopped_at": stopped_at, "stopped_scan_id": session.get("scan_id")})
        self._save_monitor_status(full_scan_active=False, full_scan_paused=False, full_scan_suppressed_until=stopped_at + _FULL_SCAN_INTERVAL)
        return {"success": True, "message": "已停止全量扫描续页；当前整理不中断，30 分钟内不会自动重启", "data": {"scan_id": session.get("scan_id"), "full_scan_active": False}}

    def run_wrapped(self, manual: bool = False) -> Dict[str, Any]:
        if manual:
            return start_full(self, "legacy-manual")
        if _load_full(self).get("active"):
            return run_full_step(self, "auto-resume")
        return run_incremental(self, "monitor")

    def tick_wrapped(self) -> None:
        self.init_organizer_monitor()
        if not getattr(self, "_organize_monitor_enabled", False):
            return
        now = time.monotonic()
        if _load_full(self).get("active"):
            last = float(getattr(self, "_v376_full_last_step_mono", 0) or 0)
            if last and now - last < _FULL_STEP_MIN_GAP:
                return
            self._v376_full_last_step_mono = now
            return run_full_step(self, "auto-resume")
        if _full_due(self):
            self._v376_full_last_step_mono = now
            return start_full(self, "scheduled")
        return original_tick(self)

    def api_scan(self, payload: dict = None) -> Dict[str, Any]:
        return start_full(self, "manual")

    def api_incremental(self, payload: dict = None) -> Dict[str, Any]:
        return run_incremental(self, "manual")

    def api_full(self, payload: dict = None) -> Dict[str, Any]:
        return start_full(self, "manual")

    def api_full_stop(self, payload: dict = None) -> Dict[str, Any]:
        return stop_full(self, "manual")

    def status_wrapped(self) -> Dict[str, Any]:
        response = original_status(self)
        if not isinstance(response, dict) or not response.get("success"):
            return response
        status = response.setdefault("data", {}).setdefault("status", {})
        session = _load_full(self)
        last = self.get_data(_FULL_LAST_KEY) or {}
        if not isinstance(last, dict):
            last = {}
        status.update({
            "scan_engine": "dual-channel-v3.7.6", "full_scan_active": bool(session.get("active")),
            "full_scan_id": str(session.get("scan_id") or ""), "full_scan_paused": bool(session.get("paused")),
            "full_scan_pause_reason": str(session.get("pause_reason") or ""), "full_scan_started_at": float(session.get("started_at") or 0),
            "full_scan_pages": int(session.get("pages") or 0), "full_scan_dirs": int(session.get("dirs_scanned") or 0),
            "full_scan_files": int(session.get("files_seen") or 0), "full_scan_resources": int(session.get("resource_dirs") or 0),
            "full_scan_remaining_dirs": int(session.get("remaining_dirs") or 0), "full_scan_last_completed_at": float(last.get("completed_at") or 0),
            "full_scan_suppressed_until": float(last.get("suppressed_until") or 0), "full_scan_interval": int(_FULL_SCAN_INTERVAL),
            "incremental_strategy": "pending->known->discovery-page", "log_stage_schema": "1触发/2准备/3发现/4判定/5入队/6完成",
            "log_filter_hint": "【光鸭云盘助手】【整理】",
        })
        return response

    def get_api_wrapped(self):
        apis = list(original_get_api(self) or [])
        for row in apis:
            if str(row.get("path") or "") == "/organize/monitor/scan":
                row["endpoint"] = self.api_organize_monitor_scan
                row["summary"] = "启动完整全量扫描"
        extra = [
            {"path": "/organize/monitor/incremental-scan", "endpoint": self.api_organize_monitor_incremental_scan, "auth": "bear", "methods": ["POST"], "summary": "执行一次增量扫描", "response_model": GuangYaOrganizerResponse},
            {"path": "/organize/monitor/full-scan", "endpoint": self.api_organize_monitor_full_scan, "auth": "bear", "methods": ["POST"], "summary": "开始或继续完整全量扫描", "response_model": GuangYaOrganizerResponse},
            {"path": "/organize/monitor/full-scan/stop", "endpoint": self.api_organize_monitor_full_scan_stop, "auth": "bear", "methods": ["POST"], "summary": "停止全量扫描续页", "response_model": GuangYaOrganizerResponse},
        ]
        existing = {str(row.get("path") or "") for row in apis}
        apis.extend(row for row in extra if row["path"] not in existing)
        return apis

    _MonitorMixin._v360_schedule_resource = schedule_wrapped
    _MonitorMixin.run_organize_monitor_scan = run_wrapped
    _MonitorMixin.organize_monitor_tick = tick_wrapped
    _MonitorMixin.api_organize_monitor_scan = api_scan
    _MonitorMixin.api_organize_monitor_incremental_scan = api_incremental
    _MonitorMixin.api_organize_monitor_full_scan = api_full
    _MonitorMixin.api_organize_monitor_full_scan_stop = api_full_stop
    _MonitorMixin.api_organize_monitor_status = status_wrapped
    _BaseOrganizerMixin.get_organizer_api = get_api_wrapped
    setattr(_MonitorMixin, _INSTALL_FLAG, True)
    logger.info("【光鸭云盘助手】【整理】v3.7.6 双通道扫描已启用：增量监控 + 持久全量兜底")


__all__ = ["install_dual_scan_v376", "_FULL_SESSION_KEY", "_FULL_LAST_KEY", "_full_due"]
