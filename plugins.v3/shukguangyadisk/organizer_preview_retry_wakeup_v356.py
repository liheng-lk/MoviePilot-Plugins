"""v3.5.6：升级后立即唤醒 v3.5.5 之前遗留的“目录预览缺员”重试状态。

v3.5.5 已经能够把新的 MoviePilot 目录 preview 缺员拆成逐文件补预览并局部隔离，
但升级前已经进入 retry 的成员仍保留旧指数退避 ``retry_at``。当这些成员属于当前
TV sticky Season 时，sticky 会继续认为事务未收口，后续资源全部进入 capacity_wait，
导致 v3.5.5 没有机会真正执行。

本层只做一次性状态迁移：
- 仅匹配 retry.last_error 中明确包含“源文件未进入 MoviePilot 预览”的旧状态；
- 只把 retry_at 调整为 0，让下一次扫描立即重新提交；
- 不修改 attempts/fingerprint，不清除 retry，不直接标 completed；
- 网络失败、真实整理失败、历史门控失败等其它 retry 完全不动；
- 重新提交后仍由 v3.5.5 的 MoviePilot preview + v3.5.4 的最终证据边界决定结果。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

from app.sdk.logging import logger

from .organizer_folder_stream import GuangYaFolderStreamMixin


_MARKER_KEY = "organize_v356_preview_retry_wakeup"
_MISSING_PREVIEW_TOKEN = "源文件未进入 MoviePilot 预览"


def _wake_legacy_preview_retries(plugin: Any) -> Dict[str, Any]:
    marker = plugin.get_data(_MARKER_KEY) or {}
    if isinstance(marker, dict) and marker.get("applied"):
        return marker

    state_store = plugin._state()
    now = time.time()

    def apply(state: Dict[str, Any]) -> Dict[str, Any]:
        retry = dict(state.get("retry") or {})
        woken: List[str] = []
        untouched = 0
        for path, raw in list(retry.items()):
            if not isinstance(raw, dict):
                untouched += 1
                continue
            reason = str(raw.get("last_error") or "")
            if _MISSING_PREVIEW_TOKEN not in reason:
                untouched += 1
                continue
            row = dict(raw)
            row["retry_at"] = 0
            row["v356_wakeup_at"] = now
            row["v356_wakeup_reason"] = "升级后立即重新进入 v3.5.5 MoviePilot 逐文件补预览"
            retry[path] = row
            woken.append(str(path))

        state["retry"] = retry
        return {
            "woken": len(woken),
            "paths": woken[:20],
            "untouched": untouched,
        }

    result = dict(state_store.mutate(apply) or {})
    marker = {
        "applied": True,
        "applied_at": now,
        "woken": int(result.get("woken") or 0),
        "paths": list(result.get("paths") or []),
        "untouched": int(result.get("untouched") or 0),
    }
    plugin.save_data(_MARKER_KEY, marker)

    if marker["woken"]:
        logger.warning(
            "【光鸭云盘助手】【v3.5.6】【升级自愈】发现旧版目录预览缺员 retry=%s，"
            "已取消旧指数退避并立即交回 v3.5.5 MoviePilot 补预览；其它 retry 保持原样",
            marker["woken"],
        )
        try:
            plugin._save_monitor_status(
                preview_retry_wakeup_v356=marker["woken"],
                preview_retry_wakeup_v356_at=now,
            )
        except Exception:
            pass
    else:
        logger.info("【光鸭云盘助手】【v3.5.6】【升级自愈】没有发现需要唤醒的旧预览缺员 retry")

    return marker


def install_preview_retry_wakeup_v356() -> None:
    if getattr(GuangYaFolderStreamMixin, "_guangya_preview_retry_wakeup_v356", False):
        return

    previous_scan = GuangYaFolderStreamMixin.run_organize_monitor_scan

    def run_scan(self: Any, manual: bool = False):
        try:
            _wake_legacy_preview_retries(self)
        except Exception as err:  # noqa: BLE001
            # 自愈失败不能阻断普通扫描；保留原 retry 状态，下轮仍可继续尝试。
            logger.exception("【光鸭云盘助手】【v3.5.6】【升级自愈】旧预览缺员 retry 唤醒失败: %s", err)
        return previous_scan(self, manual=manual)

    GuangYaFolderStreamMixin.run_organize_monitor_scan = run_scan
    GuangYaFolderStreamMixin._guangya_preview_retry_wakeup_v356 = True
    logger.info("【光鸭云盘助手】【v3.5.6】旧预览缺员 retry 一次性唤醒已启用")


__all__ = ["install_preview_retry_wakeup_v356", "_wake_legacy_preview_retries"]
