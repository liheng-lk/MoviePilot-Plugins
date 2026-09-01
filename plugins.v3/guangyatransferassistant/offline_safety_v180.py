"""v1.8.0 光鸭原生云添加安全收口。

该层只修正任务恢复和对外展示，不改变 multisource_v180 的业务入口：
- 有 taskId 的 queued/submitted/waiting 永远轮询，不重复 create_task；
- 已提交任务的临时轮询网络错误不会把任务误判为永久失败；
- 来源列表不返回 Magnet tracker 等原始 URI，避免把可能含私有参数的链接暴露到状态接口。
"""

from __future__ import annotations

from typing import Any, Dict

from .source_types_v180 import SOURCE_INFLIGHT_STATES


class GuangYaOfflineSafetyMixin:
    """必须放在 GuangYaMultiSourceMixin 之前。"""

    def _submit_offline_source(self, source_id: str) -> Dict[str, Any]:
        source = dict(self._source_store()["items"].get(str(source_id or "")) or {})
        task_id = str(source.get("task_id") or "").strip()
        state = str(source.get("state") or "new")
        if task_id:
            if state == "completed":
                return {"success": True, "message": "来源已完成", "data": source}
            if state in {"retry", "failed"}:
                return self._retry_offline_task(source)
            # 只要服务端任务已经存在，不论旧版本落下什么中间 state，都只能查询既有任务。
            return self._poll_offline_source(source)
        return super()._submit_offline_source(source_id)

    def _poll_offline_source(self, source: Dict[str, Any]) -> Dict[str, Any]:
        before_attempts = int(source.get("attempts") or 0)
        result = super()._poll_offline_source(source)
        data = result.get("data") if isinstance(result, dict) else None
        if not isinstance(data, dict):
            return result

        # status=5 是光鸭明确返回的部分完成/失败，允许进入 retry/failed。
        # 其它失败若已有 taskId，则属于“查询暂不可用”，必须保留任务等待下轮，不得重新提交。
        if (
            str(source.get("task_id") or "").strip()
            and not bool(result.get("success"))
            and int(data.get("task_status") if data.get("task_status") is not None else -1) != 5
        ):
            updated = self._update_source(
                str(source.get("id") or ""),
                state="waiting",
                attempts=before_attempts,
                next_retry_at=0,
                last_error=str(result.get("message") or data.get("last_error") or "任务状态查询暂不可用")[:500],
            ) or data
            return {
                "success": False,
                "message": str(result.get("message") or "任务状态查询暂不可用，已保留 taskId 等待恢复"),
                "data": updated,
            }
        return result

    @staticmethod
    def _source_public_view(source: Dict[str, Any]) -> Dict[str, Any]:
        row = dict(source or {})
        raw_uri = str(row.pop("uri", "") or "")
        source_type = str(row.get("type") or "")
        identity = str(row.get("identity") or "")
        name = str(row.get("name") or row.get("resolved_name") or "")[:120]
        size = int(row.get("size") or 0)
        if source_type == "magnet":
            row["uri_preview"] = f"magnet:?xt=urn:btih:{identity}"
        elif source_type == "ed2k":
            row["uri_preview"] = f"ed2k://|file|{name}|{size}|{identity}|/"
        else:
            row["uri_preview"] = raw_uri[:120]
        return row

    def api_source_list(self, subscribe_id: int = 0) -> Dict[str, Any]:
        sid = int(subscribe_id or 0)
        rows = []
        for source in self._source_store()["items"].values():
            if not isinstance(source, dict):
                continue
            if sid and int(source.get("subscribe_id") or 0) != sid:
                continue
            rows.append(self._source_public_view(source))
        rows.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
        return {"success": True, "count": len(rows), "data": rows[:100]}


__all__ = ["GuangYaOfflineSafetyMixin"]
