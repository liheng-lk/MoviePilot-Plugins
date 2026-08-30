"""v3.6.0：自动整理调度收敛层。

这一版不再继续叠加 v3.5.x 的 discovery monkey-patch，而是把调度边界集中到
``GuangYaCandidateFilterMixin``：

- 唯一分页发现器：每轮最多访问 50 个目录，持久 BFS 游标断点续扫；
- sticky 空值保持为空，绝不把“无当前剧集”正规化成根目录 ``/``；历史 ``/`` sticky
  会自动清掉，不再锁死全库；
- Worker 热更新交接时，新实例冻结旧实例的 discovery/refill；已经进入旧扫描循环的实例
  从下一目录开始只做 no-op，不再 mark_submitting / 写入伪 retry；
- 所有新扫描入口在旧 owner 仍存活时直接跳过；
- v3.5.9 之前由“私有 worker 当前未接收文件夹任务”制造的 retry 直接删除并重新发现，
  不继承虚假 attempts/指数退避；其它真正的 MoviePilot/网络/识别失败状态不动；
- 恢复 init_organizer_monitor 的幂等语义，避免 legacy queue cleanup 每次状态查询/扫描都重跑。

媒体识别、分类、重命名、目标目录、覆盖、刮削和最终整理仍完全由 MoviePilot 负责。
"""

from __future__ import annotations

import time
import types
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, Iterator, List, Set, Tuple

from app.sdk.logging import logger

from . import organizer_orchestrator_v351 as _orch
from . import organizer_tv_sticky_graceful_stop_v352 as _sticky
from .organizer_deep_folder_stream_v3413 import _is_streaming_container
from .organizer_empty_folder_guard_v3410 import _runtime_media_exts
from .organizer_queue_recovery import GuangYaQueueRecoveryMixin
from .organizer_worker_guard import GuangYaWorkerGuardMixin


_CURSOR_KEY = "organize_v360_scan_cursor"
_RECONCILE_KEY = "organize_v360_false_retry_reconcile"
_PAGE_DIR_LIMIT = 50
_CURSOR_SCHEMA = 1
_CURSOR_CHECKPOINT_EVERY = 10
_MAX_CURSOR_DIRS = 20000
_MAX_CURSOR_FILES = 50000
_FREEZE_ATTR = "_guangya_discovery_frozen_v360"
_FALSE_RETRY_MARKERS = (
    "私有 worker 当前未接收文件夹任务",
    "MoviePilot 预检允许提交，但当前未接收入队",
)


def _norm(plugin: Any, value: Any) -> str:
    """路径正规化必须区分“空值”和真实根目录 /。"""
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        return plugin._organize_normalize_path(raw)
    except Exception:
        return raw.replace("\\", "/").rstrip("/") or "/"


def _under(plugin: Any, path: str, root: str) -> bool:
    path = _norm(plugin, path)
    root = _norm(plugin, root)
    if not path or not root:
        return False
    try:
        child = PurePosixPath(path)
        parent = PurePosixPath(root)
        return child == parent or child.is_relative_to(parent)
    except Exception:
        return False


def _dedupe(values: Iterable[str], *, limit: int) -> List[str]:
    result: List[str] = []
    seen: Set[str] = set()
    for raw in values:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
        if len(result) >= limit:
            break
    return result


def _new_cursor(root: str, cycle: int = 1) -> Dict[str, Any]:
    return {
        "schema": _CURSOR_SCHEMA,
        "monitor_path": root,
        "cycle": max(int(cycle or 1), 1),
        "page": 0,
        "queue": [root],
        "seen_dirs": [root],
        "inventory_paths": [],
        "overflow": False,
        "updated_at": time.time(),
    }


