"""v3.6.9 / v3.6.13：自动监控连续发现、远端读取故障隔离与状态可达性回收。

v3.6.6 引入 known-resource 增量索引后，已完成基线的日常 tick 只检查旧资源目录；新创建、
从未进入 known 索引的资源只能等 30 分钟 full discovery。这让“60 秒监控”并不等价于
“60 秒内发现新资源”，同时每轮最多检查 500 个旧目录会产生大量远端 API 请求。

v3.6.9 保持严格单任务流水与 MoviePilot 业务边界，只修发现/状态基础设施：
- known-resource 每轮预算收敛到 24 个目录；
- known 检查没有提交任务时，同一个 monitor tick 继续推进一页 50 目录 discovery 游标；
- v3.6 engine 目录读取改用 GuangYaApi.list_strict；网络/API 失败必须传播为扫描错误；
- 成功读取目录后回收已经搬走的状态，避免长期运行状态 JSON 无界增长。

v3.6.13 继续收口状态回收语义：旧实现只清“当前目录直属文件”，如果一个资源子目录整体
被搬走，子目录内 completed/blocked/retry/stabilizing/inflight/ignored 永远没有机会再被直属
回收；同时旧 helper 即使没有任何状态变化也会调用 state.mutate()，导致每成功读取一个目录
都整份重写状态 JSON。本层现在基于严格完整目录列表做可达性证明：
- 当前目录明确不存在/已变成非目录时，清理其整棵状态子树；
- 当前目录存在时，只清直属已消失文件，以及“直属子目录已明确消失”之下的后代状态；
- 仍存在的直属子目录整棵保留，等待后续扫描该子目录再细化，不做祖先猜测；
- 网络/API失败绝不回收；非递归监控也使用原始完整 children 判断子目录是否存在；
- 先只读预检是否真的有状态需要删除，无变化时不调用 mutate，避免空扫描反复写大 JSON。
"""

from __future__ import annotations

import time
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Sequence, Set, Tuple

from app.sdk.logging import logger

from . import organizer_monitor_v366 as _v366
from .organizer_engine_v360 import GuangYaOrganizerEngineV360Mixin
from .organizer_monitor_v366 import GuangYaOrganizerMonitorV366Mixin


_KNOWN_SCAN_BUDGET = 24
_PATCH_FLAG = "_v369_runtime_hardening_ready"
_STATE_NAMES = ("completed", "ignored", "blocked", "stabilizing", "inflight", "retry")


def _network_status(plugin: Any) -> Dict[str, Any]:
    api = getattr(plugin, "_guangya_api", None)
    client = getattr(api, "client", None) or getattr(plugin, "_client", None)
    getter = getattr(client, "get_network_status", None)
    if not callable(getter):
        return {"available": True, "hosts": {}}
    try:
        return dict(getter() or {})
    except Exception:
        return {"available": True, "hosts": {}}


def _direct_parent(plugin: Any, raw_path: str) -> str:
    try:
        return plugin._v360_norm(PurePosixPath(str(raw_path or "")).parent.as_posix())
    except Exception:
        return ""


def _child_path(plugin: Any, group: str, child: Any) -> str:
    raw_path = str(getattr(child, "path", "") or "")
    if raw_path:
        return plugin._v360_norm(raw_path)
    name = str(getattr(child, "name", "") or "")
    if not name:
        return ""
    try:
        return plugin._v360_norm((PurePosixPath(group) / name).as_posix())
    except Exception:
        return ""


def _present_direct_children(
    plugin: Any,
    group: str,
    children: Sequence[Any],
) -> Tuple[Set[str], Set[str]]:
    """从严格完整 children 提取真实直属目录/文件；不受 recursive 配置影响。"""
    present_dirs: Set[str] = set()
    present_files: Set[str] = set()
    for child in children:
        path = _child_path(plugin, group, child)
        if not path or _direct_parent(plugin, path) != group:
            continue
        kind = str(getattr(child, "type", "") or "")
        if kind == "dir":
            present_dirs.add(path)
        elif kind == "file":
            present_files.add(path)
    return present_dirs, present_files


