"""v3.6.11：失败历史复用 MoviePilot durable task，禁止不同 planning_input 二次准入。

MoviePilot 新版整理链把同一 ``(storage, src_path)`` 的 durable admission 绑定到首次
``planning_input``。失败终态会保留 ``transferpending`` 及冻结计划；普通自动路径的
history gate 虽然会对未耗尽失败记录返回 PASS_FAILED，但若调用方随后重新执行一次
``do_transfer(manual=False)``，会重新构造 planning_input，并在 admit 阶段触发：

``整理源文件已按不同输入准入``

正确恢复路径不是删除 pending，也不是再次规划，而是调用 MoviePilot 自身
``TransferExecutionCommand.request_retry``，让 durable scheduler 复用原 task/checkpoint。

本模块只修调度身份：
- failed history + transfer_task_id + PASS_FAILED -> 请求 durable retry，不新建 Worker task；
- retry_wait 请求天然幂等；running/settling 只等待，不抢占；
- durable failed history 对应的源文件版本已变化时禁止复用旧冻结计划，进入持久 blocked，
  等用户在 MoviePilot 放弃/删除旧失败任务后再重新规划；
- admission conflict fallback 改为持久阻断，不再每 10 分钟重复撞同一条持久准入；
- 历史任务身份变化后允许重新评估，文件指纹变化仍由 OrganizerStateStore 自动解除旧状态。

不修改 MoviePilot 的识别、分类、命名、目标目录、overwrite 或真实执行规则。
"""

from __future__ import annotations

import time
from pathlib import PurePosixPath
from typing import Any, Dict, Optional, Tuple

from app.sdk.logging import logger

from .organizer_engine_v360 import GuangYaOrganizerEngineV360Mixin
from .organizer_monitor_v366 import GuangYaOrganizerMonitorV366Mixin


_PATCH_FLAG = "_v3611_durable_retry_ready"
_ADMISSION_CONFLICT_TOKENS = (
    "整理源文件已按不同输入准入",
    "TransferAdmissionConflictError",
)
_PASS_FAILED = "pass_failed"
_PASS_FAILED_VERSION_CHANGED = "pass_failed_version_changed"
# admission conflict 是持久 identity 冲突，不应靠 10 分钟计时猜测会自行消失。
_PERSISTENT_RECHECK_AT = 32503680000.0  # 3000-01-01 UTC 左右，仅作为持久 blocked 哨兵。
_ACTIVE_DURABLE_STATES = {"running", "settling", "retry_wait"}


def _state_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip().casefold()


def _is_admission_conflict(message: Any) -> bool:
    text = str(message or "")
    return any(token in text for token in _ADMISSION_CONFLICT_TOKENS)


def _history_numbers(decision: Dict[str, Any]) -> Tuple[int, int]:
    try:
        history_id = int(decision.get("history_id") or 0)
    except (TypeError, ValueError):
        history_id = 0
    try:
        revision = int(decision.get("transfer_settlement_revision") or 0)
    except (TypeError, ValueError):
        revision = 0
    return history_id, revision


def _blocked_row(plugin: Any, path: str) -> Dict[str, Any]:
    try:
        raw = plugin._state().load()
        row = dict((raw.get("blocked") or {}).get(path) or {})
        return row
    except Exception:
        return {}


def _clear_blocked_path(plugin: Any, path: str) -> bool:
    def apply(state: Dict[str, Any]) -> bool:
        blocked = dict(state.get("blocked") or {})
        existed = path in blocked
        blocked.pop(path, None)
        state["blocked"] = blocked
        return existed

    try:
        return bool(plugin._state().mutate(apply))
    except Exception:
        return False


def _persist_admission_block(
    plugin: Any,
    *,
    path: str,
    fingerprint: str,
    reason: str,
    decision: Optional[Dict[str, Any]] = None,
) -> None:
    """写入不会靠时间自动开放的 admission block，并保存当前 MP 证据身份。"""
    decision = dict(decision or {})
    history_id, revision = _history_numbers(decision)
    transfer_task_id = str(decision.get("transfer_task_id") or "")
    now = time.time()
    store = plugin._state()
    store.mark_blocked(
        path=path,
        fingerprint=fingerprint,
        reason=reason,
        now=now,
    )

    def apply(state: Dict[str, Any]) -> None:
        row = dict((state.get("blocked") or {}).get(path) or {})
        if not row or str(row.get("fingerprint") or "") != fingerprint:
            return
        row.update(
            {
                "reason": reason,
                "recheck_at": _PERSISTENT_RECHECK_AT,
                "v3611_persistent_admission": True,
                "v3611_history_id": history_id,
                "v3611_transfer_task_id": transfer_task_id,
                "v3611_settlement_revision": revision,
                "v3611_blocked_at": now,
            }
        )
        state["blocked"][path] = row

    store.mutate(apply)


