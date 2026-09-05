"""v3.5.5：目录预览缺员时局部补预览，避免剧集粘性事务永久空转。

问题背景：
MoviePilot 对完整 Season 目录执行 preview 时，个别源文件可能不会出现在预览 items 中。
v3.4.9/v3.5.3 的零损失保护会因此整组返回失败；v3.5.2 的 TV 粘性又会把该 Season
保持为当前事务，失败成员进入 retry 后其它资源全部 capacity_wait，最终形成“worker 已空闲，
但一直扫描且不再提交”的假死。

本层不放宽安全边界，也不自行计算媒体目标：
1. 只有完整目录预览因“源文件未进入 MoviePilot 预览”失败时才介入；
2. 对当前 Season 的每个仍待处理成员，继续携带同一 MoviePilot 目录识别上下文逐文件 preview；
3. 逐文件 preview 得到唯一非空目标的成员才执行真实整理；
4. 逐文件仍无法 preview、目标为空或多个源撞同一目标的成员单独 blocked，源文件保持原位；
5. 其它安全成员继续整理，避免一个坏成员拖死整季及后续资源；
6. 最终 completed 仍只由 MoviePilot 最终事件/历史证据确认，沿用 v3.5.4 完成态证据边界。
"""

from __future__ import annotations

import time
from collections import defaultdict
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

from app.sdk.logging import logger

from . import organizer_conflict_resolution_v353 as _conflict
from . import organizer_loss_guard_v349 as _loss_guard
from .organizer_folder_batch_v342 import _FolderBatchEnvelope
from .organizer_policy import (
    FileDisposition,
    decide_failed_execution,
    should_probe_source_presence,
)
from .organizer_source_terminal_v3618 import (
    probe_source_presence_v3618,
    retire_missing_source_v3618,
)


_MISSING_PREVIEW_TOKEN = "源文件未进入 MoviePilot 预览"


def _norm(plugin: Any, value: Any) -> str:
    try:
        return plugin._organize_normalize_path(str(value or ""))
    except Exception:
        return str(value or "").replace("\\", "/").rstrip("/")


def _still_inflight_paths(plugin: Any) -> set[str]:
    try:
        raw = plugin._state().load()
    except Exception:
        return set()
    return {_norm(plugin, path) for path in dict(raw.get("inflight") or {})}


