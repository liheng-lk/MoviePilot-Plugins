"""v1.12.6 当日更新剧快速追更层。

目标：
- 保留 v1.12.5 的频道 Push / 日历 Pull 分工，不让 5 分钟频道 tick 主动访问 GYING；
- AiringDue 服务改为每 10 分钟唤醒一次；
- 仅 TV/动漫的 airing_pull 使用 10 分钟外部检索窗口，电影继续沿用 v1.12.5 的 60 分钟窗口；
- 真正是否访问外部来源仍由既有 due_uncovered、reservation、source claim、episode fence 决定；
  非更新日、已入库、已在途的订阅即使服务被唤醒也不会搜索；
- GYING 单次查询结果缓存只有 120 秒，短于 10 分钟窗口，因此下一次快追会重新取得站点结果，
  不会因为上一轮空结果被长时间负缓存锁死。

本层只改变追更响应速度，不改变来源优先级：
观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List


class GuangYaFastRecallV1126Mixin:
    """把当天应播 TV 的最坏主动发现延迟从约 60 分钟降到约 10 分钟。"""

    plugin_version = "1.12.6"
    build_id = "20260904-r52"
    _fast_recall_minutes_v1126 = 10
    _movie_recall_minutes_v1126 = 60

    def get_service(self) -> List[Dict[str, Any]]:
        services = list(super().get_service() or [])
        for index, raw in enumerate(list(services)):
            if not isinstance(raw, dict) or str(raw.get("id") or "") != "GuangYaTransferAssistantAiringDue":
                continue
            service = dict(raw)
            kwargs = dict(service.get("kwargs") or {})
            kwargs["minutes"] = int(self._fast_recall_minutes_v1126)
            service["kwargs"] = kwargs
            service["name"] = "光鸭转存助手当日更新剧快速追更"
            services[index] = service
            break
        return services

    @staticmethod
    def _recall_last_at_v1126(state: Dict[str, Any], sid: int) -> float:
        row = dict(state.get(str(sid)) or {})
        try:
            return float(row.get("last_at") or 0)
        except (TypeError, ValueError):
            return 0.0

    def _external_cooldown_due_v1125(
        self,
        sid: int,
        state: Dict[str, Any],
        now: float,
    ) -> bool:
        subscribe = self._find_subscription(sid)
        if not subscribe or self._is_movie_subscription(subscribe):
            return bool(super()._external_cooldown_due_v1125(sid, state, now))
        last_at = self._recall_last_at_v1126(state, sid)
        cooldown = max(60, int(self._fast_recall_minutes_v1126) * 60)
        return not last_at or now - last_at >= cooldown

    def _claim_external_search_round_v1114(self, subscribe: Any, force: bool = False) -> bool:
        reader = getattr(self, "_route_source_mode_value_v1115", None)
        mode = str(reader() if callable(reader) else getattr(self, "_route_source_mode_v1115", "") or "")
        if force or mode != "airing_pull" or self._is_movie_subscription(subscribe):
            return bool(super()._claim_external_search_round_v1114(subscribe, force=force))

        sid = int(getattr(subscribe, "id", 0) or 0)
        if sid <= 0:
            return False
        try:
            state = dict(self._external_search_state_v1114() or {})
        except Exception:
            state = {}
        row = dict(state.get(str(sid)) or {})
        last_at = self._recall_last_at_v1126(state, sid)
        now = time.time()
        cooldown = max(60, int(self._fast_recall_minutes_v1126) * 60)
        allowed = not last_at or now - last_at >= cooldown

        allowed_state = getattr(self, "_external_round_allowed_v1114", None)
        if not isinstance(allowed_state, dict):
            allowed_state = {}
            self._external_round_allowed_v1114 = allowed_state
        allowed_state[sid] = allowed

        if allowed:
            state[str(sid)] = {
                **row,
                "last_at": now,
                "last_time": self._now_text(),
                "cooldown_minutes": int(self._fast_recall_minutes_v1126),
                "origin": "airing_fast_recall_v1126",
            }
            if len(state) > 1000:
                state = dict(sorted(
                    state.items(),
                    key=lambda pair: float((pair[1] or {}).get("last_at") or 0),
                    reverse=True,
                )[:1000])
            self.save_data("external_search_guard", state)
        else:
            remaining = max(1, int((cooldown - (now - last_at)) / 60))
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【快速追更】#%s %s 距上次主动检索不足 10 分钟，约 %s 分钟后再查",
                sid,
                str(getattr(subscribe, "name", "") or ""),
                remaining,
            )
        return allowed


__all__ = ["GuangYaFastRecallV1126Mixin"]
