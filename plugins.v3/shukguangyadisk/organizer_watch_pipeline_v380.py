"""v3.8.0：CloudLinkMonitor 风格的“持续发现 + 独立全量 + 单一执行队列”。

本层只负责发现与调度，不复制 MoviePilot 的识别、分类、命名、冲突和真实整理规则。

本地目录可以依赖 watchdog/PoolingObserver 的 created/moved 事件；光鸭是远端 API，宿主没有
可订阅的文件系统事件。因此这里用目录直接子项的 fileId/name/size/modify_time 构造稳定签名，
把“轮询目录快照发生变化”定义为远端事件。目录发现和真实整理彻底解耦：

    增量目录观察 ─┐
                  ├─> 持久 resource queue -> 单 Dispatcher -> 私有 Worker -> MoviePilot
    独立全量巡检 ─┘

关键约束：
- Worker 忙时仍继续只读发现，绝不因为正在整理而停止监控；
- 容器目录也纳入 watch registry，新剧/新 Season 会沿目录层级快速传播发现；
- 近期变化资源保持 hot watch；冷资源轮转复查；固定周期全量巡检最终兜底；
- resource queue 持久化，插件重启/热更新后不会丢掉已经发现但尚未执行的目录；
- 同一资源只通过现有 ``_v360_schedule_resource`` 进入 MoviePilot，仍保持单 Worker；
- 手动全量是“强校验”，会把所有资源目录送入同一队列重新经过历史/状态门控；
- 自动全量只做完整发现和变化补漏，避免周期性把整个历史库反复塞入执行队列。
"""
from __future__ import annotations

import hashlib
import threading
import time
import uuid
from pathlib import PurePosixPath
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from app.sdk.logging import logger

from .models import GuangYaOrganizerResponse
from .organizer import GuangYaOrganizerMixin as _BaseOrganizerMixin
from .organizer_monitor_v366 import GuangYaOrganizerMonitorV366Mixin as _MonitorMixin


_WATCH_KEY = "organize_v380_watch_registry"
_RESOURCE_KEY = "organize_v380_resource_queue"
_FULL_KEY = "organize_v380_full_session"
_FULL_LAST_KEY = "organize_v380_full_last"
_SCHEMA = 1
_WATCH_LIMIT = 20000
_RESOURCE_LIMIT = 5000
_WATCH_BUDGET = 64
_WATCH_WHILE_FULL_BUDGET = 12
_FULL_STEP_BUDGET = 50
_FULL_SCAN_INTERVAL = 3600.0
_HOT_SECONDS = 2 * 24 * 3600.0
_COLD_RECHECK_SECONDS = 15 * 60.0
_MIN_WATCH_INTERVAL = 10.0
_INSTALL_FLAG = "_v380_watch_pipeline_installed"


def _scan_id(prefix: str) -> str:
    return f"{prefix}-{time.strftime('%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"


def _root(plugin: Any) -> str:
    return plugin._v360_norm(getattr(plugin, "_organize_monitor_path", ""))


def _is_under(path: str, parent: str) -> bool:
    try:
        child = PurePosixPath(path)
        root = PurePosixPath(parent)
        return child == root or child.is_relative_to(root)
    except Exception:
        return False


def _depth(path: str, root: str) -> int:
    try:
        rel = PurePosixPath(path).relative_to(PurePosixPath(root))
        return len(rel.parts)
    except Exception:
        return 9999


def _load_rows(plugin: Any, key: str) -> Dict[str, Dict[str, Any]]:
    raw = plugin.get_data(key) or {}
    if not isinstance(raw, dict) or int(raw.get("schema") or 0) != _SCHEMA:
        return {}
    root = _root(plugin)
    if plugin._v360_norm(raw.get("monitor_path")) != root:
        return {}
    rows: Dict[str, Dict[str, Any]] = {}
    for raw_path, raw_row in dict(raw.get("rows") or {}).items():
        path = plugin._v360_norm(raw_path)
        if not path or not isinstance(raw_row, dict) or not _is_under(path, root):
            continue
        rows[path] = dict(raw_row)
    return rows


