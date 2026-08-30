"""v3.6.0：统一自动整理引擎。

3.5.x 在长期迭代中把 discovery、single-flight、TV sticky、worker handoff、retry 与
MoviePilot 最终回执分别包在多个运行时补丁里。真实运行证明这些状态会互相放大：一次
worker 交接失败就可能把整库候选写入 retry，随后 retry 又维持 sticky，最终让监控根本身
都可能成为“当前剧集”。

v3.6.0 重新定义唯一调度边界：

    discovery(最多 50 个目录) -> scheduler(只选 1 个资源) -> private worker
    -> MoviePilot -> TransferComplete/TransferFailed/history

本模块只接管调度与状态语义，不重新实现 MoviePilot 的媒体识别、分类、命名、冲突处理、
安全预览或 season 识别。旧模块仍可提供这些兼容能力，但不再拥有主调度权。

硬约束：
- worker 未取得 owner / 正在热更新交接：不扫描、不入队、不修改 retry；
- 扫描候选与真实任务失败分离：稳定等待/历史未知/队列暂不可接收都不是 retry；
- 不再使用持久 TV sticky；当前资源直接来自私有 worker；
- 旧 3.5.x retry/stabilizing 在首次升级时清空并由 discovery 重新确认；completed/blocked 保留；
- 同步 do_transfer 成功但最终事件/历史尚未落库时保持 evidence-pending，不伪造 completed；
- 只有真实执行返回失败且成员仍处于 inflight 时才写 retry。
"""

from __future__ import annotations

import datetime
import time
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from app.sdk.logging import logger

from . import organizer_orchestrator_v351 as _orch
from .organizer_empty_folder_guard_v3410 import _runtime_media_exts
from .organizer_folder_batch_v342 import (
    _FolderBatchEnvelope,
    _batch_fingerprint,
    _can_use_native_directory_batch,
)


_ENGINE_VERSION = "3.6.0"
_CURSOR_KEY = "organize_v360_discovery_cursor"
_MIGRATION_KEY = "organize_v360_semantic_migration"
_CURSOR_SCHEMA = 1
_PAGE_DIR_LIMIT = 50
_MAX_CURSOR_DIRS = 20000


