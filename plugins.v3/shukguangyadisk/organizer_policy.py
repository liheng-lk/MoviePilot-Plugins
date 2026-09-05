"""光鸭自动整理唯一文件处理策略。

本模块是 v3.7 起自动整理的**唯一决策表**。发现、MoviePilot 识别/预览、光鸭执行、状态和
UI 可以分层实现，但“一个源文件最终应该怎么办”只能在这里定义，禁止再用新的
``organizer_*_vXXXX.py`` 补丁各自发明终态语义。

长期不变量：
1. 只有 MoviePilot 已经给出可靠媒体身份和可审计目标的资源才允许整理；
2. 识别失败/无法形成可靠目标且源仍存在：原地保留，不移动、不删除、不改名、不进入 retry；
3. 只有可靠目标已经存在且源/目标**字节大小均已知并完全一致**时，才可判定重复并删除源；
4. 同一媒体身份/目标但大小不同：不是重复，必须保留为不同版本，不得覆盖或删除；
5. 任一大小未知：禁止自动删除；
6. 网络/API/宿主异常属于暂时故障，允许 retry，不能伪装成“未识别”；
7. 源明确已经不存在：只回收本地调度状态，不制造 completed 历史。

这里不决定分类目录、重命名模板、媒体 ID、move/copy 类型或刮削；这些仍由 MoviePilot
负责。这里也不直接调用光鸭 API，因此规则可以零副作用单测。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional


class SourcePresence(str, Enum):
    """远端源存在性三态；unknown 绝不能被当成 missing。"""

    PRESENT = "present"
    MISSING = "missing"
    UNKNOWN = "unknown"


class FileDisposition(str, Enum):
    """自动整理允许产生的文件级决策。"""

    ORGANIZE = "organize"
    LEAVE_UNRECOGNIZED = "leave_unrecognized"
    DELETE_DUPLICATE = "delete_duplicate"
    ORGANIZE_VERSION = "organize_version"
    RETRY_TRANSIENT = "retry_transient"
    BLOCK_SAFETY = "block_safety"
    RETIRE_MISSING = "retire_missing"


# 这些都是“宿主明确没有形成可整理媒体身份/目标”的语义，不包含网络/API 异常。
_UNRECOGNIZED_MARKERS = (
    "没有找到可整理的媒体文件",
    "安全识别已停止整理",
    "未识别到媒体信息",
    "未识别到该目录",
    "识别未确认",
    "无法为当前源生成可审计预览",
    "预览仍未返回当前源文件",
)

# 命中这些词时，即使同时出现“识别”字样，也必须保留 retry，避免网络抖动被永久停放。
_TRANSIENT_MARKERS = (
    "异常",
    "网络",
    "连接失败",
    "连接超时",
    "timeout",
    "timed out",
    "temporary",
    "temporarily",
    "service unavailable",
    "api失败",
    "api 失败",
)

_MISSING_MARKERS = (
    "目录或文件不存在",
    "源目录不存在",
    "source not found",
    "file not found",
)


def normalize_size(value: Any) -> Optional[int]:
    """只接受可靠非负整数字节数；None 表示未知，未知大小绝不用于删除判断。"""
    if value is None or value == "":
        return None
    try:
        size = int(value)
    except (TypeError, ValueError):
        return None
    return size if size >= 0 else None


def is_unrecognized_message(message: Any) -> bool:
    """判断公开失败是否属于确定的“无法形成可整理媒体”语义。"""
    text = str(message or "")
    lowered = text.casefold()
    if any(marker.casefold() in lowered for marker in _TRANSIENT_MARKERS):
        return False
    return any(marker.casefold() in lowered for marker in _UNRECOGNIZED_MARKERS)


def should_probe_source_presence(message: Any) -> bool:
    """只有语义可能依赖“源是否还存在”时才额外访问远端，普通失败不增加 I/O。"""
    text = str(message or "").casefold()
    return (
        is_unrecognized_message(message)
        or any(marker.casefold() in text for marker in _MISSING_MARKERS)
    )


def decide_failed_execution(message: Any, presence: SourcePresence) -> FileDisposition:
    """把 MoviePilot 失败收口成唯一终态，不靠模块安装顺序猜测。"""
    if presence == SourcePresence.MISSING:
        return FileDisposition.RETIRE_MISSING
    if presence == SourcePresence.UNKNOWN:
        return FileDisposition.RETRY_TRANSIENT
    if is_unrecognized_message(message):
        return FileDisposition.LEAVE_UNRECOGNIZED
    return FileDisposition.RETRY_TRANSIENT


def decide_existing_target(source_size: Any, target_size: Any) -> FileDisposition:
    """已有目标的唯一大小规则：同字节=重复；不同字节=版本；未知=安全阻断。"""
    source = normalize_size(source_size)
    target = normalize_size(target_size)
    if source is None or target is None:
        return FileDisposition.BLOCK_SAFETY
    if source == target:
        return FileDisposition.DELETE_DUPLICATE
    return FileDisposition.ORGANIZE_VERSION


__all__ = [
    "FileDisposition",
    "SourcePresence",
    "decide_existing_target",
    "decide_failed_execution",
    "is_unrecognized_message",
    "normalize_size",
    "should_probe_source_presence",
]