def _save_rows(plugin: Any, key: str, rows: Dict[str, Dict[str, Any]], limit: int) -> None:
    root = _root(plugin)
    ordered = sorted(
        rows.items(),
        key=lambda pair: (
            int((pair[1] or {}).get("priority") or 100),
            -float((pair[1] or {}).get("last_changed") or 0),
            float((pair[1] or {}).get("first_seen") or 0),
            pair[0],
        ),
    )[:limit]
    plugin.save_data(
        key,
        {
            "schema": _SCHEMA,
            "monitor_path": root,
            "rows": {path: row for path, row in ordered},
            "updated_at": time.time(),
        },
    )


def _item_token(plugin: Any, item: Any) -> str:
    path = plugin._v360_norm(getattr(item, "path", ""))
    return "|".join(
        (
            str(getattr(item, "type", "") or ""),
            str(getattr(item, "fileid", "") or ""),
            path,
            str(getattr(item, "name", "") or ""),
            str(int(getattr(item, "size", 0) or 0)),
            str(int(float(getattr(item, "modify_time", 0) or 0))),
        )
    )


def _directory_signature(plugin: Any, child_dirs: Sequence[Any], direct_files: Sequence[Any]) -> str:
    tokens = [_item_token(plugin, item) for item in list(child_dirs) + list(direct_files)]
    tokens.sort()
    return hashlib.sha1("\n".join(tokens).encode("utf-8")).hexdigest()


def _latest_mtime(items: Iterable[Any]) -> float:
    return max([float(getattr(item, "modify_time", 0) or 0) for item in items] or [0.0])


def _enqueue_resource(
    rows: Dict[str, Dict[str, Any]],
    *,
    path: str,
    reason: str,
    signature: str,
    force: bool = False,
) -> bool:
    now = time.time()
    previous = dict(rows.get(path) or {})
    created = not bool(previous)
    first_seen = float(previous.get("first_seen") or now)
    priority = 0 if force else min(int(previous.get("priority") or 20), 10)
    previous.update(
        {
            "path": path,
            "reason": reason,
            "signature": signature,
            "first_seen": first_seen,
            "last_seen": now,
            "next_due": min(float(previous.get("next_due") or now), now),
            "priority": priority,
            "force_verify": bool(force or previous.get("force_verify")),
        }
    )
    rows[path] = previous
    return created


def _drop_subtree(rows: Dict[str, Dict[str, Any]], parent: str) -> int:
    removed = 0
    for path in list(rows):
        if _is_under(path, parent):
            rows.pop(path, None)
            removed += 1
    return removed


def _ensure_watch_row(rows: Dict[str, Dict[str, Any]], path: str, root: str, *, parent: str = "") -> bool:
    if path in rows:
        return False
    rows[path] = {
        "path": path,
        "parent": parent,
        "depth": _depth(path, root),
        "signature": "",
        "kind": "unknown",
        "last_checked": 0,
        "last_changed": 0,
        "hot_until": 0,
        "children": [],
        "first_seen": time.time(),
        "priority": 10 if _depth(path, root) <= 1 else 50,
    }
    return True


def _watch_interval(plugin: Any) -> float:
    configured = float(getattr(plugin, "_organize_monitor_interval", 60) or 60)
    return max(configured, _MIN_WATCH_INTERVAL)


def _watch_lock(plugin: Any) -> threading.Lock:
    lock = getattr(plugin, "_v380_watch_lock", None)
    if lock is None:
        lock = threading.Lock()
        plugin._v380_watch_lock = lock
    return lock


def _log(scan_id: str, stage: str, message: str, *, level: str = "info") -> None:
    getattr(logger, level, logger.info)(
        "【光鸭云盘助手】【监控】【%s】【%s】%s",
        scan_id,
        stage,
        message,
    )


