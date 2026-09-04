"""v1.12.5 人工动作异步语义修复。

页面/消息命令为了避免 HTTP 或消息线程被频道/GYING 网络请求阻塞，会先进入可靠后台队列。
队列化只能改变执行线程，不能改变原动作语义：
- “立即检查缺集”与 /gycheck 仍是人工 force 检查，允许绕过自动检索冷却与更新日门禁，
  但继续经过真实缺集、媒体身份、reservation/source claim、Episode Fence 和质量门禁；
- “复查待落盘”继续调用原有 force=False 复查入口，绝不能被误升级成人工强制重提；
- 页面/消息把已有订阅切到光鸭路线时，语义与新订阅 prime 一致：缓存 miss 时只合并刷新频道一次，
  先消费已经到达的频道 Push，再仅对当前日历允许的缺口做非 force 主动 Pull。

本层只恢复被“同步 API -> 异步队列”转换丢失的调用合同，不实现任何转存/下载业务。
"""
from __future__ import annotations

from typing import Any, Iterable, List


class GuangYaManualDispatchV1125Mixin:
    """最终人工入口边界：异步执行必须保留原 API 的 force/复查/接管语义。"""

    build_id = "20260904-r51-preview"

    _manual_force_triggers_v1125 = {
        "状态页立即检查缺集",
        "消息立即检查",
    }
    _pending_recheck_triggers_v1125 = {
        "状态页复查待落盘",
    }
    _route_activation_triggers_v1125 = {
        "消息切换路线",
        "页面切换光鸭路线",
    }

    @staticmethod
    def _manual_positive_ids_v1125(values: Iterable[Any]) -> List[int]:
        result = set()
        for raw in values or []:
            try:
                value = int(raw or 0)
            except (TypeError, ValueError):
                continue
            if value > 0:
                result.add(value)
        return sorted(result)

    def _run_manual_api_v1125(self, ids: List[int], *, pending_only: bool) -> None:
        """在后台 worker 中调用未包装的真实插件方法，完整保留 legacy API 合同。"""
        for sid in ids:
            if not bool(getattr(self, "_enabled", False)):
                return
            runtime_check = getattr(self, "_runtime_is_current", None)
            if callable(runtime_check) and not runtime_check():
                return
            try:
                if pending_only:
                    result = dict(self.api_recheck_pending(subscribe_id=sid) or {})
                    action = "复查待落盘"
                else:
                    # legacy.api_check_missing 本身包含人工门禁、缓存优先频道补查，最终明确
                    # _try_transfer_subscription(... force=True, refresh_channel=False)。
                    result = dict(self.api_check_missing(subscribe_id=sid) or {})
                    action = "立即检查缺集"
                self._record_route_health(
                    last_manual_async_id=sid,
                    last_manual_async_action=action,
                    last_manual_async_success=bool(result.get("success")),
                    last_manual_async_result=str(result.get("message") or "检查完成")[:500],
                    last_manual_async_at=self._now_text(),
                )
                self._plugin_log(
                    "INFO" if bool(result.get("success")) else "WARNING",
                    "【光鸭转存助手】【人工异步】#%s %s：%s",
                    sid,
                    action,
                    str(result.get("message") or "检查完成")[:360],
                )
            except Exception as err:
                self._plugin_log(
                    "EXCEPTION",
                    "【光鸭转存助手】【人工异步】#%s %s异常：%s",
                    sid,
                    "复查待落盘" if pending_only else "立即检查缺集",
                    err,
                )

    def _run_route_activation_v1125(self, ids: List[int], trigger: str) -> None:
        """已有订阅被人工接管时，复用新订阅的频道优先 + 日历 Pull 策略。"""
        active: List[int] = []
        cache_miss = 0
        for sid in ids:
            subscribe = self._find_subscription(sid)
            if not subscribe or not self._is_guangya_route(subscribe):
                continue
            if str(getattr(subscribe, "state", "") or "") not in {"N", "R"}:
                continue
            active.append(sid)
            try:
                if not self._cached_matches_for_subscription(subscribe):
                    cache_miss += 1
            except Exception:
                cache_miss += 1

        if not active:
            return None
        if cache_miss:
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【人工接管】%s：%s/%s 个订阅频道缓存未命中，合并现查频道一次",
                trigger,
                cache_miss,
                len(active),
            )
            try:
                self.refresh_channels(force=True)
            except Exception as err:
                self._plugin_log(
                    "WARNING",
                    "【光鸭转存助手】【人工接管】频道现查失败，继续使用缓存并按更新日历判断主动 Pull：%s",
                    str(err)[:260],
                )

        # 交回 v1.12.5 FinalPolicy 的唯一新订阅执行语义：channel_event -> smart airing_pull。
        return super()._run_dispatch_trigger_v1125(active, "新订阅资源匹配")

    def _run_dispatch_trigger_v1125(self, ids: List[int], trigger: str) -> None:
        normalized = self._manual_positive_ids_v1125(ids)
        text = str(trigger or "")
        if text in self._manual_force_triggers_v1125:
            return self._run_manual_api_v1125(normalized, pending_only=False)
        if text in self._pending_recheck_triggers_v1125:
            return self._run_manual_api_v1125(normalized, pending_only=True)
        if text in self._route_activation_triggers_v1125:
            return self._run_route_activation_v1125(normalized, text)
        return super()._run_dispatch_trigger_v1125(normalized, trigger)


__all__ = ["GuangYaManualDispatchV1125Mixin"]
