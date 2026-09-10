"""v3.7.6：将自动整理发现改造成显式“增量监控 + 全量兜底”双通道。

设计借鉴 CloudLinkMonitor 的核心结构，但适配远端云盘没有本地 watchdog 文件事件的事实：
- 增量通道：每个监控周期优先回访 pending、检查 known-resource 内容变化，并继续推进
  一页持久 discovery 游标，因此已有资源变化与新建资源目录都不会只依赖低频全量扫描；
- 全量通道：用户/定时触发后建立持久 full-scan session，重置 discovery 游标，从监控根
  开始完整遍历。单 Worker 忙时只暂停扫描，不结束 session；任务收尾后自动继续下一页，
  直到 cycle_complete 才真正结束；
- 手动入口独立：增量一次、启动全量、停止全量。旧 /organize/monitor/scan 保持兼容，
  语义升级为“启动完整全量扫描”；
- 可观测性：每次扫描拥有 scan_id，并统一输出 1/6~6/6 阶段日志与状态字段。

本层只编排扫描，不改变 MoviePilot 媒体识别、分类、命名、目标目录、覆盖、刮削和文件
处置策略；具体资源调度继续调用 v3.6.6/v3.7.x 既有 _v360_schedule_resource 链。
"""

from __future__ import annotations

import datetime
import time
import uuid
from typing import Any, Dict, List, Sequence

from app.sdk.logging import logger

from .models import GuangYaOrganizerResponse


_FULL_SESSION_KEY = "organize_v376_full_scan_session"
_FULL_LAST_KEY = "organize_v376_full_scan_last"
_FULL_SCAN_INTERVAL = 1800.0
_FULL_STEP_MIN_GAP = 2.0
_STAGE_TOTAL = 6


