"""自动整理对 MoviePilot 整理历史的只读预检适配。

``TransferDispatcher.handle_file()`` 返回 False 并不只表示“失败”：它也可能表示已有
成功历史、失败重试预算耗尽、TTL 去重或暂时性历史查询故障。插件不能重新发明一套
去重规则，因此优先复用 MoviePilot 自己的 history gate。

历史预检是增强能力，不应成为插件安装/加载的硬依赖。不同 MoviePilot V3 小版本中
history helper 的模块位置和公开程度可能不同，因此这里采用运行时惰性探测：宿主未
暴露该 API 时直接把历史门控交回 TransferDispatcher，而不是在 import 阶段让整个插件
无法安装。

v3.6.11 起在不改变 MoviePilot history gate 判定的前提下，同时投影 durable 整理任务身份。
失败历史如果绑定 ``transfer_task_id``，调度器必须复用 MoviePilot 自身 durable retry，
禁止重新构造另一份 planning_input 再次 admit 同一源文件。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple


def _load_history_api() -> Optional[Tuple[Any, Any, Any, Any, Any, Any]]:
    """惰性加载当前 MoviePilot history gate；不把内部模块变成安装期硬依赖。"""
    try:
        from app.application.history import (
            HistoryGateAction,
            describe_history_gate,
            evaluate_history_gate,
            get_transfer_history_port,
            resolve_history,
        )
    except (ImportError, AttributeError):
        return None
    return (
        HistoryGateAction,
        describe_history_gate,
        evaluate_history_gate,
        get_transfer_history_port,
        resolve_history,
        True,
    )


def _history_identity(history: Any) -> Dict[str, Any]:
    """只投影宿主公开历史快照中的稳定身份，不泄漏 ORM/仓储对象。"""
    if history is None:
        return {
            "history_id": 0,
            "history_status": None,
            "transfer_task_id": "",
            "transfer_settlement_revision": 0,
        }
    try:
        history_id = int(getattr(history, "id", 0) or 0)
    except (TypeError, ValueError):
        history_id = 0
    try:
        settlement_revision = int(
            getattr(history, "transfer_settlement_revision", 0) or 0
        )
    except (TypeError, ValueError):
        settlement_revision = 0
    return {
        "history_id": history_id,
        "history_status": bool(getattr(history, "status", False)),
        "transfer_task_id": str(getattr(history, "transfer_task_id", "") or ""),
        "transfer_settlement_revision": settlement_revision,
    }


def inspect_moviepilot_history(
    *,
    storage: str,
    path: Path,
    file_size: Any = None,
    file_modify_time: Any = None,
    fileid: Any = None,
) -> Dict[str, Any]:
    """返回 ``submit/completed/blocked/unknown`` 四态预检结果。

    - 宿主支持当前 history gate：完全复用 MoviePilot 的判定。
    - 宿主未公开该 helper：返回 ``submit``，让 TransferDispatcher 自己做原生历史门控。
    - helper 存在但数据库/历史端口临时异常：返回 ``unknown``，保守等待重试。
    - 返回值额外携带 ``history_id/transfer_task_id`` 等只读稳定身份；它们只用于选择
      “复用 durable task”还是“新建 planning”，绝不改变 MoviePilot 的媒体业务判定。
    """
    api = _load_history_api()
    if not api:
        return {
            "decision": "submit",
            "action": "delegate_to_dispatcher",
            "message": "当前 MoviePilot 未暴露 history gate 预检 API，已交由原生 TransferDispatcher 进行历史门控",
            **_history_identity(None),
        }

    (
        HistoryGateAction,
        describe_history_gate,
        evaluate_history_gate,
        get_transfer_history_port,
        resolve_history,
        _,
    ) = api

    src_path = Path(path).as_posix()
    try:
        history = resolve_history(
            src_path,
            storage=storage,
            transfer_history_oper=get_transfer_history_port(),
        )
        action = evaluate_history_gate(
            history,
            file_size=file_size,
            file_modify_time=file_modify_time,
            fileid=fileid,
        )
        description = describe_history_gate(
            history,
            file_size=file_size,
            file_modify_time=file_modify_time,
            fileid=fileid,
        )
    except Exception as err:  # 历史存储/数据库瞬时故障必须保守重试
        return {
            "decision": "unknown",
            "action": "history_unavailable",
            "message": f"MoviePilot 整理历史暂不可用：{err}",
            **_history_identity(None),
        }

    identity = _history_identity(history)
    if action == HistoryGateAction.SKIP:
        return {
            "decision": "completed",
            "action": action,
            "message": f"MoviePilot 已有有效成功历史：{description}",
            **identity,
        }
    if action == HistoryGateAction.SKIP_RETRY_EXHAUSTED:
        return {
            "decision": "blocked",
            "action": action,
            "message": f"MoviePilot 失败重试预算已用尽：{description}",
            **identity,
        }
    return {
        "decision": "submit",
        "action": action,
        "message": description,
        **identity,
    }


__all__ = ["inspect_moviepilot_history"]
