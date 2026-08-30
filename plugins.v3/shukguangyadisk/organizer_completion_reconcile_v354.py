"""v3.5.4：自动整理完成态证据校验与旧缓存自愈。

问题背景：历史版本的私有同步 worker 在 ``TransferChain.do_transfer()`` 返回 True、
但 MoviePilot 没有发送最终事件时，会通过 fallback 直接把仍在 inflight 的源文件写入
插件 ``completed`` 缓存。后续扫描看到同一 fingerprint 后会直接跳过，因此可能出现
“目录扫描正常、提交 MP=0、MoviePilot 整理历史为空”的假完成状态。

本层只修正状态机证据边界：
1. 升级后把当前监控目录内旧 ``completed`` 缓存一次性退回立即核验；真实已有 MP 成功
   历史的文件会在原生 history gate 中重新确认，不会重复整理。
2. 对同步 worker 的 success fallback，只允许 MP history gate 已确认成功的成员保持
   ``completed``；没有成功历史的成员强制退回 retry，等待下一轮重新提交。
3. 不改变 MoviePilot 的识别、分类、命名、目标目录、覆盖、刮削或真实整理实现。
"""

from __future__ import annotations

import time
from pathlib import PurePosixPath
from typing import Any, Dict, List, Tuple

from app.sdk.logging import logger

from .organizer_folder_stream import GuangYaFolderStreamMixin
from .organizer_queue_recovery import GuangYaQueueRecoveryMixin


_RECONCILE_MARKER_KEY = "organize_v354_completion_reconcile"
_RECONCILE_REVISION = 1


def _norm(plugin: Any, value: Any) -> str:
    try:
        return plugin._organize_normalize_path(value)
    except Exception:
        return str(value or "").replace("\\", "/").rstrip("/")


def _under_monitor(plugin: Any, path: str) -> bool:
    checker = getattr(plugin, "_is_monitored_path", None)
    if callable(checker):
        try:
            return bool(checker(path))
        except Exception:
            pass
    try:
        child = PurePosixPath(_norm(plugin, path))
        root = PurePosixPath(_norm(plugin, getattr(plugin, "_organize_monitor_path", "")))
        return root != PurePosixPath("/") and (child == root or child.is_relative_to(root))
    except (TypeError, ValueError):
        return False


def _members(item: Any) -> List[Any]:
    members = list(getattr(item, "members", None) or [])
    return members or [item]


def _inflight_rows(plugin: Any, item: Any) -> List[Tuple[Any, str, str, Dict[str, Any]]]:
    """只抓 fallback 调用前仍在 inflight 的成员，避免触碰已收到真实终态的成员。"""
    try:
        raw = plugin._state().load()
    except Exception:
        return []
    inflight = dict(raw.get("inflight") or {})
    rows: List[Tuple[Any, str, str, Dict[str, Any]]] = []
    for member in _members(item):
        path = _norm(plugin, getattr(member, "path", ""))
        if not path:
            continue
        fingerprint = plugin._fingerprint(member)
        state_row = inflight.get(path)
        if not isinstance(state_row, dict):
            continue
        if str(state_row.get("fingerprint") or "") != fingerprint:
            continue
        rows.append((member, path, fingerprint, dict(state_row)))
    return rows


def _force_retry(
    plugin: Any,
    *,
    path: str,
    fingerprint: str,
    reason: str,
    previous: Dict[str, Any] | None = None,
    retry_at: float = 0.0,
) -> None:
    """从 completed/其它瞬态强制回到 retry；不能使用 mark_deferred 的 completed 短路。"""
    previous = dict(previous or {})

    def apply(state: Dict[str, Any]) -> None:
        for bucket in ("completed", "ignored", "blocked", "stabilizing", "inflight"):
            mapping = state.get(bucket)
            if isinstance(mapping, dict):
                mapping.pop(path, None)
        retry = dict(state.get("retry") or {})
        retry[path] = {
            "fingerprint": fingerprint,
            "attempts": max(int(previous.get("attempts") or 0), 0),
            "retry_at": float(retry_at or 0.0),
            "last_error": reason,
            "reconciled_at": time.time(),
        }
        state["retry"] = retry

    plugin._state().mutate(apply)