def _scan_directory(
    plugin: Any,
    path: str,
    watch_rows: Dict[str, Dict[str, Any]],
    resource_rows: Dict[str, Dict[str, Any]],
    *,
    reason: str,
    force_resource: bool,
) -> Dict[str, Any]:
    root = _root(plugin)
    normalized = plugin._v360_norm(path)
    previous = dict(watch_rows.get(normalized) or {})
    child_dirs, direct_files = plugin._v360_list_directory(normalized)
    now = time.time()
    signature = _directory_signature(plugin, child_dirs, direct_files)
    old_signature = str(previous.get("signature") or "")
    changed = not old_signature or old_signature != signature
    primary = list(plugin._v360_primary_files(direct_files) or [])
    children = [
        plugin._v360_norm(getattr(item, "path", ""))
        for item in child_dirs
        if plugin._v360_norm(getattr(item, "path", ""))
    ]

    old_children = {plugin._v360_norm(value) for value in previous.get("children") or [] if value}
    new_children = set(children)
    vanished = old_children - new_children
    pruned_watch = pruned_resource = 0
    for missing in vanished:
        pruned_watch += _drop_subtree(watch_rows, missing)
        pruned_resource += _drop_subtree(resource_rows, missing)

    discovered_children: List[str] = []
    for child_path in children:
        if _ensure_watch_row(watch_rows, child_path, root, parent=normalized):
            discovered_children.append(child_path)

    hot_until = float(previous.get("hot_until") or 0)
    if changed and primary:
        hot_until = max(hot_until, now + _HOT_SECONDS)

    watch_rows[normalized] = {
        **previous,
        "path": normalized,
        "parent": str(previous.get("parent") or ""),
        "depth": _depth(normalized, root),
        "signature": signature,
        "kind": "resource" if primary else "container",
        "last_checked": now,
        "last_changed": now if changed else float(previous.get("last_changed") or 0),
        "hot_until": hot_until,
        "children": children,
        "child_count": len(child_dirs),
        "file_count": len(direct_files),
        "primary_count": len(primary),
        "latest_mtime": _latest_mtime(list(child_dirs) + list(direct_files)),
        "last_error": "",
        "priority": 10 if _depth(normalized, root) <= 1 else (20 if primary else 50),
    }

    queued = False
    if primary and (changed or force_resource):
        queued = _enqueue_resource(
            resource_rows,
            path=normalized,
            reason=reason if changed else f"{reason}:full-verify",
            signature=signature,
            force=force_resource,
        )
    elif not primary:
        resource_rows.pop(normalized, None)

    return {
        "path": normalized,
        "changed": changed,
        "queued": queued,
        "primary": len(primary),
        "children": children,
        "new_children": discovered_children,
        "files": len(direct_files),
        "pruned_watch": pruned_watch,
        "pruned_resource": pruned_resource,
    }


def _select_watch_paths(
    rows: Dict[str, Dict[str, Any]],
    *,
    root: str,
    now: float,
    interval: float,
    budget: int,
) -> List[str]:
    _ensure_watch_row(rows, root, root)
    selected: List[str] = []

    def add(path: str) -> None:
        if path and path not in selected and len(selected) < budget:
            selected.append(path)

    # P0：根目录和第一层结构目录相当于远端 PollingObserver 的入口，固定高频轮询。
    shallow = sorted(
        rows.items(),
        key=lambda pair: (int((pair[1] or {}).get("depth") or 9999), pair[0]),
    )
    for path, row in shallow:
        depth = int(row.get("depth") if row.get("depth") is not None else _depth(path, root))
        last = float(row.get("last_checked") or 0)
        if depth <= 1 and (last <= 0 or now - last >= interval):
            add(path)

    # P1：刚发现但从未读取的子目录立即追踪，避免新剧要等整库游标绕一圈。
    never = sorted(
        ((path, row) for path, row in rows.items() if float(row.get("last_checked") or 0) <= 0),
        key=lambda pair: (int(pair[1].get("depth") or 9999), float(pair[1].get("first_seen") or 0), pair[0]),
    )
    for path, _ in never:
        add(path)

    # P2：近期发生过变化的资源保持 hot watch；追更剧集能以配置 interval 直接检测下一集。
    hot = sorted(
        (
            (path, row)
            for path, row in rows.items()
            if float(row.get("hot_until") or 0) > now
            and now - float(row.get("last_checked") or 0) >= interval
        ),
        key=lambda pair: (float(pair[1].get("last_checked") or 0), pair[0]),
    )
    for path, _ in hot:
        add(path)

    # P3：剩余冷目录持续轮转，保证即使父目录 mtime 不传播也不会永久漏掉深层变化。
    cold = sorted(
        (
            (path, row)
            for path, row in rows.items()
            if now - float(row.get("last_checked") or 0) >= _COLD_RECHECK_SECONDS
        ),
        key=lambda pair: (float(pair[1].get("last_checked") or 0), pair[0]),
    )
    for path, _ in cold:
        add(path)
    return selected