def _load_cursor(plugin: Any, root: str) -> Dict[str, Any]:
    raw = plugin.get_data(_CURSOR_KEY) or {}
    if not isinstance(raw, dict):
        return _new_cursor(root)
    if int(raw.get("schema") or 0) != _CURSOR_SCHEMA:
        return _new_cursor(root)
    if _norm(plugin, raw.get("monitor_path")) != root:
        return _new_cursor(root)

    queue = _dedupe((_norm(plugin, item) for item in raw.get("queue") or []), limit=_MAX_CURSOR_DIRS)
    seen_dirs = _dedupe((_norm(plugin, item) for item in raw.get("seen_dirs") or []), limit=_MAX_CURSOR_DIRS)
    inventory = _dedupe((_norm(plugin, item) for item in raw.get("inventory_paths") or []), limit=_MAX_CURSOR_FILES)
    if not queue:
        return _new_cursor(root, cycle=int(raw.get("cycle") or 0) + 1)
    return {
        "schema": _CURSOR_SCHEMA,
        "monitor_path": root,
        "cycle": max(int(raw.get("cycle") or 1), 1),
        "page": max(int(raw.get("page") or 0), 0),
        "queue": queue,
        "seen_dirs": seen_dirs or [root],
        "inventory_paths": inventory,
        "overflow": bool(raw.get("overflow")),
        "updated_at": float(raw.get("updated_at") or 0),
    }


def _save_cursor(plugin: Any, cursor: Dict[str, Any]) -> None:
    payload = dict(cursor)
    payload["updated_at"] = time.time()
    plugin.save_data(_CURSOR_KEY, payload)


def _direct_children(plugin: Any, path: str) -> Tuple[List[Any], List[Any], bool]:
    if not plugin._guangya_api:
        raise RuntimeError("光鸭云盘尚未登录或存储未初始化")
    current = plugin._guangya_api.get_item(Path(path))
    if not current or str(getattr(current, "type", "") or "") != "dir":
        return [], [], False
    child_dirs: List[Any] = []
    direct_files: List[Any] = []
    for child in list(plugin._guangya_api.list(current) or []):
        name = str(getattr(child, "name", "") or "")
        if name.startswith("."):
            continue
        kind = str(getattr(child, "type", "") or "")
        if kind == "dir":
            if plugin._organize_monitor_recursive:
                child_dirs.append(child)
        elif kind == "file":
            direct_files.append(child)
    child_dirs.sort(key=plugin._group_sort_key)
    direct_files.sort(key=plugin._file_sort_key)
    return child_dirs, direct_files, True


def _primary_files(files: List[Any]) -> List[Any]:
    media_exts = _runtime_media_exts()
    return [
        item for item in files
        if Path(str(getattr(item, "name", "") or getattr(item, "path", "") or "")).suffix.casefold()
        in media_exts
    ]


def _account_files(plugin: Any, files: List[Any], scan_meta: Dict[str, Any], inventory: Set[str]) -> bool:
    overflow = False
    for item in files:
        path = _norm(plugin, getattr(item, "path", ""))
        if not path:
            continue
        scan_meta["inventory_paths"].add(path)
        scan_meta["files"] += 1
        if path in inventory:
            continue
        if len(inventory) >= _MAX_CURSOR_FILES:
            overflow = True
            continue
        inventory.add(path)
    return overflow


def _clear_corrupt_sticky(plugin: Any, reason: str) -> None:
    plugin._save_monitor_status(
        sticky_tv_group_path="",
        sticky_tv_group_since=0,
        sticky_tv_group_active=False,
        sticky_tv_group_release_reason=reason,
        sticky_tv_group_released_at=time.time(),
    )


def _sticky_group(plugin: Any) -> str:
    status = dict(plugin.get_data(plugin._monitor_status_key) or {})
    raw = str(status.get("sticky_tv_group_path") or "").strip()
    if not raw:
        return ""
    sticky = _norm(plugin, raw)
    monitor = _norm(plugin, getattr(plugin, "_organize_monitor_path", ""))
    if sticky == "/" or not _under(plugin, sticky, monitor):
        _clear_corrupt_sticky(plugin, "v3.6.0 清理无效/根目录 sticky")
        logger.warning("【光鸭云盘助手】【v3.6.0】【状态自愈】已清理无效 sticky: %s", raw)
        return ""
    try:
        if not _sticky._group_has_pending(plugin, sticky):
            _clear_corrupt_sticky(plugin, "当前剧集已无 inflight/retry/stabilizing 成员")
            return ""
    except Exception:
        pass
    return sticky


def _handoff_active(plugin: Any) -> Tuple[bool, Dict[str, Any]]:
    try:
        snapshot = dict(plugin._isolated_queue_snapshot() or {})
    except Exception:
        return False, {}
    active = bool(snapshot.get("owner_worker_alive") and not snapshot.get("owner_current"))
    return active, snapshot


