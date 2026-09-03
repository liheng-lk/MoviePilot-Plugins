"""v3.6.6：自动监控灵敏度、增量资源索引与 MoviePilot 准入冲突保护。

修复 v3.6.0~v3.6.5 的三个调度问题：
- 恢复用户配置的 monitor interval，30 秒 heartbeat 不再等价于 30 秒真实扫描；
- 目录只有部分成员 ready 时禁止 MoviePilot 原生目录批量，只执行插件已确认的成员；
- 完成一次基线 discovery 后，日常轮询只检查已知“有主媒体”的资源目录，并以目录签名跳过
  未变化的历史文件；完整目录树仅低频巡检，避免空目录/历史目录永久循环扫描。

此外，MoviePilot 的 ``整理源文件已按不同输入准入`` 属于持久准入冲突，不应按普通执行失败
每分钟重试；该类冲突会进入 blocked，等待宿主准入记录自然收敛后再复核。
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.sdk.logging import logger

from . import organizer_orchestrator_v351 as _orch
from .organizer_folder_batch_v342 import _can_use_native_directory_batch


_KNOWN_KEY = "organize_v366_known_resources"
_BASELINE_KEY = "organize_v366_baseline"
_KNOWN_SCHEMA = 1
_KNOWN_LIMIT = 1000
_KNOWN_SCAN_LIMIT = 500
_FULL_DISCOVERY_INTERVAL = 1800.0
_ADMISSION_CONFLICT_TOKENS = (
    "整理源文件已按不同输入准入",
    "TransferAdmissionConflictError",
)


class GuangYaOrganizerMonitorV366Mixin:
    """位于 v3.6.1/v3.6.0 之前的最终自动监控调度边界。"""

    _v366_known_scan_active: bool = False

    def _v366_load_known(self) -> Dict[str, Dict[str, Any]]:
        raw = self.get_data(_KNOWN_KEY) or {}
        if not isinstance(raw, dict) or int(raw.get("schema") or 0) != _KNOWN_SCHEMA:
            return {}
        root = self._v360_norm(getattr(self, "_organize_monitor_path", ""))
        if self._v360_norm(raw.get("monitor_path")) != root:
            return {}
        rows: Dict[str, Dict[str, Any]] = {}
        for raw_path, raw_row in dict(raw.get("rows") or {}).items():
            path = self._v360_norm(raw_path)
            if not path or not isinstance(raw_row, dict):
                continue
            rows[path] = dict(raw_row)
            if len(rows) >= _KNOWN_LIMIT:
                break
        return rows

    def _v366_save_known(self, rows: Dict[str, Dict[str, Any]]) -> None:
        root = self._v360_norm(getattr(self, "_organize_monitor_path", ""))
        ordered = sorted(
            rows.items(),
            key=lambda pair: (-float((pair[1] or {}).get("last_seen") or 0), pair[0]),
        )[:_KNOWN_LIMIT]
        self.save_data(
            _KNOWN_KEY,
            {
                "schema": _KNOWN_SCHEMA,
                "monitor_path": root,
                "rows": {path: row for path, row in ordered},
                "updated_at": time.time(),
            },
        )

    def _v366_resource_signature(self, members: Sequence[Any]) -> str:
        rows: List[str] = []
        for member in members:
            try:
                path, fingerprint = self._v360_member_identity(member)
            except Exception:
                continue
            rows.append(f"{path}|{fingerprint}")
        rows.sort()
        return hashlib.sha1("\n".join(rows).encode("utf-8")).hexdigest()

    def _v366_remember_resource(self, group_path: str, primary: Sequence[Any]) -> None:
        if self._v366_known_scan_active or not primary:
            return
        path = self._v360_norm(group_path)
        if not path or path == "/":
            return
        rows = self._v366_load_known()
        row = dict(rows.get(path) or {})
        row.update(
            {
                "signature": self._v366_resource_signature(primary),
                "file_count": len(primary),
                "last_seen": time.time(),
            }
        )
        rows[path] = row
        self._v366_save_known(rows)

    def _v366_finish_schedule(
        self,
        group_path: str,
        files: Sequence[Any],
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        primary = self._v360_primary_files(files)
        if primary:
            self._v366_remember_resource(group_path, primary)

        remove_pending = getattr(self, "_v361_remove_pending", None)
        register_pending = getattr(self, "_v361_register_pending", None)
        if result.get("scheduled"):
            if callable(remove_pending):
                remove_pending(group_path)
            return result

        reason = str(result.get("reason") or "")
        phases = dict(result.get("phases") or {})
        waiting = reason in {"member_wait", "resource_wait"} or any(
            phases.get(name) for name in ("stabilizing", "history_wait", "retry_wait", "inflight")
        )
        if waiting and callable(register_pending):
            register_pending(group_path, files, result)
        elif reason in {"no_primary", "no_ready", "state_changed"} and callable(remove_pending):
            remove_pending(group_path)
        return result

    def _v360_schedule_resource(self, group_path: str, files: Sequence[Any]) -> Dict[str, Any]:
        primary = self._v360_primary_files(files)
        if not primary:
            return self._v366_finish_schedule(
                group_path,
                files,
                {"scheduled": False, "reason": "no_primary", "primary": 0},
            )

        monitor_root = self._v360_norm(self._organize_monitor_path)
        normalized_group = self._v360_norm(group_path)
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
            phase, row = self._v360_prepare_member(member)
            phases[phase] = phases.get(phase, 0) + 1
            if row:
                rows.append(row)

        if loose:
            if not rows:
                return self._v366_finish_schedule(
                    normalized_group,
                    files,
                    {"scheduled": False, "reason": "member_wait", "primary": len(primary), "phases": phases},
                )
            selected = [rows[0]]
            directory_mode = False
        else:
            hard_wait = sum(
                phases.get(name, 0)
                for name in ("stabilizing", "inflight", "retry_wait", "history_wait")
            )
            if hard_wait:
                return self._v366_finish_schedule(
                    normalized_group,
                    files,
                    {"scheduled": False, "reason": "resource_wait", "primary": len(primary), "phases": phases},
                )
            if not rows:
                return self._v366_finish_schedule(
                    normalized_group,
                    files,
                    {"scheduled": False, "reason": "no_ready", "primary": len(primary), "phases": phases},
                )
            selected = rows
            all_primary_ready = (
                len(selected) == len(primary)
                and int(phases.get("ready") or 0) == len(primary)
                and sum(int(value or 0) for value in phases.values()) == len(primary)
            )
            directory_mode = bool(
                all_primary_ready
                and _can_use_native_directory_batch(
                    self,
                    normalized_group,
                    [row[0] for row in selected],
                )
            )

        envelope = self._v360_make_envelope(
            normalized_group,
            [row[0] for row in selected],
            directory_mode=directory_mode,
        )
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
                    "v366_selected_member": True,
                },
            )
            if attempt:
                accepted_members.append(member)

        if not accepted_members:
            return self._v366_finish_schedule(
                normalized_group,
                files,
                {"scheduled": False, "reason": "state_changed", "primary": len(primary), "phases": phases},
            )
        envelope.members = accepted_members

        try:
            accepted = bool(self._dispatch_to_moviepilot(envelope))
        except Exception as err:
            accepted = False
            dispatch_message = str(err)
        else:
            dispatch_message = ""

        if not accepted:
            restored = self._v360_return_members_to_pending(
                accepted_members,
                reason=dispatch_message or "私有 worker 暂未接收；仅回 discovery pending",
            )
            logger.warning(
                "【光鸭云盘助手】【v3.6.6】【调度】资源未进入 worker，成员=%s 已回 pending，不写 retry: %s%s",
                restored,
                normalized_group,
                f" - {dispatch_message}" if dispatch_message else "",
            )
            return self._v366_finish_schedule(
                normalized_group,
                files,
                {"scheduled": False, "reason": "worker_not_accept", "primary": len(primary), "phases": phases},
            )

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
        mode_text = "MoviePilot原生目录（全成员ready）" if directory_mode else "已筛选成员"
        logger.info(
            "【光鸭云盘助手】【v3.6.6】【调度】当前资源已入队: %s，主媒体=%s，实际成员=%s，模式=%s，phases=%s",
            normalized_group,
            len(primary),
            len(accepted_members),
            mode_text,
            phases,
        )
        return self._v366_finish_schedule(
            normalized_group,
            files,
            {
                "scheduled": True,
                "reason": "queued",
                "primary": len(primary),
                "submitted": len(accepted_members),
                "directory_mode": directory_mode,
                "phases": phases,
            },
        )

    @staticmethod
    def _v366_is_admission_conflict(message: str) -> bool:
        text = str(message or "")
        return any(token in text for token in _ADMISSION_CONFLICT_TOKENS)

    def _fallback_terminal_state(self, item: Any, success: bool, message: str) -> None:
        if not success and self._v366_is_admission_conflict(message):
            store = self._state()
            blocked = 0
            for member in self._v360_members(item):
                try:
                    path, fingerprint = self._v360_member_identity(member)
                except Exception:
                    continue
                raw = store.load()
                if path not in dict(raw.get("inflight") or {}):
                    continue
                store.mark_blocked(
                    path=path,
                    fingerprint=fingerprint,
                    reason=f"MoviePilot 持久准入冲突：{message}",
                    now=time.time(),
                )
                blocked += 1
            if blocked:
                self._save_monitor_status(
                    admission_conflict_blocked=blocked,
                    admission_conflict_message=str(message or ""),
                    admission_conflict_at=time.time(),
                )
                logger.warning(
                    "【光鸭云盘助手】【v3.6.6】【准入冲突】%s 个成员已进入 blocked，停止分钟级重复提交: %s",
                    blocked,
                    message,
                )
            return
        return super()._fallback_terminal_state(item, success=success, message=message)

    def organize_monitor_tick(self) -> None:
        self.init_organizer_monitor()
        if not getattr(self, "_organize_monitor_enabled", False):
            return
        if not float(getattr(self, "_organize_monitor_last_tick", 0.0) or 0.0):
            self._v360_last_tick = 0.0

        now = time.monotonic()
        interval = max(float(getattr(self, "_organize_monitor_interval", 60) or 60), 1.0)
        last = float(getattr(self, "_v360_last_tick", 0.0) or 0.0)
        if last and now - last < interval:
            return
        self._v360_last_tick = now
        self._organize_monitor_last_tick = now
        return self.run_organize_monitor_scan(manual=False)

    def _v366_baseline_due(self) -> bool:
        raw = self.get_data(_BASELINE_KEY) or {}
        if not isinstance(raw, dict):
            return True
        root = self._v360_norm(getattr(self, "_organize_monitor_path", ""))
        if self._v360_norm(raw.get("monitor_path")) != root:
            return True
        completed_at = float(raw.get("completed_at") or 0)
        return completed_at <= 0 or time.time() - completed_at >= _FULL_DISCOVERY_INTERVAL

    def _v366_mark_baseline_complete(self) -> None:
        self.save_data(
            _BASELINE_KEY,
            {
                "monitor_path": self._v360_norm(getattr(self, "_organize_monitor_path", "")),
                "completed_at": time.time(),
            },
        )

    def _v366_scan_known_resources(self) -> Dict[str, Any]:
        rows = self._v366_load_known()
        if not rows:
            return {
                "success": True,
                "message": "暂无已知资源目录，等待基线 discovery",
                "data": {"known_scan": True, "known_total": 0, "known_checked": 0, "known_changed": 0, "scheduled": False},
            }

        lock = self._organize_scan_lock
        if lock is None:
            import threading
            lock = threading.Lock()
            self._organize_scan_lock = lock
        if not lock.acquire(blocking=False):
            return {
                "success": True,
                "message": "已有 discovery 正在运行",
                "data": {"known_scan": True, "scan_busy": True, "scheduled": False},
            }

        checked = changed = removed = errors = 0
        scheduled_result: Optional[Dict[str, Any]] = None
        now = time.time()
        candidates = sorted(
            rows.items(),
            key=lambda pair: (float((pair[1] or {}).get("last_checked") or 0), pair[0]),
        )[:_KNOWN_SCAN_LIMIT]

        self._v366_known_scan_active = True
        try:
            for group_path, previous in candidates:
                try:
                    _, direct_files = self._v360_list_directory(group_path)
                except Exception as err:
                    errors += 1
                    row = dict(previous or {})
                    row.update({"last_checked": now, "last_error": str(err)})
                    rows[group_path] = row
                    continue

                checked += 1
                primary = self._v360_primary_files(direct_files)
                if not primary:
                    rows.pop(group_path, None)
                    removed += 1
                    remove_pending = getattr(self, "_v361_remove_pending", None)
                    if callable(remove_pending):
                        remove_pending(group_path)
                    continue

                signature = self._v366_resource_signature(primary)
                old_signature = str((previous or {}).get("signature") or "")
                row = dict(previous or {})
                row.update(
                    {
                        "signature": signature,
                        "file_count": len(primary),
                        "last_seen": now,
                        "last_checked": now,
                        "last_error": "",
                    }
                )
                rows[group_path] = row

                if old_signature and old_signature == signature:
                    continue

                changed += 1
                result = dict(self._v360_schedule_resource(group_path, direct_files) or {})
                if result.get("scheduled"):
                    scheduled_result = result
                    break
        finally:
            self._v366_known_scan_active = False
            self._v366_save_known(rows)
            try:
                lock.release()
            except RuntimeError:
                pass

        self._save_monitor_status(
            known_resource_total=len(rows),
            known_resource_checked=checked,
            known_resource_changed=changed,
            known_resource_removed=removed,
            known_resource_errors=errors,
            known_resource_scan_at=now,
        )
        logger.info(
            "【光鸭云盘助手】【v3.6.6】【增量监控】已知资源=%s，检查=%s，内容变化=%s，移除空目录=%s，错误=%s，提交=%s",
            len(rows),
            checked,
            changed,
            removed,
            errors,
            1 if scheduled_result else 0,
        )
        return {
            "success": True,
            "message": "已知资源目录增量检查完成" if not scheduled_result else "已知资源变化已提交",
            "data": {
                "known_scan": True,
                "known_total": len(rows),
                "known_checked": checked,
                "known_changed": changed,
                "known_removed": removed,
                "known_errors": errors,
                "scheduled": bool(scheduled_result),
            },
        }

    def run_organize_monitor_scan(self, manual: bool = False) -> Dict[str, Any]:
        self.init_organizer_monitor()
        if not manual and not getattr(self, "_organize_monitor_enabled", False):
            return {"success": True, "message": "自动整理监控未启用", "data": {"disabled": True}}
        if not getattr(self, "_enabled", False) or not getattr(self, "_guangya_api", None):
            return {"success": False, "message": "光鸭云盘未启用或未登录"}
        if self._v360_norm(getattr(self, "_organize_monitor_path", "/")) == "/":
            return {"success": False, "message": "请先选择具体监控目录，禁止直接监控根目录"}

        owner_ok, snapshot = self._v360_owner_gate()
        if not owner_ok:
            return {
                "success": True,
                "message": "旧 Worker 正在交接，本轮不扫描、不入队、不修改 retry",
                "data": {"handoff": True},
            }
        self._recover_isolated_inflight_once()
        snapshot = dict(self._isolated_queue_snapshot() or {})
        if self._v360_worker_busy(snapshot):
            running = str(snapshot.get("running_path") or "")
            return {
                "success": True,
                "message": "当前资源整理中，本轮不扫描下一资源",
                "data": {"busy": True, "current_task_path": running},
            }

        priority_getter = getattr(self, "_v361_try_due_resource", None)
        if callable(priority_getter):
            priority = priority_getter()
            if priority is not None:
                return priority

        known_result = self._v366_scan_known_resources()
        if bool((known_result.get("data") or {}).get("scheduled")):
            return known_result

        if manual or self._v366_baseline_due():
            baseline = super().run_organize_monitor_scan(manual=manual)
            data = dict((baseline or {}).get("data") or {}) if isinstance(baseline, dict) else {}
            if data.get("cycle_complete"):
                self._v366_mark_baseline_complete()
                self._save_monitor_status(full_discovery_completed_at=time.time())
                logger.info("【光鸭云盘助手】【v3.6.6】【基线发现】本轮完整 discovery cycle 已完成；切换为资源目录增量监控")
            return baseline

        return known_result

    def api_organize_monitor_status(self) -> Dict[str, Any]:
        response = super().api_organize_monitor_status()
        if not isinstance(response, dict) or not response.get("success"):
            return response
        data = response.setdefault("data", {})
        status = data.setdefault("status", {})
        known = self._v366_load_known()
        baseline = self.get_data(_BASELINE_KEY) or {}
        status.update(
            {
                "monitor_engine_patch": "v3.6.6",
                "effective_scan_interval": int(getattr(self, "_organize_monitor_interval", 60) or 60),
                "known_resource_total": len(known),
                "full_discovery_interval": int(_FULL_DISCOVERY_INTERVAL),
                "full_discovery_completed_at": float((baseline or {}).get("completed_at") or 0),
            }
        )
        return response


__all__ = ["GuangYaOrganizerMonitorV366Mixin"]
