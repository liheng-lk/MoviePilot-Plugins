"""v1.10.15 频道事件驱动 + 7 天资源缓存 + 观影独立轮询。

运行语义：
- Telegram/频道仍按既有游标每 5 分钟增量刷新，但只有“本轮真正新增”的消息才触发订阅匹配；
- 新频道消息先做标题/TMDB/季与显式集号的轻量匹配，只把可能覆盖当前缺集的订阅送进执行链；
- 频道 ResourceGroup/分享链接进入 7 天本地缓存，新订阅直接查缓存，不为单个订阅重复刷新频道；
- 频道事件批次禁止访问观影/迅雷外部搜索，不消耗观影轮询冷却；
- 观影保持独立定时轮询，只处理仍有缺集且达到外部检索冷却时间的订阅；
- 同一 tick 若频道命中订阅，频道优先，观影最多顺延一个 tick，避免刚命中频道又重复搜索站点；
- 周期批次仍复用可靠后台队列，执行中重复事件继续由 v1.10.14 去自激层合并。

v1.12.5 的最终调度层会把常规观影轮询收口到 AiringDue；本层保留旧 ABI，并把来源 mode
改成 thread-local 真相，避免频道 worker 与日历/人工线程并发时互相误读 channel_event。
"""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Any, Dict, Iterable, List, Tuple

from .episode_resolver_v190 import reliable_episode_set, resolve_episode
from .legacy import _entry_match_reason
from .xunlei_final_v1114 import GuangYaXunleiFinalV1114Mixin


_CHANNEL_CACHE_KEY_V1115 = "channel_resource_cache_v1115"
_CHANNEL_CACHE_RETENTION_SECONDS_V1115 = 7 * 24 * 60 * 60
_CHANNEL_CACHE_CLEANUP_SECONDS_V1115 = 7 * 24 * 60 * 60
_CHANNEL_CACHE_MAX_ITEMS_V1115 = 5000


def _entry_key_v1115(entry: Dict[str, Any]) -> str:
    """频道资源稳定键：新消息即使复用旧分享也必须得到新键。"""
    row = dict(entry or {})
    source = str(row.get("source_url") or row.get("source_label") or "").strip()
    message_id = str(row.get("message_id") or "").strip()
    resource_group_id = str(row.get("resource_group_id") or "").strip()
    share = str(row.get("share_url") or "").strip()
    external = []
    for item in row.get("external_sources") or []:
        if not isinstance(item, dict):
            continue
        external.append(
            f"{str(item.get('type') or '').strip()}:{str(item.get('identity') or item.get('uri') or '').strip()}"
        )
    external.sort()
    if resource_group_id:
        marker = f"rg:{resource_group_id}"
    elif message_id:
        marker = f"msg:{message_id}|share:{share}|ext:{'|'.join(external)}"
    else:
        marker = f"share:{share}|ext:{'|'.join(external)}|title:{str(row.get('display_title') or '')}"
    if not marker.strip("|:"):
        return ""
    return hashlib.sha256(f"{source}|{marker}".encode("utf-8")).hexdigest()


