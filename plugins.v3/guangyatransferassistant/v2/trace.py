"""决策轨迹：每条订阅处理写可解释阶段与拒绝码。"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional


TRACE_DATA_KEY = "decision_traces"
TRACE_LIMIT = 200


def _now_text() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class DecisionTraceStore:
    def __init__(self, plugin: Any):
        self.plugin = plugin

    def _load(self) -> Dict[str, Any]:
        raw = self.plugin.get_data(TRACE_DATA_KEY) or {}
        if not isinstance(raw, dict):
            return {"items": [], "updated_at": ""}
        items = raw.get("items")
        if not isinstance(items, list):
            items = []
        return {"items": items, "updated_at": str(raw.get("updated_at") or "")}

    def _save(self, payload: Dict[str, Any]) -> None:
        self.plugin.save_data(TRACE_DATA_KEY, payload)

    def append(
        self,
        *,
        subscribe_id: int,
        title: str,
        stage: str,
        decision: str,
        reason_code: str = "",
        message: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        row = {
            "time": _now_text(),
            "subscribe_id": int(subscribe_id or 0),
            "title": str(title or "")[:200],
            "stage": str(stage or "")[:80],
            "decision": str(decision or "")[:40],
            "reason_code": str(reason_code or "")[:80],
            "message": str(message or "")[:500],
            "details": dict(details or {}),
        }
        store = self._load()
        items: List[Dict[str, Any]] = list(store.get("items") or [])
        items.insert(0, row)
        store["items"] = items[:TRACE_LIMIT]
        store["updated_at"] = row["time"]
        self._save(store)
        return row

    def recent(self, *, limit: int = 50, subscribe_id: int = 0) -> List[Dict[str, Any]]:
        items = list(self._load().get("items") or [])
        if subscribe_id:
            items = [row for row in items if int(row.get("subscribe_id") or 0) == int(subscribe_id)]
        return items[: max(1, int(limit or 50))]

    def rejected_hits(self, *, limit: int = 30) -> List[Dict[str, Any]]:
        rows = []
        for row in self._load().get("items") or []:
            if str(row.get("decision") or "").lower() != "reject":
                continue
            rows.append(row)
            if len(rows) >= limit:
                break
        return rows
