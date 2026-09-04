"""v1.12.5 预览：频道 Push / 观影 Pull 调度收口层。

原则：
- 5 分钟 tick 只负责频道增量，不再同时启动主动 GYING；
- 频道是被动到达的资源，命中真实缺集后不受播出日期门禁限制，但仍受媒体身份、
  reservation/source claim、episode fence 与质量门禁限制；频道批次继续禁止主动 GYING；
- 主动 GYING 只由更新日历服务统一驱动：TV/动漫先按 due_uncovered 过滤，电影按外部
  检索冷却参与；日历不可用时才退回旧的“真实缺集 + 冷却”语义；
- 每天 04:10 全员复核改为两阶段：先用频道缓存/现查补全，再只对仍未覆盖且不在途的
  订阅做一次强制 GYING 补漏，避免频道已有资源时仍先打观影服务器。

这个层只改“什么时候触发哪个来源”，不改变迅雷 JSON、媒体身份、资源质量、Episode
Resolver、光鸭转存/cloudcollection 与 MoviePilot 完成事实的既有实现。
"""
from __future__ import annotations

import datetime
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


class GuangYaDispatchPolicyV1125Mixin:
    """最终触发策略：频道被动消费、日历主动拉取、每日两阶段修复。"""

    build_id = "20260904-r51-preview"

    def init_plugin(self, config: dict = None) -> None:
        # 仅用于抑制 lower channel-event tick 中的旧 viewing poll；使用 thread-local，
        # 避免 5 分钟频道线程短暂运行时误伤并发的每小时日历服务。
        self._dispatch_tick_local_v1125 = threading.local()
        return super().init_plugin(config)

    @staticmethod
    def _positive_ids_v1125(values: Iterable[Any]) -> Set[int]:
        result: Set[int] = set()
        for raw in values or []:
            try:
                value = int(raw or 0)
            except (TypeError, ValueError):
                continue
            if value > 0:
                result.add(value)
        return result

    def _active_selected_subscriptions_v1125(self) -> List[Any]:
        selected = self._positive_ids_v1125(getattr(self, "_selected_subscriptions", []) or [])
        rows: List[Any] = []
        for subscribe in self._list_subscriptions("N,R") or []:
            sid = int(getattr(subscribe, "id", 0) or 0)
            if sid <= 0 or sid not in selected:
                continue
            try:
                if not self._is_guangya_route(subscribe):
                    continue
            except Exception:
                continue
            rows.append(subscribe)
        return rows

    def _uncovered_missing_v1125(self, subscribe: Any) -> Set[int]:
        if self._is_movie_subscription(subscribe):
            return set()
        try:
            missing = self._positive_ids_v1125(self._subscription_missing_episodes(subscribe) or [])
        except Exception:
            missing = set()
        if not missing:
            return set()
        try:
            reservations = dict(self._pending_reservations(subscribe) or {})
            reserved = self._positive_ids_v1125(reservations.get("episodes") or [])
        except Exception:
            reserved = set()
        sid = int(getattr(subscribe, "id", 0) or 0)
        try:
            claimed = self._positive_ids_v1125(self._active_source_claims(sid) or [])
        except Exception:
            claimed = set()
        return missing - reserved - claimed

    def _movie_needs_pull_v1125(self, subscribe: Any) -> bool:
        if not self._is_movie_subscription(subscribe):
            return False
        confirmed = getattr(self, "_movie_transfer_confirmed", None)
        if callable(confirmed):
            try:
                if bool(confirmed(subscribe)):
                    try:
                        self._finish_subscription_if_complete(subscribe)
                    except Exception:
                        pass
                    return False
            except Exception:
                pass
        try:
            reservations = dict(self._pending_reservations(subscribe) or {})
            if bool(reservations.get("movie")):
                return False
        except Exception:
            pass
        return str(getattr(subscribe, "state", "") or "") in {"N", "R", ""}

    # ------------------------------------------------------------------
    # 频道 Push：日期只控制主动搜索，不拒绝已经到达且匹配真实缺集的资源。
    # ------------------------------------------------------------------
    def _airing_gate_v1120(self, subscribe: Any, payload: Dict[str, Any] = None) -> Dict[str, Any]:
        result = dict(super()._airing_gate_v1120(subscribe, payload=payload) or {})
        if self._is_movie_subscription(subscribe):
            return result
        mode_reader = getattr(self, "_route_source_mode_value_v1115", None)
        mode = str(mode_reader() if callable(mode_reader) else getattr(self, "_route_source_mode_v1115", "") or "")
        if mode != "channel_event":
            return result

        raw_missing = self._positive_ids_v1125(result.get("raw_missing") or [])
        reserved = self._positive_ids_v1125(result.get("reserved") or [])
        claimed = self._positive_ids_v1125(result.get("claimed") or [])
        strict_due = list(result.get("due_uncovered") or [])
        strict_future = list(result.get("future_missing") or [])
        strict_off_day = list(result.get("off_day_missing") or [])
        passive_uncovered = raw_missing - reserved - claimed
        result.update({
            # 被动资源不依赖日历可用性；强制让 scheduler 继续走 due scope，而不是 legacy fallback。
            "calendar_available": True,
            "due_missing": sorted(raw_missing),
            "due_uncovered": sorted(passive_uncovered),
            "future_missing": [],
            "unscheduled_missing": [],
            "off_day_missing": [],
            "passive_channel_bypass_v1125": True,
            "strict_due_uncovered_v1125": strict_due,
            "strict_future_missing_v1125": strict_future,
            "strict_off_day_missing_v1125": strict_off_day,
        })
        return result

    # ------------------------------------------------------------------
    # 5 分钟 tick：只保留频道刷新/事件匹配，旧 viewing poll 在本线程内返回空。
    # ------------------------------------------------------------------
    def _tick_local_v1125(self):
        local = getattr(self, "_dispatch_tick_local_v1125", None)
        if local is None:
            local = threading.local()
            self._dispatch_tick_local_v1125 = local
        return local

    def _tick(self, host_service: bool = True) -> None:
        local = self._tick_local_v1125()
        previous = bool(getattr(local, "channel_only", False))
        local.channel_only = True
        try:
            return super()._tick(host_service=host_service)
        finally:
            local.channel_only = previous

    # ------------------------------------------------------------------
    # 单一主动 Pull 选择器：先冷却，再日历；日历不可用才退回旧缺集语义。
    # ------------------------------------------------------------------
    def _external_cooldown_due_v1125(
        self,
        sid: int,
        state: Dict[str, Any],
        now: float,
    ) -> bool:
        row = dict(state.get(str(sid)) or {})
        try:
            last_at = float(row.get("last_at") or 0)
        except (TypeError, ValueError):
            last_at = 0.0
        try:
            cooldown = max(900, int(getattr(self, "_external_search_cooldown_minutes_v1114", 180) or 180) * 60)
        except (TypeError, ValueError):
            cooldown = 180 * 60
        return not last_at or now - last_at >= cooldown

    def _smart_pull_due_ids_v1125(self) -> List[int]:
        rows = self._active_selected_subscriptions_v1125()
        try:
            state = dict(self._external_search_state_v1114() or {})
        except Exception:
            state = {}
        now = time.time()

        cooldown_rows: List[Any] = []
        for subscribe in rows:
            sid = int(getattr(subscribe, "id", 0) or 0)
            if sid > 0 and self._external_cooldown_due_v1125(sid, state, now):
                cooldown_rows.append(subscribe)

        # 没有任何订阅达到外部冷却时，不刷新日历，也不做额外媒体查询。
        if not cooldown_rows:
            return []

        calendar: Optional[Dict[str, Any]] = None
        if any(not self._is_movie_subscription(subscribe) for subscribe in cooldown_rows):
            try:
                calendar = dict(self._refresh_airing_calendar_v1120(force=False) or {})
            except Exception:
                calendar = None

        due: List[int] = []
        fallback = 0
        off_day = 0
        for subscribe in cooldown_rows:
            sid = int(getattr(subscribe, "id", 0) or 0)
            if sid <= 0:
                continue
            if self._is_movie_subscription(subscribe):
                if self._movie_needs_pull_v1125(subscribe):
                    due.append(sid)
                continue

            uncovered = self._uncovered_missing_v1125(subscribe)
            if not uncovered:
                try:
                    if not self._subscription_missing_episodes(subscribe):
                        self._finish_subscription_if_complete(subscribe)
                except Exception:
                    pass
                continue

            try:
                if calendar is not None:
                    gate = dict(self._airing_gate_v1120(subscribe, payload=calendar) or {})
                else:
                    gate = dict(self._airing_gate_v1120(subscribe) or {})
            except Exception:
                gate = {}

            if bool(gate.get("calendar_available")):
                if self._positive_ids_v1125(gate.get("due_uncovered") or []):
                    due.append(sid)
                else:
                    off_day += 1
                continue

            # 与既有 scheduler 保持一致：日历完全不可用时不能冻结追更，退回真实缺集 + 冷却。
            fallback += 1
            due.append(sid)

        try:
            self.save_data("dispatch_policy_v1125", {
                "selector_at": datetime.datetime.now().isoformat(timespec="seconds"),
                "active": len(rows),
                "cooldown_due": len(cooldown_rows),
                "pull_due": len(due),
                "off_day": off_day,
                "calendar_fallback": fallback,
            })
        except Exception:
            pass
        return sorted(set(due))

    def _viewing_due_subscription_ids_v1115(self) -> List[int]:
        local = self._tick_local_v1125()
        if bool(getattr(local, "channel_only", False)):
            return []
        return self._smart_pull_due_ids_v1125()

    # 频道消息的异步 worker 结束后不再追加一次主动观影；历史遗留的“观影定时轮询”
    # 若仍进入队列，也必须重新经过当前智能 selector，不能按旧大列表直接执行。
    def _run_reliability_route_batch(self, batch: List[int], trigger: str) -> None:
        text = str(trigger or "")
        normalized = sorted(self._positive_ids_v1125(batch or []))
        if "频道新增资源" in text:
            if normalized:
                return self._run_v1115_mode_batch(normalized, trigger, "channel_event", force=False)
            return None
        if "观影定时轮询" in text:
            allowed = set(self._smart_pull_due_ids_v1125())
            filtered = [sid for sid in normalized if sid in allowed]
            if filtered:
                return self._run_v1115_mode_batch(filtered, "更新日历主动拉取", "airing_pull", force=False)
            return None
        return super()._run_reliability_route_batch(batch, trigger)

    # ------------------------------------------------------------------
    # 每小时 AiringDue：唯一常规主动 GYING 时钟，严格服从外部检索冷却。
    # ------------------------------------------------------------------
    def _calendar_due_check_v1110(self) -> Dict[str, Any]:
        active = self._active_selected_subscriptions_v1125()
        due_ids = self._smart_pull_due_ids_v1125()
        now_text = datetime.datetime.now().isoformat(timespec="seconds")
        state = self.get_data("airing_check_state_v1110") or {}
        if not isinstance(state, dict):
            state = {}

        results: List[Dict[str, Any]] = []
        for sid in due_ids:
            subscribe = self._find_subscription(sid)
            episodes: List[int] = []
            if subscribe and not self._is_movie_subscription(subscribe):
                try:
                    gate = dict(self._airing_gate_v1120(subscribe) or {})
                    episodes = sorted(self._positive_ids_v1125(gate.get("due_uncovered") or []))
                except Exception:
                    episodes = []
            state[str(sid)] = {
                "checked_at": now_text,
                "episodes": episodes,
                "mode": "airing_pull",
            }
            results.append({
                "subscribe_id": sid,
                "episodes": episodes,
                "scheduled": True,
                "mode": "airing_pull",
            })
        if len(state) > 1000:
            state = dict(list(state.items())[-1000:])
        self.save_data("airing_check_state_v1110", state)

        if due_ids:
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【主动拉取】日历/电影冷却筛选后执行 %s 个订阅；5 分钟频道 tick 不再启动 GYING",
                len(due_ids),
            )
            self._run_v1115_mode_batch(
                due_ids,
                "更新日历主动拉取",
                "airing_pull",
                force=False,
            )
        return {
            "success": True,
            "checked": len(due_ids),
            "skipped": max(0, len(active) - len(due_ids)),
            "results": results,
            "mode": "single_airing_pull",
        }

    # ------------------------------------------------------------------
    # 每日 04:10：频道优先全量修复 -> 重算真实缺口 -> 仅剩余项 GYING 强制补漏。
    # ------------------------------------------------------------------
    def _repair_signature_v1125(self, subscribe: Any) -> Tuple[int, ...] | Tuple[str]:
        if self._is_movie_subscription(subscribe):
            return ("movie",) if self._movie_needs_pull_v1125(subscribe) else tuple()
        try:
            return tuple(sorted(self._positive_ids_v1125(self._subscription_missing_episodes(subscribe) or [])))
        except Exception:
            return tuple()

    def _daily_full_catchup_v1110(self) -> Dict[str, Any]:
        started = datetime.datetime.now()
        try:
            self.refresh_channels(force=True)
        except Exception as err:
            self._plugin_log(
                "WARNING",
                "【光鸭转存助手】【每日全员复核】频道强制刷新失败，继续使用缓存：%s",
                str(err)[:260],
            )
        try:
            self._refresh_airing_calendar_v1120(force=True)
        except Exception as err:
            self._plugin_log(
                "WARNING",
                "【光鸭转存助手】【每日全员复核】更新日历刷新失败，仍继续两阶段修复：%s",
                str(err)[:260],
            )

        initial_rows = self._active_selected_subscriptions_v1125()
        initial_ids = [int(getattr(subscribe, "id", 0) or 0) for subscribe in initial_rows]
        before: Dict[int, Tuple[Any, ...]] = {}
        names: Dict[int, str] = {}
        for subscribe in initial_rows:
            sid = int(getattr(subscribe, "id", 0) or 0)
            names[sid] = str(getattr(subscribe, "name", "") or "")
            try:
                sync = getattr(self, "_sync_media_library_progress", None)
                if callable(sync):
                    sync(subscribe)
            except Exception:
                pass
            fresh = self._find_subscription(sid) or subscribe
            before[sid] = tuple(self._repair_signature_v1125(fresh))

        # 第一阶段只消费频道现有资源；channel_event 会关闭 GYING，并由本层绕过日期门禁。
        if initial_ids:
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【每日全员复核】阶段1：%s 个订阅先消费频道资源，不访问 GYING",
                len(initial_ids),
            )
            self._run_v1115_mode_batch(
                initial_ids,
                "每日全员复核·频道阶段",
                "channel_event",
                force=False,
            )

        # 重新读取成功回执 / reservation / source claim，只让真正仍未覆盖的订阅进入主动搜索。
        remaining: List[int] = []
        after_channel: Dict[int, Tuple[Any, ...]] = {}
        for subscribe in self._active_selected_subscriptions_v1125():
            sid = int(getattr(subscribe, "id", 0) or 0)
            fresh = self._find_subscription(sid) or subscribe
            after_channel[sid] = tuple(self._repair_signature_v1125(fresh))
            if self._is_movie_subscription(fresh):
                if self._movie_needs_pull_v1125(fresh):
                    remaining.append(sid)
                continue
            if self._uncovered_missing_v1125(fresh):
                remaining.append(sid)

        if remaining:
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【每日全员复核】阶段2：频道后仍有 %s 个订阅存在未覆盖缺口，才进入 GYING 强制补漏",
                len(remaining),
            )
            self._run_v1115_mode_batch(
                remaining,
                "每日全员复核·GYING阶段",
                "daily_repair_pull",
                force=True,
            )

        final_rows = {int(getattr(subscribe, "id", 0) or 0): subscribe for subscribe in self._active_selected_subscriptions_v1125()}
        results: List[Dict[str, Any]] = []
        failed = changed = 0
        for sid in initial_ids:
            subscribe = final_rows.get(sid) or self._find_subscription(sid)
            if subscribe:
                final_signature = tuple(self._repair_signature_v1125(subscribe))
                if self._is_movie_subscription(subscribe):
                    still_needs = self._movie_needs_pull_v1125(subscribe)
                else:
                    still_needs = bool(self._uncovered_missing_v1125(subscribe))
            else:
                final_signature = tuple()
                still_needs = False
            if before.get(sid, tuple()) != final_signature:
                changed += 1
            if still_needs:
                failed += 1
            results.append({
                "subscribe_id": sid,
                "name": names.get(sid, ""),
                "missing_before": list(before.get(sid, tuple())),
                "missing_after_channel": list(after_channel.get(sid, tuple())),
                "missing_after": list(final_signature),
                "gying_attempted": sid in set(remaining),
                "success": not still_needs,
            })

        payload = {
            "started_at": started.isoformat(timespec="seconds"),
            "finished_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "checked": len(initial_ids),
            "channel_phase": len(initial_ids),
            "gying_phase": len(remaining),
            "changed": changed,
            "failed": failed,
            "results": results[-200:],
            "strategy": "channel_first_then_gying",
        }
        self.save_data("daily_catchup_v1110", payload)
        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【每日全员复核】完成：订阅=%s 频道阶段=%s GYING阶段=%s 仍需补漏=%s",
            payload["checked"],
            payload["channel_phase"],
            payload["gying_phase"],
            payload["failed"],
        )
        return {
            "success": True,
            "data": payload,
            "message": f"已复核 {payload['checked']} 个订阅；仅 {payload['gying_phase']} 个进入 GYING 补漏",
        }


__all__ = ["GuangYaDispatchPolicyV1125Mixin"]
