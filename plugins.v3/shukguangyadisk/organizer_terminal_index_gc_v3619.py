"""v3.6.19：严格远端可达性事实同步收口 known/pending 调度索引。

v3.6.13 已能在父目录严格分页读取后删除不可达的 OrganizerStateStore 状态；
但 v3.6.6 known-resource 与 v3.6.1 pending-resource 是独立持久索引。于是一个资源目录
已经被 MoviePilot move 掉后，completed 状态虽然被父目录清理，旧 known/pending 行仍可能
保留到后续轮询，再次触碰已经不存在的历史路径。

本层不增加任何媒体业务规则，只复用 v3.6.13 已经成立的严格目录事实：
- 当前目录明确不存在时，清理该目录及其后代的 known/pending 行；
- 当前目录存在时，仅当某个索引行位于“已严格确认缺失的直属子目录”下才删除；
- 仍存在的直属子目录整棵保留，等待扫描子目录时继续细化；
- 网络/API失败不会进入 v3.6.13 reconcile，因此本层也绝不会把网络故障当删除；
- 只在 v3.6.13 本轮确实回收了 organizer 状态时同步索引，避免每个正常目录都重复读写
  两份持久索引；其它无状态的陈旧 known 行仍由原 v3.6.7 known scan 自己确认并删除。
"""

from __future__ import annotations

import time
from pathlib import PurePosixPath
from typing import Any, Dict, Set

from app.sdk.logging import logger


_PATCH_FLAG = "_v3619_terminal_index_gc_ready"


def _index_path_unreachable_v3619(
    plugin: Any,
    *,
    group: str,
    path: str,
    directory_exists: bool,
    present_dirs: Set[str],
) -> bool:
    normalized = plugin._v360_norm(path)
    if not normalized:
        return False
    prefix = group.rstrip("/") + "/" if group != "/" else "/"

    if not directory_exists:
        return normalized == group or normalized.startswith(prefix)

    if normalized == group or not normalized.startswith(prefix):
        return False

    relative = normalized[len(prefix):]
    first = relative.split("/", 1)[0]
    if not first:
        return False
    first_child = plugin._v360_norm((PurePosixPath(group) / first).as_posix())
    return first_child not in present_dirs


def _prune_one_index_v3619(
    plugin: Any,
    *,
    loader_name: str,
    saver_name: str,
    group: str,
    directory_exists: bool,
    present_dirs: Set[str],
) -> int:
    loader = getattr(plugin, loader_name, None)
    saver = getattr(plugin, saver_name, None)
    if not callable(loader) or not callable(saver):
        return 0
    try:
        rows = dict(loader() or {})
    except Exception:
        return 0
    removed = 0
    for raw_path in list(rows):
        if not _index_path_unreachable_v3619(
            plugin,
            group=group,
            path=str(raw_path or ""),
            directory_exists=directory_exists,
            present_dirs=present_dirs,
        ):
            continue
        rows.pop(raw_path, None)
        removed += 1
    if not removed:
        return 0
    try:
        saver(rows)
    except Exception:
        return 0
    return removed


def prune_unreachable_resource_indexes_v3619(
    plugin: Any,
    *,
    group: str,
    directory_exists: bool,
    present_dirs: Set[str],
) -> Dict[str, int]:
    """按已经严格成立的父目录事实，同步删除不可达 known/pending 行。"""
    known = _prune_one_index_v3619(
        plugin,
        loader_name="_v366_load_known",
        saver_name="_v366_save_known",
        group=group,
        directory_exists=directory_exists,
        present_dirs=present_dirs,
    )
    pending = _prune_one_index_v3619(
        plugin,
        loader_name="_v361_load_pending",
        saver_name="_v361_save_pending",
        group=group,
        directory_exists=directory_exists,
        present_dirs=present_dirs,
    )
    if known or pending:
        now = time.time()
        status = getattr(plugin, "_save_monitor_status", None)
        if callable(status):
            try:
                status(
                    terminal_index_pruned=known + pending,
                    terminal_index_known_pruned=known,
                    terminal_index_pending_pruned=pending,
                    terminal_index_pruned_at=now,
                    terminal_index_pruned_path=group,
                )
            except Exception:
                pass
        logger.info(
            "【光鸭云盘助手】【v3.6.19】【终态索引】严格远端事实同步清理不可达调度索引："
            "known=%s pending=%s path=%s",
            known,
            pending,
            group,
        )
    return {"known": known, "pending": pending}


def install_terminal_index_gc_v3619() -> None:
    """包裹 v3.6.13 reachability helper；必须在 v3.6.9 hardening installer 之后执行。"""
    from . import organizer_hardening_v369 as hardening

    if getattr(hardening, _PATCH_FLAG, False):
        return
    previous = hardening._reconcile_reachable_state

    def reconcile(plugin: Any, group_path: str, children, *, directory_exists: bool):
        stats = dict(previous(plugin, group_path, children, directory_exists=directory_exists) or {})
        # 正常目录无状态变化时不要额外读取两份索引；v3.6.7 known scan 本身会处理纯索引陈旧项。
        # 目录自身明确不存在时即使状态已被别处先收口，也仍应把该目录的调度索引一起清掉。
        if int(stats.get("total") or 0) <= 0 and directory_exists:
            return stats
        group = plugin._v360_norm(group_path)
        present_dirs, _ = hardening._present_direct_children(plugin, group, children)
        pruned = prune_unreachable_resource_indexes_v3619(
            plugin,
            group=group,
            directory_exists=directory_exists,
            present_dirs=present_dirs,
        )
        stats["known_index"] = int(pruned.get("known") or 0)
        stats["pending_index"] = int(pruned.get("pending") or 0)
        return stats

    hardening._reconcile_reachable_state = reconcile
    setattr(hardening, _PATCH_FLAG, True)
    logger.info(
        "【光鸭云盘助手】【v3.6.19】终态索引收口已启用：严格缺失子树同步清理 known-resource/pending-resource，"
        "网络/API失败不触发删除"
    )


__all__ = [
    "install_terminal_index_gc_v3619",
    "prune_unreachable_resource_indexes_v3619",
]