def _worker_busy(plugin: Any) -> bool:
    try:
        snapshot = dict(plugin._isolated_queue_snapshot() or {})
    except Exception:
        return False
    return bool(
        snapshot.get("running_path")
        or int(snapshot.get("queued") or 0) > 0
        or int(snapshot.get("owned") or 0) > 0
    )


def _empty_group_counters(files: List[Any]) -> Dict[str, int]:
    return {
        "files": len(files), "changed": 0, "waiting": 0, "inflight": 0,
        "retry_wait": 0, "completed": 0, "ignored": 0, "blocked": 0,
        "ready": 0, "submitted": 0, "deferred": 0, "failed": 0,
        "unsupported": 0, "history_completed": 0, "newly_blocked": 0,
        "capacity_wait": 0, "folder_tasks": 0,
    }


def _freeze_old_owner(owner: Any) -> None:
    """冻结旧实例 discovery；当前正在执行的同步 MoviePilot 整理继续自然收尾。"""
    if owner is None:
        return
    try:
        setattr(owner, _FREEZE_ATTR, True)
        setattr(owner, "_organize_monitor_enabled", False)
    except Exception:
        pass

    timer = getattr(owner, "_guangya_single_flight_idle_timer_v350", None)
    if timer is not None:
        try:
            timer.cancel()
        except Exception:
            pass
        try:
            setattr(owner, "_guangya_single_flight_idle_timer_v350", None)
        except Exception:
            pass

    # 已经进入旧 run_scan 的函数栈无法被新版本替换；但它每个目录都会动态调用
    # self._process_folder_group。把旧实例自己的方法替成 no-op，可阻止后续目录继续写状态。
    try:
        def frozen_process(this: Any, **kwargs: Any) -> Dict[str, int]:
            return _empty_group_counters(list(kwargs.get("files") or []))
        owner._process_folder_group = types.MethodType(frozen_process, owner)
    except Exception:
        pass

    try:
        def frozen_scan(this: Any, manual: bool = False) -> Dict[str, Any]:
            return {
                "success": True,
                "message": "旧插件实例已进入 Worker 交接，只允许当前整理收尾",
                "data": {"handoff": True, "submitted": 0},
            }
        owner.run_organize_monitor_scan = types.MethodType(frozen_scan, owner)
    except Exception:
        pass

    try:
        owner._save_monitor_status(
            worker_handoff_waiting=True,
            worker_handoff_discovery_frozen=True,
            runtime_phase="handoff",
            runtime_label="Worker 交接中，旧实例发现已冻结",
        )
    except Exception:
        pass


def _reconcile_false_retry(plugin: Any, *, finalize: bool) -> int:
    marker = plugin.get_data(_RECONCILE_KEY) or {}
    if isinstance(marker, dict) and bool(marker.get("done")):
        return 0

    def apply(state: Dict[str, Any]) -> int:
        retry = dict(state.get("retry") or {})
        removed = 0
        for path, raw in list(retry.items()):
            if not isinstance(raw, dict):
                continue
            reason = str(raw.get("last_error") or "")
            if not any(token in reason for token in _FALSE_RETRY_MARKERS):
                continue
            retry.pop(path, None)
            removed += 1
        state["retry"] = retry
        return removed

    try:
        removed = int(plugin._state().mutate(apply) or 0)
    except Exception as err:  # noqa: BLE001
        logger.warning("【光鸭云盘助手】【v3.6.0】【状态自愈】伪 retry 清理失败: %s", err)
        return 0

    total = int(marker.get("removed_total") or 0) if isinstance(marker, dict) else 0
    plugin.save_data(_RECONCILE_KEY, {
        "done": bool(finalize),
        "removed_total": total + removed,
        "last_removed": removed,
        "at": time.time(),
    })
    if removed:
        logger.warning(
            "【光鸭云盘助手】【v3.6.0】【状态自愈】已移除 worker 交接制造的伪 retry=%s；"
            "这些文件将按正常稳定性规则重新发现，真实失败 retry 未修改",
            removed,
        )
    return removed