def _admission_evidence_changed(row: Dict[str, Any], decision: Dict[str, Any]) -> bool:
    """只有已经记录过 durable 身份时，才用身份变化自动解除持久冲突。"""
    old_task = str(row.get("v3611_transfer_task_id") or "")
    old_history = int(row.get("v3611_history_id") or 0)
    old_revision = int(row.get("v3611_settlement_revision") or 0)
    if not (old_task or old_history or old_revision):
        return False
    task = str(decision.get("transfer_task_id") or "")
    history_id, revision = _history_numbers(decision)
    # 用户在 MoviePilot 放弃失败 durable task 后，历史会解除 transfer_task_id 绑定；
    # 或后续结算产生新 revision/history，均视为宿主证据已经变化，应重新评估。
    return (task, history_id, revision) != (old_task, old_history, old_revision)


def _mark_durable_inflight(
    plugin: Any,
    *,
    member: Any,
    path: str,
    fingerprint: str,
    decision: Dict[str, Any],
) -> bool:
    history_id, revision = _history_numbers(decision)
    task_id = str(decision.get("transfer_task_id") or "")
    try:
        parent = plugin._v360_norm(PurePosixPath(path).parent.as_posix())
    except Exception:
        parent = ""
    attempt = plugin._state().mark_submitting(
        path=path,
        fingerprint=fingerprint,
        now=time.time(),
        metadata={
            "name": str(getattr(member, "name", "") or PurePosixPath(path).name),
            "size": int(getattr(member, "size", 0) or 0),
            "group_path": parent,
            "group_name": PurePosixPath(parent).name if parent else "",
            "folder_task": False,
            "v360_engine": True,
            "v3611_durable_retry": True,
            "v3611_history_id": history_id,
            "v3611_transfer_task_id": task_id,
            "v3611_settlement_revision": revision,
        },
    )
    return bool(attempt)


def _request_durable_retry(
    plugin: Any,
    *,
    member: Any,
    path: str,
    fingerprint: str,
    decision: Dict[str, Any],
) -> Tuple[str, Optional[Tuple[Any, str, str]]]:
    task_id = str(decision.get("transfer_task_id") or "")
    history_id, _ = _history_numbers(decision)
    if not task_id:
        return "ready", (member, path, fingerprint)

    _clear_blocked_path(plugin, path)
    if not _mark_durable_inflight(
        plugin,
        member=member,
        path=path,
        fingerprint=fingerprint,
        decision=decision,
    ):
        return "inflight", None

    try:
        # 只依赖 MoviePilot application command + TransferChain 已装配的 repository；
        # 不直接访问 transferpending 数据库，更不绕过 lease/CAS fencing。
        from app.application.transfer.execution import TransferExecutionCommand
        from app.chain.transfer import TransferChain

        chain = TransferChain()
        repository = getattr(chain, "transfer_execution_repository", None)
        if repository is None:
            raise RuntimeError("当前 MoviePilot 未暴露 durable transfer execution repository")
        result = TransferExecutionCommand(repository).request_retry(
            task_id=task_id,
            reason=f"光鸭云盘助手自动恢复失败整理历史 #{history_id or 0}",
            requested_by="shukguangyadisk_auto",
        )
    except Exception as err:  # durable 端口临时失败：回插件 retry，绝不退回新 planning。
        plugin._state().mark_failed(
            path=path,
            fingerprint=fingerprint,
            now=time.time(),
            reason=f"MoviePilot durable retry 请求失败：{err}",
        )
        logger.warning(
            "【光鸭云盘助手】【v3.6.11】【durable重试】请求失败，已回插件 retry，不重新准入: %s - %s",
            path,
            err,
        )
        return "retry_wait", None

    accepted = bool(getattr(result, "accepted", False))
    state = _state_value(getattr(result, "state", ""))
    message = str(getattr(result, "message", "") or "")
    if accepted or state in _ACTIVE_DURABLE_STATES:
        plugin._save_monitor_status(
            durable_retry_waiting=True,
            durable_retry_path=path,
            durable_retry_task_id=task_id,
            durable_retry_history_id=history_id,
            durable_retry_state=state,
            durable_retry_message=message,
            durable_retry_requested_at=time.time(),
        )
        logger.info(
            "【光鸭云盘助手】【v3.6.11】【durable重试】复用 MoviePilot 原任务，不创建新 planning: "
            "history_id=%s task_id=%s state=%s path=%s；%s",
            history_id,
            task_id,
            state or "retry_wait",
            path,
            message or "已交回 durable scheduler",
        )
        return "inflight", None

    reason = message or f"MoviePilot durable task 当前状态 {state or 'unknown'} 不接受自动重试"
    _persist_admission_block(
        plugin,
        path=path,
        fingerprint=fingerprint,
        reason=reason,
        decision=decision,
    )
    logger.warning(
        "【光鸭云盘助手】【v3.6.11】【durable重试】宿主拒绝自动重试，已持久 blocked: %s - %s",
        path,
        reason,
    )
    return "blocked", None