def _watch_pulse(plugin: Any, *, trigger: str, budget: int = _WATCH_BUDGET) -> Dict[str, Any]:
    scan_id = _scan_id("INC")
    root = _root(plugin)
    if root == "/":
        return {"success": False, "message": "请先选择具体监控目录"}
    if not getattr(plugin, "_enabled", False) or not getattr(plugin, "_guangya_api", None):
        return {"success": False, "message": "光鸭云盘未启用或未登录"}

    lock = _watch_lock(plugin)
    if not lock.acquire(blocking=False):
        return {"success": True, "message": "目录观察器已有一轮正在执行", "data": {"watch_busy": True}}

    started = time.time()
    watch_rows = _load_rows(plugin, _WATCH_KEY)
    resource_rows = _load_rows(plugin, _RESOURCE_KEY)
    interval = _watch_interval(plugin)
    now = time.time()
    paths = _select_watch_paths(watch_rows, root=root, now=now, interval=interval, budget=max(int(budget), 1))
    scanned = changed = queued = files = primary_dirs = errors = 0
    error_sample: List[str] = []
    dynamic: List[str] = list(paths)
    seen_this_pulse = set()

    _log(scan_id, "1/4 发现", f"来源={trigger} 预算={budget} watch={len(watch_rows)} 待整理={len(resource_rows)}")
    try:
        while dynamic and scanned < max(int(budget), 1):
            path = dynamic.pop(0)
            if path in seen_this_pulse:
                continue
            seen_this_pulse.add(path)
            try:
                result = _scan_directory(
                    plugin,
                    path,
                    watch_rows,
                    resource_rows,
                    reason=f"incremental:{trigger}",
                    force_resource=False,
                )
            except Exception as err:  # noqa: BLE001 - read failure must never look like deletion
                errors += 1
                error_sample.append(f"{path}: {err}")
                row = dict(watch_rows.get(path) or {})
                row.update({"last_error": str(err), "last_error_at": time.time()})
                watch_rows[path] = row
                continue
            scanned += 1
            files += int(result.get("files") or 0)
            changed += 1 if result.get("changed") else 0
            queued += 1 if result.get("queued") else 0
            primary_dirs += 1 if int(result.get("primary") or 0) > 0 else 0
            # 新结构在同一 pulse 内继续向下追，行为接近 created/moved 事件逐层传播。
            if result.get("changed"):
                for child_path in result.get("new_children") or []:
                    if child_path not in seen_this_pulse and child_path not in dynamic:
                        dynamic.append(child_path)

        _save_rows(plugin, _WATCH_KEY, watch_rows, _WATCH_LIMIT)
        _save_rows(plugin, _RESOURCE_KEY, resource_rows, _RESOURCE_LIMIT)
        elapsed = round(time.time() - started, 3)
        plugin._save_monitor_status(
            monitor_pipeline="watch-pipeline-v3.8.0",
            watch_last_scan_id=scan_id,
            watch_last_at=time.time(),
            watch_last_trigger=trigger,
            watch_registry_total=len(watch_rows),
            resource_queue_depth=len(resource_rows),
            watch_scanned=scanned,
            watch_changed=changed,
            watch_queued=queued,
            watch_errors=errors,
            watch_interval=int(interval),
            detection_runs_while_worker_busy=True,
        )
        _log(scan_id, "2/4 变更", f"扫描目录={scanned} 变化={changed} 资源目录={primary_dirs} 文件={files} 错误={errors}")
        _log(scan_id, "3/4 待整理", f"新增/刷新={queued} 当前持久队列={len(resource_rows)}")
        if errors:
            _log(scan_id, "4/4 完成", f"增量观察完成，耗时={elapsed}s；错误样本={error_sample[:3]}", level="warning")
        else:
            _log(scan_id, "4/4 完成", f"增量观察完成，耗时={elapsed}s")
        return {
            "success": True,
            "message": "增量目录观察完成",
            "data": {
                "scan_id": scan_id,
                "scan_mode": "incremental",
                "watch_scanned": scanned,
                "watch_changed": changed,
                "watch_queued": queued,
                "watch_errors": errors,
                "watch_total": len(watch_rows),
                "resource_queue_depth": len(resource_rows),
                "elapsed": elapsed,
            },
        }
    finally:
        try:
            lock.release()
        except RuntimeError:
            pass


