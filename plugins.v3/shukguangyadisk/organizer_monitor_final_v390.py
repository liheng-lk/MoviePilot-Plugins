"""v3.9.0 最终监控层：安装期零副作用，运行期静态调度。

MoviePilot V3 的插件安装事务在提交 UserInstalledPlugins 前会执行 runtime reload 与
registration refresh。旧 v3.7.6~v3.8.x 在 ``get_service()`` -> ``init_organizer_monitor()``
期间安装多层 monkey patch，意味着安装尚未提交时就会改写 MonitorMixin/API 方法；任一
兼容边界失败都会触发宿主事务回滚，表现为“插件刚安装后又消失”。

本层作为最终 MRO 第一层，明确做到：
- get_service 只返回静态 heartbeat 描述，不初始化监控、不安装 patch、不访问光鸭 API；
- heartbeat / 手动 API 才惰性初始化监控，此时插件安装事务已经完成；
- 增量观察与全量巡检只负责发现并写持久 resource queue；Worker 忙时发现不停；
- resource queue 是唯一执行入口，每次最多提交一个真实资源；
- ready 成员可先行，只有全部主媒体 ready 才允许 MoviePilot 原生目录批量；
- 所有 heartbeat 异常在插件边界内隔离，连续失败只冷却监控，不影响插件存活。

目录快照/BFS/资源队列的纯函数继续复用 ``organizer_watch_pipeline_v380``。该模块在
v3.9.0 中仅作为无副作用 core 使用，绝不调用其 install_watch_pipeline_v380()。
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from apscheduler.triggers.interval import IntervalTrigger
from app.sdk.logging import logger

from . import organizer_orchestrator_v351 as _orch
from . import organizer_watch_pipeline_v380 as _watch
from .models import GuangYaOrganizerResponse
from .organizer_folder_batch_v342 import _can_use_native_directory_batch


_WAIT_PHASES = ("stabilizing", "history_wait", "retry_wait", "inflight")
_BOOT_GRACE_SECONDS = 180.0
_FAILURE_WINDOW_SECONDS = 600.0
_FAILURE_LIMIT = 3
_COOLDOWN_SECONDS = 300.0
_FULL_SCAN_INTERVAL = 3600.0
_TERMINAL_COMPACT_BUDGET = 32


class GuangYaFinalMonitorV390Mixin:
    """静态最终监控实现；不依赖运行期类级 monkey patch。"""

    def get_service(self) -> List[Dict[str, Any]]:
        """安装注册安全：这里只声明 service，绝不初始化 monitor。"""
        base_getter = getattr(super(), "get_service", None)
        services: List[Dict[str, Any]] = []
        # 不能调用旧 GuangYaOrganizerMixin.get_service，它会在安装事务内 init monitor。
        # 只保留其它基类真正不同的 service；当前 Shuk 无其它 service，因此默认空列表。
        if callable(base_getter):
            owner = getattr(base_getter, "__self__", None)
            name = getattr(base_getter, "__qualname__", "")
            if owner is not self or "GuangYaOrganizerMixin.get_service" not in name:
                # MRO 中后继实现目前仍是 organizer.get_service；为避免未来误触安装副作用，
                # 最终层不在 registration refresh 期间级联调用任何未知 get_service。
                services = []
        services.append({
            "id": "ShukGuangYaDiskAutoMonitor",
            "name": "光鸭云盘自动整理监控",
            "trigger": IntervalTrigger(seconds=int(getattr(self, "_monitor_heartbeat", 30) or 30)),
            "func": self.organize_monitor_tick,
            "kwargs": {},
        })
        return services

    def _v390_ensure_monitor(self) -> None:
        """仅运行期调用；此时安装事务已经提交。"""
        if not bool(getattr(self, "_organize_monitor_initialized", False)):
            super().init_organizer_monitor()

    def _v390_survival_state(self) -> Dict[str, Any]:
        state = getattr(self, "_v390_monitor_survival", None)
        if not isinstance(state, dict):
            now = time.time()
            state = {
                "boot_at": now,
                "window_started_at": now,
                "failures": 0,
                "last_error_at": 0.0,
                "last_error": "",
                "cooldown_until": 0.0,
                "last_success_at": 0.0,
            }
            self._v390_monitor_survival = state
        return state

    def _v390_full_due(self) -> bool:
        state = self._v390_survival_state()
        now = time.time()
        if now - float(state.get("boot_at") or now) < _BOOT_GRACE_SECONDS:
            return False
        raw = self.get_data(_watch._FULL_LAST_KEY) or {}
        if not isinstance(raw, dict) or self._v360_norm(raw.get("monitor_path")) != _watch._root(self):
            return True
        if float(raw.get("suppressed_until") or 0) > now:
            return False
        completed = float(raw.get("completed_at") or 0)
        return completed <= 0 or now - completed >= _FULL_SCAN_INTERVAL

    def _v390_start_full(self, *, trigger: str, force_verify: bool) -> Dict[str, Any]:
        self._v390_ensure_monitor()
        root = _watch._root(self)
        if root == "/":
            return {"success": False, "message": "请先选择具体监控目录，禁止扫描根目录"}
        if not getattr(self, "_enabled", False) or not getattr(self, "_guangya_api", None):
            return {"success": False, "message": "光鸭云盘未启用或未登录"}

        existing = _watch._full_load(self)
        if existing.get("active"):
            if force_verify and not existing.get("force_verify"):
                existing.update({
                    "active": False,
                    "superseded_at": time.time(),
                    "superseded_by": "manual-force-restart",
                })
                _watch._full_save(self, existing)
            else:
                return _watch._full_step(self, trigger="manual-resume" if trigger == "manual" else trigger)

        scan_id = _watch._scan_id("FULL")
        state = {
            "active": True,
            "scan_id": scan_id,
            "trigger": trigger,
            "force_verify": bool(force_verify),
            "started_at": time.time(),
            "queue": [root],
            "seen": [root],
            "dirs_scanned": 0,
            "files_seen": 0,
            "resource_dirs": 0,
            "queued_resources": 0,
            "errors": 0,
            "pages": 0,
        }
        _watch._full_save(self, state)
        _watch._log(scan_id, "全量开始", f"来源={trigger} 强校验={bool(force_verify)} 根目录={root}")
        return _watch._full_step(self, trigger=trigger)

    def _v390_stop_full(self, *, trigger: str) -> Dict[str, Any]:
        self._v390_ensure_monitor()
        result = _watch._stop_full(self, trigger=trigger)
        now = time.time()
        previous = self.get_data(_watch._FULL_LAST_KEY) or {}
        if not isinstance(previous, dict):
            previous = {}
        self.save_data(_watch._FULL_LAST_KEY, {
            "monitor_path": _watch._root(self),
            "completed_at": float(previous.get("completed_at") or 0),
            "scan_id": str(previous.get("scan_id") or ""),
            "suppressed_until": now + _FULL_SCAN_INTERVAL,
            "stopped_at": now,
        })
        return result

    def _v390_dispatch_one(self, *, trigger: str) -> Dict[str, Any]:
        """快速收口终态项，但一轮最多提交一个真实 Worker 任务。"""
        last: Dict[str, Any] = {"scheduled": False, "reason": "queue_empty", "queue_depth": 0}
        compacted = 0
        for _ in range(_TERMINAL_COMPACT_BUDGET):
            before = len(_watch._load_rows(self, _watch._RESOURCE_KEY))
            result = dict(_watch._dispatch_one(self, trigger=trigger) or {})
            last = result
            after = len(_watch._load_rows(self, _watch._RESOURCE_KEY))
            if result.get("scheduled"):
                break
            if str(result.get("reason") or "") in {
                "queue_empty", "queue_wait", "worker_busy", "handoff", "read_error"
            }:
                break
            if after < before:
                compacted += before - after
                continue
            break
        if compacted:
            last["terminal_compacted"] = compacted
            last["queue_depth"] = len(_watch._load_rows(self, _watch._RESOURCE_KEY))
        return last

    def organize_monitor_tick(self) -> None:
        """最终 heartbeat：异常永不冒泡到 MoviePilot/APScheduler。"""
        survival = self._v390_survival_state()
        now = time.time()
        if now < float(survival.get("cooldown_until") or 0):
            return
        try:
            self._v390_ensure_monitor()
            if not getattr(self, "_organize_monitor_enabled", False):
                return
            if not getattr(self, "_enabled", False) or not getattr(self, "_guangya_api", None):
                return
            if _watch._root(self) == "/":
                return

            now_mono = time.monotonic()
            interval = _watch._watch_interval(self)
            full = _watch._full_load(self)
            last_watch = float(getattr(self, "_v390_last_watch_mono", 0) or 0)
            if not last_watch or now_mono - last_watch >= interval:
                self._v390_last_watch_mono = now_mono
                _watch._watch_pulse(
                    self,
                    trigger="monitor",
                    budget=_watch._WATCH_WHILE_FULL_BUDGET if full.get("active") else _watch._WATCH_BUDGET,
                )

            full = _watch._full_load(self)
            last_full = float(getattr(self, "_v390_last_full_step_mono", 0) or 0)
            if full.get("active"):
                if not last_full or now_mono - last_full >= _watch._MIN_WATCH_INTERVAL:
                    self._v390_last_full_step_mono = now_mono
                    _watch._full_step(self, trigger="auto-resume")
            elif self._v390_full_due():
                self._v390_last_full_step_mono = now_mono
                self._v390_start_full(trigger="scheduled", force_verify=False)

            self._v390_dispatch_one(trigger="monitor")
            survival["last_success_at"] = now
            survival["failures"] = 0
            survival["last_error"] = ""
            survival["window_started_at"] = now
        except Exception as err:  # noqa: BLE001 - plugin survival boundary
            window = float(survival.get("window_started_at") or 0)
            if not window or now - window > _FAILURE_WINDOW_SECONDS:
                survival["window_started_at"] = now
                survival["failures"] = 0
            survival["failures"] = int(survival.get("failures") or 0) + 1
            survival["last_error_at"] = now
            survival["last_error"] = f"{type(err).__name__}: {err}"
            logger.error(
                "【光鸭云盘助手】【监控】【存活保护】本轮异常已隔离，不影响插件运行: %s",
                survival["last_error"],
            )
            if int(survival.get("failures") or 0) >= _FAILURE_LIMIT:
                survival["cooldown_until"] = now + _COOLDOWN_SECONDS
                logger.warning(
                    "【光鸭云盘助手】【监控】【存活保护】连续失败达到阈值，仅暂停监控 %ss",
                    int(_COOLDOWN_SECONDS),
                )

    def run_organize_monitor_scan(self, manual: bool = False) -> Dict[str, Any]:
        """旧 refill 兼容入口也统一进入持久 resource queue。"""
        self._v390_ensure_monitor()
        if manual:
            return self._v390_start_full(trigger="manual", force_verify=True)
        dispatch = self._v390_dispatch_one(trigger="refill")
        if str(dispatch.get("reason") or "") == "queue_empty":
            observed = _watch._watch_pulse(self, trigger="refill", budget=_watch._WATCH_BUDGET)
            dispatch = self._v390_dispatch_one(trigger="refill-after-watch")
        else:
            observed = None
        return {
            "success": True,
            "message": "v3.9.0 持久待整理队列补充完成",
            "data": {
                "monitor_pipeline": "static-watch-v3.9.0",
                "dispatch": dispatch,
                "observed": dict((observed or {}).get("data") or {}) if isinstance(observed, dict) else {},
            },
        }

    def api_organize_monitor_scan(self, payload: dict = None) -> Dict[str, Any]:
        return self._v390_start_full(trigger="manual", force_verify=True)

    def api_organize_monitor_incremental_scan(self, payload: dict = None) -> Dict[str, Any]:
        self._v390_ensure_monitor()
        result = _watch._watch_pulse(self, trigger="manual", budget=max(_watch._WATCH_BUDGET * 2, 128))
        dispatch = self._v390_dispatch_one(trigger="manual-incremental")
        if isinstance(result, dict):
            result.setdefault("data", {})["dispatch"] = dispatch
        return result

    def api_organize_monitor_full_scan(self, payload: dict = None) -> Dict[str, Any]:
        return self._v390_start_full(trigger="manual", force_verify=True)

    def api_organize_monitor_full_scan_stop(self, payload: dict = None) -> Dict[str, Any]:
        return self._v390_stop_full(trigger="manual")

    def api_organize_monitor_status(self) -> Dict[str, Any]:
        try:
            self._v390_ensure_monitor()
            response = super().api_organize_monitor_status()
        except Exception as err:  # noqa: BLE001
            logger.error("【光鸭云盘助手】【监控】状态读取异常已隔离: %s", err)
            response = {"success": True, "message": "监控状态暂不可用，插件仍正常", "data": {"status": {}, "history": []}}
        if not isinstance(response, dict):
            response = {"success": True, "data": {"status": {}, "history": []}}
        row = response.setdefault("data", {}).setdefault("status", {})
        watch_rows = _watch._load_rows(self, _watch._WATCH_KEY)
        resource_rows = _watch._load_rows(self, _watch._RESOURCE_KEY)
        full = _watch._full_load(self)
        survival = self._v390_survival_state()
        now = time.time()
        row.update({
            "monitor_pipeline": "static-watch-v3.9.0",
            "monitor_strategy": "watch-registry + persistent-resource-queue + independent-full-scan",
            "install_registration_safe": True,
            "dynamic_monitor_patch_stack": False,
            "detection_runs_while_worker_busy": True,
            "watch_registry_total": len(watch_rows),
            "watch_hot_total": sum(1 for item in watch_rows.values() if float((item or {}).get("hot_until") or 0) > now),
            "resource_queue_depth": len(resource_rows),
            "resource_queue_sample": [path for path, _ in sorted(resource_rows.items(), key=lambda pair: float((pair[1] or {}).get("first_seen") or 0))[:8]],
            "full_scan_active": bool(full.get("active")),
            "full_scan_id": str(full.get("scan_id") or ""),
            "full_scan_trigger": str(full.get("trigger") or ""),
            "full_scan_force_verify": bool(full.get("force_verify")),
            "full_scan_pages": int(full.get("pages") or 0),
            "full_scan_dirs": int(full.get("dirs_scanned") or 0),
            "full_scan_files": int(full.get("files_seen") or 0),
            "full_scan_resources": int(full.get("resource_dirs") or 0),
            "full_scan_queued": int(full.get("queued_resources") or 0),
            "full_scan_remaining_dirs": len(full.get("queue") or []),
            "full_scan_interval": int(_FULL_SCAN_INTERVAL),
            "runtime_survival_failures": int(survival.get("failures") or 0),
            "runtime_survival_last_error": str(survival.get("last_error") or ""),
            "runtime_survival_cooldown_until": float(survival.get("cooldown_until") or 0),
            "log_filter_hint": "【光鸭云盘助手】【监控】",
        })
        return response

    def get_organizer_api(self):
        """静态 API 投影，不改写其它类方法。"""
        apis = list(super().get_organizer_api() or [])
        replacements = {
            "/organize/monitor/scan": (self.api_organize_monitor_scan, "强制全量扫描并校验所有资源"),
            "/organize/monitor/incremental-scan": (self.api_organize_monitor_incremental_scan, "执行一次目录快照增量观察"),
            "/organize/monitor/full-scan": (self.api_organize_monitor_full_scan, "启动/继续强制全量巡检"),
            "/organize/monitor/full-scan/stop": (self.api_organize_monitor_full_scan_stop, "停止全量发现续页"),
        }
        existing = set()
        for api in apis:
            path = str(api.get("path") or "")
            existing.add(path)
            if path in replacements:
                endpoint, summary = replacements[path]
                api["endpoint"] = endpoint
                api["summary"] = summary
        apis.extend([
            {
                "path": path,
                "endpoint": endpoint,
                "auth": "bear",
                "methods": ["POST"],
                "summary": summary,
                "response_model": GuangYaOrganizerResponse,
            }
            for path, (endpoint, summary) in replacements.items()
            if path not in existing
        ])
        return apis

    def _v366_finish_schedule(self, group_path: str, files: Sequence[Any], result: Dict[str, Any]) -> Dict[str, Any]:
        returned = super()._v366_finish_schedule(group_path, files, result)
        if not bool(result.get("scheduled")):
            return returned
        phases = dict(result.get("phases") or {})
        remaining = sum(int(phases.get(name) or 0) for name in _WAIT_PHASES)
        if remaining <= 0:
            return returned
        register_pending = getattr(self, "_v361_register_pending", None)
        if callable(register_pending):
            pending = dict(result)
            pending.update({"scheduled": False, "reason": "partial_wait"})
            register_pending(group_path, files, pending)
        self._save_monitor_status(
            partial_revisit_pending=remaining,
            partial_revisit_path=self._v360_norm(group_path),
        )
        return returned

    def _v360_schedule_resource(self, group_path: str, files: Sequence[Any]) -> Dict[str, Any]:
        """ready 先行；仅全成员 ready 才允许原生目录批量。"""
        primary = self._v360_primary_files(files)
        if not primary:
            return self._v366_finish_schedule(group_path, files, {"scheduled": False, "reason": "no_primary", "primary": 0})

        monitor_root = self._v360_norm(self._organize_monitor_path)
        normalized_group = self._v360_norm(group_path)
        manual_safe_mode = bool(getattr(self, "_v366_manual_scan_active", False))
        loose = normalized_group == monitor_root
        if not loose:
            try:
                loose = bool(_orch._is_loose_container_v351(self, normalized_group, list(files)))
            except Exception:
                loose = False

        rows: List[Tuple[Any, str, str]] = []
        phases: Dict[str, int] = {}
        candidates = primary[:1] if loose else primary
        for member in candidates:
            phase, prepared = self._v360_prepare_member(member)
            phases[phase] = phases.get(phase, 0) + 1
            if prepared:
                rows.append(prepared)

        hard_wait = sum(int(phases.get(name) or 0) for name in _WAIT_PHASES)
        if not rows:
            return self._v366_finish_schedule(normalized_group, files, {
                "scheduled": False,
                "reason": "member_wait" if loose else ("resource_wait" if hard_wait else "no_ready"),
                "primary": len(primary),
                "phases": phases,
            })

        selected = [rows[0]] if loose else rows
        all_primary_ready = (
            not loose
            and len(selected) == len(primary)
            and int(phases.get("ready") or 0) == len(primary)
            and sum(int(value or 0) for value in phases.values()) == len(primary)
        )
        directory_mode = bool(
            not manual_safe_mode
            and all_primary_ready
            and _can_use_native_directory_batch(self, normalized_group, [row[0] for row in selected])
        )
        envelope = self._v360_make_envelope(normalized_group, [row[0] for row in selected], directory_mode=directory_mode)
        store = self._state()
        accepted_members: List[Any] = []
        for member, path, fingerprint in selected:
            attempt = store.mark_submitting(
                path=path,
                fingerprint=fingerprint,
                now=time.time(),
                metadata={
                    "name": str(getattr(member, "name", "") or Path(path).name),
                    "size": int(getattr(member, "size", 0) or 0),
                    "group_path": normalized_group,
                    "group_name": self._group_name(normalized_group),
                    "batch_id": envelope.batch_id,
                    "folder_task": True,
                    "v360_engine": True,
                    "v390_final_monitor": True,
                },
            )
            if attempt:
                accepted_members.append(member)
        if not accepted_members:
            return self._v366_finish_schedule(normalized_group, files, {
                "scheduled": False, "reason": "state_changed", "primary": len(primary), "phases": phases
            })
        envelope.members = accepted_members

        try:
            accepted = bool(self._dispatch_to_moviepilot(envelope))
            dispatch_message = ""
        except Exception as err:  # noqa: BLE001
            accepted = False
            dispatch_message = str(err)
        if not accepted:
            self._v360_return_members_to_pending(
                accepted_members,
                reason=dispatch_message or "私有 Worker 暂未接收；保持 resource queue 待处理",
            )
            return self._v366_finish_schedule(normalized_group, files, {
                "scheduled": False, "reason": "worker_not_accept", "primary": len(primary), "phases": phases
            })

        self._save_monitor_status(
            runtime_phase="queued",
            runtime_label="当前资源已进入私有 Worker",
            current_task_path=normalized_group,
            current_group=normalized_group,
            current_group_name=self._group_name(normalized_group),
            active_resource_tasks=1,
            submitted=len(accepted_members),
            selected_member_mode=not directory_mode,
        )
        logger.info(
            "【光鸭云盘助手】【监控】【调度】资源已入 Worker: %s，主媒体=%s，提交=%s，目录模式=%s，phases=%s",
            normalized_group,
            len(primary),
            len(accepted_members),
            directory_mode,
            phases,
        )
        return self._v366_finish_schedule(normalized_group, files, {
            "scheduled": True,
            "reason": "queued",
            "primary": len(primary),
            "submitted": len(accepted_members),
            "directory_mode": directory_mode,
            "phases": phases,
        })


__all__ = ["GuangYaFinalMonitorV390Mixin"]
