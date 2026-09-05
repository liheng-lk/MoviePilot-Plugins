"""v1.12.15：频道缓存被动补偿 + 新订阅频道预热。

严格频道游标只回答“这一轮是不是新消息”，7 天频道缓存回答“资源现在是否已经存在”。
旧实现只把严格新消息送入 channel_event，因此在首次建立游标、插件重启/bootstrap、
或事件触发被后台合并等情况下，会出现“频道缓存明明已有可用资源，但已有订阅没有再进入转存”的空窗。

另一个实机空窗发生在“资源先发、订阅后加”：新增订阅过去虽然会在本地缓存未命中时
``refresh_channels(force=True)``，但底层刷新仍受 Telegram message cursor 约束；如果目标资源
位于当前游标之前、又从未进入 7 天缓存，强刷也可能只得到游标之后/当前页资源，最终误表现为
“本地频道没有”。v1.12.15 因此把新增订阅顺序收口为：

1. 先强刷全部配置频道，把本轮可见资源写入 7 天 cache；
2. 再匹配刚新增的订阅；
3. 若仍未命中且频道刷新健康，则按现有 ``_history_pages`` 对配置频道做一次有界历史回溯，
   复用现有频道解析器并把回溯结果写入 7 天 cache；
4. 历史回溯只补 cache，不推进/回退 ``channel_cursors``，也不把旧消息伪造成新事件；
5. 完成预热后才把新增订阅送入既有 ``subscription_prime`` 执行链。

本层不把频道变成主动资源站搜索器。所有频道命中仍服从以下边界：
- 不访问 GYING，不消耗外部检索冷却；
- 不绕过媒体身份、质量、MoviePilot library missing、reservation/source claim；
- 不绕过 v1.12.14 物理文件 episodes ⊆ allowed missing；
- 不改变来源优先级和 Magnet/ED2K 的光鸭 cloudcollection 路线。
"""
from __future__ import annotations

import threading
from typing import Any, Dict, Iterable, List, Set, Tuple

from . import legacy as _legacy_module
from .channel_event_v1115 import _entry_key_v1115
from .core_pipeline_final_v11214 import GuangYaCorePipelineFinalV11214Mixin


