"""自动整理对 MoviePilot 整理历史的只读预检适配。

``TransferDispatcher.handle_file()`` 返回 False 并不只表示“失败”：它也可能表示已有
成功历史、失败重试预算耗尽、TTL 去重或暂时性历史查询故障。插件不能重新发明一套
去重规则，因此这里只复用 MoviePilot 自己的 history gate，把结果翻译成稳定状态。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from app.application.history import (
    HistoryGateAction,
    describe_history_gate,
    evaluate_history_gate,
    get_transfer_history_port,
    resolve_history,
)


def inspect_moviepilot_history(
    *,
    storage: str,
    path: Path,
    file_size: Any = None,
    file_modify_time: Any = None,
    fileid: Any = None,
) -> Dict[str, Any]:
    """返回 ``submit/completed/blocked/unknown`` 四态预检结果。

    ``completed`` 与 ``blocked`` 都来自 MoviePilot 自己的历史闸语义；``unknown`` 仅表示
    历史端口暂不可用，调用方应稍后重试，绝不能把它当作完成或永久跳过。
    """
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
        }

    if action == HistoryGateAction.SKIP:
        return {
            "decision": "completed",
            "action": action,
            "message": f"MoviePilot 已有有效成功历史：{description}",
        }
    if action == HistoryGateAction.SKIP_RETRY_EXHAUSTED:
        return {
            "decision": "blocked",
            "action": action,
            "message": f"MoviePilot 失败重试预算已用尽：{description}",
        }
    return {
        "decision": "submit",
        "action": action,
        "message": description,
    }


__all__ = ["inspect_moviepilot_history"]
