"""v3.6.17：blocked 只读诊断。

现场 v3.6.16 已确认 pending 公平调度正常，但仍可能存在少量 blocked 成员。
blocked 本身是安全门控，不能为了降低数字盲目清理；本模块只读取 OrganizerStateStore，
把实际成员路径、阻断原因、是否为 v3.6.11 持久 admission block、宿主 history/task 身份
和 recheck 时间投影到状态 API / 启动日志，供后续判定是否应解除。

本模块绝不 mutate/clear/mark 任意 Organizer 状态，也不修改 MoviePilot 业务规则。
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List

from app.sdk.logging import logger


_BLOCKED_DIAG_LIMIT = 12
_SECRET_PATTERNS = (
    re.compile(r"(?i)(access[_-]?token|refresh[_-]?token|authorization)\s*[=:]\s*[^\s,;]+"),
    re.compile(r"(?i)Bearer\s+[A-Za-z0-9._~+\-/=]+"),
)


def _redact_text(value: Any, *, limit: int = 320) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda match: f"{match.group(1)}=<redacted>" if match.lastindex else "Bearer <redacted>", text)
    return text[: max(int(limit or 0), 0)]


def _short_task_id(value: Any) -> str:
    text = str(value or "")
    if len(text) <= 14:
        return text
    return f"{text[:8]}…{text[-4:]}"


def blocked_diagnostics(plugin: Any, *, now: float | None = None, limit: int = _BLOCKED_DIAG_LIMIT) -> Dict[str, Any]:
    """只读返回 blocked 摘要；失败时返回 error，不影响监控主链。"""
    current = float(time.time() if now is None else now)
    try:
        state = dict(plugin._state().load() or {})
        blocked = dict(state.get("blocked") or {})
    except Exception as err:  # noqa: BLE001 - diagnostics must never break runtime
        return {"total": 0, "persistent": 0, "timed": 0, "due": 0, "rows": [], "error": _redact_text(err)}

    rows: List[Dict[str, Any]] = []
    persistent = timed = due = 0
    for raw_path, raw_row in sorted(blocked.items(), key=lambda pair: str(pair[0])):
        row = dict(raw_row or {}) if isinstance(raw_row, dict) else {}
        is_persistent = bool(row.get("v3611_persistent_admission"))
        recheck_at = float(row.get("recheck_at") or 0)
        if is_persistent:
            persistent += 1
        else:
            timed += 1
            if recheck_at <= current:
                due += 1
        if len(rows) >= max(int(limit or 0), 0):
            continue
        rows.append(
            {
                "path": str(raw_path or ""),
                "reason": _redact_text(row.get("reason") or ""),
                "persistent_admission": is_persistent,
                "recheck_at": recheck_at,
                "recheck_due": bool(not is_persistent and recheck_at <= current),
                "history_id": int(row.get("v3611_history_id") or 0),
                "transfer_task_id": _short_task_id(row.get("v3611_transfer_task_id") or ""),
                "settlement_revision": int(row.get("v3611_settlement_revision") or 0),
            }
        )

    return {
        "total": len(blocked),
        "persistent": persistent,
        "timed": timed,
        "due": due,
        "shown": len(rows),
        "truncated": len(blocked) > len(rows),
        "rows": rows,
    }


def log_blocked_diagnostics(plugin: Any) -> Dict[str, Any]:
    """启动时只打印一次 blocked 事实；日志同样只读且做敏感文本遮罩。"""
    data = blocked_diagnostics(plugin)
    total = int(data.get("total") or 0)
    if total <= 0:
        logger.info("【光鸭云盘助手】【v3.6.17】【blocked诊断】当前无 blocked 成员")
        return data

    logger.warning(
        "【光鸭云盘助手】【v3.6.17】【blocked诊断】总数=%s，持久准入=%s，定时复核=%s，已到期=%s，展示=%s%s",
        total,
        int(data.get("persistent") or 0),
        int(data.get("timed") or 0),
        int(data.get("due") or 0),
        int(data.get("shown") or 0),
        "（其余已省略）" if data.get("truncated") else "",
    )
    for row in list(data.get("rows") or []):
        logger.warning(
            "【光鸭云盘助手】【v3.6.17】【blocked成员】path=%s persistent=%s due=%s history=%s task=%s revision=%s reason=%s",
            row.get("path") or "-",
            bool(row.get("persistent_admission")),
            bool(row.get("recheck_due")),
            int(row.get("history_id") or 0),
            row.get("transfer_task_id") or "-",
            int(row.get("settlement_revision") or 0),
            row.get("reason") or "-",
        )
    return data


__all__ = ["blocked_diagnostics", "log_blocked_diagnostics"]