def _full_load(plugin: Any) -> Dict[str, Any]:
    raw = plugin.get_data(_FULL_KEY) or {}
    if not isinstance(raw, dict) or int(raw.get("schema") or 0) != _SCHEMA:
        return {}
    if plugin._v360_norm(raw.get("monitor_path")) != _root(plugin):
        return {}
    return dict(raw)


def _full_save(plugin: Any, state: Dict[str, Any]) -> None:
    payload = dict(state or {})
    payload["schema"] = _SCHEMA
    payload["monitor_path"] = _root(plugin)
    payload["updated_at"] = time.time()
    plugin.save_data(_FULL_KEY, payload)


def _full_due(plugin: Any) -> bool:
    raw = plugin.get_data(_FULL_LAST_KEY) or {}
    if not isinstance(raw, dict) or plugin._v360_norm(raw.get("monitor_path")) != _root(plugin):
        return True
    return time.time() - float(raw.get("completed_at") or 0) >= _FULL_SCAN_INTERVAL


def _start_full(plugin: Any, *, trigger: str, force_verify: bool) -> Dict[str, Any]:
    plugin.init_organizer_monitor()
    root = _root(plugin)
    if root == "/":
        return {"success": False, "message": "请先选择具体监控目录，禁止扫描根目录"}
    if not getattr(plugin, "_enabled", False) or not getattr(plugin, "_guangya_api", None):
        return {"success": False, "message": "光鸭云盘未启用或未登录"}
    existing = _full_load(plugin)
    if existing.get("active"):
        return _full_step(plugin, trigger="manual-resume" if trigger == "manual" else trigger)
    scan_id = _scan_id("FULL")
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
    _full_save(plugin, state)
    _log(scan_id, "全量开始", f"来源={trigger} 强校验={bool(force_verify)} 根目录={root}")
    return _full_step(plugin, trigger=trigger)


def _full_step(plugin: Any, *, trigger: str) -> Dict[str, Any]:
    state = _full_load(plugin)
    if not state.get("active"):
        return {"success": True, "message": "当前没有运行中的全量巡检", "data": {"full_scan_active": False}}
    scan_id = str(state.get("scan_id") or _scan_id("FULL"))
    queue = [plugin._v360_norm(value) for value in state.get("queue") or [] if value]
    seen = {plugin._v360_norm(value) for value in state.get("seen") or [] if value}
    watch_rows = _load_rows(plugin, _WATCH_KEY)
    resource_rows = _load_rows(plugin, _RESOURCE_KEY)
    step_dirs = step_files = step_resources = step_queued = 0
    errors: List[str] = []

    while queue and step_dirs < _FULL_STEP_BUDGET:
        path = queue[0]
        try:
            result = _scan_directory(
                plugin,
                path,
                watch_rows,
                resource_rows,
                reason=f"full:{state.get('trigger') or trigger}",
                force_resource=bool(state.get("force_verify")),
            )
        except Exception as err:  # noqa: BLE001
            errors.append(f"{path}: {err}")
            # 失败目录保留在队首，下轮从同一断点重试；绝不把读取失败当空目录。
            break
        queue.pop(0)
        step_dirs += 1
        step_files += int(result.get("files") or 0)
        step_resources += 1 if int(result.get("primary") or 0) > 0 else 0
        step_queued += 1 if result.get("queued") else 0
        for child_path in result.get("children") or []:
            if child_path and child_path not in seen:
                seen.add(child_path)
                queue.append(child_path)

    state["pages"] = int(state.get("pages") or 0) + 1
    state["queue"] = queue
    state["seen"] = list(seen)
    state["dirs_scanned"] = int(state.get("dirs_scanned") or 0) + step_dirs
    state["files_seen"] = int(state.get("files_seen") or 0) + step_files
    state["resource_dirs"] = int(state.get("resource_dirs") or 0) + step_resources
    state["queued_resources"] = int(state.get("queued_resources") or 0) + step_queued
    state["errors"] = int(state.get("errors") or 0) + len(errors)
    state["last_errors"] = errors[:5]

    completed = not queue and not errors
    if completed:
        state["active"] = False
        state["completed_at"] = time.time()
        plugin.save_data(
            _FULL_LAST_KEY,
            {
                "monitor_path": _root(plugin),
                "completed_at": state["completed_at"],
                "scan_id": scan_id,
                "force_verify": bool(state.get("force_verify")),
            },
        )

    _save_rows(plugin, _WATCH_KEY, watch_rows, _WATCH_LIMIT)
    _save_rows(plugin, _RESOURCE_KEY, resource_rows, _RESOURCE_LIMIT)
    _full_save(plugin, state)
    plugin._save_monitor_status(
        monitor_pipeline="watch-pipeline-v3.8.0",
        full_scan_active=bool(state.get("active")),
        full_scan_id=scan_id,
        full_scan_trigger=str(state.get("trigger") or ""),
        full_scan_force_verify=bool(state.get("force_verify")),
        full_scan_pages=int(state.get("pages") or 0),
        full_scan_dirs=int(state.get("dirs_scanned") or 0),
        full_scan_files=int(state.get("files_seen") or 0),
        full_scan_resources=int(state.get("resource_dirs") or 0),
        full_scan_queued=int(state.get("queued_resources") or 0),
        full_scan_remaining_dirs=len(queue),
        resource_queue_depth=len(resource_rows),
    )
    _log(
        scan_id,
        "全量进度" if not completed else "全量完成",
        f"本步目录={step_dirs} 文件={step_files} 资源={step_resources} 入待整理={step_queued} "
        f"累计目录={int(state.get('dirs_scanned') or 0)} 剩余={len(queue)} 错误={len(errors)}",
        level="warning" if errors else "info",
    )
    return {
        "success": not bool(errors),
        "message": "全量巡检已完整完成" if completed else ("全量巡检断点保留，等待下轮重试" if errors else "全量巡检进行中"),
        "data": {
            "scan_id": scan_id,
            "scan_mode": "full",
            "full_scan_active": bool(state.get("active")),
            "full_scan_force_verify": bool(state.get("force_verify")),
            "full_scan_pages": int(state.get("pages") or 0),
            "full_scan_dirs": int(state.get("dirs_scanned") or 0),
            "full_scan_files": int(state.get("files_seen") or 0),
            "full_scan_resources": int(state.get("resource_dirs") or 0),
            "full_scan_queued": int(state.get("queued_resources") or 0),
            "full_scan_remaining_dirs": len(queue),
            "resource_queue_depth": len(resource_rows),
            "errors": errors[:5],
        },
    }