def _force_blocked(
    plugin: Any,
    *,
    path: str,
    fingerprint: str,
    reason: str,
) -> None:
    def apply(state: Dict[str, Any]) -> None:
        for bucket in ("completed", "ignored", "stabilizing", "inflight", "retry"):
            mapping = state.get(bucket)
            if isinstance(mapping, dict):
                mapping.pop(path, None)
        blocked = dict(state.get("blocked") or {})
        blocked[path] = {
            "fingerprint": fingerprint,
            "reason": reason,
            "blocked_at": time.time(),
        }
        state["blocked"] = blocked

    plugin._state().mutate(apply)


def _requeue_legacy_completed_once(plugin: Any) -> int:
    """升级后只执行一次：旧 completed 不再被当作真实 MP 历史的替代品。"""
    monitor_path = _norm(plugin, getattr(plugin, "_organize_monitor_path", ""))
    marker = plugin.get_data(_RECONCILE_MARKER_KEY) or {}
    if (
        isinstance(marker, dict)
        and int(marker.get("revision") or 0) >= _RECONCILE_REVISION
        and _norm(plugin, marker.get("monitor_path") or "") == monitor_path
    ):
        return 0

    now = time.time()

    def apply(state: Dict[str, Any]) -> int:
        completed = dict(state.get("completed") or {})
        retry = dict(state.get("retry") or {})
        moved = 0
        for path, fingerprint in list(completed.items()):
            if not _under_monitor(plugin, str(path or "")):
                continue
            completed.pop(path, None)
            retry[path] = {
                "fingerprint": str(fingerprint or ""),
                "attempts": 0,
                "retry_at": 0,
                "last_error": "v3.5.4 升级核验：旧 completed 缓存必须重新经过 MoviePilot 成功历史确认",
                "reconciled_at": now,
            }
            moved += 1
        state["completed"] = completed
        state["retry"] = retry
        return moved

    try:
        moved = int(plugin._state().mutate(apply) or 0)
    except Exception as err:  # noqa: BLE001
        logger.warning("【光鸭云盘助手】【完成态自愈】旧 completed 缓存重新核验失败: %s", err)
        return 0

    plugin.save_data(
        _RECONCILE_MARKER_KEY,
        {
            "revision": _RECONCILE_REVISION,
            "monitor_path": monitor_path,
            "applied_at": now,
            "requeued": moved,
        },
    )
    plugin._save_monitor_status(
        completion_reconcile_revision=_RECONCILE_REVISION,
        completion_reconcile_requeued=moved,
        completion_reconcile_at=now,
    )
    if moved:
        logger.warning(
            "【光鸭云盘助手】【完成态自愈】发现旧版完成缓存 %s 个，已全部退回 MoviePilot 历史核验；"
            "真实已整理项会被 MP 历史直接确认，未真实整理项会重新提交",
            moved,
        )
    else:
        logger.info("【光鸭云盘助手】【完成态自愈】旧 completed 缓存无需修复")
    return moved


def _reconcile_success_fallback(
    plugin: Any,
    rows: List[Tuple[Any, str, str, Dict[str, Any]]],
    message: str,
) -> Tuple[int, int, int]:
    """同步调用返回 success 不是完成证据；仅 MP history=completed 才保留 completed。"""
    confirmed = reopened = blocked = 0
    for member, path, fingerprint, state_row in rows:
        try:
            preflight = dict(plugin._preflight_history(member, path) or {})
        except Exception as err:  # noqa: BLE001
            preflight = {
                "decision": "unknown",
                "message": f"MoviePilot 成功历史复核异常：{err}",
            }
        decision = str(preflight.get("decision") or "unknown")
        detail = str(preflight.get("message") or "")
        if decision == "completed":
            confirmed += 1
            continue
        if decision == "blocked":
            reason = detail or "MoviePilot 历史门控阻止再次提交"
            _force_blocked(
                plugin,
                path=path,
                fingerprint=fingerprint,
                reason=reason,
            )
            blocked += 1
            continue

        reason = (
            "同步整理调用返回成功，但没有 MoviePilot 成功历史/最终事件证据；"
            f"已退回待核验，禁止写入假 completed。{detail or message or ''}"
        ).rstrip("。")
        # 给数据库/事件一个很短的落库窗口；下一轮会先走 MP history gate，
        # 若刚才其实已真实整理，会直接重新确认而不会重复执行。
        _force_retry(
            plugin,
            path=path,
            fingerprint=fingerprint,
            reason=reason,
            previous=state_row,
            retry_at=time.time() + 5.0,
        )
        reopened += 1
        plugin._append_monitor_history({
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "path": path,
            "name": str(getattr(member, "name", "") or PurePosixPath(path).name),
            "size": int(getattr(member, "size", 0) or 0),
            "result": "completion_unverified",
            "message": reason,
        })

    return confirmed, reopened, blocked