class GuangYaOrganizerDualScanV376Mixin:
    """最终扫描编排层：显式区分 incremental 与 full。"""

    _v376_scan_id: str = ""
    _v376_scan_mode: str = ""
    _v376_scan_trigger: str = ""
    _v376_full_last_step_mono: float = 0.0

    # ------------------------------------------------------------------
    # trace / session state
    # ------------------------------------------------------------------
    @staticmethod
    def _v376_new_scan_id(mode: str) -> str:
        prefix = "FULL" if str(mode).lower() == "full" else "INC"
        stamp = datetime.datetime.now().strftime("%m%d-%H%M%S")
        return f"{prefix}-{stamp}-{uuid.uuid4().hex[:4]}"

    @staticmethod
    def _v376_mode_text(mode: str) -> str:
        return "全量" if str(mode).lower() == "full" else "增量"

    def _v376_trace(
        self,
        stage: int,
        title: str,
        message: str,
        *,
        level: str = "info",
        scan_id: str = "",
        mode: str = "",
        persist: bool = True,
    ) -> None:
        sid = scan_id or self._v376_scan_id or "NO-SCAN"
        actual_mode = mode or self._v376_scan_mode or "incremental"
        line = (
            f"【光鸭云盘助手】【整理】【{sid}】【{stage}/{_STAGE_TOTAL} {title}】"
            f"{message}"
        )
        log_func = getattr(logger, level, logger.info)
        log_func(line)
        if persist:
            try:
                self._save_monitor_status(
                    scan_id=sid,
                    scan_mode=actual_mode,
                    scan_mode_label=self._v376_mode_text(actual_mode),
                    scan_trigger=self._v376_scan_trigger,
                    scan_stage=title,
                    scan_stage_no=int(stage),
                    scan_stage_total=_STAGE_TOTAL,
                    scan_message=message,
                    scan_updated_at=time.time(),
                )
            except Exception:
                pass

    def _v376_load_full_session(self) -> Dict[str, Any]:
        raw = self.get_data(_FULL_SESSION_KEY) or {}
        if not isinstance(raw, dict):
            return {}
        root = self._v360_norm(getattr(self, "_organize_monitor_path", ""))
        if self._v360_norm(raw.get("monitor_path")) != root:
            return {}
        return dict(raw)

    def _v376_save_full_session(self, session: Dict[str, Any]) -> None:
        payload = dict(session or {})
        payload["updated_at"] = time.time()
        self.save_data(_FULL_SESSION_KEY, payload)

    def _v376_full_due(self) -> bool:
        raw = self.get_data(_FULL_LAST_KEY) or {}
        if not isinstance(raw, dict):
            return True
        root = self._v360_norm(getattr(self, "_organize_monitor_path", ""))
        if self._v360_norm(raw.get("monitor_path")) != root:
            return True
        completed_at = float(raw.get("completed_at") or 0)
        return completed_at <= 0 or time.time() - completed_at >= _FULL_SCAN_INTERVAL

    def _v376_mark_full_complete(self, session: Dict[str, Any]) -> None:
        completed_at = time.time()
        self.save_data(
            _FULL_LAST_KEY,
            {
                "monitor_path": self._v360_norm(getattr(self, "_organize_monitor_path", "")),
                "completed_at": completed_at,
                "scan_id": str(session.get("scan_id") or ""),
            },
        )
        # 同步既有 baseline 时间戳以及 v3.7.5 一次性恢复标记。
        marker = getattr(self, "_v366_mark_baseline_complete", None)
        if callable(marker):
            marker()

    def _v376_set_context(self, scan_id: str, mode: str, trigger: str) -> tuple[str, str, str]:
        previous = (
            str(getattr(self, "_v376_scan_id", "") or ""),
            str(getattr(self, "_v376_scan_mode", "") or ""),
            str(getattr(self, "_v376_scan_trigger", "") or ""),
        )
        self._v376_scan_id = scan_id
        self._v376_scan_mode = mode
        self._v376_scan_trigger = trigger
        return previous

    def _v376_restore_context(self, previous: tuple[str, str, str]) -> None:
        self._v376_scan_id, self._v376_scan_mode, self._v376_scan_trigger = previous

    # ------------------------------------------------------------------
    # resource stage tracing
    # ------------------------------------------------------------------
    def _v360_schedule_resource(self, group_path: str, files: Sequence[Any]) -> Dict[str, Any]:
        sid = str(getattr(self, "_v376_scan_id", "") or "")
        primary_count = len(self._v360_primary_files(files))
        if sid:
            self._v376_trace(
                4,
                "判定",
                f"资源={self._v360_norm(group_path)} 主媒体={primary_count}，进入稳定性/历史/重试/完成态判定",
                persist=True,
            )

        result = dict(super()._v360_schedule_resource(group_path, files) or {})
        if not sid:
            return result

        phases = dict(result.get("phases") or {})
        ready = int(phases.get("ready") or 0)
        waiting = sum(
            int(phases.get(name) or 0)
            for name in ("stabilizing", "history_wait", "retry_wait", "inflight")
        )
        if result.get("scheduled"):
            self._v376_trace(
                5,
                "入队",
                (
                    f"资源={self._v360_norm(group_path)} submitted={int(result.get('submitted') or 0)} "
                    f"ready={ready} wait={waiting}，已交给单 Worker"
                ),
                persist=True,
            )
        else:
            self._v376_trace(
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

    # ------------------------------------------------------------------
    # scan channels
    # ------------------------------------------------------------------
    def _v376_run_incremental(self, *, trigger: str = "monitor") -> Dict[str, Any]:
        scan_id = self._v376_new_scan_id("incremental")
        previous = self._v376_set_context(scan_id, "incremental", trigger)
        started = time.time()
        root = self._v360_norm(getattr(self, "_organize_monitor_path", ""))
        try:
            self._v376_trace(1, "触发", f"来源={trigger}，执行一次增量检查")
            self._v376_trace(
                2,
                "准备",
                f"监控目录={root}；顺序=pending→known变化→discovery推进1页",
            )
            # manual=True 的 v3.6.6 路径会在 known 未提交后继续推进一页 discovery，
            # 与仅 known-resource 的旧自动入口不同，因此新目录也能持续被发现。
            result = dict(super().run_organize_monitor_scan(manual=True) or {})
            data = dict(result.get("data") or {})
            dirs_scanned = int(data.get("dirs_scanned") or 0)
            files_seen = int(data.get("files_seen") or 0)
            resources = int(data.get("resource_dirs") or 0)
            remaining = int(data.get("remaining_dirs") or 0)
            scheduled = bool(data.get("scheduled"))
            self._v376_trace(
                3,
                "发现",
                (
                    f"目录={dirs_scanned} 文件={files_seen} 资源目录={resources} "
                    f"剩余游标={remaining} scheduled={int(scheduled)}"
                ),
            )
            elapsed = round(time.time() - started, 3)
            self._save_monitor_status(
                incremental_last_at=time.time(),
                incremental_last_scan_id=scan_id,
                incremental_last_duration=elapsed,
                full_scan_active=bool(self._v376_load_full_session().get("active")),
            )
            self._v376_trace(
                6,
                "完成",
                f"增量轮次结束，耗时={elapsed}s；下一轮继续从持久游标推进",
            )
            data.update(
                {
                    "scan_id": scan_id,
                    "scan_mode": "incremental",
                    "scan_trigger": trigger,
                }
            )
            result["data"] = data
            if result.get("success", True):
                result["message"] = result.get("message") or "增量扫描完成"
            return result
        except Exception as err:
            self._v376_trace(6, "失败", f"增量扫描异常: {err}", level="error")
            raise
        finally:
            self._v376_restore_context(previous)

    def _v376_start_full(self, *, trigger: str = "manual") -> Dict[str, Any]:
        self.init_organizer_monitor()
        root = self._v360_norm(getattr(self, "_organize_monitor_path", ""))
        if root == "/":
            return {"success": False, "message": "请先选择具体监控目录，禁止直接扫描根目录"}
        if not getattr(self, "_enabled", False) or not getattr(self, "_guangya_api", None):
            return {"success": False, "message": "光鸭云盘未启用或未登录"}

        existing = self._v376_load_full_session()
        if bool(existing.get("active")):
            result = self._v376_run_full_step(trigger="manual-resume" if trigger == "manual" else trigger)
            result.setdefault("data", {})["already_active"] = True
            return result

        scan_id = self._v376_new_scan_id("full")
        cursor = self._v360_load_cursor(root)
        next_cycle = max(int(cursor.get("cycle") or 1), 1)
        self._v360_save_cursor(self._v360_new_cursor(root, cycle=next_cycle))
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
            "paused": False,
            "stop_requested": False,
        }
        self._v376_save_full_session(session)
        previous = self._v376_set_context(scan_id, "full", trigger)
        try:
            self._v376_trace(1, "触发", f"来源={trigger}，启动完整目录树全量扫描")
            self._v376_trace(
                2,
                "准备",
                f"监控目录={root}；已重置 discovery 游标，全量会话保持到 cycle_complete",
            )
        finally:
            self._v376_restore_context(previous)
        return self._v376_run_full_step(trigger=trigger)

    def _v376_run_full_step(self, *, trigger: str = "resume") -> Dict[str, Any]:
        session = self._v376_load_full_session()
        if not bool(session.get("active")):
            return {
                "success": True,
                "message": "当前没有运行中的全量扫描",
                "data": {"full_scan_active": False},
            }

        scan_id = str(session.get("scan_id") or self._v376_new_scan_id("full"))
        original_trigger = str(session.get("trigger") or trigger)
        previous = self._v376_set_context(scan_id, "full", original_trigger)
        try:
            result = dict(super().run_organize_monitor_scan(manual=True) or {})
            data = dict(result.get("data") or {})

            if data.get("busy") or data.get("handoff") or data.get("scan_busy"):
                session["paused"] = True
                session["pause_reason"] = (
                    "worker_busy" if data.get("busy") else "handoff" if data.get("handoff") else "scan_busy"
                )
                self._v376_save_full_session(session)
                self._save_monitor_status(
                    full_scan_active=True,
                    full_scan_id=scan_id,
                    full_scan_paused=True,
                    full_scan_pause_reason=session["pause_reason"],
                    full_scan_started_at=float(session.get("started_at") or 0),
                )
                return {
                    "success": True,
                    "message": "全量扫描会话已保留；当前整理/交接结束后自动继续",
                    "data": {
                        **data,
                        "scan_id": scan_id,
                        "scan_mode": "full",
                        "full_scan_active": True,
                        "full_scan_paused": True,
                    },
                }

            session["paused"] = False
            session["pause_reason"] = ""
            page_dirs = int(data.get("dirs_scanned") or 0)
            page_files = int(data.get("files_seen") or 0)
            page_resources = int(data.get("resource_dirs") or 0)
            if page_dirs or page_files or page_resources or "cycle_complete" in data:
                session["pages"] = int(session.get("pages") or 0) + 1
            session["dirs_scanned"] = int(session.get("dirs_scanned") or 0) + page_dirs
            session["files_seen"] = int(session.get("files_seen") or 0) + page_files
            session["resource_dirs"] = int(session.get("resource_dirs") or 0) + page_resources
            if bool(data.get("scheduled")):
                session["scheduled_resources"] = int(session.get("scheduled_resources") or 0) + 1
            session["errors"] = int(session.get("errors") or 0) + len(list(data.get("errors") or []))
            session["remaining_dirs"] = int(data.get("remaining_dirs") or 0)

            self._v376_trace(
                3,
                "发现",
                (
                    f"全量页={session.get('pages', 0)} 本页目录={page_dirs} 本页文件={page_files} "
                    f"累计资源目录={session.get('resource_dirs', 0)} 剩余游标={session.get('remaining_dirs', 0)}"
                ),
            )

            cycle_complete = bool(data.get("cycle_complete"))
            if cycle_complete:
                session["active"] = False
                session["completed_at"] = time.time()
                session["remaining_dirs"] = 0
                self._v376_save_full_session(session)
                self._v376_mark_full_complete(session)
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
                self._v376_trace(
                    6,
                    "完成",
                    (
                        f"全量遍历完成：页={session.get('pages', 0)} 目录={session.get('dirs_scanned', 0)} "
                        f"文件={session.get('files_seen', 0)} 资源目录={session.get('resource_dirs', 0)} "
                        f"提交资源={session.get('scheduled_resources', 0)} 耗时={elapsed}s"
                    ),
                )
            else:
                self._v376_save_full_session(session)
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
            if cycle_complete:
                result["message"] = "全量扫描已完整遍历监控目录"
            else:
                result["message"] = "全量扫描已启动/继续；会自动续页直到完整遍历"
            return result
        except Exception as err:
            session["last_error"] = str(err)
            session["errors"] = int(session.get("errors") or 0) + 1
            self._v376_save_full_session(session)
            self._v376_trace(6, "失败", f"全量扫描本步异常，会话保留等待下次继续: {err}", level="error")
            return {
                "success": False,
                "message": f"全量扫描本步失败，已保留扫描断点: {err}",
                "data": {"scan_id": scan_id, "scan_mode": "full", "full_scan_active": True},
            }
        finally:
            self._v376_restore_context(previous)

    def _v376_stop_full(self, *, trigger: str = "manual") -> Dict[str, Any]:
        session = self._v376_load_full_session()
        if not bool(session.get("active")):
            return {
                "success": True,
                "message": "当前没有运行中的全量扫描",
                "data": {"full_scan_active": False},
            }
        session["active"] = False
        session["stop_requested"] = True
        session["stopped_at"] = time.time()
        session["stopped_by"] = trigger
        self._v376_save_full_session(session)
        scan_id = str(session.get("scan_id") or "")
        previous = self._v376_set_context(scan_id, "full", str(session.get("trigger") or trigger))
        try:
            self._v376_trace(
                6,
                "停止",
                "用户停止全量 discovery；不会中断正在执行的 MoviePilot 文件整理任务",
            )
            self._save_monitor_status(
                full_scan_active=False,
                full_scan_paused=False,
                full_scan_stopped_at=float(session.get("stopped_at") or 0),
            )
        finally:
            self._v376_restore_context(previous)
        return {
            "success": True,
            "message": "已停止全量扫描续页；当前正在整理的资源不会被中断",
            "data": {"scan_id": scan_id, "full_scan_active": False},
        }

    # ------------------------------------------------------------------
    # scheduler authority
    # ------------------------------------------------------------------
    def organize_monitor_tick(self) -> None:
        self.init_organizer_monitor()
        if not getattr(self, "_organize_monitor_enabled", False):
            return

        now_mono = time.monotonic()
        session = self._v376_load_full_session()
        if bool(session.get("active")):
            last = float(getattr(self, "_v376_full_last_step_mono", 0.0) or 0.0)
            if last and now_mono - last < _FULL_STEP_MIN_GAP:
                return
            self._v376_full_last_step_mono = now_mono
            return self._v376_run_full_step(trigger="auto-resume")

        if self._v376_full_due():
            self._v376_full_last_step_mono = now_mono
            return self._v376_start_full(trigger="scheduled")

        interval = max(float(getattr(self, "_organize_monitor_interval", 60) or 60), 1.0)
        last = float(getattr(self, "_v360_last_tick", 0.0) or 0.0)
        if last and now_mono - last < interval:
            return
        self._v360_last_tick = now_mono
        self._organize_monitor_last_tick = now_mono
        return self._v376_run_incremental(trigger="monitor")

    def run_organize_monitor_scan(self, manual: bool = False) -> Dict[str, Any]:
        """兼容旧调用：manual=True 表示用户要求完整全量；自动调用走一次增量。"""
        if manual:
            return self._v376_start_full(trigger="legacy-manual")
        session = self._v376_load_full_session()
        if bool(session.get("active")):
            return self._v376_run_full_step(trigger="auto-resume")
        return self._v376_run_incremental(trigger="monitor")

    # ------------------------------------------------------------------
    # API / status
    # ------------------------------------------------------------------
    def api_organize_monitor_scan(self, payload: dict = None) -> Dict[str, Any]:
        """旧立即扫描按钮/API 保持兼容，但升级为真正的完整全量扫描会话。"""
        return self._v376_start_full(trigger="manual")

    def api_organize_monitor_incremental_scan(self, payload: dict = None) -> Dict[str, Any]:
        return self._v376_run_incremental(trigger="manual")

    def api_organize_monitor_full_scan(self, payload: dict = None) -> Dict[str, Any]:
        return self._v376_start_full(trigger="manual")

    def api_organize_monitor_full_scan_stop(self, payload: dict = None) -> Dict[str, Any]:
        return self._v376_stop_full(trigger="manual")

    def api_organize_monitor_status(self) -> Dict[str, Any]:
        response = super().api_organize_monitor_status()
        if not isinstance(response, dict) or not response.get("success"):
            return response
        data = response.setdefault("data", {})
        status = data.setdefault("status", {})
        session = self._v376_load_full_session()
        full_last = self.get_data(_FULL_LAST_KEY) or {}
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
                "full_scan_last_completed_at": float((full_last or {}).get("completed_at") or 0),
                "full_scan_interval": int(_FULL_SCAN_INTERVAL),
                "incremental_strategy": "pending->known->discovery-page",
                "log_stage_schema": "1触发/2准备/3发现/4判定/5入队/6完成",
            }
        )
        return response

    def get_organizer_api(self) -> List[Dict[str, Any]]:
        apis = list(super().get_organizer_api() or [])
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
        apis.extend(item for item in additions if str(item.get("path") or "") not in existing)
        return apis


__all__ = ["GuangYaOrganizerDualScanV376Mixin"]
