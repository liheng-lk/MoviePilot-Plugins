"""v3.6.1 / v3.6.8：稳定等待资源优先回访与陈旧 pending 自愈。

3.6.0 已把自动整理收口为统一 discovery/scheduler/worker 状态机，但首次发现的资源在
``stabilizing`` 期间会随着 50 目录游标继续向后走，只能等整个 discovery cycle 绕回后
再次检查。在大目录中这会让已经稳定的资源无谓等待数分钟。

v3.6.1 增加轻量 pending-resource，让 stabilizing/history_wait/retry_wait 到期后优先回访。
v3.6.8 进一步修复终态清理：历史版本会让已经整理完成、已经搬空的资源继续留在 pending，
而旧实现每个 monitor tick 只清 1 条，历史残留会长期抢占新资源扫描。本层现在：
- 启动与最终成功后先用状态机证据批量剔除已经没有等待态的 pending；
- 对仍需远端确认的陈旧记录，同一轮最多连续清理 50 个“已搬空/无主视频”目录；
- 只要遇到一个仍有主视频的真实 pending，立即停止清理并按原语义调度该资源；
- 清理 pending 时同步移除 v3.6.6 known-resource 陈旧索引，避免下一阶段再次检查同一路径；
- 真正处于 stabilizing/history_wait/retry_wait/inflight 的资源仍保留，不清空有效等待。
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
_PENDING_STALE_SWEEP_LIMIT = 50


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
        pruned = self._v361_prune_stale_pending()
        logger.info(
            "【光鸭云盘助手】【v3.6.8】稳定资源优先回访已启用：pending 到期即优先处理，不等待整库 cycle；"
            "first_seen 修复=%s，升级种入资源=%s，陈旧 pending 自愈=%s",
            repaired,
            seeded,
            pruned,
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

    def _v361_direct_members(self, mapping: Dict[str, Any], group_path: str) -> List[str]:
        """返回状态表中直属于 group_path 的成员路径，避免父级目录误吸收其它资源。"""
        group_path = self._v360_norm(group_path)
        members: List[str] = []
        for raw_path in mapping:
            path = self._v360_norm(raw_path)
            if not path:
                continue
            parent = self._v360_norm(Path(path).parent.as_posix())
            if parent == group_path:
                members.append(path)
        return members

    def _v361_pending_has_state_evidence(
        self,
        group_path: str,
        row: Dict[str, Any],
        state: Dict[str, Any],
    ) -> bool:
        """判断 pending 是否仍有本地等待态证据；只看直属成员，避免库根误保活。"""
        for name in ("stabilizing", "inflight", "retry"):
            if self._v361_direct_members(dict(state.get(name) or {}), group_path):
                return True

        # history_wait 的本地状态仍是 completed；历史接口暂不可用时必须保留回访。
        phases = dict((row or {}).get("phases") or {})
        if int(phases.get("history_wait") or 0) > 0:
            completed = dict(state.get("completed") or {})
            if self._v361_direct_members(completed, group_path):
                return True
        return False

    def _v361_prune_stale_pending(self) -> int:
        """纯本地批量清理已经没有任何等待态证据的历史 pending，不发远端请求。"""
        rows = self._v361_load_pending()
        if not rows:
            return 0
        state = self._state().load()
        removed: List[str] = []
        for group_path, row in list(rows.items()):
            if self._v361_pending_has_state_evidence(group_path, dict(row or {}), state):
                continue
            rows.pop(group_path, None)
            removed.append(group_path)
        if not removed:
            return 0
        self._v361_save_pending(rows)
        self._save_monitor_status(
            pending_stale_local_pruned=len(removed),
            pending_stale_local_pruned_at=time.time(),
            pending_revisit_total=len(rows),
        )
        logger.info(
            "【光鸭云盘助手】【v3.6.8】【pending自愈】本地批量清理无等待态历史 pending=%s，剩余=%s",
            len(removed),
            len(rows),
        )
        return len(removed)

    def _v361_forget_known_resource(self, group_path: str) -> None:
        """资源已搬空时同步清掉 v3.6.6 known-resource 索引，避免后续重复目录检查。"""
        loader = getattr(self, "_v366_load_known", None)
        saver = getattr(self, "_v366_save_known", None)
        if not callable(loader) or not callable(saver):
            return
        try:
            rows = dict(loader() or {})
        except Exception:
            return
        group_path = self._v360_norm(group_path)
        if group_path not in rows:
            return
        rows.pop(group_path, None)
        try:
            saver(rows)
        except Exception:
            return

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
        """优先处理真实等待资源；同轮批量扫掉已搬空历史 pending，避免一分钟只清一条。"""
        local_pruned = self._v361_prune_stale_pending()
        remote_pruned = 0
        last_pruned_path = ""

        for _ in range(_PENDING_STALE_SWEEP_LIMIT):
            group_path, pending_row = self._v361_next_due()
            if not group_path:
                if local_pruned or remote_pruned:
                    self._save_monitor_status(
                        pending_stale_remote_pruned=remote_pruned,
                        pending_stale_remote_pruned_at=time.time(),
                        pending_revisit_total=len(self._v361_load_pending()),
                    )
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
                    "【光鸭云盘助手】【v3.6.8】【优先回访】资源目录读取失败，稍后再查，不写 retry: %s - %s",
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
                self._v361_forget_known_resource(group_path)
                remote_pruned += 1
                last_pruned_path = group_path
                continue

            result = dict(self._v360_schedule_resource(group_path, direct_files) or {})
            scheduled = bool(result.get("scheduled"))
            if local_pruned or remote_pruned:
                logger.info(
                    "【光鸭云盘助手】【v3.6.8】【pending自愈】提交真实等待资源前已清理：本地=%s，搬空目录=%s",
                    local_pruned,
                    remote_pruned,
                )
            logger.info(
                "【光鸭云盘助手】【v3.6.8】【优先回访】%s -> scheduled=%s reason=%s phases=%s",
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
                    "stale_local_pruned": local_pruned,
                    "stale_remote_pruned": remote_pruned,
                },
            }

        # 单轮最多 50 个远端陈旧目录，保护 API；下一 tick 继续，但已不再是一分钟只清 1 条。
        if remote_pruned:
            remaining = len(self._v361_load_pending())
            self._save_monitor_status(
                pending_stale_remote_pruned=remote_pruned,
                pending_stale_remote_pruned_at=time.time(),
                pending_revisit_total=remaining,
            )
            logger.info(
                "【光鸭云盘助手】【v3.6.8】【pending自愈】单轮已批量清理搬空 pending=%s，剩余=%s，最后=%s",
                remote_pruned,
                remaining,
                last_pruned_path,
            )
            return {
                "success": True,
                "message": "陈旧 pending 已批量清理",
                "data": {
                    "priority_revisit": True,
                    "scheduled": False,
                    "stale_local_pruned": local_pruned,
                    "stale_remote_pruned": remote_pruned,
                    "pending_remaining": remaining,
                },
            }
        return None

    def _record_terminal_transfer(self, event: Any, success: bool) -> None:
        """最终成功落状态后立即做一次纯本地 pending 收口，避免等下一次扫描。"""
        super()._record_terminal_transfer(event, success)
        if not success:
            return
        pruned = self._v361_prune_stale_pending()
        if pruned:
            logger.info(
                "【光鸭云盘助手】【v3.6.8】【终态清理】MoviePilot 成功后即时移除陈旧 pending=%s",
                pruned,
            )

    def run_organize_monitor_scan(self, manual: bool = False) -> Dict[str, Any]:
        """到期 pending 优先于普通游标；陈旧项批量清理，真实资源仍只调度 1 个。"""
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