def install_completion_reconcile_v354() -> None:
    if getattr(GuangYaQueueRecoveryMixin, "_guangya_completion_reconcile_v354", False):
        return

    # 安装在所有旧 fallback wrapper 之后。先让旧层完成其日志/续跑/粘性收尾，
    # 再只针对调用前仍在 inflight 的成员核验证据；真实终态已收口的成员不会被触碰。
    previous_fallback = GuangYaQueueRecoveryMixin._fallback_terminal_state

    def fallback(self: Any, item: Any, success: bool, message: str) -> None:
        unresolved_before = _inflight_rows(self, item) if success else []
        status_before = dict(self.get_data(self._monitor_status_key) or {}) if unresolved_before else {}
        sticky_before = str(status_before.get("sticky_tv_group_path") or "")

        previous_fallback(self, item, success=success, message=message)
        if not success or not unresolved_before:
            return

        confirmed, reopened, blocked = _reconcile_success_fallback(
            self,
            unresolved_before,
            message,
        )

        # v3.5.2 fallback 可能因为临时假 completed 提前释放剧集粘性；若成员被重新打开，
        # 在续跑 timer 触发前恢复原 sticky，确保同一 Season 继续收口。
        if reopened and sticky_before:
            self._save_monitor_status(
                sticky_tv_group_path=sticky_before,
                sticky_tv_group_active=True,
                sticky_tv_group_release_reason="",
            )

        status = dict(self.get_data(self._monitor_status_key) or {})
        self._save_monitor_status(
            completion_fallback_confirmed_total=int(status.get("completion_fallback_confirmed_total") or 0) + confirmed,
            completion_fallback_reopened_total=int(status.get("completion_fallback_reopened_total") or 0) + reopened,
            completion_fallback_blocked_total=int(status.get("completion_fallback_blocked_total") or 0) + blocked,
        )
        if reopened or blocked:
            logger.warning(
                "【光鸭云盘助手】【完成态证据】同步调用 success 但 MP 未确认完成："
                "重新待处理=%s，门控=%s，已由 MP 历史确认=%s",
                reopened,
                blocked,
                confirmed,
            )

    GuangYaQueueRecoveryMixin._fallback_terminal_state = fallback

    previous_scan = GuangYaFolderStreamMixin.run_organize_monitor_scan

    def run_scan(self: Any, manual: bool = False) -> Dict[str, Any]:
        requeued = _requeue_legacy_completed_once(self)
        result = previous_scan(self, manual=manual)
        if not isinstance(result, dict):
            return result
        data = dict(result.get("data") or {})
        if requeued:
            data["completion_reconcile_requeued"] = requeued
            result["data"] = data
        logger.info(
            "【光鸭云盘助手】【自动整理】【状态诊断】待处理=%s，等待稳定=%s，"
            "状态完成缓存=%s，已忽略=%s，历史本轮确认=%s，延后=%s，提交=%s",
            int(data.get("changed") or 0),
            int(data.get("waiting") or 0),
            int(data.get("completed") or data.get("state_completed") or 0),
            int(data.get("ignored") or data.get("state_ignored") or 0),
            int(data.get("history_completed") or 0),
            int(data.get("deferred") or 0),
            int(data.get("submitted") or 0),
        )
        return result

    GuangYaFolderStreamMixin.run_organize_monitor_scan = run_scan
    GuangYaQueueRecoveryMixin._guangya_completion_reconcile_v354 = True
    logger.info("【光鸭云盘助手】【v3.5.4】完成态证据校验与旧缓存自愈已启用")


__all__ = [
    "install_completion_reconcile_v354",
    "_requeue_legacy_completed_once",
    "_reconcile_success_fallback",
]