class GuangYaOrganizerEngineV360Mixin:
    """自动整理的唯一 discovery/scheduler 状态机。"""

    _v360_engine_initialized: bool = False
    _v360_inflight_recovered: bool = False
    _v360_last_tick: float = 0.0

    # ------------------------------------------------------------------
    # lifecycle / migration
    # ------------------------------------------------------------------
    def init_organizer_monitor(self) -> None:
        super().init_organizer_monitor()
        if self._v360_engine_initialized:
            return
        self._v360_engine_initialized = True
        self._v360_clear_legacy_sticky()
        self._v360_migrate_legacy_discovery_state_once()
        logger.info(
            "【光鸭云盘助手】【v3.6.0】统一整理引擎已启用：50目录 discovery → 单资源 scheduler → 私有 worker → MoviePilot 最终证据"
        )

    def _v360_clear_legacy_sticky(self) -> None:
        """3.6 不再消费 sticky；每次进程启动都清掉旧 UI/状态残留。"""
        try:
            status = dict(self.get_data(self._monitor_status_key) or {})
        except Exception:
            status = {}
        if not any(
            status.get(key)
            for key in (
                "sticky_tv_group_path",
                "sticky_tv_group_active",
                "sticky_tv_group_since",
            )
        ):
            return
        self._save_monitor_status(
            sticky_tv_group_path="",
            sticky_tv_group_active=False,
            sticky_tv_group_since=0,
            sticky_tv_group_release_reason="v3.6.0 已移除持久剧集粘性，当前资源改由 worker 唯一表示",
            sticky_tv_group_released_at=time.time(),
        )
        logger.warning("【光鸭云盘助手】【v3.6.0】【状态迁移】已清除旧 sticky；3.6 当前资源只取私有 worker")

    def _v360_migrate_legacy_discovery_state_once(self) -> None:
        """清掉 3.5.x 被 discovery/交接污染的 retry 与 stabilizing。

        retry 只是“稍后重试”的调度信息，不是用户数据。全部重新发现不会产生数据损失；
        真正仍失败的文件会在 3.6 的 MoviePilot 执行失败后重新进入干净 retry。
        completed/blocked 保留，inflight 留给 owner 交接完成后的恢复逻辑处理。
        """
        marker = self.get_data(_MIGRATION_KEY) or {}
        if isinstance(marker, dict) and marker.get("applied"):
            return

        store = self._state()
        now = time.time()

        def apply(state: Dict[str, Any]) -> Dict[str, int]:
            old_retry = len(dict(state.get("retry") or {}))
            old_stabilizing = len(dict(state.get("stabilizing") or {}))
            state["retry"] = {}
            state["stabilizing"] = {}
            state["migration"] = "v3.6.0-discovery-task-separation"
            state["updated_at"] = now
            return {
                "retry": old_retry,
                "stabilizing": old_stabilizing,
                "inflight": len(dict(state.get("inflight") or {})),
                "completed": len(dict(state.get("completed") or {})),
                "blocked": len(dict(state.get("blocked") or {})),
            }

        counts = dict(store.mutate(apply) or {})
        self.save_data(
            _MIGRATION_KEY,
            {
                "applied": True,
                "at": now,
                "cleared_retry": counts.get("retry", 0),
                "cleared_stabilizing": counts.get("stabilizing", 0),
                "preserved_inflight": counts.get("inflight", 0),
                "preserved_completed": counts.get("completed", 0),
                "preserved_blocked": counts.get("blocked", 0),
            },
        )
        logger.warning(
            "【光鸭云盘助手】【v3.6.0】【状态迁移】旧 discovery 状态已重置：retry=%s，stabilizing=%s；"
            "completed=%s、blocked=%s 保留，inflight=%s 等待 worker owner 收口",
            counts.get("retry", 0),
            counts.get("stabilizing", 0),
            counts.get("completed", 0),
            counts.get("blocked", 0),
            counts.get("inflight", 0),
        )

    # ------------------------------------------------------------------
    # state semantics
    # ------------------------------------------------------------------
    def _v360_members(self, item: Any) -> List[Any]:
        return list(getattr(item, "members", None) or [item])

    def _v360_member_identity(self, member: Any) -> Tuple[str, str]:
        path = self._organize_normalize_path(getattr(member, "path", ""))
        fingerprint = self._fingerprint(member)
        return path, fingerprint

    def _v360_return_members_to_pending(self, members: Iterable[Any], *, reason: str) -> int:
        """调度/交接未执行的成员回 discovery，不进入 retry，也不累计失败次数。"""
        rows: List[Tuple[str, str]] = []
        for member in members:
            for real_member in self._v360_members(member):
                try:
                    path, fingerprint = self._v360_member_identity(real_member)
                except Exception:
                    continue
                if path:
                    rows.append((path, fingerprint))
        if not rows:
            return 0

        now = time.time()

        def apply(state: Dict[str, Any]) -> int:
            completed = dict(state.get("completed") or {})
            inflight = dict(state.get("inflight") or {})
            retry = dict(state.get("retry") or {})
            stabilizing = dict(state.get("stabilizing") or {})
            restored = 0
            for path, fingerprint in rows:
                if completed.get(path) == fingerprint:
                    inflight.pop(path, None)
                    retry.pop(path, None)
                    stabilizing.pop(path, None)
                    continue
                inflight.pop(path, None)
                retry.pop(path, None)
                stabilizing[path] = {
                    "fingerprint": fingerprint,
                    "first_seen": 0,
                    "v360_pending_reason": reason,
                    "v360_pending_at": now,
                }
                restored += 1
            state["inflight"] = inflight
            state["retry"] = retry
            state["stabilizing"] = stabilizing
            return restored

        return int(self._state().mutate(apply) or 0)

    def _return_items_to_retry_now(self, items: List[Any], reason: str) -> int:
        """兼容 WorkerGuard 的旧方法名，但 3.6 语义明确是 pending，不是 retry。"""
        restored = self._v360_return_members_to_pending(items, reason=reason)
        if restored:
            logger.info(
                "【光鸭云盘助手】【v3.6.0】【Worker交接】未开始成员=%s 已回 discovery pending，不写 retry",
                restored,
            )
        return restored

    def _recover_isolated_inflight_once(self) -> int:
        """只有取得 owner 后才恢复遗留 inflight；恢复目标是 pending，不是失败重试。"""
        if self._v360_inflight_recovered:
            return 0
        self._v360_inflight_recovered = True
        now = time.time()

        def apply(state: Dict[str, Any]) -> int:
            inflight = dict(state.get("inflight") or {})
            stabilizing = dict(state.get("stabilizing") or {})
            recovered = 0
            for path, row in list(inflight.items()):
                if not isinstance(row, dict):
                    continue
                fingerprint = str(row.get("fingerprint") or "")
                stabilizing[path] = {
                    "fingerprint": fingerprint,
                    "first_seen": 0,
                    "v360_pending_reason": "worker owner 已重新取得，遗留 inflight 交回 MoviePilot 历史预检",
                    "v360_pending_at": now,
                }
                inflight.pop(path, None)
                recovered += 1
            state["inflight"] = inflight
            state["stabilizing"] = stabilizing
            return recovered

        recovered = int(self._state().mutate(apply) or 0)
        if recovered:
            logger.warning(
                "【光鸭云盘助手】【v3.6.0】【Worker恢复】遗留 inflight=%s 已回 discovery pending，不作为失败计数",
                recovered,
            )
        return recovered

    def _v360_history_decision(self, member: Any, path: str) -> Dict[str, Any]:
        try:
            return dict(self._preflight_history(member, path) or {})
        except Exception as err:  # noqa: BLE001 - history unavailable is deferred, never failure
            return {"decision": "unknown", "message": str(err)}

    def _v360_reopen_completed(self, path: str, fingerprint: str) -> None:
        def apply(state: Dict[str, Any]) -> None:
            if dict(state.get("completed") or {}).get(path) == fingerprint:
                state["completed"].pop(path, None)
            state["stabilizing"][path] = {
                "fingerprint": fingerprint,
                "first_seen": 0,
                "v360_pending_reason": "源文件仍存在且 MoviePilot 历史不再确认完成，重新发现",
            }

        self._state().mutate(apply)

    def _fallback_terminal_state(self, item: Any, success: bool, message: str) -> None:
        """同步返回只是兜底；最终成功优先相信 MP event/history，失败才进入 retry。"""
        members = self._v360_members(item)
        store = self._state()

        if not success:
            failed = 0
            for member in members:
                try:
                    path, fingerprint = self._v360_member_identity(member)
                except Exception:
                    continue
                raw = store.load()
                if path not in dict(raw.get("inflight") or {}):
                    # TransferFailed/TransferComplete 事件已经收敛，不二次覆盖。
                    continue
                store.mark_failed(
                    path=path,
                    fingerprint=fingerprint,
                    now=time.time(),
                    reason=message or "MoviePilot 整理失败",
                )
                failed += 1
            if failed:
                logger.warning(
                    "【光鸭云盘助手】【v3.6.0】【最终结果】MoviePilot 明确执行失败，真实 retry=%s: %s",
                    failed,
                    message or "MoviePilot 整理失败",
                )
            return

        confirmed = 0
        pending_evidence = 0
        for member in members:
            try:
                path, fingerprint = self._v360_member_identity(member)
            except Exception:
                continue
            raw = store.load()
            inflight = dict(raw.get("inflight") or {})
            if path not in inflight:
                # 正常 TransferComplete 已先到达。
                continue

            decision: Dict[str, Any] = {}
            for attempt in range(3):
                decision = self._v360_history_decision(member, path)
                if str(decision.get("decision") or "") == "completed":
                    break
                if attempt < 2:
                    time.sleep(0.2)

            if str(decision.get("decision") or "") == "completed":
                store.mark_completed(path=path, fingerprint=fingerprint)
                confirmed += 1
                continue

            # 同步成功但最终事件/历史可能有落库延迟。保持 inflight 作为 evidence-pending，
            # 不伪造 completed，也绝不因为“暂时查不到”改判失败。
            now = time.time()

            def mark_pending_evidence(state: Dict[str, Any]) -> None:
                row = dict((state.get("inflight") or {}).get(path) or {})
                if not row:
                    return
                row.update({
                    "v360_sync_success": True,
                    "v360_evidence_pending_since": now,
                    "v360_sync_message": message,
                })
                state["inflight"][path] = row

            store.mutate(mark_pending_evidence)
            pending_evidence += 1

        if confirmed or pending_evidence:
            logger.info(
                "【光鸭云盘助手】【v3.6.0】【最终结果】同步成功：MP历史确认=%s，等待最终事件/历史=%s；不把等待证据写成失败",
                confirmed,
                pending_evidence,
            )

    # ------------------------------------------------------------------
    # owner / runtime status
    # ------------------------------------------------------------------
    def _v360_owner_gate(self) -> Tuple[bool, Dict[str, Any]]:
        """所有扫描入口的统一 owner 门禁。"""
        try:
            claimed = bool(self._claim_isolated_runtime())
        except Exception as err:  # noqa: BLE001
            self._save_monitor_status(
                runtime_phase="handoff",
                runtime_label="Worker owner 检查失败，暂停发现",
                worker_handoff_waiting=True,
                worker_handoff_error=str(err),
            )
            return False, {}

        snapshot = dict(self._isolated_queue_snapshot() or {})
        if not claimed:
            owner_path = str(snapshot.get("owner_running_path") or "")
            self._save_monitor_status(
                runtime_phase="handoff",
                runtime_label="Worker 交接中，不扫描、不入队、不写 retry",
                worker_handoff_waiting=True,
                current_task_path=owner_path,
                worker_handoff_path=owner_path,
                scan_in_progress=False,
            )
            return False, snapshot

        self._save_monitor_status(worker_handoff_waiting=False)
        return True, snapshot

    @staticmethod
    def _v360_worker_busy(snapshot: Dict[str, Any]) -> bool:
        return bool(
            str(snapshot.get("running_path") or "")
            or int(snapshot.get("queued") or 0) > 0
            or int(snapshot.get("owned") or 0) > 0
        )

    # ------------------------------------------------------------------
    # persistent 50-directory discovery cursor
    # ------------------------------------------------------------------
    def _v360_norm(self, value: Any) -> str:
        try:
            return self._organize_normalize_path(str(value or ""))
        except Exception:
            return str(value or "").replace("\\", "/").rstrip("/")

    def _v360_new_cursor(self, root: str, *, cycle: int = 1) -> Dict[str, Any]:
        return {
            "schema": _CURSOR_SCHEMA,
            "monitor_path": root,
            "cycle": max(int(cycle or 1), 1),
            "page": 0,
            "queue": [root],
            "seen": [root],
            "updated_at": time.time(),
        }

    def _v360_load_cursor(self, root: str) -> Dict[str, Any]:
        raw = self.get_data(_CURSOR_KEY) or {}
        if not isinstance(raw, dict):
            return self._v360_new_cursor(root)
        if int(raw.get("schema") or 0) != _CURSOR_SCHEMA:
            return self._v360_new_cursor(root)
        if self._v360_norm(raw.get("monitor_path")) != root:
            return self._v360_new_cursor(root)

        queue: List[str] = []
        seen: Set[str] = set()
        for value in raw.get("queue") or []:
            path = self._v360_norm(value)
            if path and path not in queue:
                queue.append(path)
            if len(queue) >= _MAX_CURSOR_DIRS:
                break
        for value in raw.get("seen") or []:
            path = self._v360_norm(value)
            if path:
                seen.add(path)
            if len(seen) >= _MAX_CURSOR_DIRS:
                break
        if not queue:
            return self._v360_new_cursor(root, cycle=int(raw.get("cycle") or 0) + 1)
        return {
            "schema": _CURSOR_SCHEMA,
            "monitor_path": root,
            "cycle": max(int(raw.get("cycle") or 1), 1),
            "page": max(int(raw.get("page") or 0), 0),
            "queue": queue,
            "seen": list(seen or {root}),
            "updated_at": float(raw.get("updated_at") or 0),
        }

    def _v360_save_cursor(self, cursor: Dict[str, Any]) -> None:
        payload = dict(cursor)
        payload["updated_at"] = time.time()
        self.save_data(_CURSOR_KEY, payload)

    def _v360_list_directory(self, path: str) -> Tuple[List[Any], List[Any]]:
        if not self._guangya_api:
            raise RuntimeError("光鸭云盘尚未登录或存储未初始化")
        current = self._guangya_api.get_item(Path(path))
        if not current or str(getattr(current, "type", "") or "") != "dir":
            return [], []
        dirs: List[Any] = []
        files: List[Any] = []
        for child in list(self._guangya_api.list(current) or []):
            name = str(getattr(child, "name", "") or "")
            if not name or name.startswith("."):
                continue
            kind = str(getattr(child, "type", "") or "")
            if kind == "dir":
                if self._organize_monitor_recursive:
                    dirs.append(child)
            elif kind == "file":
                files.append(child)
        dirs.sort(key=self._group_sort_key)
        files.sort(key=self._file_sort_key)
        return dirs, files

    @staticmethod
    def _v360_is_under(path: str, parent: str) -> bool:
        try:
            child = PurePosixPath(path)
            root = PurePosixPath(parent)
            return child == root or child.is_relative_to(root)
        except Exception:
            return False

    def _v360_primary_files(self, files: Sequence[Any]) -> List[Any]:
        media_exts = _runtime_media_exts()
        return [
            item
            for item in files
            if Path(str(getattr(item, "name", "") or getattr(item, "path", "") or "")).suffix.casefold()
            in media_exts
        ]

    # ------------------------------------------------------------------
    # scheduler
    # ------------------------------------------------------------------
    def _v360_prepare_member(self, member: Any) -> Tuple[str, Optional[Tuple[Any, str, str]]]:
        """返回 (phase, ready-row)。unknown/history wait 不写 retry。"""
        path, fingerprint = self._v360_member_identity(member)
        store = self._state()
        now = time.time()
        phase = store.classify(
            path=path,
            fingerprint=fingerprint,
            now=now,
            stability_seconds=self._organize_monitor_stability,
            inflight_lease_seconds=self._monitor_inflight_lease,
        )

        if phase == "completed":
            decision = self._v360_history_decision(member, path)
            kind = str(decision.get("decision") or "")
            if kind == "completed":
                return "completed", None
            if kind == "blocked":
                store.mark_blocked(
                    path=path,
                    fingerprint=fingerprint,
                    reason=str(decision.get("message") or "MoviePilot 历史阻断"),
                    now=now,
                )
                return "blocked", None
            if kind == "unknown":
                # 历史暂不可用时宁可保留 completed，也不重复搬运。
                return "history_wait", None
            self._v360_reopen_completed(path, fingerprint)
            phase = "ready"

        if phase == "ignored":
            return "ignored", None
        if phase == "blocked":
            return "blocked", None
        if phase == "stabilizing":
            return "stabilizing", None
        if phase == "retry_wait":
            return "retry_wait", None
        if phase == "inflight":
            raw = store.load()
            row = dict((raw.get("inflight") or {}).get(path) or {})
            if row.get("v360_sync_success"):
                decision = self._v360_history_decision(member, path)
                if str(decision.get("decision") or "") == "completed":
                    store.mark_completed(path=path, fingerprint=fingerprint)
                    return "completed", None
            return "inflight", None

        decision = self._v360_history_decision(member, path)
        kind = str(decision.get("decision") or "")
        if kind == "completed":
            store.mark_completed(path=path, fingerprint=fingerprint)
            return "completed", None
        if kind == "blocked":
            store.mark_blocked(
                path=path,
                fingerprint=fingerprint,
                reason=str(decision.get("message") or "MoviePilot 历史阻断"),
                now=now,
            )
            return "blocked", None
        if kind == "unknown":
            return "history_wait", None
        return "ready", (member, path, fingerprint)

    def _v360_make_envelope(
        self,
        group_path: str,
        members: Sequence[Any],
        *,
        directory_mode: bool,
    ) -> _FolderBatchEnvelope:
        now = time.time()
        batch_id = self._new_group_batch_id(group_path, now)
        members = list(members)
        return _FolderBatchEnvelope(
            path=group_path,
            name=self._group_name(group_path),
            members=members,
            batch_id=batch_id,
            directory_mode=directory_mode,
            fileid=_batch_fingerprint(self, members, group_path),
            size=sum(int(getattr(item, "size", 0) or 0) for item in members),
            modify_time=max([float(getattr(item, "modify_time", 0) or 0) for item in members] or [0.0]),
        )

    def _v360_schedule_resource(self, group_path: str, files: Sequence[Any]) -> Dict[str, Any]:
        primary = self._v360_primary_files(files)
        if not primary:
            return {"scheduled": False, "reason": "no_primary", "primary": 0}

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
                return {"scheduled": False, "reason": "member_wait", "primary": len(primary), "phases": phases}
            selected = [rows[0]]
            directory_mode = False
        else:
            # 资源目录采用一次 MoviePilot 目录任务。只要还有 stabilizing/inflight/retry/history_wait，
            # 就不把目录整体交给 MP，避免绕过文件级等待边界。blocked/completed 不阻断其它成员。
            hard_wait = sum(
                phases.get(name, 0)
                for name in ("stabilizing", "inflight", "retry_wait", "history_wait")
            )
            if hard_wait:
                return {"scheduled": False, "reason": "resource_wait", "primary": len(primary), "phases": phases}
            if not rows:
                return {"scheduled": False, "reason": "no_ready", "primary": len(primary), "phases": phases}
            selected = rows
            directory_mode = _can_use_native_directory_batch(self, normalized_group, [row[0] for row in selected])

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
                },
            )
            if attempt:
                accepted_members.append(member)

        if not accepted_members:
            return {"scheduled": False, "reason": "state_changed", "primary": len(primary), "phases": phases}
        envelope.members = accepted_members

        try:
            accepted = bool(self._dispatch_to_moviepilot(envelope))
        except Exception as err:  # noqa: BLE001 - scheduling failure is pending, not retry
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
                "【光鸭云盘助手】【v3.6.0】【调度】资源未进入 worker，成员=%s 已回 pending，不写 retry: %s%s",
                restored,
                normalized_group,
                f" - {dispatch_message}" if dispatch_message else "",
            )
            return {"scheduled": False, "reason": "worker_not_accept", "primary": len(primary), "phases": phases}

        self._save_monitor_status(
            runtime_phase="queued",
            runtime_label="当前资源已进入私有 Worker",
            current_task_path=normalized_group,
            current_group=normalized_group,
            current_group_name=self._group_name(normalized_group),
            active_resource_tasks=1,
            submitted=len(accepted_members),
        )
        mode_text = "MoviePilot原生目录" if directory_mode else "单文件/弱命名兼容"
        logger.info(
            "【光鸭云盘助手】【v3.6.0】【调度】当前资源已入队: %s，成员=%s，模式=%s",
            normalized_group,
            len(accepted_members),
            mode_text,
        )
        return {
            "scheduled": True,
            "reason": "queued",
            "primary": len(primary),
            "submitted": len(accepted_members),
            "directory_mode": directory_mode,
            "phases": phases,
        }

    # ------------------------------------------------------------------
    # public scan/tick authority
    # ------------------------------------------------------------------
    def organize_monitor_tick(self) -> None:
        self.init_organizer_monitor()
        if not getattr(self, "_organize_monitor_enabled", False):
            return
        # heartbeat 本身就是有界触发器。worker busy/handoff 会在 run 的统一门禁立即返回。
        return self.run_organize_monitor_scan(manual=False)

    def run_organize_monitor_scan(self, manual: bool = False) -> Dict[str, Any]:
        """唯一扫描入口：owner gate 在任何状态/目录枚举之前执行。"""
        self.init_organizer_monitor()
        if not manual and not self._organize_monitor_enabled:
            return {"success": True, "message": "自动整理监控未启用", "data": {"disabled": True}}
        if not self._enabled or not self._guangya_api:
            return {"success": False, "message": "光鸭云盘未启用或未登录"}
        if self._organize_monitor_path == "/":
            return {"success": False, "message": "请先选择具体监控目录，禁止直接监控根目录"}

        # P0：任何入口（初始化首扫/手动/heartbeat/refill）都必须先取得 owner。
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
            self._save_monitor_status(
                runtime_phase="running",
                runtime_label="当前资源整理中",
                current_task_path=running,
                scan_in_progress=False,
                active_resource_tasks=1,
            )
            return {
                "success": True,
                "message": "当前资源整理中，本轮不扫描下一资源",
                "data": {"busy": True, "current_task_path": running},
            }

        lock = self._organize_scan_lock
        if lock is None:
            import threading
            lock = threading.Lock()
            self._organize_scan_lock = lock
        if not lock.acquire(blocking=False):
            return {"success": True, "message": "已有 discovery 正在运行", "data": {"scan_busy": True}}

        started = time.time()
        root = self._v360_norm(self._organize_monitor_path)
        cursor = self._v360_load_cursor(root)
        cursor["page"] = int(cursor.get("page") or 0) + 1
        queue = list(cursor.get("queue") or [root])
        seen: Set[str] = set(cursor.get("seen") or [root])
        dirs_scanned = 0
        files_seen = 0
        resource_dirs = 0
        scheduled_result: Optional[Dict[str, Any]] = None
        errors: List[str] = []
        now_text = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self._save_monitor_status(
            running=self._organize_monitor_enabled,
            runtime_phase="discovering",
            runtime_label="按 50 目录游标发现资源",
            scan_in_progress=True,
            scan_started=now_text,
            current_task_path="",
            scan_page_size=_PAGE_DIR_LIMIT,
            scan_cursor_cycle=int(cursor.get("cycle") or 1),
            scan_cursor_page=int(cursor.get("page") or 1),
        )

        try:
            while queue and dirs_scanned < _PAGE_DIR_LIMIT:
                current_path = queue[0]
                try:
                    child_dirs, direct_files = self._v360_list_directory(current_path)
                except Exception as err:  # noqa: BLE001 - discovery failure never becomes task retry
                    errors.append(f"{current_path}: {err}")
                    cursor.update({"queue": queue, "seen": list(seen)})
                    self._v360_save_cursor(cursor)
                    logger.warning(
                        "【光鸭云盘助手】【v3.6.0】【发现】目录读取失败，本轮停在断点，不修改任务 retry: %s - %s",
                        current_path,
                        err,
                    )
                    break

                queue.pop(0)
                dirs_scanned += 1
                files_seen += len(direct_files)
                for child in child_dirs:
                    child_path = self._v360_norm(getattr(child, "path", ""))
                    if not child_path or child_path in seen:
                        continue
                    if len(seen) >= _MAX_CURSOR_DIRS:
                        errors.append("目录游标达到安全上限")
                        break
                    seen.add(child_path)
                    queue.append(child_path)

                primary = self._v360_primary_files(direct_files)
                if not primary:
                    continue
                resource_dirs += 1

                result = self._v360_schedule_resource(current_path, direct_files)
                if result.get("scheduled"):
                    # 当前资源完成后优先回来看同目录：成功时目录已空会自然前进；部分失败时
                    # retry_wait 会让该目录暂不提交，但不会形成持久 sticky。
                    if current_path not in queue:
                        queue.insert(0, current_path)
                    scheduled_result = result
                    break

            cycle_complete = not queue
            completed_cycle = int(cursor.get("cycle") or 1)
            if cycle_complete:
                cursor = self._v360_new_cursor(root, cycle=completed_cycle + 1)
            else:
                cursor.update({"queue": queue, "seen": list(seen)})
            self._v360_save_cursor(cursor)

            status_phase = "queued" if scheduled_result else "idle"
            status_label = "当前资源已入队" if scheduled_result else "本页 discovery 完成，等待下一页"
            self._save_monitor_status(
                scan_in_progress=False,
                runtime_phase=status_phase,
                runtime_label=status_label,
                scan_page_size=_PAGE_DIR_LIMIT,
                scan_dirs_scanned=dirs_scanned,
                scan_files_seen=files_seen,
                scan_resource_dirs=resource_dirs,
                scan_cursor_cycle=int(cursor.get("cycle") or 1),
                scan_cursor_page=int(cursor.get("page") or 0),
                scan_cursor_remaining_dirs=len(cursor.get("queue") or []),
                scan_cycle_complete=cycle_complete,
                scan_errors=errors[:10],
            )

            logger.info(
                "【光鸭云盘助手】【v3.6.0】【发现】本轮目录=%s/%s，文件=%s，资源目录=%s，提交资源=%s，"
                "剩余目录=%s，cycle=%s；无全库重扫、无 discovery→retry",
                dirs_scanned,
                _PAGE_DIR_LIMIT,
                files_seen,
                resource_dirs,
                1 if scheduled_result else 0,
                len(cursor.get("queue") or []),
                completed_cycle,
            )
            return {
                "success": True,
                "message": "已提交 1 个资源" if scheduled_result else "本页 discovery 完成",
                "data": {
                    "dirs_scanned": dirs_scanned,
                    "files_seen": files_seen,
                    "resource_dirs": resource_dirs,
                    "scheduled": bool(scheduled_result),
                    "remaining_dirs": len(cursor.get("queue") or []),
                    "cycle_complete": cycle_complete,
                    "elapsed": round(time.time() - started, 3),
                    "errors": errors[:10],
                },
            }
        finally:
            try:
                lock.release()
            except RuntimeError:
                pass


__all__ = ["GuangYaOrganizerEngineV360Mixin", "_PAGE_DIR_LIMIT"]
