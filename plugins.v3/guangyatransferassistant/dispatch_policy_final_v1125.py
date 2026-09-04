"""v1.12.5 最终调度收口。

在 dispatch_policy_v1125 的 Push/Pull 分流之上处理发布前边界：
- 没有逐集日期、但历史更新星期已经稳定时，仍把星期规则视为有效调度事实；
  不能误判“日历不可用”后回退为全量缺集主动搜索；
- 新订阅仍立即响应：先查频道缓存，必要时只合并强刷频道一次，再消费频道；
  频道后仅对当前更新日/电影冷却允许的缺口主动 GYING，未来集/非更新日不能因新增订阅绕门禁；
- 每日 04:10 的自动强制 GYING 虽可绕过冷却执行本轮，但执行后必须登记正常冷却，
  避免 05:00 的小时 Pull 立刻再次访问观影；人工强制检查不受此规则影响。

本层是标准 cooperative mixin，不继承预览策略类；运行时由显式 MRO 把它放在
GuangYaDispatchPolicyV1125Mixin 之前，所有 super() 都沿最终插件 MRO 继续下传。
"""
from __future__ import annotations

import time
from typing import Any, Dict, Iterable, List


class GuangYaDispatchPolicyFinalV1125Mixin:
    """最终发布前调度权威。"""

    build_id = "20260904-r51-preview"

    def _airing_gate_v1120(self, subscribe: Any, payload: Dict[str, Any] = None) -> Dict[str, Any]:
        result = dict(super()._airing_gate_v1120(subscribe, payload=payload) or {})
        if self._is_movie_subscription(subscribe) or bool(result.get("passive_channel_bypass_v1125")):
            return result

        # Weekly 层只有在历史样本达到置信门槛时才会给出 weekday。
        # 这已经足够说明“调度可判定”：今天命中则 due_uncovered 有值，非更新日则必须等待。
        # 不能因为当前缺集没有逐集 air_date 就退回 legacy 全量缺集搜索。
        if not bool(result.get("calendar_available")) and result.get("weekday") is not None:
            result["calendar_explicit_available_v1125"] = False
            result["calendar_available"] = True
            result["calendar_available_basis_v1125"] = "stable_weekday"
        return result

    def _record_auto_external_cooldown_v1125(self, subscribe: Any, origin: str) -> None:
        sid = int(getattr(subscribe, "id", 0) or 0)
        if sid <= 0:
            return
        try:
            state = dict(self._external_search_state_v1114() or {})
        except Exception:
            state = {}
        now = time.time()
        row = dict(state.get(str(sid)) or {})
        row.update({
            "last_at": now,
            "last_time": self._now_text(),
            "cooldown_minutes": int(getattr(self, "_external_search_cooldown_minutes_v1114", 180) or 180),
            "origin": str(origin or "automatic_force"),
        })
        state[str(sid)] = row
        if len(state) > 1000:
            state = dict(sorted(
                state.items(),
                key=lambda pair: float((pair[1] or {}).get("last_at") or 0),
                reverse=True,
            )[:1000])
        self.save_data("external_search_guard", state)

    def _claim_external_search_round_v1114(self, subscribe: Any, force: bool = False) -> bool:
        allowed = bool(super()._claim_external_search_round_v1114(subscribe, force=force))
        if not allowed or not force:
            return allowed
        reader = getattr(self, "_route_source_mode_value_v1115", None)
        mode = str(reader() if callable(reader) else getattr(self, "_route_source_mode_v1115", "") or "")
        if mode == "daily_repair_pull":
            self._record_auto_external_cooldown_v1125(subscribe, "daily_repair_pull")
        return allowed

    def _spawn_route_prime(self, sids: Iterable[int], trigger: str = "立即检查") -> None:
        """新增订阅只做一次频道补查；主动站点搜索仍交给最终日历 selector。"""
        ids = sorted(self._positive_ids_v1125(sids or []))
        if not ids or not self._enabled:
            return

        missing_cache: List[int] = []
        for sid in ids:
            subscribe = self._find_subscription(sid)
            if not subscribe or not self._is_guangya_route(subscribe):
                continue
            try:
                if not self._cached_matches_for_subscription(subscribe):
                    missing_cache.append(sid)
            except Exception:
                missing_cache.append(sid)

        if missing_cache:
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【新订阅】%s 个订阅频道缓存未命中，合并现查频道一次；随后仅按更新日历判断是否主动搜索",
                len(missing_cache),
            )
            try:
                self.refresh_channels(force=True)
            except Exception as err:
                self._plugin_log(
                    "WARNING",
                    "【光鸭转存助手】【新订阅】频道现查失败，仍继续按当前更新日历判断主动搜索：%s",
                    str(err)[:260],
                )

        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【新订阅】进入频道缓存/现查 + 当前应播主动搜索判定，共 %s 个订阅",
            len(ids),
        )
        self._queue_async_route_check(ids, trigger="新订阅资源匹配")

    def _run_reliability_route_batch(self, batch: List[int], trigger: str) -> None:
        text = str(trigger or "")
        if "新订阅资源匹配" not in text:
            return super()._run_reliability_route_batch(batch, trigger)

        ids = sorted(self._positive_ids_v1125(batch or []))
        if not ids:
            return None

        # 新订阅入口已经完成必要的合并频道现查；异步执行阶段先只消费频道。
        # channel_event 会禁止任何 GYING 调用，并绕过日期门禁处理已经到达的真实资源。
        self._run_v1115_mode_batch(
            ids,
            "新订阅资源匹配·频道阶段",
            "channel_event",
            force=False,
        )

        # 频道处理完成后重新读 MoviePilot 缺集/在途事实，再套当前更新日 + 外部冷却。
        # 只允许本次新订阅集合进入主动 Pull，不能顺带触发其它订阅。
        allowed = set(self._smart_pull_due_ids_v1125())
        pull_ids = [sid for sid in ids if sid in allowed]
        if pull_ids:
            self._run_v1115_mode_batch(
                pull_ids,
                "新订阅资源匹配·更新日历主动拉取",
                "airing_pull",
                force=False,
            )
        return None


__all__ = ["GuangYaDispatchPolicyFinalV1125Mixin"]
