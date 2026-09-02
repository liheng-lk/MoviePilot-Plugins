"""v1.10.13 观影执行完整日志与剩余缺集收口层。

迅雷秒传现在严格分成两阶段：
- 迅雷分享生成与稳定脚本兼容的 JSON 模板；
- 光鸭按 importMd5Json 的纯秒传子集消费该 JSON。
完整性层继续负责 fileSize 校验与异常占位清理。
"""

from __future__ import annotations

from typing import Any, Dict

from .viewing_dispatch_v1113 import GuangYaViewingDispatchV1113Mixin
from .xunlei_json_pipeline_v1117 import GuangYaXunleiJsonPipelineV1117Mixin
from .xunlei_integrity_v1116 import GuangYaXunleiIntegrityV1116Mixin


class GuangYaViewingLoggingV1113Mixin(
    GuangYaViewingDispatchV1113Mixin,
    GuangYaXunleiJsonPipelineV1117Mixin,
    GuangYaXunleiIntegrityV1116Mixin,
):
    """记录完整 cloudcollection 生命周期，并防止部分成功提前截断观影回退。"""

    build_id = "20260902-r30"

    def _submit_offline_source(self, source_id: str) -> Dict[str, Any]:
        source_id = str(source_id or "").strip()
        source = dict((self._source_store().get("items") or {}).get(source_id) or {})
        viewing = str(source.get("origin") or "").startswith("viewing")
        if viewing:
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【原生云添加】观影来源开始：source=%s type=%s state=%s subscribe=%s target=%s 搜索标题=%s 资源名=%s",
                source_id or "-",
                str(source.get("type") or "-").upper(),
                str(source.get("state") or "new"),
                int(source.get("subscribe_id") or 0),
                ",".join(str(v) for v in (source.get("target_episodes") or [])) or "movie/auto",
                str(source.get("search_title") or "-")[:180],
                str(source.get("search_resource_name") or source.get("name") or "-")[:220],
            )
        result = dict(super()._submit_offline_source(source_id) or {})
        if viewing:
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            self._plugin_log(
                "INFO" if bool(result.get("success")) else "WARNING",
                "【光鸭转存助手】【原生云添加】观影来源结果：source=%s success=%s state=%s task=%s progress=%s name=%s 信息=%s",
                source_id or "-",
                bool(result.get("success")),
                str(data.get("state") or source.get("state") or "-"),
                str(data.get("task_id") or source.get("task_id") or "-")[:90],
                int(data.get("progress") or 0),
                str(data.get("requested_name") or data.get("resolved_name") or source.get("requested_name") or "-")[:220],
                str(result.get("message") or data.get("last_error") or "-")[:360],
            )
        return result

    def _poll_offline_source(self, source: Dict[str, Any]) -> Dict[str, Any]:
        viewing = str(source.get("origin") or "").startswith("viewing")
        if viewing:
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【原生云添加】观影任务轮询：source=%s task=%s state=%s progress=%s",
                str(source.get("id") or "-")[:40],
                str(source.get("task_id") or "-")[:90],
                str(source.get("state") or "-"),
                int(source.get("progress") or 0),
            )
        result = dict(super()._poll_offline_source(source) or {})
        if viewing:
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            self._plugin_log(
                "INFO" if bool(result.get("success")) else "WARNING",
                "【光鸭转存助手】【原生云添加】观影任务轮询结果：source=%s task=%s state=%s progress=%s fileId=%s name=%s 信息=%s",
                str(source.get("id") or "-")[:40],
                str(data.get("task_id") or source.get("task_id") or "-")[:90],
                str(data.get("state") or "-"),
                int(data.get("progress") or 0),
                str(data.get("file_id") or "-")[:90],
                str(data.get("resolved_name") or data.get("requested_name") or "-")[:220],
                str(result.get("message") or data.get("last_error") or "-")[:360],
            )
        return result

    def _viewing_gap_v1113(self, subscribe: Any) -> Dict[str, Any]:
        if self._is_movie_subscription(subscribe):
            reservations = dict(self._pending_reservations(subscribe) or {})
            active_movie = any(
                isinstance(row, dict)
                and int(row.get("subscribe_id") or 0) == int(getattr(subscribe, "id", 0) or 0)
                and str(row.get("state") or "") in {"new", "retry", "dispatching", "submitted", "queued", "waiting", "completed"}
                for row in (self._source_store().get("items") or {}).values()
            )
            return {
                "covered": bool(reservations.get("movie")) or active_movie,
                "missing": [],
                "reserved": [],
                "claimed": [],
                "uncovered": [],
            }

        missing = set(int(v) for v in (self._subscription_missing_episodes(subscribe) or []) if int(v or 0) > 0)
        reservations = dict(self._pending_reservations(subscribe) or {})
        reserved = set(int(v) for v in (reservations.get("episodes") or set()) if int(v or 0) > 0)
        claimed = set(int(v) for v in (self._active_source_claims(int(getattr(subscribe, "id", 0) or 0)) or set()) if int(v or 0) > 0)
        uncovered = missing - reserved - claimed
        return {
            "covered": not uncovered,
            "missing": sorted(missing),
            "reserved": sorted(reserved),
            "claimed": sorted(claimed),
            "uncovered": sorted(uncovered),
        }

    def _try_transfer_subscription_inner(
        self,
        subscribe: Any,
        force: bool = False,
        refresh_channel: bool = True,
    ) -> Dict[str, Any]:
        result = dict(super()._try_transfer_subscription_inner(
            subscribe,
            force=force,
            refresh_channel=refresh_channel,
        ) or {})

        existing_viewing = result.get("viewing_external") if isinstance(result.get("viewing_external"), dict) else {}
        if existing_viewing:
            return result

        # handled 是前序链的最终覆盖合同。电影没有 episode 集合，不能再用
        # uncovered=movie 覆盖掉这个强确认，否则会在迅雷成功后错误创建 Magnet。
        if bool(result.get("handled")):
            sid = int(getattr(subscribe, "id", 0) or 0)
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【观影执行】#%s 前序结果 handled=True，硬阻断观影 Magnet/ED2K；信息=%s",
                sid,
                str(result.get("message") or "前序来源已完整覆盖")[:260],
            )
            return result

        gap = self._viewing_gap_v1113(subscribe)
        sid = int(getattr(subscribe, "id", 0) or 0)
        if bool(gap.get("covered")):
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【观影执行】#%s 前序来源已覆盖当前目标，停止继续建云添加任务；missing=%s reserved=%s claimed=%s",
                sid,
                ",".join(str(v) for v in (gap.get("missing") or [])) or "-",
                ",".join(str(v) for v in (gap.get("reserved") or [])) or "-",
                ",".join(str(v) for v in (gap.get("claimed") or [])) or "-",
            )
            return result

        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【观影执行】#%s 前序链未完整覆盖，继续观影 Magnet/ED2K；uncovered=%s 前序success=%s handled=%s 信息=%s",
            sid,
            ",".join(str(v) for v in (gap.get("uncovered") or [])) or "movie",
            bool(result.get("success")),
            bool(result.get("handled")),
            str(result.get("message") or "-")[:260],
        )
        try:
            viewing = dict(self._dispatch_viewing_external_v1113(subscribe) or {})
        except Exception as err:
            self._plugin_log(
                "WARNING",
                "【光鸭转存助手】【观影执行】#%s 剩余目标自动云添加规划异常：%s",
                sid,
                str(err)[:360],
            )
            viewing = {"success": False, "actions": [], "message": str(err)}
        if viewing.get("actions"):
            return {
                **result,
                "success": True,
                "handled": True,
                "viewing_external": viewing,
                "message": f"{str(result.get('message') or '前序来源已检查')}；{viewing.get('message')}",
            }
        return {**result, "viewing_external": viewing}


__all__ = ["GuangYaViewingLoggingV1113Mixin"]
