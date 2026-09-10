"""v3.7.6：显式“增量监控 + 全量兜底”双通道扫描编排。

借鉴 CloudLinkMonitor 的核心思想：实时/增量链负责快速发现变化，全量链负责完整兜底，
两条链最终共用同一套资源处理逻辑。光鸭是远端云盘，没有本地 watchdog 事件，因此增量
链使用短周期轮询：pending -> known-resource 签名变化 -> discovery 游标推进一页；这样
既能快速处理已知剧集新增集，也能持续发现新建目录。全量链则建立持久 session，从监控
根目录重置游标后持续续页，遇到单 Worker 正在整理只暂停，不把会话误判为完成。

日志统一为 scan_id + 1/6~6/6 阶段；旧扫描器的业务规则、MoviePilot 媒体识别/分类/
命名/目标目录/覆盖/刮削和文件处置策略全部保持不变。
"""

from __future__ import annotations

import datetime
import time
import uuid
from typing import Any, Dict, List, Sequence

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


def _mode_text(mode: str) -> str:
    return "全量" if mode == "full" else "增量"


def _load_full(plugin: Any) -> Dict[str, Any]:
    raw = plugin.get_data(_FULL_SESSION_KEY) or {}
    if not isinstance(raw, dict):
        return {}
    root = plugin._v360_norm(getattr(plugin, "_organize_monitor_path", ""))
    if plugin._v360_norm(raw.get("monitor_path")) != root:
        return {}
    return dict(raw)


def _save_full(plugin: Any, session: Dict[str, Any]) -> None:
    payload = dict(session or {})
    payload["updated_at"] = time.time()
    plugin.save_data(_FULL_SESSION_KEY, payload)


def _trace(
    plugin: Any,
    stage: int,
    title: str,
    message: str,
    *,
    level: str = "info",
    persist: bool = True,
) -> None:
    scan_id = str(getattr(plugin, "_v376_active_scan_id", "") or "NO-SCAN")
    mode = str(getattr(plugin, "_v376_active_scan_mode", "") or "incremental")
    trigger = str(getattr(plugin, "_v376_active_scan_trigger", "") or "")
    log_func = getattr(logger, level, logger.info)
    log_func(
        "【光鸭云盘助手】【整理】【%s】【%s/%s %s】%s",
        scan_id,
        int(stage),
        _STAGE_TOTAL,
        title,
        message,
    )
    if not persist:
        return
    try:
        plugin._save_monitor_status(
            scan_id=scan_id,
            scan_mode=mode,
            scan_mode_label=_mode_text(mode),
            scan_trigger=trigger,
            scan_stage=title,
            scan_stage_no=int(stage),
            scan_stage_total=_STAGE_TOTAL,
            scan_message=message,
            scan_updated_at=time.time(),
        )
    except Exception:
        pass


def _set_context(plugin: Any, scan_id: str, mode: str, trigger: str) -> tuple[str, str, str]:
    previous = (
        str(getattr(plugin, "_v376_active_scan_id", "") or ""),
        str(getattr(plugin, "_v376_active_scan_mode", "") or ""),
        str(getattr(plugin, "_v376_active_scan_trigger", "") or ""),
    )
    plugin._v376_active_scan_id = scan_id
    plugin._v376_active_scan_mode = mode
    plugin._v376_active_scan_trigger = trigger
    return previous


def _restore_context(plugin: Any, previous: tuple[str, str, str]) -> None:
    (
        plugin._v376_active_scan_id,
        plugin._v376_active_scan_mode,
        plugin._v376_active_scan_trigger,
    ) = previous


def _full_due(plugin: Any) -> bool:
    raw = plugin.get_data(_FULL_LAST_KEY) or {}
    if not isinstance(raw, dict):
        return True
    root = plugin._v360_norm(getattr(plugin, "_organize_monitor_path", ""))
    if plugin._v360_norm(raw.get("monitor_path")) != root:
        return True
    now = time.time()
    suppressed_until = float(raw.get("suppressed_until") or 0)
    if suppressed_until > now:
        return False
    completed_at = float(raw.get("completed_at") or 0)
    return completed_at <= 0 or now - completed_at >= _FULL_SCAN_INTERVAL


