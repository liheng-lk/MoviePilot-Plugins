"""Worker 执行边界的源路径存在性与终态回收。

v3.7 起该文件不再自己决定“失败要不要 retry”，只提供一个可靠的远端事实：源当前是
``present / missing / unknown``。唯一文件处理策略位于 :mod:`organizer_policy`。

安全边界：
- 必须使用 ``refresh_item`` 失效路径缓存并重新解析；
- 只有明确返回 ``None``/``FileNotFoundError`` 才是 missing；
- 网络/API异常是 unknown，绝不能当成 missing 或“未识别”；
- 源明确消失时只清理本地 organizer 状态，不制造 completed/ignored/retry 历史。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from app.sdk.logging import logger

from .organizer_policy import SourcePresence


SOURCE_MISSING_TERMINAL_V3618 = "__shuk_source_missing_terminal_v3618__"
_STATE_TABLES = ("completed", "ignored", "blocked", "stabilizing", "inflight", "retry")
_MISSING_HINTS = (
    "没有找到可整理的媒体文件",
    "目录或文件不存在",
    "源目录不存在",
    "source not found",
    "file not found",
)


def _norm(plugin: Any, path: Any) -> str:
    normalizer = getattr(plugin, "_v360_norm", None) or getattr(plugin, "_organize_normalize_path", None)
    if callable(normalizer):
        try:
            return str(normalizer(str(path or "")) or "")
        except Exception:
            pass
    text = str(path or "").replace("\\", "/")
    if len(text) > 1:
        text = text.rstrip("/")
    return text


def source_missing_hint_v3618(message: Any) -> bool:
    """兼容旧调用点；新的失败决策请使用 organizer_policy。"""
    text = str(message or "").lower()
    return any(marker.lower() in text for marker in _MISSING_HINTS)


def probe_source_presence_v3618(plugin: Any, item: Any) -> SourcePresence:
    """强制刷新远端路径并返回三态事实；异常永远是 unknown。"""
    path = _norm(plugin, getattr(item, "path", ""))
    if not path:
        return SourcePresence.UNKNOWN
    api = getattr(plugin, "_guangya_api", None)
    refresh = getattr(api, "refresh_item", None)
    if not callable(refresh):
        return SourcePresence.UNKNOWN
    try:
        current = refresh(Path(path))
    except FileNotFoundError:
        return SourcePresence.MISSING
    except Exception as err:  # noqa: BLE001 - network/API failure is not absence evidence
        logger.debug(
            "【光鸭云盘助手】【源存在性】远端复核失败，事实=unknown，保留原状态: path=%s error=%s",
            path,
            err,
        )
        return SourcePresence.UNKNOWN
    return SourcePresence.MISSING if current is None else SourcePresence.PRESENT


def confirm_source_missing_v3618(plugin: Any, item: Any) -> bool:
    """旧接口兼容：只有三态探针明确 missing 才返回 True。"""
    return probe_source_presence_v3618(plugin, item) == SourcePresence.MISSING


def retire_missing_source_v3618(plugin: Any, item: Any, *, subtree: bool = False) -> Dict[str, int]:
    """清理已经明确不存在的源状态；不制造任何新的 terminal/retry 行。"""
    path = _norm(plugin, getattr(item, "path", ""))
    if not path:
        return {name: 0 for name in _STATE_TABLES}
    prefix = path.rstrip("/") + "/"
    state_store = plugin._state()

    def apply(state: Dict[str, Any]) -> Dict[str, int]:
        removed: Dict[str, int] = {}
        for name in _STATE_TABLES:
            mapping = dict(state.get(name) or {})
            before = len(mapping)
            if subtree:
                mapping = {
                    raw_path: row
                    for raw_path, row in mapping.items()
                    if not (
                        _norm(plugin, raw_path) == path
                        or _norm(plugin, raw_path).startswith(prefix)
                    )
                }
            else:
                mapping.pop(path, None)
                for raw_path in list(mapping):
                    if _norm(plugin, raw_path) == path:
                        mapping.pop(raw_path, None)
            state[name] = mapping
            removed[name] = before - len(mapping)
        return removed

    removed = dict(state_store.mutate(apply) or {})

    prune = getattr(plugin, "_v361_prune_stale_pending", None)
    if callable(prune):
        try:
            prune()
        except Exception as err:  # noqa: BLE001
            logger.debug("【光鸭云盘助手】【源消失终态】pending 自愈失败: %s", err)

    total = sum(int(value or 0) for value in removed.values())
    logger.info(
        "【光鸭云盘助手】【源消失终态】远端已确认源不存在，停止再次整理并清理本地状态: "
        "path=%s subtree=%s removed=%s details=%s",
        path,
        subtree,
        total,
        removed,
    )
    return removed


__all__ = [
    "SOURCE_MISSING_TERMINAL_V3618",
    "confirm_source_missing_v3618",
    "probe_source_presence_v3618",
    "retire_missing_source_v3618",
    "source_missing_hint_v3618",
]