def install_durable_retry_v3611() -> None:
    """幂等安装 durable retry bridge 与 admission-conflict 持久阻断。"""
    if getattr(GuangYaOrganizerEngineV360Mixin, _PATCH_FLAG, False):
        return

    previous_prepare = GuangYaOrganizerEngineV360Mixin._v360_prepare_member
    previous_fallback = GuangYaOrganizerMonitorV366Mixin._fallback_terminal_state

    def prepare_member(plugin: Any, member: Any):
        path, fingerprint = plugin._v360_member_identity(member)
        existing_block = _blocked_row(plugin, path)

        # v3.6.7/3.6.10 已经留下的准入冲突不能继续等 10 分钟重撞。先查宿主历史证据，
        # 能识别 durable failed task 就直接切入正确 retry；宿主证据确实变化才重新开放。
        if (
            existing_block
            and str(existing_block.get("fingerprint") or "") == fingerprint
            and _is_admission_conflict(existing_block.get("reason"))
        ):
            decision = dict(plugin._v360_history_decision(member, path) or {})
            if str(decision.get("decision") or "") == "completed":
                plugin._state().mark_completed(path=path, fingerprint=fingerprint)
                return "completed", None
            if _admission_evidence_changed(existing_block, decision):
                _clear_blocked_path(plugin, path)
                existing_block = {}
            else:
                action = str(decision.get("action") or "")
                task_id = str(decision.get("transfer_task_id") or "")
                if action == _PASS_FAILED and task_id:
                    return _request_durable_retry(
                        plugin,
                        member=member,
                        path=path,
                        fingerprint=fingerprint,
                        decision=decision,
                    )
                _persist_admission_block(
                    plugin,
                    path=path,
                    fingerprint=fingerprint,
                    reason=str(existing_block.get("reason") or "MoviePilot 持久准入冲突"),
                    decision=decision,
                )
                return "blocked", None

        phase, row = previous_prepare(plugin, member)
        if phase != "ready" or not row:
            return phase, row

        # previous_prepare 已完成插件稳定性/完成态/历史 gate。只在最终 ready 时再读取一次
        # history 的 durable 身份；失败历史很少见，额外一次只读查询换取清晰的任务边界。
        decision = dict(plugin._v360_history_decision(member, path) or {})
        action = str(decision.get("action") or "")
        task_id = str(decision.get("transfer_task_id") or "")
        history_status = decision.get("history_status")

        if action == _PASS_FAILED and task_id and history_status is False:
            return _request_durable_retry(
                plugin,
                member=member,
                path=path,
                fingerprint=fingerprint,
                decision=decision,
            )

        if action == _PASS_FAILED_VERSION_CHANGED and task_id and history_status is False:
            reason = (
                "MoviePilot durable 失败任务仍绑定旧 planning，但当前源文件版本已变化；"
                "为避免复用旧冻结计划或产生不同输入准入冲突，请先在 MoviePilot 放弃/删除该失败任务后重新规划"
            )
            _persist_admission_block(
                plugin,
                path=path,
                fingerprint=fingerprint,
                reason=reason,
                decision=decision,
            )
            logger.warning(
                "【光鸭云盘助手】【v3.6.11】【durable版本变化】已阻止旧计划复用: %s task_id=%s",
                path,
                task_id,
            )
            return "blocked", None

        # legacy 失败历史没有 transfer_task_id，继续保留 MoviePilot 原有重新规划兼容行为。
        return phase, row

    def fallback_terminal(plugin: Any, item: Any, success: bool, message: str) -> None:
        if success or not _is_admission_conflict(message):
            return previous_fallback(plugin, item, success=success, message=message)

        store = plugin._state()
        blocked = 0
        for member in plugin._v360_members(item):
            try:
                path, fingerprint = plugin._v360_member_identity(member)
            except Exception:
                continue
            raw = store.load()
            if path not in dict(raw.get("inflight") or {}):
                continue
            decision = dict(plugin._v360_history_decision(member, path) or {})
            _persist_admission_block(
                plugin,
                path=path,
                fingerprint=fingerprint,
                reason=f"MoviePilot 持久准入冲突：{message}",
                decision=decision,
            )
            blocked += 1

        if blocked:
            plugin._save_monitor_status(
                admission_conflict_blocked=blocked,
                admission_conflict_message=str(message or ""),
                admission_conflict_at=time.time(),
                admission_conflict_persistent=True,
            )
            logger.warning(
                "【光鸭云盘助手】【v3.6.11】【准入冲突】%s 个成员已持久 blocked；"
                "不再按 10 分钟自动重撞，后续只在 MoviePilot durable 证据或文件版本变化后重新评估: %s",
                blocked,
                message,
            )
        return None

    GuangYaOrganizerEngineV360Mixin._v360_prepare_member = prepare_member
    GuangYaOrganizerMonitorV366Mixin._fallback_terminal_state = fallback_terminal
    setattr(GuangYaOrganizerEngineV360Mixin, _PATCH_FLAG, True)
    logger.info(
        "【光鸭云盘助手】【v3.6.11】MoviePilot durable retry bridge 已启用：失败历史复用原 task，准入冲突不再定时重撞"
    )


__all__ = ["install_durable_retry_v3611"]