def _checkpoint(
    plugin: Any,
    cursor: Dict[str, Any],
    queue: List[str],
    seen_dirs: Set[str],
    inventory: Set[str],
    overflow: bool,
) -> None:
    cursor.update({
        "queue": list(queue),
        "seen_dirs": list(seen_dirs),
        "inventory_paths": list(inventory),
        "overflow": bool(overflow),
    })
    _save_cursor(plugin, cursor)


def _iter_groups(self: Any, root_path: str, scan_meta: Dict[str, Any]) -> Iterator[Tuple[str, List[Any]]]:
    if bool(getattr(self, _FREEZE_ATTR, False)):
        scan_meta["truncated"] = True
        return

    handoff, _snapshot = _handoff_active(self)
    if handoff or _worker_busy(self):
        scan_meta["truncated"] = True
        return

    root = _norm(self, root_path)
    sticky = _sticky_group(self)
    if sticky:
        child_dirs, direct_files, exists = _direct_children(self, sticky)
        scan_meta["truncated"] = True
        scan_meta["paged_scan"] = True
        scan_meta["paged_sticky_priority"] = True
        scan_meta["paged_dir_limit"] = _PAGE_DIR_LIMIT
        scan_meta["visited"] += 1
        _account_files(self, direct_files, scan_meta, set())
        if not exists:
            _clear_corrupt_sticky(self, "sticky 源目录已不存在")
            logger.warning("【光鸭云盘助手】【v3.6.0】【状态自愈】sticky 源目录已不存在，已释放: %s", sticky)
            return
        if direct_files:
            scan_meta["groups_discovered"] += 1
            scan_meta["groups_scanned"] += 1
            yield sticky, direct_files
            return
        if child_dirs:
            _clear_corrupt_sticky(self, "sticky 已变成容器目录，释放后重新发现真实资源目录")
            logger.warning(
                "【光鸭云盘助手】【v3.6.0】【状态自愈】sticky 已变成无直接文件的容器，已释放并等待重新发现: %s",
                sticky,
            )
        return

    cursor = _load_cursor(self, root)
    cursor["page"] = int(cursor.get("page") or 0) + 1
    queue: List[str] = list(cursor.get("queue") or [root])
    seen_dirs: Set[str] = set(cursor.get("seen_dirs") or [root])
    inventory: Set[str] = set(cursor.get("inventory_paths") or [])
    overflow = bool(cursor.get("overflow"))
    dirs_scanned = 0

    scan_meta["paged_scan"] = True
    scan_meta["paged_dir_limit"] = _PAGE_DIR_LIMIT
    scan_meta["paged_page"] = cursor["page"]
    scan_meta["paged_cycle"] = cursor["cycle"]

    while queue and dirs_scanned < _PAGE_DIR_LIMIT:
        if bool(getattr(self, _FREEZE_ATTR, False)) or _worker_busy(self):
            scan_meta["truncated"] = True
            _checkpoint(self, cursor, queue, seen_dirs, inventory, overflow)
            return

        current_path = queue[0]
        child_dirs, direct_files, exists = _direct_children(self, current_path)
        queue.pop(0)
        if not exists:
            continue
        dirs_scanned += 1
        scan_meta["visited"] += 1

        for child in child_dirs:
            child_path = _norm(self, getattr(child, "path", ""))
            if not child_path or child_path in seen_dirs:
                continue
            if len(seen_dirs) >= _MAX_CURSOR_DIRS:
                overflow = True
                break
            seen_dirs.add(child_path)
            queue.append(child_path)

        overflow = _account_files(self, direct_files, scan_meta, inventory) or overflow
        if dirs_scanned % _CURSOR_CHECKPOINT_EVERY == 0:
            _checkpoint(self, cursor, queue, seen_dirs, inventory, overflow)

        if not direct_files:
            continue

        loose = bool(
            _is_streaming_container(self, current_path)
            or _orch._is_loose_container_v351(self, current_path, direct_files)
        )
        if loose:
            primary = _primary_files(direct_files)
            scan_meta["groups_discovered"] += len(primary)
            for member in primary:
                scan_meta["groups_scanned"] += 1
                yield current_path, [member]
                if getattr(self, "_guangya_single_flight_claimed_v350", False):
                    if current_path not in queue:
                        queue.insert(0, current_path)
                    _checkpoint(self, cursor, queue, seen_dirs, inventory, overflow)
                    scan_meta["truncated"] = True
                    return
            continue

        scan_meta["groups_discovered"] += 1
        scan_meta["groups_scanned"] += 1
        yield current_path, direct_files
        if getattr(self, "_guangya_single_flight_claimed_v350", False):
            _checkpoint(self, cursor, queue, seen_dirs, inventory, overflow)
            scan_meta["truncated"] = True
            return

    scan_meta["paged_dirs_scanned"] = dirs_scanned
    scan_meta["paged_dirs_remaining"] = len(queue)
    if queue:
        scan_meta["truncated"] = True
        _checkpoint(self, cursor, queue, seen_dirs, inventory, overflow)
        logger.info(
            "【光鸭云盘助手】【v3.6.0】【分段扫描】本轮目录=%s/%s，剩余=%s，cycle=%s page=%s；"
            "下次从游标继续",
            dirs_scanned,
            _PAGE_DIR_LIMIT,
            len(queue),
            cursor["cycle"],
            cursor["page"],
        )
        return

    scan_meta["inventory_paths"] = set(inventory)
    scan_meta["truncated"] = bool(overflow)
    completed_cycle = int(cursor.get("cycle") or 1)
    _save_cursor(self, _new_cursor(root, completed_cycle + 1))
    logger.info(
        "【光鸭云盘助手】【v3.6.0】【分段扫描】完整 cycle=%s 已结束，累计文件=%s，inventory_complete=%s",
        completed_cycle,
        len(inventory),
        not overflow,
    )


