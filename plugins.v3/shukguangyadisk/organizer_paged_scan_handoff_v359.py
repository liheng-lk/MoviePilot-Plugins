"""v3.5.9：50 目录增量扫描游标 + Worker 热更新交接暂停。

解决两个会互相放大的运行时问题：

1. 单任务 worker 空闲/交接期间，连续补充会反复从监控根开始全树扫描；几千文件会被
   每 10~30 秒重新枚举一次，只得到大量 ``capacity_wait``，浪费光鸭 API 与 CPU。
2. 热更新后旧 worker 仍在同步 TransferChain 收尾时，新实例不能接管；旧逻辑仍继续
   扫描并尝试入队，UI 因而出现“当前剧集目录有值、当前资源为空”。

本层只调整“发现”的调度方式，不改变 MoviePilot 的识别、分类、命名、目标目录、覆盖、
刮削和实际整理：
- 每轮最多访问 50 个目录节点，剩余目录保存在持久游标，下一轮从断点继续；
- 当前 TV sticky 事务永远优先，直接扫描当前剧集目录，不等待游标转到它；
- 分页扫描期间 inventory 标记为 truncated，不会用局部清单误删状态；完整走完一轮目录
  游标时才用累计 inventory 做一次 reconciliation；
- 旧 worker 仍存活时完全暂停 refill/目录扫描；旧 worker 退出后下一个 heartbeat 立即接管；
- 交接期间把 sticky 路径投影为 current_task_path，让 UI 明确显示正在等待继续的资源。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Set, Tuple

from app.sdk.logging import logger

from .organizer_deep_folder_stream_v3413 import _is_streaming_container
from .organizer_empty_folder_guard_v3410 import _runtime_media_exts
from .organizer_folder_history import GuangYaFolderHistoryMixin
from .organizer_folder_stream import GuangYaFolderStreamMixin
from . import organizer_tv_sticky_graceful_stop_v352 as _sticky


_CURSOR_KEY = "organize_v359_paged_scan_cursor"
_CURSOR_SCHEMA = 1
_PAGE_DIR_LIMIT = 50
_MAX_CURSOR_DIRS = 20000
_MAX_CURSOR_FILES = 50000


def _norm(plugin: Any, value: Any) -> str:
    try:
        return plugin._organize_normalize_path(str(value or ""))
    except Exception:
        return str(value or "").replace("\\", "/").rstrip("/")


def _dedupe(values: Iterable[str], *, limit: int) -> List[str]:
    result: List[str] = []
    seen: Set[str] = set()
    for raw in values:
        value = str(raw or "")
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
        if len(result) >= limit:
            break
    return result


def _new_cursor(root: str, *, cycle: int = 1) -> Dict[str, Any]:
    return {
        "schema": _CURSOR_SCHEMA,
        "monitor_path": root,
        "cycle": max(int(cycle or 1), 1),
        "page": 0,
        "queue": [root],
        "seen_dirs": [root],
        "inventory_paths": [],
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

    queue = _dedupe((_norm(plugin, value) for value in raw.get("queue") or []), limit=_MAX_CURSOR_DIRS)
    seen_dirs = _dedupe((_norm(plugin, value) for value in raw.get("seen_dirs") or []), limit=_MAX_CURSOR_DIRS)
    inventory = _dedupe((_norm(plugin, value) for value in raw.get("inventory_paths") or []), limit=_MAX_CURSOR_FILES)
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
        "updated_at": float(raw.get("updated_at") or 0),
    }


def _save_cursor(plugin: Any, cursor: Dict[str, Any]) -> None:
    payload = dict(cursor)
    payload["updated_at"] = time.time()
    plugin.save_data(_CURSOR_KEY, payload)


def _handoff_snapshot(plugin: Any) -> Tuple[bool, Dict[str, Any]]:
    try:
        snapshot = dict(plugin._isolated_queue_snapshot() or {})
    except Exception:
        return False, {}
    active = bool(snapshot.get("owner_worker_alive") and not snapshot.get("owner_current"))
    return active, snapshot


def _worker_busy(snapshot: Dict[str, Any]) -> bool:
    return bool(
        snapshot.get("running_path")
        or int(snapshot.get("queued") or 0) > 0
        or int(snapshot.get("owned") or 0) > 0
    )


def _direct_children(plugin: Any, path: str) -> Tuple[List[Any], List[Any]]:
    if not plugin._guangya_api:
        raise RuntimeError("光鸭云盘尚未登录或存储未初始化")
    current = plugin._guangya_api.get_item(Path(path))
    if not current or str(getattr(current, "type", "") or "") != "dir":
        return [], []
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
    return child_dirs, direct_files


def _primary_files(files: List[Any]) -> List[Any]:
    media_exts = _runtime_media_exts()
    return [
        item for item in files
        if Path(str(getattr(item, "name", "") or getattr(item, "path", "") or "")).suffix.casefold()
        in media_exts
    ]


def _account_files(plugin: Any, files: List[Any], scan_meta: Dict[str, Any], inventory: Set[str]) -> None:
    for item in files:
        path = _norm(plugin, getattr(item, "path", ""))
        if not path:
            continue
        scan_meta["inventory_paths"].add(path)
        inventory.add(path)
        scan_meta["files"] += 1


def _sticky_group(plugin: Any) -> str:
    status = dict(plugin.get_data(plugin._monitor_status_key) or {})
    sticky = _norm(plugin, status.get("sticky_tv_group_path") or "")
    if not sticky:
        return ""
    try:
        if not _sticky._group_has_pending(plugin, sticky):
            return ""
    except Exception:
        return sticky
    return sticky


def _yield_sticky_first(
    plugin: Any,
    sticky: str,
    scan_meta: Dict[str, Any],
) -> Iterator[Tuple[str, List[Any]]]:
    child_dirs, direct_files = _direct_children(plugin, sticky)
    scan_meta["truncated"] = True
    scan_meta["paged_scan"] = True
    scan_meta["paged_sticky_priority"] = True
    scan_meta["paged_dir_limit"] = _PAGE_DIR_LIMIT
    scan_meta["paged_dirs_scanned"] = 1
    scan_meta["visited"] += 1
    _account_files(plugin, direct_files, scan_meta, scan_meta["inventory_paths"])
    if direct_files:
        scan_meta["groups_discovered"] += 1
        scan_meta["groups_scanned"] += 1
        yield sticky, direct_files
    elif child_dirs:
        logger.warning(
            "【光鸭云盘助手】【v3.5.9】【分段扫描】当前 sticky 目录已变为容器且无直接文件，"
            "暂不猜测新的剧集边界: %s",
            sticky,
        )


def _iter_paged_groups(
    plugin: Any,
    root_path: str,
    scan_meta: Dict[str, Any],
) -> Iterator[Tuple[str, List[Any]]]:
    """持久 BFS：每轮最多访问 50 个目录，之后从断点继续。"""
    if not plugin._guangya_api:
        raise RuntimeError("光鸭云盘尚未登录或存储未初始化")

    setattr(plugin, "_guangya_single_flight_claimed_v350", False)
    root = _norm(plugin, root_path)
    handoff, snapshot = _handoff_snapshot(plugin)
    if handoff:
        scan_meta["truncated"] = True
        scan_meta["paged_scan"] = True
        scan_meta["worker_handoff_wait"] = True
        plugin._save_monitor_status(
            worker_handoff_waiting=True,
            worker_handoff_path=_sticky_group(plugin),
            worker_handoff_at=time.time(),
            scan_page_size=_PAGE_DIR_LIMIT,
        )
        return

    try:
        snapshot = dict(plugin._isolated_queue_snapshot() or {})
    except Exception:
        snapshot = {}
    if _worker_busy(snapshot):
        scan_meta["truncated"] = True
        scan_meta["single_flight_busy"] = True
        scan_meta["paged_scan"] = True
        return

    sticky = _sticky_group(plugin)
    if sticky:
        yield from _yield_sticky_first(plugin, sticky, scan_meta)
        return

    cursor = _load_cursor(plugin, root)
    cursor["page"] = int(cursor.get("page") or 0) + 1
    queue: List[str] = list(cursor.get("queue") or [root])
    seen_dirs: Set[str] = set(cursor.get("seen_dirs") or [root])
    inventory: Set[str] = set(cursor.get("inventory_paths") or [])
    dirs_scanned = 0
    page_started_queue = len(queue)

    scan_meta["paged_scan"] = True
    scan_meta["paged_dir_limit"] = _PAGE_DIR_LIMIT
    scan_meta["paged_page"] = cursor["page"]
    scan_meta["paged_cycle"] = cursor["cycle"]

    while queue and dirs_scanned < _PAGE_DIR_LIMIT:
        current_path = queue[0]
        child_dirs, direct_files = _direct_children(plugin, current_path)
        queue.pop(0)
        dirs_scanned += 1
        scan_meta["visited"] += 1

        for child in child_dirs:
            child_path = _norm(plugin, getattr(child, "path", ""))
            if not child_path or child_path in seen_dirs:
                continue
            if len(seen_dirs) >= _MAX_CURSOR_DIRS:
                scan_meta["truncated"] = True
                logger.warning(
                    "【光鸭云盘助手】【v3.5.9】【分段扫描】目录游标达到安全上限 %s，暂停继续扩展: %s",
                    _MAX_CURSOR_DIRS,
                    current_path,
                )
                break
            seen_dirs.add(child_path)
            queue.append(child_path)

        _account_files(plugin, direct_files, scan_meta, inventory)
        scan_meta["groups_discovered"] += 1 if direct_files else 0

        cursor.update({
            "queue": list(queue),
            "seen_dirs": list(seen_dirs),
            "inventory_paths": list(inventory),
        })
        _save_cursor(plugin, cursor)

        if not direct_files:
            continue

        if _is_streaming_container(plugin, current_path):
            primary = _primary_files(direct_files)
            for member in primary:
                scan_meta["groups_scanned"] += 1
                yield current_path, [member]
                if getattr(plugin, "_guangya_single_flight_claimed_v350", False):
                    if current_path not in queue:
                        queue.insert(0, current_path)
                    cursor.update({
                        "queue": list(queue),
                        "seen_dirs": list(seen_dirs),
                        "inventory_paths": list(inventory),
                    })
                    _save_cursor(plugin, cursor)
                    scan_meta["truncated"] = True
                    scan_meta["single_flight_partial"] = True
                    scan_meta["paged_dirs_scanned"] = dirs_scanned
                    scan_meta["paged_dirs_remaining"] = len(queue)
                    return
            continue

        scan_meta["groups_scanned"] += 1
        yield current_path, direct_files
        if getattr(plugin, "_guangya_single_flight_claimed_v350", False):
            scan_meta["truncated"] = True
            scan_meta["single_flight_partial"] = True
            scan_meta["paged_dirs_scanned"] = dirs_scanned
            scan_meta["paged_dirs_remaining"] = len(queue)
            return

    cursor.update({
        "queue": list(queue),
        "seen_dirs": list(seen_dirs),
        "inventory_paths": list(inventory),
    })
    scan_meta["paged_dirs_scanned"] = dirs_scanned
    scan_meta["paged_dirs_remaining"] = len(queue)
    scan_meta["paged_page_started_queue"] = page_started_queue

    if queue:
        scan_meta["truncated"] = True
        _save_cursor(plugin, cursor)
        logger.info(
            "【光鸭云盘助手】【v3.5.9】【分段扫描】本轮最多扫描 %s 个目录：已扫描=%s，"
            "剩余目录=%s，cycle=%s page=%s；下一轮从断点继续",
            _PAGE_DIR_LIMIT,
            dirs_scanned,
            len(queue),
            cursor["cycle"],
            cursor["page"],
        )
        return

    scan_meta["inventory_paths"] = set(inventory)
    scan_meta["truncated"] = False
    completed_cycle = int(cursor.get("cycle") or 1)
    next_cursor = _new_cursor(root, cycle=completed_cycle + 1)
    _save_cursor(plugin, next_cursor)
    logger.info(
        "【光鸭云盘助手】【v3.5.9】【分段扫描】目录游标完成一轮：cycle=%s，累计文件=%s；"
        "已允许本轮执行完整 inventory 核验",
        completed_cycle,
        len(inventory),
    )


def install_paged_scan_handoff_v359(candidate_mixin: Any) -> None:
    if getattr(GuangYaFolderStreamMixin, "_guangya_paged_scan_handoff_v359", False):
        return

    GuangYaFolderStreamMixin._iter_folder_groups = _iter_paged_groups

    previous_tick = candidate_mixin.organize_monitor_tick

    def organize_monitor_tick(self: Any) -> None:
        self.init_organizer_monitor()
        if not getattr(self, "_organize_monitor_enabled", False):
            return
        handoff, snapshot = _handoff_snapshot(self)
        status = dict(self.get_data(self._monitor_status_key) or {})
        if handoff:
            try:
                claimed = bool(self._claim_isolated_runtime())
            except Exception:
                claimed = False
            if claimed:
                self._save_monitor_status(
                    worker_handoff_waiting=False,
                    worker_handoff_finished_at=time.time(),
                    runtime_phase="idle",
                    runtime_label="Worker 交接完成，继续当前资源",
                )
                logger.info("【光鸭云盘助手】【v3.5.9】【Worker交接】已取得新 worker 所有权，立即继续当前资源")
                return self.run_organize_monitor_scan(manual=False)

            sticky = _sticky_group(self)
            self._save_monitor_status(
                worker_handoff_waiting=True,
                worker_handoff_path=sticky,
                worker_handoff_worker=str(snapshot.get("running_path") or "ShukGuangYa-IsolatedTransfer"),
                runtime_phase="handoff",
                runtime_label="Worker 交接中，等待继续当前资源",
                current_task_path=sticky or str(status.get("current_task_path") or ""),
                scan_page_size=_PAGE_DIR_LIMIT,
            )
            return

        if bool(status.get("worker_handoff_waiting")):
            self._save_monitor_status(
                worker_handoff_waiting=False,
                worker_handoff_finished_at=time.time(),
                runtime_phase="idle",
                runtime_label="Worker 交接完成，继续当前资源",
            )
            logger.info("【光鸭云盘助手】【v3.5.9】【Worker交接】旧 worker 已退出，立即恢复当前资源发现")
            return self.run_organize_monitor_scan(manual=False)

        return previous_tick(self)

    candidate_mixin.organize_monitor_tick = organize_monitor_tick

    previous_status = GuangYaFolderHistoryMixin.api_organize_monitor_status

    def api_status(self: Any) -> Dict[str, Any]:
        response = previous_status(self)
        if not isinstance(response, dict) or not response.get("success"):
            return response
        data = response.setdefault("data", {})
        status = data.setdefault("status", {})
        sticky = _sticky_group(self)
        handoff, _snapshot = _handoff_snapshot(self)
        if sticky and handoff and not str(status.get("current_task_path") or ""):
            status["current_task_path"] = sticky
            status["runtime_phase"] = "handoff"
            status["runtime_label"] = "Worker 交接中，等待继续当前剧集"
        status["scan_page_size"] = _PAGE_DIR_LIMIT
        cursor = _load_cursor(self, _norm(self, self._organize_monitor_path))
        status["scan_cursor_cycle"] = int(cursor.get("cycle") or 1)
        status["scan_cursor_page"] = int(cursor.get("page") or 0)
        status["scan_cursor_remaining_dirs"] = len(cursor.get("queue") or [])
        return response

    GuangYaFolderHistoryMixin.api_organize_monitor_status = api_status
    GuangYaFolderStreamMixin._guangya_paged_scan_handoff_v359 = True
    logger.info("【光鸭云盘助手】【v3.5.9】50 目录增量扫描、sticky 优先与 Worker 交接暂停已启用")


__all__ = [
    "install_paged_scan_handoff_v359",
    "_PAGE_DIR_LIMIT",
    "_load_cursor",
    "_new_cursor",
]
