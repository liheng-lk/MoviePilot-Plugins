"""v1.12.5 最终调度收口。

在 dispatch_policy_v1125 的 Push/Pull 分流之上处理发布前边界：
- 没有逐集日期、但历史更新星期已经稳定时，仍把星期规则视为有效调度事实；
  不能误判“日历不可用”后回退为全量缺集主动搜索；
- 新订阅仍立即响应：先查频道缓存，必要时只合并强刷频道一次，再消费频道；
  频道后仅对当前更新日/电影待处理缺口进入主动完整资源链，未来集/非更新日不能因新增订阅绕门禁；
- 每小时 AiringDue 只处理今天应更新且仍未覆盖的媒体，并给这些媒体独立的 60 分钟外部检索窗口；
  执行仍复用既有完整链路：观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K；
- 每日 04:10 的自动强制 GYING 虽可绕过冷却执行本轮，但执行后必须登记冷却时间，
  避免 05:00 的小时 Pull 立刻再次访问观影；人工强制检查不受此规则影响；
- 04:10 的强制日历刷新延后到频道 + GYING 两阶段结束后，避免 TMDB/每日助手慢响应
  把本应最先执行的频道补漏阻塞在前面；
- 常规日历刷新若抛异常，60 秒内返回显式“不可用”哨兵，避免 selector 首次失败后
  每个订阅的 gate 又各自触发一次网络刷新形成故障风暴；
- Reliability 仍按订阅 ID 合并后台任务，但每个订阅额外保存真实 trigger；同一 worker 中同时到达
  频道 Push / Airing Pull / 新订阅时按真实来源重新分组，不能被第一个 worker trigger 串改执行模式；
- trigger 记录与 Governance/可靠性队列共用同一 RLock 完成原子入队，避免“刚判断未 active，下一瞬
  被其它线程抢先 active”后留下陈旧 trigger 污染下一轮；
- 频道故障恢复只恢复并消费频道，不得借恢复任务偷偷启动主动 GYING。

本层是标准 cooperative mixin，不继承预览策略类；运行时由显式 MRO 把它放在
GuangYaDispatchPolicyV1125Mixin 之前，所有 super() 都沿最终插件 MRO 继续下传。
"""
from __future__ import annotations

import datetime
import threading
import time
from typing import Any, Dict, Iterable, List


