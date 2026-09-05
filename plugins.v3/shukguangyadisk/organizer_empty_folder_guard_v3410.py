"""v3.4.10：空目录/已搬空目录不再进入 MoviePilot 识别。

私有 worker 中的文件夹任务是扫描时快照。任务真正执行前，源目录可能已经被上一轮整理
搬空，只剩空目录、字幕或其它非视频文件。此时继续调用 MoviePilot 的目录识别与集数模板
推荐没有意义，还会产生“目录中没有可用于识别的媒体文件”等误导性 WARNING。

本补丁在 v3.4.9 数据安全校验之前重新读取光鸭源目录，只检查 MoviePilot 当前配置的
RMT_MEDIAEXT 视频扩展名：
- 仍有视频：继续原有 MoviePilot 识别、预览和真实整理；
- 已无视频/目录已不存在：把该内存中的陈旧文件夹任务静默收口，不再调用 MoviePilot；
- 文件 API 网络异常：不把“读取为空”误判为真实空目录，安全退回重试。

不改变 MoviePilot 的识别、分类、命名、覆盖或目标目录规则。
"""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any, Optional, Set, Tuple

from app.runtime.settings import get_runtime_setting
from app.sdk.logging import logger

from .guangya_network_resilience_v347 import _api_network_status, _network_retry_after
from .organizer_folder_batch_v342 import _FolderBatchEnvelope
from .organizer_mp_folder_context_v346 import _is_monitor_root_folder_task


def _runtime_media_exts() -> Set[str]:
    value = get_runtime_setting("RMT_MEDIAEXT")
    if not value:
        return set()
    if isinstance(value, str):
        values = [part.strip() for part in value.split(",")]
    else:
        values = [str(part).strip() for part in value]
    return {
        (part if part.startswith(".") else f".{part}").casefold()
        for part in values
        if part
    }


def _live_primary_media_state(plugin: Any, folder_path: str) -> Tuple[str, int, str]:
    """返回 (media/empty/missing/network/unknown, 视频数量, 说明)。"""
    before = _api_network_status(plugin)
    if not before.get("available", True):
        retry_after = max(int(_network_retry_after(before)), 1)
        return "network", 0, f"光鸭文件 API 暂不可用，约 {retry_after}s 后重试"

    api = getattr(plugin, "_guangya_api", None)
    if not api:
        return "unknown", 0, "光鸭存储尚未初始化"

    normalized = plugin._organize_normalize_path(folder_path)
    try:
        root = api.get_item(Path(normalized))
    except Exception as err:  # noqa: BLE001
        after = _api_network_status(plugin)
        if not after.get("available", True):
            retry_after = max(int(_network_retry_after(after)), 1)
            return "network", 0, f"光鸭文件 API 暂不可用，约 {retry_after}s 后重试"
        return "unknown", 0, f"读取源目录失败：{err}"

    after_get = _api_network_status(plugin)
    if not after_get.get("available", True):
        retry_after = max(int(_network_retry_after(after_get)), 1)
        return "network", 0, f"光鸭文件 API 暂不可用，约 {retry_after}s 后重试"

    if not root:
        return "missing", 0, "源目录已不存在"
    if str(getattr(root, "type", "") or "") != "dir":
        return "missing", 0, "源路径已不是目录"

    media_exts = _runtime_media_exts()
    if not media_exts:
        # 无法读取 MoviePilot 视频扩展名时，不冒险把目录判空。
        return "unknown", 0, "MoviePilot RMT_MEDIAEXT 当前为空"

    queue = deque([root])
    media_count = 0
    try:
        while queue:
            current = queue.popleft()
            children = api.list(current) or []
            status = _api_network_status(plugin)
            if not status.get("available", True):
                retry_after = max(int(_network_retry_after(status)), 1)
                return "network", 0, f"光鸭文件 API 暂不可用，约 {retry_after}s 后重试"
            for child in children:
                name = str(getattr(child, "name", "") or "")
                if name.startswith("."):
                    continue
                child_type = str(getattr(child, "type", "") or "")
                if child_type == "dir":
                    queue.append(child)
                    continue
                if child_type != "file":
                    continue
                suffix = Path(name or str(getattr(child, "path", "") or "")).suffix.casefold()
                if suffix in media_exts:
                    media_count += 1
                    # 只需确认“仍有视频”，不必为执行前门禁重新遍历整季。
                    return "media", media_count, ""
    except Exception as err:  # noqa: BLE001
        status = _api_network_status(plugin)
        if not status.get("available", True):
            retry_after = max(int(_network_retry_after(status)), 1)
            return "network", 0, f"光鸭文件 API 暂不可用，约 {retry_after}s 后重试"
        return "unknown", 0, f"读取源目录内容失败：{err}"

    return "empty", 0, "源目录当前已无 MoviePilot 可整理的视频文件"


def _clear_stale_transient_state(plugin: Any, item: _FolderBatchEnvelope) -> int:
    """陈旧内存任务不标 completed，只移除已经不存在源文件的临时状态。"""
    paths = {
        plugin._organize_normalize_path(str(getattr(member, "path", "") or ""))
        for member in item.members
        if getattr(member, "path", None)
    }
    paths.discard("")
    if not paths:
        return 0

    state_store = plugin._state()

    def apply(state: dict) -> int:
        removed = 0
        for name in ("blocked", "stabilizing", "inflight", "retry"):
            mapping = state.get(name) or {}
            for path in paths:
                if path in mapping:
                    mapping.pop(path, None)
                    removed += 1
            state[name] = mapping
        return removed

    return int(state_store.mutate(apply) or 0)



__all__ = [
    "_clear_stale_transient_state",
    "_live_primary_media_state",
    "_runtime_media_exts",
]