def _stop_full(plugin: Any, *, trigger: str) -> Dict[str, Any]:
    state = _full_load(plugin)
    if not state.get("active"):
        return {"success": True, "message": "当前没有运行中的全量巡检", "data": {"full_scan_active": False}}
    state.update({"active": False, "stopped_at": time.time(), "stopped_by": trigger})
    _full_save(plugin, state)
    plugin._save_monitor_status(full_scan_active=False)
    _log(str(state.get("scan_id") or "FULL"), "全量停止", f"来源={trigger}；仅停止发现，不中断当前 Worker")
    return {"success": True, "message": "已停止全量巡检；当前整理任务不中断", "data": {"full_scan_active": False}}


def _queue_terminal(result: Dict[str, Any]) -> bool:
    primary = int(result.get("primary") or 0)
    if primary <= 0 or str(result.get("reason") or "") == "no_primary":
        return True
    phases = dict(result.get("phases") or {})
    waiting = sum(int(phases.get(name) or 0) for name in ("stabilizing", "history_wait", "retry_wait", "inflight", "ready"))
    terminal = sum(int(phases.get(name) or 0) for name in ("completed", "blocked", "ignored"))
    return waiting <= 0 and terminal >= primary


def _dispatch_one(plugin: Any, *, trigger: str) -> Dict[str, Any]:
    rows = _load_rows(plugin, _RESOURCE_KEY)
    if not rows:
        plugin._save_monitor_status(resource_queue_depth=0)
        return {"scheduled": False, "reason": "queue_empty", "queue_depth": 0}

    owner_ok, snapshot = plugin._v360_owner_gate()
    if not owner_ok:
        return {"scheduled": False, "reason": "handoff", "queue_depth": len(rows)}
    snapshot = dict(plugin._isolated_queue_snapshot() or {})
    if plugin._v360_worker_busy(snapshot):
        # 发现队列仍继续增长/去重；只有执行器等待。
        plugin._save_monitor_status(
            resource_queue_depth=len(rows),
            resource_dispatch_waiting=True,
            resource_dispatch_wait_reason="worker_busy",
        )
        return {
            "scheduled": False,
            "reason": "worker_busy",
            "queue_depth": len(rows),
            "current_task_path": str(snapshot.get("running_path") or ""),
        }

    now = time.time()
    candidates = sorted(
        rows.items(),
        key=lambda pair: (
            int((pair[1] or {}).get("priority") or 100),
            float((pair[1] or {}).get("next_due") or 0),
            float((pair[1] or {}).get("first_seen") or 0),
            pair[0],
        ),
    )
    selected: Tuple[str, Dict[str, Any]] | None = None
    for path, row in candidates:
        if float((row or {}).get("next_due") or 0) <= now:
            selected = (path, dict(row or {}))
            break
    if selected is None:
        return {"scheduled": False, "reason": "queue_wait", "queue_depth": len(rows)}

    path, row = selected
    dispatch_id = _scan_id("RUN")
    _log(dispatch_id, "调度", f"来源={trigger} path={path} 队列={len(rows)} reason={row.get('reason') or '-'}")
    try:
        _, direct_files = plugin._v360_list_directory(path)
    except Exception as err:  # noqa: BLE001
        row.update({"next_due": now + 30, "last_result": "read_error", "last_error": str(err), "last_attempt": now})
        rows[path] = row
        _save_rows(plugin, _RESOURCE_KEY, rows, _RESOURCE_LIMIT)
        _log(dispatch_id, "等待", f"目录读取失败，30s 后重试: {err}", level="warning")
        return {"scheduled": False, "reason": "read_error", "queue_depth": len(rows)}

    result = dict(plugin._v360_schedule_resource(path, direct_files) or {})
    if result.get("scheduled"):
        # 不立即删除资源队列项。Worker 完成后再次读取同目录，若还有未整理成员会继续；
        # 若源已搬空或所有成员都有终态证据，下次会自动收口。这是“整理一半继续跑”的关键。
        row.update(
            {
                "last_attempt": now,
                "last_result": "queued",
                "next_due": now + max(float(getattr(plugin, "_organize_monitor_stability", 10) or 10), 10.0),
                "priority": max(int(row.get("priority") or 10), 10),
                "force_verify": False,
            }
        )
        rows[path] = row
        _save_rows(plugin, _RESOURCE_KEY, rows, _RESOURCE_LIMIT)
        plugin._save_monitor_status(
            resource_queue_depth=len(rows),
            resource_dispatch_waiting=False,
            resource_last_dispatched_path=path,
            resource_last_dispatch_at=now,
        )
        _log(dispatch_id, "已入队", f"已交给单 Worker；资源目录继续保留复核，防止半整理丢失: {path}")
        return {**result, "queue_depth": len(rows), "path": path}

    if _queue_terminal(result):
        rows.pop(path, None)
        action = "收口"
        detail = "目录无主媒体或成员均已是终态"
    else:
        phases = dict(result.get("phases") or {})
        wait = str(result.get("reason") or "waiting")
        delay = 5.0 if wait in {"worker_not_accept", "state_changed"} else 30.0
        if int(phases.get("stabilizing") or 0) > 0:
            delay = max(delay, float(getattr(plugin, "_organize_monitor_stability", 10) or 10))
        row.update({"last_attempt": now, "last_result": wait, "next_due": now + delay, "force_verify": False})
        rows[path] = row
        action = "等待"
        detail = f"reason={wait} phases={phases}；{int(delay)}s 后复核"
    _save_rows(plugin, _RESOURCE_KEY, rows, _RESOURCE_LIMIT)
    plugin._save_monitor_status(resource_queue_depth=len(rows))
    _log(dispatch_id, action, f"{path}；{detail}")
    return {**result, "queue_depth": len(rows), "path": path}