class GuangYaChannelReconcileV11215Mixin(GuangYaCorePipelineFinalV11214Mixin):
    """让“频道已有资源”成为可恢复事实，并保证新订阅先预热频道再匹配。"""

    plugin_version = "1.12.15"
    build_id = "20260906-r62"
    _channel_prime_wait_seconds_v11215 = 5.0
    _channel_prime_history_pages_cap_v11215 = 20

    @staticmethod
    def _channel_entry_actionable_v11215(entry: Dict[str, Any]) -> bool:
        row = dict(entry or {})
        if row.get("stale"):
            return False
        if str(row.get("share_url") or "").strip():
            return True
        for raw in row.get("xunlei_sources") or []:
            if not isinstance(raw, dict):
                continue
            if str(raw.get("share_id") or raw.get("identity") or raw.get("uri") or "").strip():
                return True
        for raw in row.get("external_sources") or []:
            if not isinstance(raw, dict):
                continue
            source_type = str(raw.get("type") or "").strip().lower()
            if source_type not in {"magnet", "ed2k", "xunlei"}:
                continue
            if str(raw.get("identity") or raw.get("uri") or "").strip():
                return True
        return False

    def _channel_passive_gap_v11215(self, subscribe: Any) -> Tuple[Any, ...]:
        """仅用于决定要不要进入 channel_event；最终写盘仍由既有硬栅栏决定。"""
        try:
            if self._is_movie_subscription(subscribe):
                return ("movie",) if bool(self._movie_needs_pull_v1125(subscribe)) else tuple()
            values = self._uncovered_missing_v1125(subscribe) or set()
        except Exception as err:
            self._plugin_log(
                "WARNING",
                "【光鸭转存助手】【频道补偿v1.12.15】#%s %s 读取真实未覆盖缺口失败，补偿触发 fail closed：%s",
                int(getattr(subscribe, "id", 0) or 0),
                str(getattr(subscribe, "name", "") or ""),
                str(err)[:220],
            )
            return tuple()
        result: Set[int] = set()
        for raw in values:
            try:
                value = int(raw or 0)
            except (TypeError, ValueError):
                continue
            if value > 0:
                result.add(value)
        return tuple(sorted(result))

    def _cached_actionable_channel_matches_v11215(self, subscribe: Any) -> List[Dict[str, Any]]:
        matches: List[Dict[str, Any]] = []
        seen: Set[str] = set()
        try:
            pairs: Iterable[Any] = self._cached_matches_for_subscription(subscribe) or []
        except Exception as err:
            self._plugin_log(
                "WARNING",
                "【光鸭转存助手】【频道补偿v1.12.15】#%s %s 读取频道缓存匹配失败：%s",
                int(getattr(subscribe, "id", 0) or 0),
                str(getattr(subscribe, "name", "") or ""),
                str(err)[:220],
            )
            return []

        for item in pairs:
            if isinstance(item, (tuple, list)) and item:
                raw = item[0]
            else:
                raw = item
            if not isinstance(raw, dict):
                continue
            row = dict(raw)
            if not self._channel_entry_actionable_v11215(row):
                continue
            try:
                if not bool(self._entry_can_cover_missing_v1115(row, subscribe)):
                    continue
            except Exception:
                continue
            key = _entry_key_v1115(row)
            if not key:
                key = str(row.get("resource_group_id") or row.get("message_id") or row.get("share_url") or "").strip()
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            matches.append(row)
        return matches

    @staticmethod
    def _channel_label_v11215(source_url: str) -> str:
        return "光鸭云盘影视热更频道" if "regeng" in str(source_url or "").lower() else "光鸭云盘资源分享频道"

    def _channel_refresh_healthy_v11215(self) -> bool:
        """只有本轮频道抓取明确健康时才追加历史回溯，避免绕过 Reliability 退避。"""
        try:
            outage = dict(self.get_data("channel_outage") or {})
        except Exception:
            outage = {}
        if str(outage.get("state") or "").lower() not in {"", "healthy"}:
            return False
        try:
            last_run = dict(self.get_data("last_run") or {})
        except Exception:
            last_run = {}
        if "success" in last_run and not bool(last_run.get("success")):
            return False
        return True

    def _wait_for_channel_refresh_v11215(self) -> None:
        """若强刷被 Reliability 单飞合并，短等正在进行的刷新结束后再读 cache。"""
        lock = getattr(self, "_channel_refresh_lock", None)
        if lock is None or not getattr(lock, "locked", lambda: False)():
            return
        try:
            acquired = bool(lock.acquire(timeout=float(self._channel_prime_wait_seconds_v11215)))
        except Exception:
            acquired = False
        if acquired:
            try:
                pass
            finally:
                try:
                    lock.release()
                except Exception:
                    pass

    def _history_backfill_for_subscriptions_v11215(self, subscriptions: Iterable[Any]) -> Dict[str, Any]:
        """有界回溯配置频道并只补 7 天 cache；不修改严格事件游标。"""
        pending: Dict[int, Any] = {}
        for subscribe in subscriptions or []:
            sid = int(getattr(subscribe, "id", 0) or 0)
            if sid <= 0:
                continue
            if not self._channel_passive_gap_v11215(subscribe):
                continue
            if self._cached_actionable_channel_matches_v11215(subscribe):
                continue
            pending[sid] = subscribe
        if not pending:
            return {"pages": 0, "rows": 0, "cached": 0, "matched_ids": [], "errors": []}

        lock = getattr(self, "_channel_prime_backfill_lock_v11215", None)
        if lock is None:
            lock = threading.Lock()
            self._channel_prime_backfill_lock_v11215 = lock
        if not lock.acquire(blocking=False):
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【新订阅频道预热v1.12.15】已有历史回溯在执行，本批不重复请求；稍后由频道缓存补偿继续匹配",
            )
            return {"pages": 0, "rows": 0, "cached": 0, "matched_ids": [], "errors": ["coalesced"]}

        discovered: List[Dict[str, Any]] = []
        errors: List[str] = []
        matched_ids: Set[int] = set()
        pages_total = 0
        try:
            source_urls = list(self._source_urls() or [])
            page_limit = max(1, int(getattr(self, "_history_pages", 1) or 1))
            page_limit = min(page_limit, max(1, int(self._channel_prime_history_pages_cap_v11215)))
            extractor = getattr(_legacy_module, "_extract_channel_entries", None)
            pager = getattr(_legacy_module, "_extract_pagination_urls", None)
            request_cls = getattr(_legacy_module, "RequestUtils", None)
            settings_obj = getattr(_legacy_module, "settings", None)
            if not callable(extractor) or not callable(pager) or request_cls is None:
                return {"pages": 0, "rows": 0, "cached": 0, "matched_ids": [], "errors": ["channel parser unavailable"]}

            for source_url in source_urls:
                if not pending:
                    break
                queue = [str(source_url)]
                visited: Set[str] = set()
                source_pages = 0
                label = self._channel_label_v11215(str(source_url))
                while queue and source_pages < page_limit and pending:
                    page_url = str(queue.pop(0) or "").strip()
                    if not page_url or page_url in visited:
                        continue
                    visited.add(page_url)
                    try:
                        if bool(getattr(self, "_proxy", False)) and settings_obj is not None:
                            request = request_cls(proxies=getattr(settings_obj, "PROXY", None))
                        else:
                            request = request_cls()
                        response = request.get_res(page_url)
                        status = int(getattr(response, "status_code", 200) or 200) if response is not None else 0
                        if response is None or status >= 400:
                            errors.append(f"{label}: HTTP {status or 'no-response'}")
                            continue
                        page_html = str(getattr(response, "text", "") or "")
                        rows = [dict(row) for row in (extractor(page_html, str(source_url), label) or []) if isinstance(row, dict)]
                    except Exception as err:
                        errors.append(f"{label}: {str(err)[:160]}")
                        continue

                    source_pages += 1
                    pages_total += 1
                    discovered.extend(rows)

                    for sid, subscribe in list(pending.items()):
                        for row in rows:
                            if not self._channel_entry_actionable_v11215(row):
                                continue
                            try:
                                matched, _ = _legacy_module._entry_match_reason(row, subscribe)
                            except Exception:
                                matched = False
                            if not matched:
                                continue
                            try:
                                if not bool(self._entry_can_cover_missing_v1115(row, subscribe)):
                                    continue
                            except Exception:
                                continue
                            matched_ids.add(sid)
                            pending.pop(sid, None)
                            break

                    if pending and source_pages < page_limit:
                        try:
                            next_urls = list(pager(page_html, str(source_url)) or [])
                        except Exception:
                            next_urls = []
                        for next_url in next_urls:
                            value = str(next_url or "").strip()
                            if value and value not in visited and value not in queue and len(queue) < page_limit * 4:
                                queue.append(value)

            before = set()
            try:
                before = set((self._channel_cache_v1115().get("items") or {}).keys())
            except Exception:
                before = set()
            if discovered:
                self._refresh_channel_cache_v1115(discovered)
            after = set()
            try:
                after = set((self._channel_cache_v1115().get("items") or {}).keys())
            except Exception:
                after = before
            cached = max(0, len(after - before))
            return {
                "pages": pages_total,
                "rows": len(discovered),
                "cached": cached,
                "matched_ids": sorted(matched_ids),
                "errors": errors[:8],
            }
        finally:
            lock.release()

    def _spawn_route_prime(self, sids: Iterable[int], trigger: str = "立即检查") -> None:
        """新增订阅必须先拉配置频道、再匹配 cache；必要时回溯游标之前的频道历史。"""
        normalizer = getattr(self, "_positive_ids_v1125", None)
        if callable(normalizer):
            ids = sorted(normalizer(sids or []))
        else:
            ids = sorted({int(value) for value in (sids or []) if str(value).isdigit() and int(value) > 0})
        if not ids or not bool(getattr(self, "_enabled", False)):
            return

        subscriptions: List[Any] = []
        for sid in ids:
            subscribe = self._find_subscription(int(sid or 0))
            if subscribe and self._is_guangya_route(subscribe):
                subscriptions.append(subscribe)
        if not subscriptions:
            return

        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【新订阅频道预热v1.12.15】新增 %s 个固定分流订阅：先强刷全部配置频道，再读取 7 天本地缓存匹配",
            len(subscriptions),
        )
        try:
            self.refresh_channels(force=True)
        except Exception as err:
            self._plugin_log(
                "WARNING",
                "【光鸭转存助手】【新订阅频道预热v1.12.15】配置频道强刷异常；当前只能使用已有缓存，不能据此判定频道无资源：%s",
                str(err)[:260],
            )
        self._wait_for_channel_refresh_v11215()

        missing_after_refresh = [
            subscribe for subscribe in subscriptions
            if not self._cached_actionable_channel_matches_v11215(subscribe)
        ]
        hit_count = len(subscriptions) - len(missing_after_refresh)
        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【新订阅频道预热v1.12.15】配置频道强刷后缓存命中 %s/%s；未命中 %s 个",
            hit_count,
            len(subscriptions),
            len(missing_after_refresh),
        )

        if missing_after_refresh:
            if self._channel_refresh_healthy_v11215():
                self._plugin_log(
                    "INFO",
                    "【光鸭转存助手】【新订阅频道预热v1.12.15】增量/当前页仍未命中 %s 个订阅，开始按配置 history_pages 有界回溯游标之前的频道历史；历史只写 cache、不生成新事件",
                    len(missing_after_refresh),
                )
                stats = self._history_backfill_for_subscriptions_v11215(missing_after_refresh)
                remaining = [
                    subscribe for subscribe in missing_after_refresh
                    if not self._cached_actionable_channel_matches_v11215(subscribe)
                ]
                self._plugin_log(
                    "INFO",
                    "【光鸭转存助手】【新订阅频道预热v1.12.15】历史回溯完成：pages=%s rows=%s 新增缓存=%s，回溯后新增命中 %s/%s；剩余 %s 个仍未在本地缓存命中",
                    int(stats.get("pages") or 0),
                    int(stats.get("rows") or 0),
                    int(stats.get("cached") or 0),
                    len(missing_after_refresh) - len(remaining),
                    len(missing_after_refresh),
                    len(remaining),
                )
            else:
                self._plugin_log(
                    "WARNING",
                    "【光鸭转存助手】【新订阅频道预热v1.12.15】频道当前处于失败/退避状态，跳过额外历史回溯；“本地缓存未命中”不等于“频道没有资源”",
                )

        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【新订阅频道预热v1.12.15】频道预热完成，现进入既有 subscription_prime：频道优先；频道仍未覆盖时才按更新日历决定主动完整来源链",
        )
        self._queue_async_route_check(
            [int(getattr(subscribe, "id", 0) or 0) for subscribe in subscriptions],
            trigger="新订阅资源匹配",
        )

    def _subscriptions_for_new_channel_entries_v1115(self) -> List[int]:
        """严格新事件优先，再补回缓存中已经存在但尚未消费成功的真实资源。"""
        immediate = {
            int(value) for value in (super()._subscriptions_for_new_channel_entries_v1115() or [])
            if str(value).isdigit() and int(value) > 0
        }
        reconciled: Set[int] = set()
        diagnostics: List[str] = []

        try:
            subscriptions = list(self._active_selected_subscriptions_v1125() or [])
        except Exception:
            subscriptions = []

        for subscribe in subscriptions:
            sid = int(getattr(subscribe, "id", 0) or 0)
            if sid <= 0 or sid in immediate:
                continue
            gap = self._channel_passive_gap_v11215(subscribe)
            if not gap:
                continue
            matches = self._cached_actionable_channel_matches_v11215(subscribe)
            if not matches:
                continue
            reconciled.add(sid)
            diagnostics.append(
                f"#{sid}:{str(getattr(subscribe, 'name', '') or '')[:80]} gap={list(gap)} cache={len(matches)}"
            )

        if reconciled:
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【频道补偿v1.12.15】频道缓存已有可执行资源但未形成新事件，补偿触发 %s 个仍有真实缺口的订阅：%s",
                len(reconciled),
                "；".join(diagnostics[:12]),
            )
        return sorted(immediate | reconciled)


__all__ = ["GuangYaChannelReconcileV11215Mixin"]