class GuangYaChannelEventV1115Mixin(GuangYaXunleiFinalV1114Mixin):
    """把频道发现与观影轮询拆成两套触发模型。"""

    build_id = "20260902-r26"

    def init_plugin(self, config: dict = None) -> None:
        self._route_source_mode_v1115 = ""
        self._route_source_local_v1115 = threading.local()
        self._channel_new_entries_v1115: List[Dict[str, Any]] = []
        return super().init_plugin(config)

    def _route_source_mode_value_v1115(self) -> str:
        """当前线程的来源模式是真相；共享字段只在 thread-local 尚未初始化时兼容旧入口。"""
        local = getattr(self, "_route_source_local_v1115", None)
        if local is not None:
            # 关键并发语义：thread-local 已存在时，本线程没有 mode 就必须视为空模式，
            # 绝不能回退到另一个线程刚写入的共享兼容字段。
            return str(getattr(local, "mode", "") or "")
        return str(getattr(self, "_route_source_mode_v1115", "") or "")

    # ------------------------------------------------------------------
    # 7 天频道资源缓存
    # ------------------------------------------------------------------
    def _channel_cache_v1115(self) -> Dict[str, Any]:
        raw = self.get_data(_CHANNEL_CACHE_KEY_V1115) or {}
        if not isinstance(raw, dict):
            raw = {}
        items = raw.get("items")
        if not isinstance(items, dict):
            items = {}
        return {
            "items": dict(items),
            "last_cleanup_at": float(raw.get("last_cleanup_at") or 0),
            "updated_at": float(raw.get("updated_at") or 0),
        }

    def _save_channel_cache_v1115(self, cache: Dict[str, Any]) -> None:
        self.save_data(_CHANNEL_CACHE_KEY_V1115, cache)

    def _refresh_channel_cache_v1115(self, rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        cache = self._channel_cache_v1115()
        items = dict(cache.get("items") or {})
        now = time.time()
        had_cache = bool(items)
        new_rows: List[Dict[str, Any]] = []

        for raw in rows or []:
            if not isinstance(raw, dict) or raw.get("stale"):
                continue
            entry = dict(raw)
            key = _entry_key_v1115(entry)
            if not key:
                continue
            previous = dict(items.get(key) or {})
            added_at = float(previous.get("cache_added_at") or 0) or now
            entry["cache_key_v1115"] = key
            entry["cache_added_at"] = added_at
            entry["cache_seen_at"] = now
            # 首次从旧 channel_index 建缓存只作为 bootstrap，不把整个频道历史误当新消息。
            if had_cache and not previous and not entry.get("cached_index"):
                new_rows.append(dict(entry))
            items[key] = entry

        last_cleanup = float(cache.get("last_cleanup_at") or 0)
        if not last_cleanup or now - last_cleanup >= _CHANNEL_CACHE_CLEANUP_SECONDS_V1115:
            cutoff = now - _CHANNEL_CACHE_RETENTION_SECONDS_V1115
            items = {
                key: row for key, row in items.items()
                if float((row or {}).get("cache_added_at") or now) >= cutoff
            }
            last_cleanup = now

        if len(items) > _CHANNEL_CACHE_MAX_ITEMS_V1115:
            ordered = sorted(
                items.items(),
                key=lambda pair: float((pair[1] or {}).get("cache_added_at") or 0),
                reverse=True,
            )[:_CHANNEL_CACHE_MAX_ITEMS_V1115]
            items = dict(ordered)

        self._save_channel_cache_v1115({
            "items": items,
            "last_cleanup_at": last_cleanup,
            "updated_at": now,
            "retention_days": 7,
        })
        return new_rows

    def _channel_cache_rows_v1115(self) -> List[Dict[str, Any]]:
        cache = self._channel_cache_v1115()
        rows = [dict(row) for row in (cache.get("items") or {}).values() if isinstance(row, dict)]
        rows.sort(key=lambda row: float(row.get("cache_added_at") or 0), reverse=True)
        return rows

    def _hydrate_channel_index_for_subscription_v1115(self, subscribe: Any) -> int:
        """只把当前订阅相关的 7 天缓存补回 channel_index，供成熟分享/ResourcePlanner 复用。"""
        index = dict(self.get_data("channel_index") or {})
        current = list(index.get("items") or [])
        seen = {_entry_key_v1115(row) for row in current if isinstance(row, dict)}
        added = 0
        for row in self._channel_cache_rows_v1115():
            key = _entry_key_v1115(row)
            if not key or key in seen:
                continue
            try:
                matched, _ = _entry_match_reason(row, subscribe)
            except Exception:
                matched = False
            if not matched:
                continue
            restored = dict(row)
            restored["stale"] = False
            restored["cached_index"] = True
            current.append(restored)
            seen.add(key)
            added += 1
        if added:
            index["items"] = current
            index["cache_retention_days"] = 7
            self.save_data("channel_index", index)
        return added

    def _cached_matches_for_subscription(self, subscribe: Any):
        pairs = list(super()._cached_matches_for_subscription(subscribe) or [])
        seen = {_entry_key_v1115(row) for row, _ in pairs if isinstance(row, dict)}
        for row in self._channel_cache_rows_v1115():
            key = _entry_key_v1115(row)
            if not key or key in seen:
                continue
            try:
                matched, reason = _entry_match_reason(row, subscribe)
            except Exception:
                continue
            if matched:
                pairs.append((row, reason))
                seen.add(key)
        return pairs

    def refresh_channels(self, force: bool = False):
        # 主动 Pull 内部若旧层因为“无频道命中”要求 refresh，只允许读缓存，不再额外访问频道。
        if self._route_source_mode_value_v1115() in {"viewing_poll", "airing_pull", "daily_repair_pull"} and not force:
            return list((self.get_data("channel_index") or {}).get("items") or [])
        rows = list(super().refresh_channels(force=force) or [])
        self._channel_new_entries_v1115 = self._refresh_channel_cache_v1115(rows)
        return rows

    # ------------------------------------------------------------------
    # 新频道消息 -> 只匹配可能缺集的订阅
    # ------------------------------------------------------------------
    def _entry_can_cover_missing_v1115(self, entry: Dict[str, Any], subscribe: Any) -> bool:
        if self._is_movie_subscription(subscribe):
            return True
        missing = {
            int(value) for value in (self._subscription_missing_episodes(subscribe) or [])
            if int(value or 0) > 0
        }
        if not missing:
            return False
        hint = str(entry.get("episode_hint") or "").strip()
        if not hint:
            return True
        try:
            result = resolve_episode(hint, season_hint=getattr(subscribe, "season", None))
            explicit = reliable_episode_set(result, 0.99)
        except Exception:
            explicit = set()
        # 有明确集号时先本地判断交集；没有明确集号交给后续分享文件解析。
        return not explicit or bool(explicit.intersection(missing))

    def _subscriptions_for_new_channel_entries_v1115(self) -> List[int]:
        entries = list(getattr(self, "_channel_new_entries_v1115", []) or [])
        if not entries:
            return []
        selected = {
            int(value) for value in self._selected_subscriptions
            if str(value).isdigit() and int(value) > 0
        }
        matched_ids = set()
        for subscribe in self._list_subscriptions("N,R"):
            sid = int(getattr(subscribe, "id", 0) or 0)
            if sid not in selected or not self._is_guangya_route(subscribe):
                continue
            for entry in entries:
                try:
                    matched, _ = _entry_match_reason(entry, subscribe)
                except Exception:
                    matched = False
                if not matched:
                    continue
                if not self._entry_can_cover_missing_v1115(entry, subscribe):
                    continue
                matched_ids.add(sid)
                break
        return sorted(matched_ids)

    # ------------------------------------------------------------------
    # 频道批次不碰观影；主动 Pull 的冷却由上层统一调度
    # ------------------------------------------------------------------
    def _claim_external_search_round_v1114(self, subscribe: Any, force: bool = False) -> bool:
        if self._route_source_mode_value_v1115() == "channel_event":
            sid = int(getattr(subscribe, "id", 0) or 0)
            if sid > 0:
                self._external_round_allowed_v1114[sid] = False
            return False
        return super()._claim_external_search_round_v1114(subscribe, force=force)

    def _viewing_due_subscription_ids_v1115(self) -> List[int]:
        state = self._external_search_state_v1114()
        now = time.time()
        cooldown = max(900, int(self._external_search_cooldown_minutes_v1114) * 60)
        selected = {
            int(value) for value in self._selected_subscriptions
            if str(value).isdigit() and int(value) > 0
        }
        due: List[int] = []
        for subscribe in self._list_subscriptions("N,R"):
            sid = int(getattr(subscribe, "id", 0) or 0)
            if sid not in selected or not self._is_guangya_route(subscribe):
                continue
            if not self._is_movie_subscription(subscribe):
                missing = list(self._subscription_missing_episodes(subscribe) or [])
                if not missing:
                    self._finish_subscription_if_complete(subscribe)
                    continue
            row = dict(state.get(str(sid)) or {})
            try:
                last_at = float(row.get("last_at") or 0)
            except (TypeError, ValueError):
                last_at = 0.0
            if not last_at or now - last_at >= cooldown:
                due.append(sid)
        return due

    def _run_v1115_mode_batch(self, batch: List[int], trigger: str, mode: str, force: bool = False) -> None:
        local = getattr(self, "_route_source_local_v1115", None)
        if local is None:
            local = threading.local()
            self._route_source_local_v1115 = local
        had_local = hasattr(local, "mode")
        previous_local = str(getattr(local, "mode", "") or "")
        previous = str(getattr(self, "_route_source_mode_v1115", "") or "")
        local.mode = mode
        # 共享字段继续写入，兼容旧诊断；业务判断统一读取 thread-local helper。
        self._route_source_mode_v1115 = mode
        try:
            try:
                self._inspect_cache.clear()
            except Exception:
                pass
            for sid in batch:
                if not self._runtime_is_current() or not self._enabled:
                    return
                subscribe = self._find_subscription(int(sid or 0))
                if not subscribe or not self._is_guangya_route(subscribe):
                    continue
                self._hydrate_channel_index_for_subscription_v1115(subscribe)
                try:
                    result = self._try_transfer_subscription(
                        subscribe,
                        force=bool(force),
                        refresh_channel=False,
                    )
                    message = str((result or {}).get("message") or "检查完成")
                    self._record_route_health(
                        last_route_result=message[:500],
                        last_route_result_at=self._now_text(),
                        last_async_check_id=int(sid),
                        last_async_trigger=trigger,
                        last_source_mode=mode,
                    )
                    self._plugin_log(
                        "INFO",
                        "【光鸭转存助手】【来源调度】#%s %s mode=%s：%s",
                        sid,
                        getattr(subscribe, "name", ""),
                        mode,
                        message,
                    )
                except Exception as err:
                    self._plugin_log(
                        "EXCEPTION",
                        "【光鸭转存助手】【来源调度】#%s %s mode=%s 异常：%s",
                        sid,
                        getattr(subscribe, "name", ""),
                        mode,
                        err,
                    )
        finally:
            if had_local:
                local.mode = previous_local
            else:
                try:
                    delattr(local, "mode")
                except AttributeError:
                    pass
            self._route_source_mode_v1115 = previous

    def _run_reliability_route_batch(self, batch: List[int], trigger: str) -> None:
        text = str(trigger or "")
        if "频道新增资源" in text:
            return self._run_v1115_mode_batch(batch, trigger, "channel_event", force=False)
        if "观影定时轮询" in text:
            return self._run_v1115_mode_batch(batch, trigger, "viewing_poll", force=False)
        if "新订阅资源匹配" in text:
            return self._run_v1115_mode_batch(batch, trigger, "subscription_prime", force=True)
        return super()._run_reliability_route_batch(batch, trigger)

    # ------------------------------------------------------------------
    # tick：旧实现保留 ABI；v1.12.5 最外层会在 tick 线程内抑制 viewing_ids。
    # ------------------------------------------------------------------
    def _tick(self, host_service: bool = True) -> None:
        if not self._runtime_is_current() or not self._enabled:
            return
        if host_service:
            self._host_tick_heartbeat = time.monotonic()
            self._plugin_log("INFO", "【光鸭转存助手】【服务】宿主定时服务心跳已确认")
        self._install_takeover()
        self.refresh_channels(force=False)

        channel_ids = self._subscriptions_for_new_channel_entries_v1115()
        if channel_ids:
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【频道事件】本轮新增频道资源命中 %s 个订阅；只处理命中项，观影轮询顺延到下一 tick",
                len(channel_ids),
            )
            self._queue_async_route_check(channel_ids, trigger="频道新增资源")
            return

        viewing_ids = self._viewing_due_subscription_ids_v1115()
        if viewing_ids:
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【观影轮询】%s 个仍缺资源的订阅达到搜索冷却时间，进入独立观影轮询",
                len(viewing_ids),
            )
            self._queue_async_route_check(viewing_ids, trigger="观影定时轮询")

    def _startup_check(self) -> None:
        # 启动不再全量消费旧频道索引；按一次普通 tick 恢复频道游标与到期观影轮询即可。
        if not self._runtime_is_current() or not self._enabled:
            return
        return self._tick(host_service=False)

    def _spawn_route_prime(self, sids: Iterable[int], trigger: str = "立即检查") -> None:
        ids = sorted({
            int(value) for value in sids
            if str(value).isdigit() and int(value) > 0
        })
        if not ids or not self._enabled:
            return
        # 新订阅先查 7 天缓存；不为单个订阅强刷频道。force=True 只用于本轮观影立即搜索。
        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【新订阅】%s 个订阅先匹配 7 天频道缓存；未覆盖部分再立即搜索观影，不单独刷新频道",
            len(ids),
        )
        self._queue_async_route_check(ids, trigger="新订阅资源匹配")


__all__ = ["GuangYaChannelEventV1115Mixin"]