def install_watch_pipeline_v380() -> None:
    """运行期安装，必须位于 v3.6.9 hardening 与 v3.7.6 双通道之后。"""
    if bool(getattr(_MonitorMixin, _INSTALL_FLAG, False)):
        return

    original_status = _MonitorMixin.api_organize_monitor_status
    original_get_api = _BaseOrganizerMixin.get_organizer_api

    def tick(self) -> None:
        self.init_organizer_monitor()
        if not getattr(self, "_organize_monitor_enabled", False):
            return
        if not getattr(self, "_enabled", False) or not getattr(self, "_guangya_api", None):
            return

        now_mono = time.monotonic()
        interval = _watch_interval(self)
        full_state = _full_load(self)
        last_watch = float(getattr(self, "_v380_last_watch_mono", 0) or 0)
        if not last_watch or now_mono - last_watch >= interval:
            self._v380_last_watch_mono = now_mono
            _watch_pulse(
                self,
                trigger="monitor",
                budget=_WATCH_WHILE_FULL_BUDGET if full_state.get("active") else _WATCH_BUDGET,
            )

        full_state = _full_load(self)
        last_full_step = float(getattr(self, "_v380_last_full_step_mono", 0) or 0)
        if full_state.get("active"):
            if not last_full_step or now_mono - last_full_step >= _MIN_WATCH_INTERVAL:
                self._v380_last_full_step_mono = now_mono
                _full_step(self, trigger="auto-resume")
        elif _full_due(self):
            self._v380_last_full_step_mono = now_mono
            # 自动全量只补发现，不把未变化历史资源全部重送；手动全量才 force_verify。
            _start_full(self, trigger="scheduled", force_verify=False)

        _dispatch_one(self, trigger="monitor")

    def api_scan(self, payload: dict = None) -> Dict[str, Any]:
        return _start_full(self, trigger="manual", force_verify=True)

    def api_incremental(self, payload: dict = None) -> Dict[str, Any]:
        result = _watch_pulse(self, trigger="manual", budget=max(_WATCH_BUDGET * 2, 128))
        dispatch = _dispatch_one(self, trigger="manual-incremental")
        if isinstance(result, dict):
            result.setdefault("data", {})["dispatch"] = dispatch
        return result

    def api_full(self, payload: dict = None) -> Dict[str, Any]:
        return _start_full(self, trigger="manual", force_verify=True)

    def api_full_stop(self, payload: dict = None) -> Dict[str, Any]:
        return _stop_full(self, trigger="manual")

    def status(self) -> Dict[str, Any]:
        response = original_status(self)
        if not isinstance(response, dict) or not response.get("success"):
            return response
        data = response.setdefault("data", {})
        status_row = data.setdefault("status", {})
        watch_rows = _load_rows(self, _WATCH_KEY)
        resource_rows = _load_rows(self, _RESOURCE_KEY)
        full = _full_load(self)
        now = time.time()
        hot = sum(1 for row in watch_rows.values() if float((row or {}).get("hot_until") or 0) > now)
        status_row.update(
            {
                "monitor_pipeline": "watch-pipeline-v3.8.0",
                "monitor_strategy": "watch-registry + persistent-resource-queue + independent-full-scan",
                "detection_runs_while_worker_busy": True,
                "watch_registry_total": len(watch_rows),
                "watch_hot_total": hot,
                "watch_interval": int(_watch_interval(self)),
                "watch_cold_recheck_interval": int(_COLD_RECHECK_SECONDS),
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
                "log_filter_hint": "【光鸭云盘助手】【监控】",
            }
        )
        return response

    def get_api(self):
        apis = list(original_get_api(self) or [])
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
        extra = [
            {"path": path, "endpoint": endpoint, "auth": "bear", "methods": ["POST"], "summary": summary, "response_model": GuangYaOrganizerResponse}
            for path, (endpoint, summary) in replacements.items()
            if path not in existing
        ]
        apis.extend(extra)
        return apis

    _MonitorMixin.organize_monitor_tick = tick
    _MonitorMixin.api_organize_monitor_scan = api_scan
    _MonitorMixin.api_organize_monitor_incremental_scan = api_incremental
    _MonitorMixin.api_organize_monitor_full_scan = api_full
    _MonitorMixin.api_organize_monitor_full_scan_stop = api_full_stop
    _MonitorMixin.api_organize_monitor_status = status
    _BaseOrganizerMixin.get_organizer_api = get_api
    setattr(_MonitorMixin, _INSTALL_FLAG, True)
    logger.info(
        "【光鸭云盘助手】【监控】v3.8.0 watch pipeline 已启用：持续目录观察 + 持久资源队列 + 独立全量巡检；Worker 忙时仍继续发现"
    )


__all__ = [
    "install_watch_pipeline_v380",
    "_WATCH_KEY",
    "_RESOURCE_KEY",
    "_FULL_KEY",
    "_directory_signature",
    "_select_watch_paths",
    "_queue_terminal",
]
