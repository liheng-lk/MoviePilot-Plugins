"""v3.4.13：多级目录按实际文件所在目录分组。

旧 folder-stream 把“监控根的第一层子目录”当成资源目录，再递归收集其所有后代文件。
当监控目录类似 ``/剧/国产剧/花开锦绣 (2026)/Season 1`` 时，会把整个 ``/剧``
视为一个任务；这既无法代表一个具体媒体资源，也可能让 MoviePilot 对分类容器目录做识别。

本补丁只调整扫描/任务边界，不参与媒体识别和分类：
- 递归遍历任意深度；
- 每个“直接包含文件”的目录独立成为一个 group；
- 父目录与子目录不再合并为一个递归任务；
- 非叶子目录即使自身有文件，也禁止原生递归目录批量，避免把子目录重复整理；
- 真正叶子目录仍完整交给 MoviePilot ``TransferChain`` 处理。
"""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple

from app.sdk.logging import logger

from .organizer_folder_stream import GuangYaFolderStreamMixin
from . import organizer_folder_batch_v342 as _folder_batch


def _direct_child_state(plugin: Any, group_path: str) -> Tuple[bool, bool]:
    """返回 (查询成功, 是否存在直接子目录)。查询失败时由调用方保守降级。"""
    try:
        current = plugin._guangya_api.get_item(Path(group_path)) if plugin._guangya_api else None
        if not current or getattr(current, "type", None) != "dir":
            return False, False
        children = plugin._guangya_api.list(current) or []
        return True, any(
            getattr(child, "type", None) == "dir"
            and not str(getattr(child, "name", "") or "").startswith(".")
            for child in children
        )
    except Exception as err:  # noqa: BLE001 - network/storage boundary
        logger.debug(
            "【光鸭云盘助手】【多级目录】检查子目录失败，保守改用非递归成员模式: %s - %s",
            group_path,
            err,
        )
        return False, False


def _iter_deep_folder_groups(
    self: Any,
    root_path: str,
    scan_meta: Dict[str, Any],
) -> Iterator[Tuple[str, List[Any]]]:
    """按实际文件所在目录逐层产生 group，永不把第一层分类目录吞并整棵子树。"""
    if not self._guangya_api:
        raise RuntimeError("光鸭云盘尚未登录或存储未初始化")

    normalized_root = self._organize_normalize_path(root_path)
    root = self._guangya_api.get_item(Path(normalized_root))
    if not root or root.type != "dir":
        raise RuntimeError(f"监控目录不存在: {normalized_root}")

    scan_meta.setdefault("inventory_paths", set())
    scan_meta.setdefault("visited", 0)
    scan_meta.setdefault("files", 0)
    scan_meta.setdefault("groups_discovered", 0)
    scan_meta.setdefault("groups_scanned", 0)
    scan_meta.setdefault("truncated", False)
    scan_meta["grouping_mode"] = "deep_direct_files"

    def account(child: Any) -> bool:
        scan_meta["visited"] += 1
        if scan_meta["visited"] > self._monitor_inventory_cap:
            scan_meta["truncated"] = True
            return False
        return True

    queue = deque([root])
    while queue:
        current = queue.popleft()
        current_path = self._organize_normalize_path(
            getattr(current, "path", "") or normalized_root
        )
        direct_files: List[Any] = []
        child_dirs: List[Any] = []

        for child in self._guangya_api.list(current) or []:
            if not account(child):
                logger.warning(
                    "【光鸭云盘助手】【自动整理】【多级目录】扫描达到 inventory cap，"
                    "当前目录及后续目录不提交，保留已有状态: %s",
                    current_path,
                )
                return
            if str(getattr(child, "name", "") or "").startswith("."):
                continue
            if child.type == "dir":
                if self._organize_monitor_recursive:
                    child_dirs.append(child)
            elif child.type == "file":
                direct_files.append(child)
                path = self._organize_normalize_path(getattr(child, "path", ""))
                scan_meta["inventory_paths"].add(path)
                scan_meta["files"] += 1

        if direct_files:
            direct_files.sort(key=self._file_sort_key)
            scan_meta["groups_discovered"] += 1
            scan_meta["groups_scanned"] += 1
            logger.debug(
                "【光鸭云盘助手】【自动整理】【多级目录】发现文件目录: %s，直接文件=%s",
                current_path,
                len(direct_files),
            )
            yield current_path, direct_files

        if not self._organize_monitor_recursive:
            continue
        child_dirs.sort(key=self._group_sort_key)
        queue.extend(child_dirs)


def install_deep_folder_stream_v3413() -> None:
    if getattr(GuangYaFolderStreamMixin, "_guangya_deep_folder_stream_v3413", False):
        return

    # 先替换扫描分组；v3.4.7 的网络韧性补丁随后会包裹此实现。
    GuangYaFolderStreamMixin._iter_folder_groups = _iter_deep_folder_groups

    original_can_use_native = _folder_batch._can_use_native_directory_batch

    def can_use_native_directory_batch(plugin: Any, group_path: str, members: List[Any]) -> bool:
        if not original_can_use_native(plugin, group_path, members):
            return False
        checked, has_child_dir = _direct_child_state(plugin, group_path)
        if not checked:
            return False
        if has_child_dir:
            logger.info(
                "【光鸭云盘助手】【多级目录】目录自身有文件且仍包含子目录，"
                "为避免递归重复整理，当前层仅处理直接成员: %s",
                group_path,
            )
            return False
        return True

    _folder_batch._can_use_native_directory_batch = can_use_native_directory_batch
    GuangYaFolderStreamMixin._guangya_deep_folder_stream_v3413 = True


__all__ = ["install_deep_folder_stream_v3413", "_iter_deep_folder_groups"]