def _state_path_is_unreachable(
    plugin: Any,
    *,
    group: str,
    path: str,
    directory_exists: bool,
    present_dirs: Set[str],
    present_files: Set[str],
) -> Tuple[bool, str]:
    """返回 (是否不可达, direct/subtree)。只使用已严格确认的直属目录事实。"""
    normalized = plugin._v360_norm(path)
    if not normalized:
        return False, ""
    prefix = group.rstrip("/") + "/" if group != "/" else "/"

    if not directory_exists:
        if normalized == group or normalized.startswith(prefix):
            return True, "subtree"
        return False, ""

    parent = _direct_parent(plugin, normalized)
    if parent == group:
        if normalized not in present_files and normalized not in present_dirs:
            return True, "direct"
        return False, ""

    if not normalized.startswith(prefix):
        return False, ""
    relative = normalized[len(prefix):]
    if "/" not in relative:
        return False, ""
    first = relative.split("/", 1)[0]
    if not first:
        return False, ""
    first_child = plugin._v360_norm((PurePosixPath(group) / first).as_posix())
    if first_child not in present_dirs:
        return True, "subtree"
    return False, ""


def _reconcile_reachable_state(
    plugin: Any,
    group_path: str,
    children: Sequence[Any],
    *,
    directory_exists: bool,
) -> Dict[str, Any]:
    """按严格目录事实回收不可达状态；无变化时绝不写状态 JSON。"""
    group = plugin._v360_norm(group_path)
    empty = {"total": 0, "direct": 0, "subtree": 0, "by_state": {}}
    if not group:
        return empty

    present_dirs, present_files = _present_direct_children(plugin, group, children)
    store = plugin._state()

    def inspect(state: Dict[str, Any]) -> Dict[str, Any]:
        counts: Dict[str, int] = {}
        direct = 0
        subtree = 0
        for name in _STATE_NAMES:
            mapping = dict(state.get(name) or {})
            for raw_path in mapping:
                remove, scope = _state_path_is_unreachable(
                    plugin,
                    group=group,
                    path=str(raw_path or ""),
                    directory_exists=directory_exists,
                    present_dirs=present_dirs,
                    present_files=present_files,
                )
                if not remove:
                    continue
                counts[name] = counts.get(name, 0) + 1
                if scope == "direct":
                    direct += 1
                else:
                    subtree += 1
        return {
            "total": direct + subtree,
            "direct": direct,
            "subtree": subtree,
            "by_state": counts,
        }

    # 绝大多数目录扫描没有状态变化。先 load + 只读判断，零变化时不进入 mutate，避免
    # OrganizerStateStore.mutate() 无条件整份写回 JSON 的历史开销。
    preview = inspect(store.load())
    if int(preview.get("total") or 0) <= 0:
        return preview

    def apply(state: Dict[str, Any]) -> Dict[str, Any]:
        counts: Dict[str, int] = {}
        direct = 0
        subtree = 0
        for name in _STATE_NAMES:
            mapping = dict(state.get(name) or {})
            removed_here = 0
            for raw_path in list(mapping):
                remove, scope = _state_path_is_unreachable(
                    plugin,
                    group=group,
                    path=str(raw_path or ""),
                    directory_exists=directory_exists,
                    present_dirs=present_dirs,
                    present_files=present_files,
                )
                if not remove:
                    continue
                mapping.pop(raw_path, None)
                removed_here += 1
                if scope == "direct":
                    direct += 1
                else:
                    subtree += 1
            if removed_here:
                counts[name] = removed_here
                state[name] = mapping
        return {
            "total": direct + subtree,
            "direct": direct,
            "subtree": subtree,
            "by_state": counts,
        }

    return dict(store.mutate(apply) or empty)


def _split_children(plugin: Any, children: Sequence[Any]) -> Tuple[List[Any], List[Any]]:
    dirs: List[Any] = []
    files: List[Any] = []
    for child in children:
        name = str(getattr(child, "name", "") or "")
        if not name or name.startswith("."):
            continue
        kind = str(getattr(child, "type", "") or "")
        if kind == "dir":
            if getattr(plugin, "_organize_monitor_recursive", False):
                dirs.append(child)
        elif kind == "file":
            files.append(child)
    dirs.sort(key=plugin._group_sort_key)
    files.sort(key=plugin._file_sort_key)
    return dirs, files


