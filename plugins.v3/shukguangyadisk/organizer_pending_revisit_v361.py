"""v3.6.1：稳定等待资源到期后优先回访。

3.6.0 已把自动整理收口为统一 discovery/scheduler/worker 状态机，但首次发现的资源在
``stabilizing`` 期间会随着 50 目录游标继续向后走，只能等整个 discovery cycle 绕回后
再次检查。在大目录中这会让已经稳定的资源无谓等待数分钟。

本层只修调度等待，不改变 MoviePilot 识别、分类、命名、season、冲突、安全预览或最终
结果语义：
- 每个进入 stabilizing/history_wait/retry_wait 的资源目录记录一个轻量 pending-resource；
- 到期后下一次扫描优先回访该资源，成功入 Worker 后立即移除；
- 每次优先回访只读取 1 个目录，仍满足单轮最多 50 个目录的边界；
- 升级时从现有 stabilizing 文件直接种入 pending-resource，避免已有等待项再绕完整 cycle；
- 修复 3.6.0 部分“回 discovery pending”路径把 ``first_seen=0`` 写入状态，而
  ``OrganizerStateStore.classify`` 使用 ``row.get('first_seen') or now`` 导致每次重新从当前
  时间开始稳定计时、理论上永久 stabilizing 的问题。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from app.sdk.logging import logger


_PENDING_KEY = "organize_v361_pending_resources"
_PENDING_SCHEMA = 1
_PENDING_LIMIT = 1000
_HISTORY_RECHECK_SECONDS = 10.0


class GuangYaOrganizerPendingRevisitV361Mixin:
    """位于 v3.6 execution 之前的轻量等待/回访层。"""

    _v361_initialized: bool = False

    def init_organizer_monitor(self) -> None:
        super().init_organizer_monitor()
        if self._v361_initialized:
            return
        self._v361_initialized = True
        repaired = self._v361_repair_zero_first_seen()
        seeded = self._v361_seed_existing_stabilizing()
        logger.info(
            "【光鸭云盘助手】【v3.6.1】稳定资源优先回访已启用：pending 到期即优先处理，不等待整库 cycle；first_seen 修复=%s，升级种入资源=%s",
            repaired,
            seeded,
        )

    # ------------------------------------------------------------------
    # first_seen semantic repair
    # ------------------------------------------------------------------
    def _v361_repair_zero_first_seen(self, paths: Iterable[str] | None = None) -> int:
        wanted = {self._v360_norm(path) for path in (paths or []) if path}
        now = time.time()

        def apply(state: Dict[str, Any]) -> int:
            stabilizing = dict(state.get("stabilizing") or {})
            repaired = 0
            for path, raw in list(stabilizing.items()):
                if wanted and self._v360_norm(path) not in wanted:
                    continue
                row = dict(raw or {}) if isinstance(raw, dict) else {}
                try:
                    first_seen = float(row.get("first_seen") or 0)
                except (TypeError, ValueError):
                    first_seen = 0
                if first_seen > 0:
                    continue
                row["first_seen"] = now
                row["v361_first_seen_repaired"] = True
                stabilizing[path] = row
                repaired += 1
            state["stabilizing"] = stabilizing
            return repaired

        return int(self._state().mutate(apply) or 0)

    def _v360_return_members_to_pending(self, members: Iterable[Any], *, reason: str) -> int:
        members = list(members)
        restored = int(super()._v360_return_members_to_pending(members, reason=reason) or 0)
        paths: List[str] = []
        for member in members:
            for real_member in self._v360_members(member):
                try:
                    path, _ = self._v360_member_identity(real_member)
                except Exception:
                    continue
                if path:
                    paths.append(path)
        if paths:
            self._v361_repair_zero_first_seen(paths)
        return restored

    def _recover_isolated_inflight_once(self) -> int:
        recovered = int(super()._recover_isolated_inflight_once() or 0)
        if recovered:
            self._v361_repair_zero_first_seen()
            self._v361_seed_existing_stabilizing()
        return recovered

    def _v360_reopen_completed(self, path: str, fingerprint: str) -> None:
        super()._v360_reopen_completed(path, fingerprint)
        self._v361_repair_zero_first_seen([path])
        self._v361_seed_existing_stabilizing([path])

    # ------------------------------------------------------------------
    # pending resource queue
    # ------------------------------------------------------------------
    def _v361_load_pending(self) -> Dict[str, Dict[str, Any]]:
        raw = self.get_data(_PENDING_KEY) or {}
        if not isinstance(raw, dict) or int(raw.get("schema") or 0) != _PENDING_SCHEMA:
            return {}
        monitor_path = self._v360_norm(raw.get("monitor_path"))
        current_root = self._v360_norm(getattr(self, "_organize_monitor_path", ""))
        if monitor_path != current_root:
            return {}
        rows: Dict[str, Dict[str, Any]] = {}
        for path, row in dict(raw.get("rows") or {}).items():
            normalized = self._v360_norm(path)
            if not normalized or not isinstance(row, dict):
                continue
            rows[normalized] = dict(row)
            if len(rows) >= _PENDING_LIMIT:
                break
        return rows

    def _v361_save_pending(self, rows: Dict[str, Dict[str, Any]]) -> None:
        current_root = self._v360_norm(getattr(self, "_organize_monitor_path", ""))
        ordered = sorted(
            rows.items(),
            key=lambda pair: (float((pair[1] or {}).get("due_at") or 0), pair[0]),
        )[:_PENDING_LIMIT]
        self.save_data(
            _PENDING_KEY,
            {
                "schema": _PENDING_SCHEMA,
                "monitor_path": current_root,
                "rows": {path: row for path, row in ordered},
                "updated_at": time.time(),
            },
        )

    def _v361_seed_existing_stabilizing(self, only_paths: Iterable[str] | None = None) -> int:
        """把升级前已经存在的文件级 stabilizing 状态折叠成资源目录优先回访队列。"""
        wanted = {self._v360_norm(path) for path in (only_paths or []) if path}
        state = self._state().load()
        stabilizing = dict(state.get("stabilizing") or {})
        rows = self._v361_load_pending()
        root = self._v360_norm(getattr(self, "_organize_monitor_path", ""))
        stability = max(float(getattr(self, "_organize_monitor_stability", 0) or 0), 0.0)
        now = time.time()
        seeded_groups: set[str] = set()

        for raw_path, raw_row in stabilizing.items():
            path = self._v360_norm(raw_path)
            if wanted and path not in wanted:
                continue
            if not path or not root or not self._v360_is_under(path, root):
                continue
            row = dict(raw_row or {}) if isinstance(raw_row, dict) else {}
            try:
                first_seen = float(row.get("first_seen") or 0)
            except (TypeError, ValueError):
                first_seen = 0
            if first_seen <= 0:
                first_seen = now

            group_path = self._v360_norm(Path(path).parent.as_posix())
            if not group_path or group_path == "/":
                continue
            due_at = first_seen + stability
            existing = dict(rows.get(group_path) or {})
            existing_due = float(existing.get("due_at") or 0)
            # 目录任务要求同目录所有待稳定成员都成熟，因此取最晚 due_at，防止反复抢占游标。
            existing.update(
                {
                    "due_at": max(existing_due, due_at),
                    "reason": "startup_stabilizing_seed",
                    "updated_at": now,
                }
            )
            rows[group_path] = existing
            seeded_groups.add(group_path)

        if seeded_groups:
            self._v361_save_pending(rows)
        return len(seeded_groups)

    def _v361_remove_pending(self, group_path: str) -> None:
        group_path = self._v360_norm(group_path)
        rows = self._v361_load_pending()
        if group_path in rows:
            rows.pop(group_path, None)
            self._v361_save_pending(rows)

    def _v361_due_at(self, files: Sequence[Any], result: Dict[str, Any]) -> float:
        now = time.time()
        state = self._state().load()
        stabilizing = dict(state.get("stabilizing") or {})
        retry = dict(state.get("retry") or {})
        due_values: List[float] = []

        for member in self._v360_primary_files(files):
            try:
                path, fingerprint = self._v360_member_identity(member)
            except Exception:
                continue
            row = stabilizing.get(path)
            if isinstance(row, dict) and str(row.get("fingerprint") or "") == fingerprint:
                try:
                    first_seen = float(row.get("first_seen") or 0)
                except (TypeError, ValueError):
                    first_seen = 0
                if first_seen <= 0:
                    first_seen = now
                due_values.append(first_seen + max(float(self._organize_monitor_stability), 0.0))

            retry_row = retry.get(path)
            if isinstance(retry_row, dict) and str(retry_row.get("fingerprint") or "") == fingerprint:
                try:
                    retry_at = float(retry_row.get("retry_at") or 0)
                except (TypeError, ValueError):
                    retry_at = 0
                if retry_at > 0:
                    due_values.append(retry_at)

        phases = dict(result.get("phases") or {})
        if phases.get("history_wait"):
            due_values.append(now + _HISTORY_RECHECK_SECONDS)
        if phases.get("inflight"):
            due_values.append(now + _HISTORY_RECHECK_SECONDS)

        # 目录级任务必须等所有 hard-wait 成员到期，所以取最晚时间；单文件 loose 目录只有一个值。
        return max(max(due_values or [now + _HISTORY_RECHECK_SECONDS]), now + 0.5)

    def _v361_register_pending(self, group_path: str, files: Sequence[Any], result: Dict[str, Any]) -> None:
        group_path = self._v360_norm(group_path)
        if not group_path or group_path == "/":
            return
        rows = self._v361_load_pending()
        row = dict(rows.get(group_path) or {})
        row.update(
            {
                "due_at": self._v361_due_at(files, result),
                "reason": str(result.get("reason") or "wait"),
                "phases": dict(result.get("phases") or {}),
                "updated_at": time.time(),
            }
        )
        rows[group_path] = row
        self._v361_save_pending(rows)

    def _v360_schedule_resource(self, group_path: str, files: Sequence[Any]) -> Dict[str, Any]:
        result = dict(super()._v360_schedule_resource(group_path, files) or {})
        if result.get("scheduled"):
            self._v361_remove_pending(group_path)
            return result

        reason = str(result.get("reason") or "")
        phases = dict(result.get("phases") or {})
        waiting = reason in {"member_wait", "resource_wait"} or any(
            phases.get(name) for name in ("stabilizing", "history_wait", "retry_wait", "inflight")
        )
        if waiting:
            self._v361_register_pending(group_path, files, result)
        elif reason in {"no_primary", "no_ready", "state_changed"}:
            self._v361_remove_pending(group_path)
        return result

    def _v361_next_due(self) -> Tuple[str, Dict[str, Any]]:
        now = time.time()
        rows = self._v361_load_pending()
        due = [
            (path, row)
            for path, row in rows.items()
            if float((row or {}).get("due_at") or 0) <= now
        ]
        if not due:
            return "", {}
        due.sort(key=lambda pair: (float((pair[1] or {}).get("due_at") or 0), pair[0]))
        return due[0]

    def _v361_try_due_resource(self) -> Dict[str, Any] | None:
        group_path, pending_row = self._v361_next_due()
        if not group_path:
            return None

        try:
            child_dirs, direct_files = self._v360_list_directory(group_path)
            _ = child_dirs
        except Exception as err:  # discovery problem is not task failure
            rows = self._v361_load_pending()
            rows[group_path] = {
                **dict(pending_row or {}),
                "due_at": time.time() + _HISTORY_RECHECK_SECONDS,
                "last_error": str(err),
                "updated_at": time.time(),
            }
            self._v361_save_pending(rows)
            logger.warning(
                "【光鸭云盘助手】【v3.6.1】【优先回访】资源目录读取失败，稍后再查，不写 retry: %s - %s",
                group_path,
                err,
            )
            return {
                "success": True,
                "message": "待稳定资源回访读取失败，已保留等待",
                "data": {"priority_revisit": True, "scheduled": False, "path": group_path},
            }

        if not self._v360_primary_files(direct_files):
            self._v361_remove_pending(group_path)
            logger.info(
                "【光鸭云盘助手】【v3.6.1】【优先回访】资源已搬空/无主视频，移出 pending: %s",
                group_path,
            )
            return {
                "success": True,
                "message": "待稳定资源已无主视频",
                "data": {"priority_revisit": True, "scheduled": False, "path": group_path},
            }

        result = dict(self._v360_schedule_resource(group_path, direct_files) or {})
        scheduled = bool(result.get("scheduled"))
        logger.info(
            "【光鸭云盘助手】【v3.6.1】【优先回访】%s -> scheduled=%s reason=%s phases=%s",
            group_path,
            scheduled,
            result.get("reason"),
            result.get("phases"),
        )
        return {
            "success": True,
            "message": "待稳定资源已优先提交" if scheduled else "待稳定资源已优先复查",
            "data": {
                "priority_revisit": True,
                "scheduled": scheduled,
                "path": group_path,
                "result": result,
            },
        }

    def run_organize_monitor_scan(self, manual: bool = False) -> Dict[str, Any]:
        """到期 pending 优先于普通游标；每次只回访 1 个目录，因此不会突破 50 目录上限。"""
        self.init_organizer_monitor()
        if not manual and not getattr(self, "_organize_monitor_enabled", False):
            return super().run_organize_monitor_scan(manual=manual)
        if not getattr(self, "_enabled", False) or not getattr(self, "_guangya_api", None):
            return super().run_organize_monitor_scan(manual=manual)

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
            return super().run_organize_monitor_scan(manual=manual)

        priority = self._v361_try_due_resource()
        if priority is not None:
            return priority
        return super().run_organize_monitor_scan(manual=manual)


__all__ = ["GuangYaOrganizerPendingRevisitV361Mixin"]
