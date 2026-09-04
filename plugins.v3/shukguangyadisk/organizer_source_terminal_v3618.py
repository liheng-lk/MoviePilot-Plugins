"""v3.6.18：Worker 执行边界的源路径消失终态收口。

自动整理 discovery 与私有 Worker 之间存在天然时间窗口：资源在扫描时存在，但在真正
``TransferChain.do_transfer`` 前可能已经被其它整理、人工操作或同盘 move 删除。旧逻辑
会把 MoviePilot 的“没有找到可整理的媒体文件”统一当成失败写回 retry，于是一个已经不存在
的源路径会被持续重试。

本层只接受远端存在性事实：
- 必须使用 v3.6.9 ``refresh_item`` 先失效路径缓存并重新解析；
- 只有明确返回 ``None``/``FileNotFoundError`` 才认定源已消失；
- 网络/API异常返回 unknown，不清状态；
- 源已消失时仅删除该路径（目录任务则删除整棵子树）的本地 organizer 状态，随后让
  pending 自愈重算；不写 completed/ignored/retry，也不修改 MoviePilot durable task。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from app.sdk.logging import logger


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
    text = str(message or "").lower()
    return any(marker.lower() in text for marker in _MISSING_HINTS)


def confirm_source_missing_v3618(plugin: Any, item: Any) -> bool:
    """强制刷新远端路径；只有明确不存在才返回 True，异常永远返回 False。"""
    path = _norm(plugin, getattr(item, "path", ""))
    if not path:
        return False
    api = getattr(plugin, "_guangya_api", None)
    refresh = getattr(api, "refresh_item", None)
    if not callable(refresh):
        return False
    try:
        current = refresh(Path(path))
    except FileNotFoundError:
        return True
    except Exception as err:  # noqa: BLE001 - network/API failure is not absence evidence
        logger.debug(
            "【光鸭云盘助手】【v3.6.18】【源存在性】远端复核失败，保留原状态: path=%s error=%s",
            path,
            err,
        )
        return False
    return current is None


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
                # 状态表可能遗留未规范化 key；同时按 normalize 后身份删除。
                for raw_path in list(mapping):
                    if _norm(plugin, raw_path) == path:
                        mapping.pop(raw_path, None)
            state[name] = mapping
            removed[name] = before - len(mapping)
        return removed

    removed = dict(state_store.mutate(apply) or {})

    # 不直接删除整个 group pending，避免同目录其它仍在等待的成员失去优先回访；让现有
    # v3.6.8 依据剩余直属等待态事实决定是否删除 pending。
    prune = getattr(plugin, "_v361_prune_stale_pending", None)
    if callable(prune):
        try:
            prune()
        except Exception as err:  # noqa: BLE001
            logger.debug("【光鸭云盘助手】【v3.6.18】【源消失终态】pending 自愈失败: %s", err)

    total = sum(int(value or 0) for value in removed.values())
    logger.info(
        "【光鸭云盘助手】【v3.6.18】【源消失终态】远端已确认源不存在，停止再次整理并清理本地状态: "
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
    "retire_missing_source_v3618",
    "source_missing_hint_v3618",
]