def install_scheduler_convergence_v360(candidate_mixin: Any) -> None:
    if getattr(candidate_mixin, "_guangya_scheduler_convergence_v360", False):
        return

    # 1) 恢复 init 的真正幂等语义。v3.4.3 等历史层只允许首次/force 初始化执行。
    previous_init = GuangYaQueueRecoveryMixin.init_organizer_monitor

    def idempotent_init(self: Any, force: bool = False) -> None:
        if bool(getattr(self, "_organize_monitor_initialized", False)) and not force:
            return
        return previous_init(self, force=force)

    GuangYaQueueRecoveryMixin.init_organizer_monitor = idempotent_init

    # 2) 新实例请求旧 owner 交接时，先冻结旧 discovery，再让原 WorkerGuard 只收尾当前任务。
    previous_request = GuangYaWorkerGuardMixin._request_old_owner_handoff

    def request_handoff(self: Any, owner: Any) -> None:
        if owner is not None and owner is not self:
            _freeze_old_owner(owner)
        return previous_request(self, owner)

    GuangYaWorkerGuardMixin._request_old_owner_handoff = request_handoff

    # 3) CandidateFilter 本身成为唯一分页发现层，不再修改 FolderStream 类。
    candidate_mixin._iter_folder_groups = _iter_groups

    def run_scan(self: Any, manual: bool = False) -> Dict[str, Any]:
        self.init_organizer_monitor()
        handoff, snapshot = _handoff_active(self)
        _reconcile_false_retry(self, finalize=not handoff)
        if bool(getattr(self, _FREEZE_ATTR, False)):
            return {
                "success": True,
                "message": "旧插件实例 discovery 已冻结，等待当前整理自然收尾",
                "data": {"handoff": True, "submitted": 0},
            }
        if handoff:
            try:
                self._claim_isolated_runtime()
            except Exception:
                pass
            sticky = _sticky_group(self)
            self._save_monitor_status(
                worker_handoff_waiting=True,
                runtime_phase="handoff",
                runtime_label="Worker 交接中，暂停所有新发现",
                current_task_path=sticky or str(snapshot.get("running_path") or ""),
                scan_page_size=_PAGE_DIR_LIMIT,
            )
            return {
                "success": True,
                "message": "Worker 交接中：未扫描、未提交、未新增 retry",
                "data": {"handoff": True, "submitted": 0},
            }
        return super(candidate_mixin, self).run_organize_monitor_scan(manual=manual)

    candidate_mixin.run_organize_monitor_scan = run_scan
    candidate_mixin._guangya_scheduler_convergence_v360 = True
    logger.info("【光鸭云盘助手】【v3.6.0】统一调度、50目录游标、空sticky修复与交接状态自愈已启用")


__all__ = ["install_scheduler_convergence_v360", "_PAGE_DIR_LIMIT", "_CURSOR_KEY"]
