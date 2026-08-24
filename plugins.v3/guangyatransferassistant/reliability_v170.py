"""光鸭转存助手 v1.7.0 上线可靠性层。

集中解决三类真实运行问题：
1. 高频 search / API / 消息触发时的后台检查合并与同订阅最多一次补偿重查；
2. 插件热更新/重载后旧实例仍残留事件回调或后台线程时，只允许最新实例继续工作；
3. Telegram 镜像/频道源临时不可用时进入缓存降级 + 指数退避，并自动恢复检查。
"""

from __future__ import annotations

import threading
import time
import weakref
from typing import Any, Dict, Iterable, List

from app.chain.subscribe import SubscribeChain
from app.sdk.events import Event, eventmanager
from app.schemas.types import EventType


class GuangYaReliabilityMixin:
    """必须位于 GuangYaExperienceMixin 之前的最终可靠性 mixin。"""

    build_id = "20260824-r5"
    _channel_retry_base_seconds = 30.0
    _channel_retry_max_seconds = 900.0

    def _ensure_reliability_state(self) -> None:
        if not hasattr(self, "_reliability_lock"):
            self._reliability_lock = threading.RLock()
        if not hasattr(self, "_channel_refresh_lock"):
            self._channel_refresh_lock = threading.Lock()
        if not hasattr(self, "_async_route_active"):
            self._async_route_active: set[int] = set()
        if not hasattr(self, "_async_route_recheck"):
            self._async_route_recheck: set[int] = set()
        if not hasattr(self, "_channel_recovery_timer"):
            self._channel_recovery_timer = None

    def _claim_runtime_owner(self) -> None:
        """把所有热重载实例的唯一所有权锚定到 MoviePilot 稳定类对象上。"""
        self._runtime_generation = f"{time.time_ns()}-{id(self)}"
        SubscribeChain._guangya_runtime_owner_ref = weakref.ref(self)
        SubscribeChain._guangya_runtime_generation = self._runtime_generation

    def _runtime_is_current(self) -> bool:
        ref = getattr(SubscribeChain, "_guangya_runtime_owner_ref", None)
        owner = ref() if callable(ref) else None
        return owner is self and str(getattr(SubscribeChain, "_guangya_runtime_generation", "")) == str(
            getattr(self, "_runtime_generation", "")
        )

    def init_plugin(self, config: dict = None) -> None:
        self._ensure_reliability_state()
        previous_ref = getattr(SubscribeChain, "_guangya_runtime_owner_ref", None)
        previous_generation = getattr(SubscribeChain, "_guangya_runtime_generation", "")
        self._claim_runtime_owner()
        try:
            super().init_plugin(config)
        except Exception:
            # 初始化失败不能让坏实例抢占运行所有权。
            SubscribeChain._guangya_runtime_owner_ref = previous_ref
            SubscribeChain._guangya_runtime_generation = previous_generation
            raise
        self._record_route_health(
            runtime_owner=True,
            runtime_generation=self._runtime_generation,
            runtime_started_at=self._now_text(),
            build=self.build_id,
        )

    @eventmanager.register(EventType.PluginAction)
    def action_event_handler(self, event: Event) -> None:
        """热重载后旧实例即使残留回调，也不再处理旧版消息 action。"""
        if not self._runtime_is_current():
            return
        return super().action_event_handler(event)

    @eventmanager.register(EventType.PluginAction)
    def experience_action_event_handler(self, event: Event) -> None:
        """热重载后旧实例即使残留回调，也不再处理体验层消息 action。"""
        if not self._runtime_is_current():
            return
        return super().experience_action_event_handler(event)

    def _cached_channel_items(self) -> List[Dict[str, Any]]:
        index = self.get_data("channel_index") or {}
        return list(index.get("items") or [])

    def _channel_outage_state(self) -> Dict[str, Any]:
        return dict(self.get_data("channel_outage") or {})

    def _schedule_channel_recovery(self, delay: float) -> None:
        """频道故障后即使没有新的 MP 搜索事件，也会在退避到期后自动尝试恢复。"""
        self._ensure_reliability_state()
        delay = max(1.0, float(delay or 1.0))
        with self._reliability_lock:
            current = self._channel_recovery_timer
            if current and current.is_alive():
                return

            def recover() -> None:
                try:
                    if not self._runtime_is_current() or not self._enabled:
                        return
                    ids = list(sorted(set(int(v) for v in self._selected_subscriptions if int(v or 0) > 0)))
                    if ids:
                        self._plugin_log(
                            "INFO",
                            "【光鸭转存助手】【频道恢复】退避时间已到，自动重新检查 %s 个固定转存订阅",
                            len(ids),
                        )
                        self._queue_async_route_check(ids, trigger="频道故障自动恢复")
                    else:
                        # 没有固定订阅时也刷新一次索引，恢复频道健康状态。
                        self.refresh_channels(force=True)
                finally:
                    with self._reliability_lock:
                        self._channel_recovery_timer = None

            timer = threading.Timer(delay, recover)
            timer.daemon = True
            self._channel_recovery_timer = timer
            timer.start()

    def refresh_channels(self, force: bool = False):
        """频道刷新单飞 + 故障熔断。

        - 同一进程只允许一个频道刷新在跑，其它调用直接复用缓存；
        - 全源失败时保留旧索引，不把固定转存误回退到本地下载；
        - 指数退避后自动恢复，避免镜像故障时被高频 search 打爆。
        """
        self._ensure_reliability_state()
        now = time.time()
        outage = self._channel_outage_state()
        try:
            retry_after = float(outage.get("retry_after") or 0)
        except (TypeError, ValueError):
            retry_after = 0.0
        if retry_after > now:
            wait = max(1, int(retry_after - now))
            self._record_route_health(
                channel_degraded=True,
                channel_retry_after=retry_after,
                channel_retry_seconds=wait,
            )
            return self._cached_channel_items()

        if not self._channel_refresh_lock.acquire(blocking=False):
            self._record_route_health(channel_refresh_coalesced_at=self._now_text())
            return self._cached_channel_items()

        try:
            try:
                entries = super().refresh_channels(force=force)
            except Exception as err:
                last_run = {"success": False, "errors": [str(err)]}
                entries = self._cached_channel_items()
            else:
                last_run = self.get_data("last_run") or {}

            if bool(last_run.get("success")):
                previous_failures = int(outage.get("failures") or 0)
                self.save_data("channel_outage", {
                    "state": "healthy",
                    "failures": 0,
                    "recovered_at": self._now_text(),
                    "retry_after": 0,
                })
                self._record_route_health(
                    channel_degraded=False,
                    channel_failures=0,
                    channel_recovered_at=self._now_text(),
                )
                if previous_failures:
                    self._plugin_log(
                        "INFO",
                        "【光鸭转存助手】【频道恢复】频道源已恢复，结束缓存降级模式（此前连续失败 %s 次）",
                        previous_failures,
                    )
                return entries

            failures = max(1, int(outage.get("failures") or 0) + 1)
            delay = min(
                self._channel_retry_max_seconds,
                self._channel_retry_base_seconds * (2 ** min(failures - 1, 5)),
            )
            retry_at = time.time() + delay
            errors = last_run.get("errors") or []
            self.save_data("channel_outage", {
                "state": "degraded",
                "failures": failures,
                "since": outage.get("since") or self._now_text(),
                "last_failure": self._now_text(),
                "retry_after": retry_at,
                "retry_seconds": int(delay),
                "errors": list(errors)[-5:],
                "cached_items": len(self._cached_channel_items()),
            })
            self._record_route_health(
                channel_degraded=True,
                channel_failures=failures,
                channel_retry_after=retry_at,
            )
            self._plugin_log(
                "WARNING",
                "【光鸭转存助手】【频道降级】频道源连续失败 %s 次，继续使用本地缓存；%s 秒后自动重试，不回退本地下载",
                failures,
                int(delay),
            )
            self._schedule_channel_recovery(delay)
            return entries or self._cached_channel_items()
        finally:
            self._channel_refresh_lock.release()

    def _run_reliability_route_batch(self, batch: List[int], trigger: str) -> None:
        subscriptions = []
        need_refresh = False
        for sid in batch:
            if not self._runtime_is_current() or not self._enabled:
                return
            subscribe = self._find_subscription(sid)
            if not subscribe or not self._is_guangya_route(subscribe):
                continue
            subscriptions.append(subscribe)
            try:
                if not self._cached_matches_for_subscription(subscribe):
                    need_refresh = True
            except Exception:
                need_refresh = True

        if need_refresh and subscriptions:
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【后台合并】%s：%s 个订阅统一执行一次频道检查",
                trigger,
                len(subscriptions),
            )
            self.refresh_channels(force=True)

        try:
            self._inspect_cache.clear()
        except Exception:
            pass

        for subscribe in subscriptions:
            if not self._runtime_is_current() or not self._enabled:
                return
            sid = int(getattr(subscribe, "id", 0) or 0)
            try:
                result = self._try_transfer_subscription(subscribe, refresh_channel=False)
                message = str(result.get("message") or "检查完成")
                self._record_route_health(
                    last_route_result=message[:500],
                    last_route_result_at=self._now_text(),
                    last_async_check_id=sid,
                    last_async_trigger=trigger,
                )
                self._plugin_log(
                    "INFO",
                    "【光鸭转存助手】【后台检查】#%s %s：%s",
                    sid,
                    getattr(subscribe, "name", ""),
                    message,
                )
            except Exception as err:
                self._plugin_log(
                    "EXCEPTION",
                    "【光鸭转存助手】【后台检查】#%s %s 异常：%s",
                    sid,
                    getattr(subscribe, "name", ""),
                    err,
                )

    def _queue_async_route_check(self, sids: Iterable[int], trigger: str = "后台检查") -> None:
        """可靠的后台检查合并器：同一订阅执行期间最多只保留一次补偿重查。"""
        self._ensure_reliability_state()
        ids = {
            int(value) for value in sids
            if str(value).isdigit() and int(value) > 0
        }
        if not ids or not self._enabled or not self._runtime_is_current():
            return

        with self._async_route_lock:
            active_hits = ids.intersection(self._async_route_active)
            if active_hits:
                self._async_route_recheck.update(active_hits)
            self._async_route_pending.update(ids - active_hits)
            if self._async_route_worker_running:
                return
            if not self._async_route_pending:
                return
            self._async_route_worker_running = True

        def worker() -> None:
            try:
                time.sleep(float(getattr(self, "_async_route_debounce", 0.25) or 0.25))
                while self._enabled and self._runtime_is_current():
                    with self._async_route_lock:
                        batch = sorted(self._async_route_pending)
                        self._async_route_pending.clear()
                        self._async_route_active = set(batch)
                    if not batch:
                        break

                    self._run_reliability_route_batch(batch, trigger)

                    with self._async_route_lock:
                        self._async_route_active.clear()
                        if self._async_route_recheck:
                            self._async_route_pending.update(self._async_route_recheck)
                            self._async_route_recheck.clear()
                        has_more = bool(self._async_route_pending)
                    if not has_more:
                        break
                    time.sleep(0.05)
            finally:
                relaunch: List[int] = []
                with self._async_route_lock:
                    self._async_route_active.clear()
                    self._async_route_worker_running = False
                    if self._async_route_recheck:
                        self._async_route_pending.update(self._async_route_recheck)
                        self._async_route_recheck.clear()
                    if self._async_route_pending and self._enabled and self._runtime_is_current():
                        relaunch = sorted(self._async_route_pending)
                # 关键修复：补偿启动必须带真实 ID，不能用空列表，否则队列会永久卡住。
                if relaunch:
                    self._queue_async_route_check(relaunch, trigger="后台合并补偿")

        threading.Thread(target=worker, name="GuangYaReliableRouteCheck", daemon=True).start()

    def _diagnose_subscription(self, subscribe: Any) -> Dict[str, Any]:
        row = dict(super()._diagnose_subscription(subscribe))
        outage = self._channel_outage_state()
        if str(outage.get("state") or "") == "degraded" and not row.get("pending_jobs"):
            try:
                retry_after = float(outage.get("retry_after") or 0)
                wait = max(0, int(retry_after - time.time()))
            except (TypeError, ValueError):
                wait = 0
            if not row.get("matches"):
                row["reason"] = (
                    f"频道源暂时不可用，正在使用本地缓存降级；约 {wait} 秒后自动恢复检查。"
                    "固定分流仍生效，不会因此转为本地下载"
                )
                row["severity"] = "warning"
        return row

    def _build_selfcheck(self) -> Dict[str, Any]:
        report = dict(super()._build_selfcheck())
        checks = list(report.get("checks") or [])
        owner_ok = self._runtime_is_current()
        checks.append({
            "key": "runtime_owner",
            "label": "热重载实例所有权",
            "ok": owner_ok,
            "detail": "当前实例为唯一运行所有者" if owner_ok else "当前实例已被新版本替代",
            "critical": True,
        })
        outage = self._channel_outage_state()
        degraded = str(outage.get("state") or "") == "degraded"
        if degraded:
            try:
                wait = max(0, int(float(outage.get("retry_after") or 0) - time.time()))
            except (TypeError, ValueError):
                wait = 0
            detail = (
                f"缓存降级中，连续失败 {int(outage.get('failures') or 0)} 次，"
                f"缓存 {int(outage.get('cached_items') or 0)} 条，约 {wait} 秒后自动重试"
            )
        else:
            detail = "频道刷新健康，故障熔断未触发"
        checks.append({
            "key": "channel_circuit",
            "label": "频道故障降级/恢复",
            "ok": not degraded,
            "detail": detail,
            "critical": False,
        })
        report["checks"] = checks
        report["healthy"] = not any(item.get("critical") and not item.get("ok") for item in checks)
        report["build"] = self.build_id
        report["channel_degraded"] = degraded
        return report

    def get_page(self):
        pages = list(super().get_page() or [])
        outage = self._channel_outage_state()
        if str(outage.get("state") or "") != "degraded":
            return pages
        try:
            wait = max(0, int(float(outage.get("retry_after") or 0) - time.time()))
        except (TypeError, ValueError):
            wait = 0
        alert = {
            "component": "VAlert",
            "props": {
                "type": "warning",
                "variant": "tonal",
                "class": "mb-3",
                "title": "频道源暂时不可用 · 已进入缓存降级",
                "text": (
                    f"连续失败 {int(outage.get('failures') or 0)} 次，仍保留本地频道索引，"
                    f"约 {wait} 秒后自动重试。光鸭固定分流和本地下载断路器继续生效，不会静默回退。"
                ),
            },
        }
        return [alert, *pages]

    def stop_service(self) -> None:
        self._ensure_reliability_state()
        with self._reliability_lock:
            timer = self._channel_recovery_timer
            self._channel_recovery_timer = None
        if timer and timer.is_alive():
            try:
                timer.cancel()
            except Exception:
                pass
        current = self._runtime_is_current()
        try:
            return super().stop_service()
        finally:
            if current and self._runtime_is_current():
                SubscribeChain._guangya_runtime_owner_ref = None
                SubscribeChain._guangya_runtime_generation = ""


__all__ = ["GuangYaReliabilityMixin"]