def install_dual_scan_v376() -> None:
    """在最终 v3.6.6 monitor 边界安装双通道编排；保持现有 MRO 不变。"""
    if bool(getattr(_MonitorMixin, _INSTALL_FLAG, False)):
        return

    original_schedule = _MonitorMixin._v360_schedule_resource
    original_run = _MonitorMixin.run_organize_monitor_scan
    original_status = _MonitorMixin.api_organize_monitor_status
    original_get_api = _BaseOrganizerMixin.get_organizer_api

    def schedule_wrapped(self, group_path: str, files: Sequence[Any]) -> Dict[str, Any]:
        scan_id = str(getattr(self, "_v376_active_scan_id", "") or "")
        primary_count = len(self._v360_primary_files(files))
        if scan_id:
            _trace(
                self,
                4,
                "判定",
                f"资源={self._v360_norm(group_path)} 主媒体={primary_count}，检查稳定/历史/重试/完成态",
            )
        result = dict(original_schedule(self, group_path, files) or {})
        if not scan_id:
            return result
        phases = dict(result.get("phases") or {})
        ready = int(phases.get("ready") or 0)
        waiting = sum(
            int(phases.get(name) or 0)
            for name in ("stabilizing", "history_wait", "retry_wait", "inflight")
        )
        if result.get("scheduled"):
            _trace(
                self,
                5,
                "入队",
                (
                    f"资源={self._v360_norm(group_path)} submitted={int(result.get('submitted') or 0)} "
                    f"ready={ready} wait={waiting}，已交给单 Worker"
                ),
            )
        else:
            _trace(
                self,
                4,
                "判定",
                (
                    f"资源={self._v360_norm(group_path)} reason={result.get('reason') or '-'} "
                    f"ready={ready} wait={waiting} phases={phases}"
                ),
                level="debug",
                persist=False,
            )
        return result

    def run_incremental(self, trigger: str = "monitor") -> Dict[str, Any]:
        scan_id = _new_scan_id("incremental")
        previous = _set_context(self, scan_id, "incremental", trigger)
        started = time.time()
        root = self._v360_norm(getattr(self, "_organize_monitor_path", ""))
        try:
            _trace(self, 1, "触发", f"来源={trigger}，执行一次增量检查")
            _trace(self, 2, "准备", f"目录={root}；顺序=pending→known变化→discovery推进1页")
            result = dict(original_run(self, manual=True) or {})
            data = dict(result.get("data") or {})
            dirs_scanned = int(data.get("dirs_scanned") or 0)
            files_seen = int(data.get("files_seen") or 0)
            resources = int(data.get("resource_dirs") or 0)
            remaining = int(data.get("remaining_dirs") or 0)
            _trace(
                self,
                3,
                "发现",
                (
                    f"目录={dirs_scanned} 文件={files_seen} 资源目录={resources} "
                    f"剩余游标={remaining} scheduled={int(bool(data.get('scheduled')))}"
                ),
            )
            elapsed = round(time.time() - started, 3)
            self._save_monitor_status(
                incremental_last_at=time.time(),
                incremental_last_scan_id=scan_id,
                incremental_last_duration=elapsed,
            )
            _trace(self, 6, "完成", f"增量轮次结束，耗时={elapsed}s；下轮从持久游标继续")
            data.update({"scan_id": scan_id, "scan_mode": "incremental", "scan_trigger": trigger})
            result["data"] = data
            result["message"] = result.get("message") or "增量扫描完成"
            return result
        except Exception as err:
            _trace(self, 6, "失败", f"增量扫描异常: {err}", level="error")
            return {"success": False, "message": f"增量扫描失败: {err}", "data": {"scan_id": scan_id}}
        finally:
            _restore_context(self, previous)

    def run_full_step(self, trigger: str = "resume") -> Dict[str, Any]:
        session = _load_full(self)
        if not bool(session.get("active")):
            return {"success": True, "message": "当前没有运行中的全量扫描", "data": {"full_scan_active": False}}
        scan_id = str(session.get("scan_id") or _new_scan_id("full"))
        original_trigger = str(session.get("trigger") or trigger)
        previous = _set_context(self, scan_id, "full", original_trigger)
        try:
            result = dict(original_run(self, manual=True) or {})
            data = dict(result.get("data") or {})
            if data.get("busy") or data.get("handoff") or data.get("scan_busy"):
                reason = "worker_busy" if data.get("busy") else "handoff" if data.get("handoff") else "scan_busy"
                session.update({"paused": True, "pause_reason": reason})
                _save_full(self, session)
                self._save_monitor_status(
                    full_scan_active=True,
                    full_scan_id=scan_id,
                    full_scan_paused=True,
                    full_scan_pause_reason=reason,
                    full_scan_started_at=float(session.get("started_at") or 0),
                )
                return {
                    "success": True,
                    "message": "全量扫描会话已保留；当前任务结束后自动继续",
                    "data": {**data, "scan_id": scan_id, "scan_mode": "full", "full_scan_active": True, "full_scan_paused": True},
                }

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
            if bool(data.get("scheduled")):
                session["scheduled_resources"] = int(session.get("scheduled_resources") or 0) + 1
            session["errors"] = int(session.get("errors") or 0) + len(list(data.get("errors") or []))
            session["remaining_dirs"] = int(data.get("remaining_dirs") or 0)
            _trace(
                self,
                3,
                "发现",
                (
                    f"全量页={session.get('pages', 0)} 本页目录={page_dirs} 本页文件={page_files} "
                    f"累计资源={session.get('resource_dirs', 0)} 剩余游标={session.get('remaining_dirs', 0)}"
                ),
            )

            if bool(data.get("cycle_complete")):
                session.update({"active": False, "completed_at": time.time(), "remaining_dirs": 0})
                _save_full(self, session)
                self.save_data(
                    _FULL_LAST_KEY,
                    {
                        "monitor_path": self._v360_norm(getattr(self, "_organize_monitor_path", "")),
                        "completed_at": float(session.get("completed_at") or 0),
                        "scan_id": scan_id,
                        "suppressed_until": 0,
                    },
                )
                marker = getattr(self, "_v366_mark_baseline_complete", None)
                if callable(marker):
                    marker()
                elapsed = round(time.time() - float(session.get("started_at") or time.time()), 3)
                self._save_monitor_status(
                    full_scan_active=False,
                    full_scan_id=scan_id,
                    full_scan_paused=False,
                    full_scan_completed_at=float(session.get("completed_at") or 0),
                    full_scan_pages=int(session.get("pages") or 0),
                    full_scan_dirs=int(session.get("dirs_scanned") or 0),
                    full_scan_files=int(session.get("files_seen") or 0),
                    full_scan_resources=int(session.get("resource_dirs") or 0),
                    full_scan_scheduled=int(session.get("scheduled_resources") or 0),
                )
                _trace(
                    self,
                    6,
                    "完成",
                    (
                        f"全量遍历完成：页={session.get('pages', 0)} 目录={session.get('dirs_scanned', 0)} "
                        f"文件={session.get('files_seen', 0)} 资源={session.get('resource_dirs', 0)} "
                        f"提交={session.get('scheduled_resources', 0)} 耗时={elapsed}s"
                    ),
                )
            else:
                _save_full(self, session)
                self._save_monitor_status(
                    full_scan_active=True,
                    full_scan_id=scan_id,
                    full_scan_paused=False,
                    full_scan_started_at=float(session.get("started_at") or 0),
                    full_scan_pages=int(session.get("pages") or 0),
                    full_scan_dirs=int(session.get("dirs_scanned") or 0),
                    full_scan_files=int(session.get("files_seen") or 0),
                    full_scan_resources=int(session.get("resource_dirs") or 0),
                    full_scan_remaining_dirs=int(session.get("remaining_dirs") or 0),
                )
            data.update(
                {
                    "scan_id": scan_id,
                    "scan_mode": "full",
                    "full_scan_active": bool(session.get("active")),
                    "full_scan_pages": int(session.get("pages") or 0),
                    "full_scan_dirs": int(session.get("dirs_scanned") or 0),
                    "full_scan_files": int(session.get("files_seen") or 0),
                    "full_scan_resources": int(session.get("resource_dirs") or 0),
                    "full_scan_remaining_dirs": int(session.get("remaining_dirs") or 0),
                }
            )
            result["data"] = data
            result["message"] = (
                "全量扫描已完整遍历监控目录"
                if not session.get("active")
                else "全量扫描正在进行；会自动续页直到完整遍历"
            )
            return result
        except Exception as err:
            session["last_error"] = str(err)
            session["errors"] = int(session.get("errors") or 0) + 1
            _save_full(self, session)
            _trace(self, 6, "失败", f"全量本步异常，断点保留: {err}", level="error")
            return {
                "success": False,
                "message": f"全量扫描本步失败，已保留断点: {err}",
                "data": {"scan_id": scan_id, "scan_mode": "full", "full_scan_active": True},
            }
        finally:
            _restore_context(self, previous)

    def start_full(self, trigger: str = "manual") -> Dict[str, Any]:
        self.init_organizer_monitor()
        root = self._v360_norm(getattr(self, "_organize_monitor_path", ""))
        if root == "/":
            return {"success": False, "message": "请先选择具体监控目录，禁止直接扫描根目录"}
        if not getattr(self, "_enabled", False) or not getattr(self, "_guangya_api", None):
            return {"success": False, "message": "光鸭云盘未启用或未登录"}
        existing = _load_full(self)
        if bool(existing.get("active")):
            return run_full_step(self, "manual-resume" if trigger == "manual" else trigger)

        scan_id = _new_scan_id("full")
        current_cursor = self._v360_load_cursor(root)
        cycle = max(int(current_cursor.get("cycle") or 1), 1)
        self._v360_save_cursor(self._v360_new_cursor(root, cycle=cycle))
        session = {
            "active": True,
            "scan_id": scan_id,
            "monitor_path": root,
            "trigger": trigger,
            "started_at": time.time(),
            "pages": 0,
            "dirs_scanned": 0,
            "files_seen": 0,
            "resource_dirs": 0,
            "scheduled_resources": 0,
            "errors": 0,
            "remaining_dirs": 1,
            "paused": False,
        }
        _save_full(self, session)
        previous = _set_context(self, scan_id, "full", trigger)
        try:
            _trace(self, 1, "触发", f"来源={trigger}，启动完整目录树全量扫描")
            _trace(self, 2, "准备", f"目录={root}；已重置 discovery 游标，会话保持到 cycle_complete")
        finally:
            _restore_context(self, previous)
        return run_full_step(self, trigger)

    def stop_full(self, trigger: str = "manual") -> Dict[str, Any]:
        session = _load_full(self)
        if not bool(session.get("active")):
            return {"success": True, "message": "当前没有运行中的全量扫描", "data": {"full_scan_active": False}}
        stopped_at = time.time()
        session.update({"active": False, "stopped_at": stopped_at, "stopped_by": trigger})
        _save_full(self, session)
        scan_id = str(session.get("scan_id") or "")
        last = self.get_data(_FULL_LAST_KEY) or {}
        if not isinstance(last, dict):
            last = {}
        self.save_data(
            _FULL_LAST_KEY,
            {
                **last,
                "monitor_path": self._v360_norm(getattr(self, "_organize_monitor_path", "")),
                "suppressed_until": stopped_at + _FULL_SCAN_INTERVAL,
                "stopped_at": stopped_at,
                "stopped_scan_id": scan_id,
            },
        )
        previous = _set_context(self, scan_id, "full", str(session.get("trigger") or trigger))
        try:
            _trace(self, 6, "停止", "停止全量 discovery 续页；30 分钟内不自动重启，不中断当前文件整理")
            self._save_monitor_status(
                full_scan_active=False,
                full_scan_paused=False,
                full_scan_suppressed_until=stopped_at + _FULL_SCAN_INTERVAL,
            )
        finally:
            _restore_context(self, previous)
        return {
            "success": True,
            "message": "已停止全量扫描续页；当前整理不中断，30 分钟内不会自动重启全量",
            "data": {"scan_id": scan_id, "full_scan_active": False},
        }

    def run_wrapped(self, manual: bool = False) -> Dict[str, Any]:
        if manual:
            return start_full(self, "legacy-manual")
        if bool(_load_full(self).get("active")):
            return run_full_step(self, "auto-resume")
        return run_incremental(self, "monitor")

    def tick_wrapped(self) -> None:
        self.init_organizer_monitor()
        if not getattr(self, "_organize_monitor_enabled", False):
            return
        now_mono = time.monotonic()
        session = _load_full(self)
        if bool(session.get("active")):
            last = float(getattr(self, "_v376_full_last_step_mono", 0.0) or 0.0)
            if last and now_mono - last < _FULL_STEP_MIN_GAP:
                return
            self._v376_full_last_step_mono = now_mono
            return run_full_step(self, "auto-resume")

        if _full_due(self):
            self._v376_full_last_step_mono = now_mono
            return start_full(self, "scheduled")

        interval = max(float(getattr(self, "_organize_monitor_interval", 60) or 60), 1.0)
        last = float(getattr(self, "_v360_last_tick", 0.0) or 0.0)
        if last and now_mono - last < interval:
            return
        self._v360_last_tick = now_mono
        self._organize_monitor_last_tick = now_mono
        return run_incremental(self, "monitor")

    def api_scan_wrapped(self, payload: dict = None) -> Dict[str, Any]:
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
        data = response.setdefault("data", {})
        status = data.setdefault("status", {})
        session = _load_full(self)
        full_last = self.get_data(_FULL_LAST_KEY) or {}
        if not isinstance(full_last, dict):
            full_last = {}
        status.update(
            {
                "scan_engine": "dual-channel-v3.7.6",
                "full_scan_active": bool(session.get("active")),
                "full_scan_id": str(session.get("scan_id") or ""),
                "full_scan_trigger": str(session.get("trigger") or ""),
                "full_scan_paused": bool(session.get("paused")),
                "full_scan_pause_reason": str(session.get("pause_reason") or ""),
                "full_scan_started_at": float(session.get("started_at") or 0),
                "full_scan_pages": int(session.get("pages") or 0),
                "full_scan_dirs": int(session.get("dirs_scanned") or 0),
                "full_scan_files": int(session.get("files_seen") or 0),
                "full_scan_resources": int(session.get("resource_dirs") or 0),
                "full_scan_scheduled": int(session.get("scheduled_resources") or 0),
                "full_scan_remaining_dirs": int(session.get("remaining_dirs") or 0),
                "full_scan_last_completed_at": float(full_last.get("completed_at") or 0),
                "full_scan_suppressed_until": float(full_last.get("suppressed_until") or 0),
                "full_scan_interval": int(_FULL_SCAN_INTERVAL),
                "incremental_strategy": "pending->known->discovery-page",
                "log_stage_schema": "1触发/2准备/3发现/4判定/5入队/6完成",
            }
        )
        return response

    def get_api_wrapped(self) -> List[Dict[str, Any]]:
        apis = list(original_get_api(self) or [])
        additions = [
            {
                "path": "/organize/monitor/incremental-scan",
                "endpoint": self.api_organize_monitor_incremental_scan,
                "auth": "bear",
                "methods": ["POST"],
                "summary": "立即执行一次增量监控扫描",
                "response_model": GuangYaOrganizerResponse,
            },
            {
                "path": "/organize/monitor/full-scan",
                "endpoint": self.api_organize_monitor_full_scan,
                "auth": "bear",
                "methods": ["POST"],
                "summary": "启动完整全量目录扫描",
                "response_model": GuangYaOrganizerResponse,
            },
            {
                "path": "/organize/monitor/full-scan/stop",
                "endpoint": self.api_organize_monitor_full_scan_stop,
                "auth": "bear",
                "methods": ["POST"],
                "summary": "停止全量扫描续页",
                "response_model": GuangYaOrganizerResponse,
            },
        ]
        existing = {str(item.get("path") or "") for item in apis}
        apis.extend(row for row in additions if str(row.get("path") or "") not in existing)
        return apis

    _MonitorMixin._v360_schedule_resource = schedule_wrapped
    _MonitorMixin.run_organize_monitor_scan = run_wrapped
    _MonitorMixin.organize_monitor_tick = tick_wrapped
    _MonitorMixin.api_organize_monitor_scan = api_scan_wrapped
    _MonitorMixin.api_organize_monitor_incremental_scan = api_incremental
    _MonitorMixin.api_organize_monitor_full_scan = api_full
    _MonitorMixin.api_organize_monitor_full_scan_stop = api_full_stop
    _MonitorMixin.api_organize_monitor_status = status_wrapped
    _MonitorMixin._v376_run_incremental = run_incremental
    _MonitorMixin._v376_start_full_scan = start_full
    _MonitorMixin._v376_run_full_scan_step = run_full_step
    _MonitorMixin._v376_stop_full_scan = stop_full
    _BaseOrganizerMixin.get_organizer_api = get_api_wrapped
    setattr(_MonitorMixin, _INSTALL_FLAG, True)


__all__ = ["install_dual_scan_v376"]
