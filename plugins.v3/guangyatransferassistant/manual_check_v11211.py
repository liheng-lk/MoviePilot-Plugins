"""v1.12.11 人工 /gycheck 完整资源链。

历史 /gycheck 只把“消息立即检查”放进可靠后台队列；最终调度层没有给这个 trigger
分配主动 Pull 模式，因此会落回通用后台检查。实机表现为先看到“频道命中 0 条”，
而观影/Xunlei/Magnet 仍可能受自动检索冷却或旧来源模式影响，看起来像没有执行。

本层把 /gycheck 收口为真正的人工检查：
1. 强制刷新一次频道并先消费频道资源；
2. 重新计算真实剩余缺口/电影待处理事实；
3. 仅对仍未覆盖的订阅以 force=True 进入完整来源链；
4. 完整链继续复用既有优先级和安全门禁，不重写下载/秒传业务。

人工 force 只绕过“自动外部检索冷却”，不会绕过媒体身份、年份、质量、Episode Fence、
reservation/source claim、迅雷跨季物理资源栅栏等安全边界。
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List


class GuangYaManualCheckV11211Mixin:
    """把 /gycheck 显式转换成频道优先、剩余缺口强制完整来源链。"""

    plugin_version = "1.12.11"
    build_id = "20260905-r57"

    @staticmethod
    def _manual_full_chain_trigger_v11211(trigger: str) -> bool:
        text = str(trigger or "").strip()
        return "消息立即检查" in text

    def _manual_remaining_ids_v11211(self, ids: Iterable[int]) -> List[int]:
        remaining: List[int] = []
        for raw in ids or []:
            try:
                sid = int(raw or 0)
            except (TypeError, ValueError):
                continue
            if sid <= 0:
                continue
            subscribe = self._find_subscription(sid)
            if not subscribe or not self._is_guangya_route(subscribe):
                continue
            try:
                if self._is_movie_subscription(subscribe):
                    if bool(self._movie_needs_pull_v1125(subscribe)):
                        remaining.append(sid)
                    continue
                if bool(self._uncovered_missing_v1125(subscribe)):
                    remaining.append(sid)
            except Exception:
                # 人工检查遇到旧数据/诊断异常时宁可继续完整链，也不能再次退化成“频道 0 条就停”。
                remaining.append(sid)
        return sorted(set(remaining))

    def _run_dispatch_trigger_v1125(self, ids: List[int], trigger: str) -> None:
        if not self._manual_full_chain_trigger_v11211(trigger):
            return super()._run_dispatch_trigger_v1125(ids, trigger)

        normalizer = getattr(self, "_positive_ids_v1125", None)
        if callable(normalizer):
            batch = sorted(normalizer(ids or []))
        else:
            batch = sorted({int(value) for value in (ids or []) if str(value).isdigit() and int(value) > 0})
        if not batch:
            return None

        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【人工完整检查v1.12.11】收到 /gycheck：%s 个订阅先强刷频道，再对剩余缺口立即执行完整来源链",
            len(batch),
        )
        try:
            self.refresh_channels(force=True)
        except Exception as err:
            self._plugin_log(
                "WARNING",
                "【光鸭转存助手】【人工完整检查v1.12.11】频道强刷失败，继续使用缓存并执行外部完整链：%s",
                str(err)[:260],
            )

        # 第一阶段只消费频道，明确禁止借频道阶段访问 GYING。
        self._run_v1115_mode_batch(
            batch,
            "人工立即检查·频道阶段",
            "channel_event",
            force=False,
        )

        remaining = self._manual_remaining_ids_v11211(batch)
        if not remaining:
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【人工完整检查v1.12.11】频道阶段已覆盖目标，本次 /gycheck 不再访问外部资源站",
            )
            return None

        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【人工完整检查v1.12.11】频道后仍有 %s 个订阅待处理；立即执行 观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K",
            len(remaining),
        )
        # 复用 active pull 模式以禁止下层重复刷新频道；force=True 只绕过自动检索冷却。
        self._run_v1115_mode_batch(
            remaining,
            "人工立即检查·完整资源链",
            "airing_pull",
            force=True,
        )
        try:
            self._record_route_health(
                last_manual_full_check_at=self._now_text(),
                last_manual_full_check_ids=list(remaining),
            )
        except Exception:
            pass
        return None

    def _handle_check_existing_command(self, event_data: Dict[str, Any]) -> None:
        subscribe = self._command_subscription_or_reply(event_data, selected_only=True)
        if not subscribe:
            return
        sid = int(getattr(subscribe, "id", 0) or 0)
        self._queue_async_route_check([sid], trigger="消息立即检查·完整资源链")
        diagnosis = dict(self._diagnose_subscription(subscribe) or {})
        self._post_command(
            event_data,
            "🔎 已进入人工完整资源检查",
            (
                f"#{sid} {getattr(subscribe, 'name', '')} ({getattr(subscribe, 'year', '') or '-'})\n"
                "流程：频道强刷/缓存 → 观影迅雷秒传 → 光鸭直接转存 → Magnet → ED2K\n"
                "人工检查会绕过自动外部检索冷却，但仍保留媒体身份、年份、质量和跨来源安全门禁。\n"
                f"当前频道命中：{int(diagnosis.get('matches') or 0)} 条；频道为 0 不会停止后续观影检索。\n"
                f"待落盘：{int(diagnosis.get('pending_jobs') or 0)} · 失败任务：{int(diagnosis.get('failed_jobs') or 0)}\n"
                f"稍后可发送 /gywhy {sid} 查看最终原因。"
            ),
        )


__all__ = ["GuangYaManualCheckV11211Mixin"]