def _record_state_reconcile(plugin: Any, path: str, stats: Dict[str, Any], *, reason: str) -> None:
    total = int(stats.get("total") or 0)
    if total <= 0:
        return
    direct = int(stats.get("direct") or 0)
    subtree = int(stats.get("subtree") or 0)
    normalized = plugin._v360_norm(path)
    now = time.time()
    plugin._save_monitor_status(
        state_direct_pruned=direct,
        state_direct_pruned_at=now,
        state_direct_pruned_path=normalized,
        state_subtree_pruned=subtree,
        state_reachability_pruned=total,
        state_reachability_pruned_at=now,
        state_reachability_pruned_path=normalized,
    )
    logger.info(
        "【光鸭云盘助手】【v3.6.13】【状态回收】%s：总计=%s，直属=%s，缺失子目录后代=%s，状态=%s path=%s",
        reason,
        total,
        direct,
        subtree,
        stats.get("by_state") or {},
        normalized,
    )


def install_organizer_hardening_v369() -> None:
    """幂等包裹 v3.6 engine/monitor，不改变识别、分类、命名或整理策略。"""
    if getattr(GuangYaOrganizerMonitorV366Mixin, _PATCH_FLAG, False):
        return

    # 旧实现每 tick 最多读 500 个历史资源目录；先收敛远端请求预算，再持续推进 discovery。
    _v366._KNOWN_SCAN_LIMIT = min(int(getattr(_v366, "_KNOWN_SCAN_LIMIT", 500) or 500), _KNOWN_SCAN_BUDGET)

    previous_list_directory = GuangYaOrganizerEngineV360Mixin._v360_list_directory
    previous_monitor_scan = GuangYaOrganizerMonitorV366Mixin.run_organize_monitor_scan

    def list_directory(plugin: Any, path: str):
        api = getattr(plugin, "_guangya_api", None)
        if not api:
            raise RuntimeError("光鸭云盘尚未登录或存储未初始化")

        current = api.get_item(Path(path))
        if not current:
            # get_item 经 v3.6.9 完整分页明确确认不存在，整棵状态子树都已不可达。
            stats = _reconcile_reachable_state(plugin, path, [], directory_exists=False)
            _record_state_reconcile(plugin, path, stats, reason="目录已确认不存在")
            return [], []
        if str(getattr(current, "type", "") or "") != "dir":
            stats = _reconcile_reachable_state(plugin, path, [], directory_exists=False)
            _record_state_reconcile(plugin, path, stats, reason="原目录路径已变为非目录")
            return [], []

        strict_list = getattr(api, "list_strict", None)
        if not callable(strict_list):
            # 安装顺序异常时宁可保留旧语义，不在这里基于不完整列表清理状态。
            return previous_list_directory(plugin, path)

        try:
            children = list(strict_list(current) or [])
        except Exception as first_error:
            refresher = getattr(api, "refresh_item", None)
            if not callable(refresher):
                raise
            try:
                refreshed = refresher(Path(path))
            except Exception:
                raise first_error
            if not refreshed:
                # 首次 list 失败后，重新按完整路径解析确认目录确实消失，才允许整棵收口。
                stats = _reconcile_reachable_state(plugin, path, [], directory_exists=False)
                _record_state_reconcile(plugin, path, stats, reason="刷新确认目录已消失")
                return [], []
            if str(getattr(refreshed, "type", "") or "") != "dir":
                stats = _reconcile_reachable_state(plugin, path, [], directory_exists=False)
                _record_state_reconcile(plugin, path, stats, reason="刷新确认原目录已变为非目录")
                return [], []
            try:
                children = list(strict_list(refreshed) or [])
            except Exception as retry_error:
                raise RuntimeError(
                    f"严格读取目录失败，已刷新 fileId 仍不可用: {path} - {retry_error}"
                ) from retry_error

        # children 是 list_strict 的完整分页结果。必须在 _split_children 之前做可达性判断，
        # 因为 non-recursive 模式会故意不把存在的子目录加入 discovery dirs，但状态不能因此被删。
        stats = _reconcile_reachable_state(plugin, path, children, directory_exists=True)
        _record_state_reconcile(plugin, path, stats, reason="严格读取后清理不可达状态")
        dirs, files = _split_children(plugin, children)
        return dirs, files

    def run_monitor_scan(plugin: Any, manual: bool = False) -> Dict[str, Any]:
        # 先保留 v3.6.7 的 owner / pending / known / manual-safe 全部语义。
        result = previous_monitor_scan(plugin, manual=manual)
        if manual or not isinstance(result, dict):
            return result

        data = dict(result.get("data") or {})
        if any(
            data.get(key)
            for key in ("scheduled", "busy", "handoff", "disabled", "scan_busy")
        ):
            return result
        # 只有 v3.6.7 日常 known scan 正常结束后才补推进 discovery；初始/周期 baseline 已经
        # 自己调用了 engine，不能重复扫描第二页。
        if not data.get("known_scan"):
            return result

        network = _network_status(plugin)
        if not network.get("available", True):
            plugin._save_monitor_status(
                network_deferred=True,
                network_message="光鸭文件 API 暂不可用；已知资源/连续发现均保留状态等待下轮",
            )
            return {
                "success": True,
                "message": "光鸭网络/API暂不可用，本轮保留状态并延后连续发现",
                "data": {
                    **data,
                    "continuous_discovery": False,
                    "network_deferred": True,
                },
            }

        # 直接进入唯一 v3.6 engine 的一页 discovery。动态 self._v360_schedule_resource 仍会
        # 落回 v3.6.7 最终准入层，因此不会绕过手动筛选、history gate 或 admission guard。
        discovery = GuangYaOrganizerEngineV360Mixin.run_organize_monitor_scan(plugin, manual=False)
        if not isinstance(discovery, dict):
            return result
        discovery_data = discovery.setdefault("data", {})
        if not isinstance(discovery_data, dict):
            discovery_data = {}
            discovery["data"] = discovery_data
        discovery_data["continuous_discovery"] = True
        discovery_data["known_scan_summary"] = {
            "known_total": data.get("known_total", 0),
            "known_checked": data.get("known_checked", 0),
            "known_changed": data.get("known_changed", 0),
            "known_removed": data.get("known_removed", 0),
            "known_errors": data.get("known_errors", 0),
        }
        if discovery_data.get("cycle_complete"):
            marker = getattr(plugin, "_v366_mark_baseline_complete", None)
            if callable(marker):
                marker()
            plugin._save_monitor_status(full_discovery_completed_at=time.time())

        after_network = _network_status(plugin)
        if not after_network.get("available", True):
            discovery["success"] = True
            discovery["message"] = "连续发现期间网络/API中断，游标已停在断点并保留全部状态"
            discovery_data["network_deferred"] = True
        else:
            plugin._save_monitor_status(network_deferred=False, network_message="")
        logger.info(
            "【光鸭云盘助手】【v3.6.9】【连续发现】known检查=%s/%s，随后推进discovery目录=%s，提交=%s，剩余=%s",
            data.get("known_checked", 0),
            data.get("known_total", 0),
            discovery_data.get("dirs_scanned", 0),
            1 if discovery_data.get("scheduled") else 0,
            discovery_data.get("remaining_dirs", 0),
        )
        return discovery

    GuangYaOrganizerEngineV360Mixin._v360_list_directory = list_directory
    GuangYaOrganizerMonitorV366Mixin.run_organize_monitor_scan = run_monitor_scan
    setattr(GuangYaOrganizerMonitorV366Mixin, _PATCH_FLAG, True)
    logger.info(
        "【光鸭云盘助手】【v3.6.13】监控硬化已启用：known预算=%s + 每周期连续50目录discovery + "
        "严格远端读取 + 缺失子树状态回收 + 无变化零状态写入",
        _v366._KNOWN_SCAN_LIMIT,
    )


__all__ = ["install_organizer_hardening_v369"]