class GuangYaDispatchPolicyFinalV1125Mixin:
    """最终发布前调度权威。"""

    build_id = "20260904-r51-preview"
    _calendar_failure_backoff_seconds_v1125 = 60
    _async_trigger_bucket_limit_v1125 = 8
    _hourly_due_cooldown_seconds_v1125 = 60 * 60

    def init_plugin(self, config: dict = None) -> None:
        self._dispatch_final_local_v1125 = threading.local()
        self._dispatch_trigger_lock_v1125 = threading.RLock()
        self._dispatch_triggers_v1125: Dict[int, List[str]] = {}
        self._calendar_refresh_failure_until_v1125 = 0.0
        self._calendar_refresh_failure_message_v1125 = ""
        return super().init_plugin(config)

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

    def _external_cooldown_due_v1125(
        self,
        sid: int,
        state: Dict[str, Any],
        now: float,
    ) -> bool:
        """AiringDue 每小时只允许同一媒体进入一次主动资源复查窗口。"""
        row = dict(state.get(str(sid)) or {})
        try:
            last_at = float(row.get("last_at") or 0)
        except (TypeError, ValueError):
            last_at = 0.0
        cooldown = max(60, int(getattr(self, "_hourly_due_cooldown_seconds_v1125", 60 * 60) or 60 * 60))
        return not last_at or now - last_at >= cooldown

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
        reader = getattr(self, "_route_source_mode_value_v1115", None)
        mode = str(reader() if callable(reader) else getattr(self, "_route_source_mode_v1115", "") or "")

        # AiringDue 已经由逐集日历/星期门禁证明“今天应该处理”。此时不能再套默认 180 分钟
        # external_search_guard，否则“每小时检查”实际会变成三小时才访问一次 GYING/迅雷。
        # 这里只把该模式收敛到 60 分钟；频道、人工、普通后台以及每日修复继续沿用原 Governance。
        if not force and mode == "airing_pull":
            sid = int(getattr(subscribe, "id", 0) or 0)
            if sid <= 0:
                return False
            try:
                state = dict(self._external_search_state_v1114() or {})
            except Exception:
                state = {}
            row = dict(state.get(str(sid)) or {})
            try:
                last_at = float(row.get("last_at") or 0)
            except (TypeError, ValueError):
                last_at = 0.0
            now = time.time()
            cooldown = max(60, int(getattr(self, "_hourly_due_cooldown_seconds_v1125", 60 * 60) or 60 * 60))
            allowed = not last_at or now - last_at >= cooldown
            self._external_round_allowed_v1114[sid] = allowed
            if allowed:
                state[str(sid)] = {
                    **row,
                    "last_at": now,
                    "last_time": self._now_text(),
                    "cooldown_minutes": max(1, int(cooldown / 60)),
                    "origin": "airing_full_chain_v1125",
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
                    "【光鸭转存助手】【今日资源复查】#%s %s 本小时已执行过完整资源链，约 %s 分钟后再复查",
                    sid,
                    str(getattr(subscribe, "name", "") or ""),
                    remaining,
                )
            return allowed

        allowed = bool(super()._claim_external_search_round_v1114(subscribe, force=force))
        if not allowed or not force:
            return allowed
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

    # ------------------------------------------------------------------
    # 异步队列来源保持：Reliability 合并 ID，但不能合并掉每个 ID 的来源语义。
    # ------------------------------------------------------------------
    def _queue_async_route_check(self, sids: Iterable[int], trigger: str = "后台检查") -> None:
        ids = sorted(self._positive_ids_v1125(sids or []))
        if not ids or not bool(getattr(self, "_enabled", False)):
            return
        current = getattr(self, "_runtime_is_current", None)
        if callable(current) and not bool(current()):
            return

        # _async_route_lock 在 Experience 初始化为 RLock。整个“看 active -> 记录 trigger ->
        # Governance 再过滤 -> Reliability 入 pending/recheck”都在同一把锁里完成；后续 super
        # 会可重入地拿同一 RLock，因此不会在预测与真正入队之间被 worker 改写 active。
        route_lock = getattr(self, "_async_route_lock", None)
        if route_lock is None:
            route_lock = threading.RLock()
            self._async_route_lock = route_lock

        with route_lock:
            accepted = set(ids)
            automatic = getattr(self, "_automatic_trigger_v1114", None)
            manual = getattr(self, "_manual_trigger_v1114", None)
            is_automatic = bool(automatic(trigger)) if callable(automatic) else False
            is_manual = bool(manual(trigger)) if callable(manual) else False
            if is_automatic and not is_manual:
                active = set(getattr(self, "_async_route_active", set()) or set())
                accepted -= active

            if accepted:
                lock = getattr(self, "_dispatch_trigger_lock_v1125", None)
                if lock is None:
                    lock = threading.RLock()
                    self._dispatch_trigger_lock_v1125 = lock
                store = getattr(self, "_dispatch_triggers_v1125", None)
                if not isinstance(store, dict):
                    store = {}
                    self._dispatch_triggers_v1125 = store
                text = str(trigger or "后台检查")
                with lock:
                    for sid in sorted(accepted):
                        bucket = list(store.get(sid) or [])
                        # Reliability finally 的“后台合并补偿”只是内部重拉起标识；真实来源还在桶中时
                        # 绝不能覆盖成 generic trigger。
                        if text == "后台合并补偿" and bucket:
                            continue
                        if text not in bucket:
                            bucket.append(text)
                        limit = max(2, int(getattr(self, "_async_trigger_bucket_limit_v1125", 8) or 8))
                        store[sid] = bucket[-limit:]

            return super()._queue_async_route_check(ids, trigger=trigger)

    @staticmethod
    def _ordered_async_triggers_v1125(values: Iterable[str], fallback: str) -> List[str]:
        rows: List[str] = []
        for raw in values or []:
            value = str(raw or "").strip()
            if value and value not in rows:
                rows.append(value)
        if not rows:
            rows = [str(fallback or "后台检查")]

        # 新订阅任务自己已经包含“频道 -> 当前应播 Pull”，同一 debounce 内的普通频道/日历
        # 自动触发无需再重复；显式人工操作保留。
        prime = next((value for value in rows if "新订阅资源匹配" in value), "")
        if prime:
            manual_rows = [
                value for value in rows
                if any(token in value.lower() for token in ("手动", "人工", "立即", "api", "控制台", "按钮"))
            ]
            return [prime, *[value for value in manual_rows if value != prime]]

        recovery = next((value for value in rows if "频道故障自动恢复" in value), "")
        channel = [value for value in rows if "频道新增资源" in value]
        active = [
            value for value in rows
            if "观影定时轮询" in value or "更新日历" in value or "airing" in value.lower()
        ]
        others = [value for value in rows if value not in channel and value not in active and value != recovery]
        ordered: List[str] = []
        # 被动资源先消费，再允许主动 Pull 重算真实缺口。
        if recovery:
            ordered.append(recovery)
        else:
            ordered.extend(channel)
        ordered.extend(active)
        ordered.extend(others)
        return ordered or [str(fallback or "后台检查")]

    def _take_async_route_triggers_v1125(self, batch: Iterable[int], fallback: str) -> Dict[int, List[str]]:
        ids = sorted(self._positive_ids_v1125(batch or []))
        store = getattr(self, "_dispatch_triggers_v1125", None)
        lock = getattr(self, "_dispatch_trigger_lock_v1125", None)
        if not isinstance(store, dict) or lock is None:
            return {sid: [str(fallback or "后台检查")] for sid in ids}
        result: Dict[int, List[str]] = {}
        with lock:
            for sid in ids:
                values = list(store.pop(sid, []) or [])
                result[sid] = self._ordered_async_triggers_v1125(values, fallback)
        return result

    @staticmethod
    def _async_trigger_priority_v1125(trigger: str) -> int:
        text = str(trigger or "")
        if "频道故障自动恢复" in text or "频道新增资源" in text:
            return 0
        if "新订阅资源匹配" in text:
            return 1
        if "观影定时轮询" in text or "更新日历" in text or "airing" in text.lower():
            return 2
        return 3

    def _run_dispatch_trigger_v1125(self, ids: List[int], trigger: str) -> None:
        text = str(trigger or "")
        if not ids:
            return None

        if "频道故障自动恢复" in text:
            # 这是频道 transport 的恢复任务，不是主动资源站调度器。恢复成功后只消费频道缓存；
            # 常规 GYING 仍等 AiringDue/日历 selector。
            try:
                self.refresh_channels(force=True)
            except Exception as err:
                self._plugin_log(
                    "WARNING",
                    "【光鸭转存助手】【频道恢复】恢复刷新仍失败，继续仅使用频道缓存，不启动 GYING：%s",
                    str(err)[:260],
                )
            return self._run_v1115_mode_batch(ids, text, "channel_event", force=False)

        if "新订阅资源匹配" in text:
            self._run_v1115_mode_batch(
                ids,
                "新订阅资源匹配·频道阶段",
                "channel_event",
                force=False,
            )
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

        return super()._run_reliability_route_batch(ids, text)

    def _run_reliability_route_batch(self, batch: List[int], trigger: str) -> None:
        ids = sorted(self._positive_ids_v1125(batch or []))
        if not ids:
            return None
        trigger_map = self._take_async_route_triggers_v1125(ids, trigger)
        groups: Dict[str, List[int]] = {}
        for sid in ids:
            for value in trigger_map.get(sid) or [str(trigger or "后台检查")]:
                groups.setdefault(str(value or "后台检查"), []).append(sid)

        for value in sorted(groups, key=lambda item: (self._async_trigger_priority_v1125(item), item)):
            group_ids = sorted(set(groups.get(value) or []))
            self._run_dispatch_trigger_v1125(group_ids, value)
        return None

    def _calendar_failure_payload_v1125(self) -> Dict[str, Any]:
        """必须保持 truthy，避免下层 `payload or refresh()` 再次发起网络请求。"""
        return {
            "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "subscriptions": [],
            "count": 0,
            "calendar_refresh_failed_v1125": True,
            "errors": [str(getattr(self, "_calendar_refresh_failure_message_v1125", "") or "calendar unavailable")[:240]],
        }

    def _refresh_airing_calendar_v1120(self, force: bool = False) -> Dict[str, Any]:
        """每日阶段支持延迟强刷；普通刷新异常进入短退避，防止每订阅重复打日历服务。"""
        local = getattr(self, "_dispatch_final_local_v1125", None)
        if (
            force
            and local is not None
            and bool(getattr(local, "defer_daily_calendar", False))
        ):
            cached = self.get_data("airing_calendar_v1120") or {}
            if isinstance(cached, dict) and cached:
                return dict(cached)
            return self._calendar_failure_payload_v1125()

        if force:
            return dict(super()._refresh_airing_calendar_v1120(force=True) or {})

        now = time.time()
        try:
            failure_until = float(getattr(self, "_calendar_refresh_failure_until_v1125", 0.0) or 0.0)
        except (TypeError, ValueError):
            failure_until = 0.0
        if failure_until > now:
            return self._calendar_failure_payload_v1125()

        try:
            result = dict(super()._refresh_airing_calendar_v1120(force=False) or {})
        except Exception as err:
            self._calendar_refresh_failure_until_v1125 = now + max(
                15,
                int(getattr(self, "_calendar_failure_backoff_seconds_v1125", 60) or 60),
            )
            self._calendar_refresh_failure_message_v1125 = str(err)[:240]
            self._plugin_log(
                "WARNING",
                "【光鸭转存助手】【更新日历】常规刷新异常，进入短退避避免按订阅重复请求：%s",
                str(err)[:240],
            )
            return self._calendar_failure_payload_v1125()

        self._calendar_refresh_failure_until_v1125 = 0.0
        self._calendar_refresh_failure_message_v1125 = ""
        return result

    def _daily_full_catchup_v1110(self) -> Dict[str, Any]:
        """严格执行频道 -> 剩余 GYING -> 日历刷新，不让日历网络请求挡在频道前。"""
        local = getattr(self, "_dispatch_final_local_v1125", None)
        if local is None:
            local = threading.local()
            self._dispatch_final_local_v1125 = local
        previous = bool(getattr(local, "defer_daily_calendar", False))
        local.defer_daily_calendar = True
        try:
            result = super()._daily_full_catchup_v1110()
        finally:
            local.defer_daily_calendar = previous

        try:
            self._refresh_airing_calendar_v1120(force=True)
        except Exception as err:
            self._plugin_log(
                "WARNING",
                "【光鸭转存助手】【每日全员复核】两阶段补漏已完成，但末尾更新日历刷新失败：%s",
                str(err)[:260],
            )
        return result


__all__ = ["GuangYaDispatchPolicyFinalV1125Mixin"]
