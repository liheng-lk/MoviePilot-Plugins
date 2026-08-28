"""v3.4.13+：多级目录按实际文件所在目录分组。

v3.5.2 进一步修复超大平铺分类目录：``/电影`` 这类目录即使直接包含数千视频，
也不能先把全部文件塞进 inventory 再产生第一个任务，否则会在任务出现前撞上 5000
inventory cap。泛化容器现在按主视频逐个 yield，v3.5 单任务背压会在第一个真正接收的
资源处停止扫描；具体作品/Season 目录仍完整聚合，保持整季事务和目录身份。
"""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any, Dict, Iterator, List, Set, Tuple

from app.sdk.logging import logger

from .organizer_empty_folder_guard_v3410 import _runtime_media_exts
from .organizer_folder_stream import GuangYaFolderStreamMixin
from . import organizer_folder_batch_v342 as _folder_batch


_STREAMING_CONTAINER_NAMES: Set[str] = {
    "mp", "media", "medias", "download", "downloads", "incoming", "inbox",
    "movie", "movies", "film", "films", "电影", "電影", "影片",
    "华语电影", "華語電影", "国产电影", "國產電影", "外语电影", "外語電影",
    "欧美电影", "歐美電影", "日韩电影", "日韓電影", "动画电影", "動畫電影",
    "tv", "tvshows", "tv shows", "series", "shows", "电视剧", "電視劇",
    "剧", "劇", "剧集", "劇集", "国产剧", "國產劇", "欧美剧", "歐美劇",
    "日韩剧", "日韓劇", "动漫", "動漫", "动画", "動畫", "番剧", "番劇", "anime",
    "纪录片", "紀錄片", "记录片", "記錄片", "documentary", "documentaries",
    "综艺", "綜藝", "variety", "儿童", "兒童", "少儿", "少兒", "kids", "children",
    "国漫", "國漫", "日番", "合集", "collection", "collections",
    "光鸭媒体库", "光鴨媒體庫",
}


def _norm_name(value: str) -> str:
    return " ".join(str(value or "").replace("_", " ").replace("-", " ").split()).casefold()


def _is_streaming_container(plugin: Any, path: str) -> bool:
    name = _norm_name(Path(path).name)
    names = {_norm_name(value) for value in _STREAMING_CONTAINER_NAMES}
    names.update({_norm_name(value) for value in getattr(plugin, "_generic_title_dirs", set())})
    return bool(name and name in names)


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


def _iter_streaming_container(
    self: Any,
    *,
    current: Any,
    current_path: str,
    children: List[Any],
    scan_meta: Dict[str, Any],
) -> Iterator[Tuple[str, List[Any]]]:
    """泛化容器只逐个暴露主视频；旁路 mp3/字幕绝不独立形成影视任务。"""
    media_exts = _runtime_media_exts()
    child_dirs: List[Any] = []
    primary_files: List[Any] = []

    for child in children:
        name = str(getattr(child, "name", "") or "")
        if name.startswith("."):
            continue
        child_type = str(getattr(child, "type", "") or "")
        if child_type == "dir":
            if self._organize_monitor_recursive:
                child_dirs.append(child)
            continue
        if child_type != "file":
            continue
        suffix = Path(name or str(getattr(child, "path", "") or "")).suffix.casefold()
        if suffix in media_exts:
            primary_files.append(child)

    # 这是有意的“部分 inventory”：单任务模式只需要找到下一个资源，不能因为未枚举
    # 同目录剩余几千文件就把它们当作被删除。状态清理由 truncated 保护。
    if primary_files:
        scan_meta["truncated"] = True
        scan_meta["streaming_discovery"] = True
        primary_files.sort(key=self._file_sort_key)
        for child in primary_files:
            path = self._organize_normalize_path(getattr(child, "path", ""))
            scan_meta["inventory_paths"].add(path)
            scan_meta["files"] += 1
            scan_meta["groups_discovered"] += 1
            scan_meta["groups_scanned"] += 1
            logger.debug(
                "【光鸭云盘助手】【流式发现】泛化容器逐个暴露主视频: %s -> %s",
                current_path,
                path,
            )
            # group_path 保持容器路径；v3.5.1 会强制按 loose_single 处理该单视频，
            # 不会把 current_path 目录本身递归交给 MoviePilot。
            yield current_path, [child]

    # 如果同级没有可接收主视频或全部被状态机跳过，继续向下找真正资源目录。
    if self._organize_monitor_recursive:
        child_dirs.sort(key=self._group_sort_key)
        for child_dir in child_dirs:
            scan_meta["visited"] += 1
            if scan_meta["visited"] > self._monitor_inventory_cap:
                scan_meta["truncated"] = True
                logger.warning(
                    "【光鸭云盘助手】【自动整理】【多级目录】子目录遍历达到 inventory cap，"
                    "保留已有状态: %s",
                    current_path,
                )
                return
            yield "__enqueue_dir__", [child_dir]


def _iter_deep_folder_groups(
    self: Any,
    root_path: str,
    scan_meta: Dict[str, Any],
) -> Iterator[Tuple[str, List[Any]]]:
    """按实际文件所在目录逐层产生 group；超大泛化容器采用主视频流式发现。"""
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
    scan_meta["grouping_mode"] = "deep_direct_files_streaming"

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
        children = list(self._guangya_api.list(current) or [])

        if _is_streaming_container(self, current_path):
            child_dirs: List[Any] = []
            media_exts = _runtime_media_exts()
            primary_files: List[Any] = []
            for child in children:
                name = str(getattr(child, "name", "") or "")
                if name.startswith("."):
                    continue
                child_type = str(getattr(child, "type", "") or "")
                if child_type == "dir":
                    if self._organize_monitor_recursive:
                        child_dirs.append(child)
                    continue
                if child_type != "file":
                    continue
                suffix = Path(name or str(getattr(child, "path", "") or "")).suffix.casefold()
                if suffix in media_exts:
                    primary_files.append(child)

            if primary_files:
                # 不对同级全部主视频消耗 visited/inventory cap。v3.5 单任务 wrapper 会在
                # 第一个真正提交后终止本轮；如果前几个处于重试/稳定等待，则继续找下一个。
                scan_meta["truncated"] = True
                scan_meta["streaming_discovery"] = True
                primary_files.sort(key=self._file_sort_key)
                for child in primary_files:
                    path = self._organize_normalize_path(getattr(child, "path", ""))
                    scan_meta["inventory_paths"].add(path)
                    scan_meta["files"] += 1
                    scan_meta["groups_discovered"] += 1
                    scan_meta["groups_scanned"] += 1
                    yield current_path, [child]

            if self._organize_monitor_recursive:
                child_dirs.sort(key=self._group_sort_key)
                for child in child_dirs:
                    if not account(child):
                        logger.warning(
                            "【光鸭云盘助手】【自动整理】【多级目录】子目录遍历达到 inventory cap，"
                            "保留已有状态: %s",
                            current_path,
                        )
                        return
                    queue.append(child)
            continue

        direct_files: List[Any] = []
        child_dirs: List[Any] = []
        for child in children:
            if not account(child):
                logger.warning(
                    "【光鸭云盘助手】【自动整理】【多级目录】扫描达到 inventory cap，"
                    "当前具体资源目录及后续目录不提交，保留已有状态: %s",
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
                "【光鸭云盘助手】【自动整理】【多级目录】发现具体资源目录: %s，直接文件=%s",
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

    # 先替换扫描分组；后续网络韧性和单任务补丁会包裹这个实现。
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


__all__ = [
    "install_deep_folder_stream_v3413",
    "_iter_deep_folder_groups",
    "_is_streaming_container",
]
