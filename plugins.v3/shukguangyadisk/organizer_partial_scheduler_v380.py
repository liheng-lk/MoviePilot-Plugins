"""v3.8.0：资源队列的部分 ready 调度边界。

持续监控只能保证“发现不丢”；同一资源目录如果仍有 stabilizing/history_wait/retry_wait/inflight
成员，旧 v3.6.7 调度会整组 hard-wait，导致已经 ready 的新增集也无法前进。本层恢复已经在
v3.7.4/3.7.5 分支验证过的行为：

- 只要存在 ready 成员，就允许这些成员先进入私有 Worker；
- 只有全部 primary 成员同时 ready 时，才允许 MoviePilot 原生整目录批量；
- 部分提交后仍有等待成员时重新登记目录 pending；v3.8.0 resource queue 也会继续保留该目录；
- 不放宽 completed/blocked/ignored/history 等 MoviePilot/状态机安全边界。
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from app.sdk.logging import logger

from . import organizer_orchestrator_v351 as _orch
from .organizer_folder_batch_v342 import _can_use_native_directory_batch
from .organizer_monitor_v366 import GuangYaOrganizerMonitorV366Mixin as _MonitorMixin


_INSTALL_FLAG = "_v380_partial_scheduler_installed"
_WAIT_PHASES = ("stabilizing", "history_wait", "retry_wait", "inflight")


def install_partial_scheduler_v380() -> None:
    if bool(getattr(_MonitorMixin, _INSTALL_FLAG, False)):
        return

    original_finish = _MonitorMixin._v366_finish_schedule

    def finish(self: Any, group_path: str, files: Sequence[Any], result: Dict[str, Any]) -> Dict[str, Any]:
        returned = original_finish(self, group_path, files, result)
        if not bool(result.get("scheduled")):
            return returned
        phases = dict(result.get("phases") or {})
        remaining_wait = sum(int(phases.get(name) or 0) for name in _WAIT_PHASES)
        if remaining_wait <= 0:
            return returned
        register_pending = getattr(self, "_v361_register_pending", None)
        if callable(register_pending):
            pending_result = dict(result)
            pending_result["scheduled"] = False
            pending_result["reason"] = "partial_wait"
            register_pending(group_path, files, pending_result)
        try:
            self._save_monitor_status(
                partial_revisit_pending=remaining_wait,
                partial_revisit_path=self._v360_norm(group_path),
            )
        except Exception:
            pass
        logger.info(
            "【光鸭云盘助手】【监控】【部分续跑】ready 成员已提交，仍等待=%s；资源目录保持可回访: %s",
            remaining_wait,
            self._v360_norm(group_path),
        )
        return returned

    def schedule(self: Any, group_path: str, files: Sequence[Any]) -> Dict[str, Any]:
        primary = self._v360_primary_files(files)
        if not primary:
            return self._v366_finish_schedule(
                group_path,
                files,
                {"scheduled": False, "reason": "no_primary", "primary": 0},
            )

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
            hard_wait = sum(int(phases.get(name) or 0) for name in _WAIT_PHASES)
            # 关键：hard-wait sibling 只禁止“整目录提交”，不能饿死已经 ready 的成员。
            if not rows:
                return self._v366_finish_schedule(
                    normalized_group,
                    files,
                    {
                        "scheduled": False,
                        "reason": "resource_wait" if hard_wait else "no_ready",
                        "primary": len(primary),
                        "phases": phases,
                    },
                )
            selected = rows
            all_primary_ready = (
                len(selected) == len(primary)
                and int(phases.get("ready") or 0) == len(primary)
                and sum(int(value or 0) for value in phases.values()) == len(primary)
            )
            directory_mode = bool(
                not manual_safe_mode
                and all_primary_ready
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
                    "v380_selected_member": True,
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
        except Exception as err:  # noqa: BLE001
            accepted = False
            dispatch_message = str(err)
        else:
            dispatch_message = ""

        if not accepted:
            restored = self._v360_return_members_to_pending(
                accepted_members,
                reason=dispatch_message or "私有 Worker 暂未接收；保持 resource queue 待处理",
            )
            logger.warning(
                "【光鸭云盘助手】【监控】【调度】资源未进入 Worker，成员=%s 已回 pending: %s%s",
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
        if directory_mode:
            mode_text = "MoviePilot原生目录（全成员ready）"
        elif manual_safe_mode:
            mode_text = "手动安全筛选成员"
        elif hard_wait if not loose else False:
            mode_text = "部分ready成员"
        else:
            mode_text = "已筛选成员"
        logger.info(
            "【光鸭云盘助手】【监控】【调度】当前资源已入 Worker: %s，主媒体=%s，实际成员=%s，模式=%s，phases=%s",
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

    _MonitorMixin._v366_finish_schedule = finish
    _MonitorMixin._v360_schedule_resource = schedule
    setattr(_MonitorMixin, _INSTALL_FLAG, True)
    logger.info("【光鸭云盘助手】【监控】v3.8.0 部分 ready 调度已启用：ready 先行，等待成员持续回访")


__all__ = ["install_partial_scheduler_v380"]