def _preview_one(
    plugin: Any,
    transfer_chain: Any,
    base_kwargs: Dict[str, Any],
    member: Any,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """只使用 MoviePilot 自身 preview，返回当前源对应的预览行。"""
    source = _norm(plugin, getattr(member, "path", ""))
    kwargs = dict(base_kwargs)
    kwargs["fileitem"] = member
    kwargs["preview"] = True
    try:
        result = transfer_chain.do_transfer(**kwargs)
    except Exception as err:  # noqa: BLE001
        return None, f"逐文件 MoviePilot 预览异常：{err}"

    ok, payload, error = _loss_guard._preview_result(result)
    if not ok or not isinstance(payload, dict):
        return None, error or "逐文件 MoviePilot 预览失败"

    for raw in payload.get("items") or []:
        if not isinstance(raw, dict):
            continue
        if _norm(plugin, raw.get("source")) != source:
            continue
        if not bool(raw.get("success")):
            return None, str(raw.get("message") or "逐文件 MoviePilot 预览失败")
        target = _norm(plugin, raw.get("target"))
        if not target:
            return None, "逐文件 MoviePilot 预览没有目标路径"
        row = dict(raw)
        row["source"] = source
        row["target"] = target
        return row, ""

    return None, "逐文件 MoviePilot 预览仍未返回当前源文件"


def _block_member(plugin: Any, member: Any, reason: str, *, result: str) -> None:
    _conflict._mark_blocked(plugin, member, reason, result=result)
    logger.warning(
        "【光鸭云盘助手】【预览局部隔离】源文件保持原位: %s - %s",
        _norm(plugin, getattr(member, "path", "")),
        reason,
    )


def _rescue_partial_preview(plugin: Any, item: _FolderBatchEnvelope) -> Tuple[bool, str]:
    transfer_chain, _directory_item, base_kwargs, plan_error = _loss_guard._build_moviepilot_kwargs(plugin, item)
    if plan_error:
        return False, plan_error

    inflight_before = _still_inflight_paths(plugin)
    members: Dict[str, Any] = {
        _norm(plugin, getattr(member, "path", "")): member
        for member in list(getattr(item, "members", None) or [])
        if getattr(member, "path", None)
    }
    candidates = {
        path: member for path, member in members.items()
        if path in inflight_before
    }
    if not candidates:
        return True, "目录预览缺员，但成员终态已由 MoviePilot 收敛"

    rows: Dict[str, Dict[str, Any]] = {}
    errors: Dict[str, str] = {}
    for path, member in candidates.items():
        row, error = _preview_one(plugin, transfer_chain, base_kwargs, member)
        if row:
            rows[path] = row
        else:
            errors[path] = error or "MoviePilot 无法为当前源生成可审计预览"

    # 逐文件失败也统一交给 v3.7 policy：明确未识别原地停放；明确消失退休；
    # 网络/API等暂时失败保留 inflight，外层完成态会把它送回 retry；其它安全冲突才 blocked。
    unrecognized = missing_sources = transient_errors = blocked_errors = 0
    for path, reason in errors.items():
        member = candidates[path]
        if should_probe_source_presence(reason):
            presence = probe_source_presence_v3618(plugin, member)
            disposition = decide_failed_execution(reason, presence)
        else:
            disposition = FileDisposition.RETRY_TRANSIENT
        if disposition == FileDisposition.LEAVE_UNRECOGNIZED:
            fingerprint = plugin._fingerprint(member)
            if plugin._state().mark_non_actionable(path=path, fingerprint=fingerprint):
                plugin._append_monitor_history({
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "path": path,
                    "name": str(getattr(member, "name", "") or PurePosixPath(path).name),
                    "size": int(getattr(member, "size", 0) or 0),
                    "result": "unrecognized_untouched",
                    "group_path": item.path,
                    "group_name": item.name,
                    "message": f"逐文件 MoviePilot 识别/预览无法形成可靠目标，源原地保留：{reason}",
                })
            unrecognized += 1
            continue
        if disposition == FileDisposition.RETIRE_MISSING:
            retire_missing_source_v3618(plugin, member)
            missing_sources += 1
            continue
        if disposition == FileDisposition.RETRY_TRANSIENT:
            transient_errors += 1
            continue
        blocked_errors += 1
        _block_member(
            plugin,
            member,
            f"完整目录预览缺员，逐文件补预览仍无法确认：{reason}",
            result="preview_member_isolated",
        )

    # 即使逐文件预览都成功，也再次核对目标唯一性。目标冲突成员保持原位，其它成员继续。
    by_target: Dict[str, List[str]] = defaultdict(list)
    for source, row in rows.items():
        target = _norm(plugin, row.get("target"))
        if target:
            by_target[target].append(source)

    collisions = {
        target: sorted(set(sources))
        for target, sources in by_target.items()
        if len(set(sources)) > 1
    }
    collision_sources: set[str] = set()
    for target, sources in collisions.items():
        names = ", ".join(PurePosixPath(source).name for source in sources)
        reason = f"逐文件补预览发现重复目标，安全隔离本冲突组：{names} -> {target}"
        for source in sources:
            collision_sources.add(source)
            _block_member(
                plugin,
                candidates[source],
                reason,
                result="preview_target_conflict_isolated",
            )

    attempted = 0
    call_failed = 0
    for source, member in sorted(candidates.items()):
        if source in errors or source in collision_sources:
            continue
        if source not in rows:
            continue
        attempted += 1
        success, message = _conflict._execute_member(
            plugin,
            transfer_chain,
            base_kwargs,
            member,
            None,
        )
        if not success:
            call_failed += 1
            logger.warning(
                "【光鸭云盘助手】【预览局部补救】安全成员整理调用失败，交由完成态证据层重试: %s - %s",
                source,
                message,
            )

    plugin._append_monitor_history({
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "path": item.path,
        "name": item.name,
        "size": item.size,
        "result": "partial_preview_rescued",
        "group_path": item.path,
        "group_name": item.name,
        "batch_id": item.batch_id,
        "message": (
            f"目录预览缺员已局部处理：逐文件确认={len(rows)}，实际整理={attempted}，"
            f"调用失败={call_failed}，未识别保留={unrecognized}，源消失={missing_sources}，"
            f"暂时失败={transient_errors}，安全阻断={blocked_errors + len(collision_sources)}"
        ),
    })
    logger.warning(
        "【光鸭云盘助手】【整理策略】【预览局部补救】%s：逐文件确认=%s，实际整理=%s，"
        "调用失败=%s，未识别保留=%s，暂时失败=%s，安全阻断=%s；不再因单个缺员拖死整个资源",
        item.path,
        len(rows),
        attempted,
        call_failed,
        unrecognized,
        transient_errors,
        blocked_errors + len(collision_sources),
    )

    # 返回 True 只表示该批已被安全拆分处理。成员是否完成仍由 MP 最终事件/历史证据决定。
    return True, (
        f"目录预览缺员局部处理完成：整理 {attempted}，调用失败 {call_failed}，"
        f"未识别保留 {unrecognized}，暂时失败 {transient_errors}，安全阻断 {blocked_errors + len(collision_sources)}"
    )


def rescue_partial_preview_if_needed(
    plugin: Any,
    item: Any,
    result: Tuple[bool, str],
) -> Tuple[bool, str]:
    """Rescue only the historical MoviePilot folder-preview missing-member failure."""
    if not isinstance(item, _FolderBatchEnvelope):
        return result
    try:
        success, message = result
    except Exception:
        return result
    if success or _MISSING_PREVIEW_TOKEN not in str(message or ""):
        return result
    logger.warning(
        "【光鸭云盘助手】【整理策略】【预览局部补救】完整目录预览存在缺员，"
        "切换为同一 MoviePilot 上下文逐文件补预览: %s",
        item.path,
    )
    try:
        return _rescue_partial_preview(plugin, item)
    except Exception as err:  # noqa: BLE001
        logger.exception(
            "【光鸭云盘助手】【整理策略】【预览局部补救】执行异常，保持原失败语义: %s - %s",
            item.path,
            err,
        )
        return result


__all__ = ["rescue_partial_preview_if_needed", "_rescue_partial_preview"]
