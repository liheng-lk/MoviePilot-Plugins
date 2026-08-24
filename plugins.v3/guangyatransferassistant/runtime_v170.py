"""光鸭转存助手 v1.7.0 最终运行编排层。

把 legacy/routing/experience/reliability 已有能力统一收口到一个运行语义：
- 宿主 scheduler takeover 与 SubscribeChain.search 一样只做硬分流，绝不在搜索线程同步跑网盘转存；
- 所有周期批量检查统一进入可靠后台合并队列；
- 旧热重载实例的 tick/刷新/新转存入口与内置守护线程全部失效；
- scheduler takeover 跨热重载会追溯真实 MoviePilot 原回调，不形成“旧插件回调链”；
- 修正频道自动恢复定时器自我占用导致“只重试一次”的边界；
- 诊断按媒体事实键读取 transfer_jobs，避免任务明明待落盘却显示 0。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

from app.chain.subscribe import SubscribeChain


class GuangYaRuntimeFinalizerMixin:
    """位于 GuangYaReliabilityMixin 之前的最终运行编排。"""

    build_id = "20260824-r7"

    def _schedule_channel_recovery(self, delay: float) -> None:
        """可连续重试的恢复定时器。

        旧实现的 timer 在 recover 回调内部仍处于 alive 状态；若本次恢复再次失败，
        refresh_channels() 想安排下一轮时会被“已有 timer”判断挡住。这里在真正发起恢复前
        先释放当前 timer 槽位，因此每次失败都能继续按指数退避安排下一轮。
        """
        self._ensure_reliability_state()
        delay = max(1.0, float(delay or 1.0))
        with self._reliability_lock:
            current = self._channel_recovery_timer
            if current and current.is_alive():
                return

            timer = None

            def recover() -> None:
                with self._reliability_lock:
                    if self._channel_recovery_timer is timer:
                        self._channel_recovery_timer = None
                if not self._runtime_is_current() or not self._enabled:
                    return
                ids = list(sorted(set(
                    int(value) for value in self._selected_subscriptions
                    if str(value).isdigit() and int(value) > 0
                )))
                if ids:
                    self._plugin_log(
                        "INFO",
                        "【光鸭转存助手】【频道恢复】退避到期，自动重新检查 %s 个固定转存订阅",
                        len(ids),
                    )
                    self._queue_async_route_check(ids, trigger="频道故障自动恢复")
                else:
                    self.refresh_channels(force=True)

            timer = threading.Timer(delay, recover)
            timer.daemon = True
            self._channel_recovery_timer = timer
            timer.start()

    def _unwrap_takeover_original(self, job_id: str, func: Any) -> Any:
        """沿旧插件实例的 _takeover_originals 追溯真正 MoviePilot 原调度函数。"""
        current = func
        seen = set()
        for _ in range(8):
            marker = id(current)
            if marker in seen:
                break
            seen.add(marker)
            owner = getattr(current, "__self__", None)
            if owner is None or owner is self:
                break
            mapping = getattr(owner, "_takeover_originals", None)
            if not isinstance(mapping, dict):
                break
            candidate = mapping.get(job_id)
            if candidate is None or candidate is current:
                break
            current = candidate
        return current

    def _install_takeover(self) -> None:
        """安装 scheduler takeover，并修正热重载产生的旧实例回调链。"""
        if not self._runtime_is_current() or not self._enabled:
            return
        super()._install_takeover()
        originals = dict(getattr(self, "_takeover_originals", {}) or {})
        for job_id, original in originals.items():
            unwrapped = self._unwrap_takeover_original(job_id, original)
            if unwrapped is original:
                continue
            self._takeover_originals[job_id] = unwrapped
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【热重载】%s 已从旧插件回调链追溯到 MoviePilot 原调度函数",
                job_id,
            )

    def refresh_channels(self, force: bool = False):
        """旧热重载实例不再触碰频道索引或外部网络。"""
        if hasattr(self, "_runtime_generation") and not self._runtime_is_current():
            return self._cached_channel_items()
        return super().refresh_channels(force=force)

    def _runtime_worker_loop(self, generation: int) -> None:
        """内置守护使用稳定 runtime owner，而不是仅依赖热重载后会重建的 Python class generation。"""
        stop = getattr(self, "_runtime_stop", None)
        if stop is None:
            return
        if stop.wait(1.5):
            return
        if not self._runtime_is_current() or not self._enabled:
            return
        try:
            self._plugin_log("INFO", "【光鸭转存助手】【启动检查】内置守护开始首轮缓存检查")
            self._startup_check()
        except Exception as err:
            self._plugin_log("EXCEPTION", "【光鸭转存助手】【启动检查】内置守护首轮执行异常：%s", err)

        while self._enabled and self._runtime_is_current():
            interval = max(60, int(self._refresh_minutes or 5) * 60)
            if stop.wait(interval):
                return
            if not self._runtime_is_current() or not self._enabled:
                return
            heartbeat = float(getattr(self, "_host_tick_heartbeat", 0.0) or 0.0)
            if heartbeat and (time.monotonic() - heartbeat) < interval * 1.5:
                continue
            try:
                self._plugin_log(
                    "WARNING",
                    "【光鸭转存助手】【服务回退】未检测到宿主定时服务心跳，内置守护执行本轮检查；无需手动保存配置",
                )
                self._tick(host_service=False)
            except Exception as err:
                self._plugin_log("EXCEPTION", "【光鸭转存助手】【服务回退】内置守护执行异常：%s", err)

    def _startup_check(self) -> None:
        if not self._runtime_is_current() or not self._enabled:
            return
        return super()._startup_check()

    def _tick(self, host_service: bool = True) -> None:
        """宿主/内置定时器只允许最新实例执行。"""
        if not self._runtime_is_current() or not self._enabled:
            return
        return super()._tick(host_service=host_service)

    def _process_selected_subscriptions(
        self,
        trigger: str = "后台检查",
        refresh_channel: bool = False,
    ) -> List[Dict[str, Any]]:
        """所有批量周期处理统一排入后台，不再和 search/tick 并发直接提交转存。"""
        if not self._runtime_is_current() or not self._enabled:
            return []
        ids = []
        rows = []
        for raw_sid in list(self._selected_subscriptions):
            try:
                sid = int(raw_sid)
            except (TypeError, ValueError):
                continue
            subscribe = self._find_subscription(sid)
            if not subscribe:
                continue
            state = str(getattr(subscribe, "state", "") or "")
            if state not in ("N", "R"):
                rows.append({
                    "subscribe_id": sid,
                    "success": True,
                    "handled": True,
                    "queued": False,
                    "message": f"订阅状态 {state or '-'} 非活跃，固定路线保留但不执行",
                })
                continue
            ids.append(sid)
            rows.append({
                "subscribe_id": sid,
                "success": True,
                "handled": True,
                "queued": True,
                "message": "已进入光鸭后台合并队列",
            })
        if ids:
            self._queue_async_route_check(ids, trigger=trigger)
        return rows

    def _dispatch_subscribe_search(
        self,
        sid: Optional[int] = None,
        state: Optional[str] = "R",
        manual: Optional[bool] = False,
        progress_callback=None,
    ):
        """宿主 scheduler takeover 的最终固定分流。

        固定转存订阅：只排后台光鸭检查并立即返回。
        普通订阅：继续交给 MoviePilot SubscribeChain.search。
        """
        if not self._runtime_is_current() or not self._enabled:
            return True

        selected = set(int(value) for value in self._selected_subscriptions if str(value).isdigit())
        if sid:
            current_sid = int(sid)
            if current_sid in selected:
                subscribe = self._find_subscription(current_sid)
                if subscribe and str(getattr(subscribe, "state", "") or "") in ("N", "R"):
                    self._queue_async_route_check([current_sid], trigger="宿主订阅搜索分流")
                    self._plugin_log(
                        "INFO",
                        "【光鸭转存助手】【调度分流】#%s %s 已阻断原生搜索并转入后台光鸭检查",
                        current_sid,
                        getattr(subscribe, "name", ""),
                    )
                else:
                    self._plugin_log(
                        "INFO",
                        "【光鸭转存助手】【调度分流】固定转存 #%s 不存在或非活跃；仍阻断原生下载",
                        current_sid,
                    )
                if progress_callback:
                    progress_callback(value=100, text="固定转存订阅已交由光鸭后台检查")
                return True
            return SubscribeChain().search(
                sid=current_sid,
                state=state,
                manual=manual,
                progress_callback=progress_callback,
            )

        route_ids: List[int] = []
        native_ids: List[int] = []
        subscriptions = self._list_subscriptions(state or "N,R")
        for subscribe in subscriptions:
            current_sid = int(getattr(subscribe, "id", 0) or 0)
            if not current_sid:
                continue
            if current_sid in selected:
                route_ids.append(current_sid)
            else:
                native_ids.append(current_sid)

        if route_ids:
            self._queue_async_route_check(route_ids, trigger="宿主批量订阅搜索分流")
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【调度分流】批量阻断 %s 个固定转存订阅的原生搜索；后台统一检查",
                len(route_ids),
            )

        for index, native_sid in enumerate(native_ids):
            SubscribeChain().search(
                sid=native_sid,
                state=None,
                manual=manual,
                progress_callback=progress_callback if index == 0 else None,
            )
        if progress_callback and not native_ids:
            progress_callback(value=100, text="固定转存订阅已全部交由光鸭后台检查")
        return True

    def _try_transfer_subscription(
        self,
        subscribe: Any,
        force: bool = False,
        refresh_channel: bool = True,
    ) -> Dict[str, Any]:
        """旧热重载实例不得再启动新的分享检查/转存提交。"""
        if not self._runtime_is_current():
            return {
                "success": True,
                "handled": True,
                "stale_instance": True,
                "message": "旧插件实例已被新版本接管，本次不再执行转存",
            }
        return super()._try_transfer_subscription(
            subscribe,
            force=force,
            refresh_channel=refresh_channel,
        )

    def _diagnose_subscription(self, subscribe: Any) -> Dict[str, Any]:
        """使用 legacy 真正的 media fact key 关联任务，修正待落盘/失败数显示。"""
        row = dict(super()._diagnose_subscription(subscribe))
        prefix = self._media_fact_prefix(subscribe)
        jobs = [
            dict(item) for item in (self.get_data("transfer_jobs") or {}).values()
            if isinstance(item, dict) and str(item.get("media") or "") == str(prefix)
        ]
        pending_status = {"submitting", "submitted", "task_confirmed", "verifying"}
        pending = [item for item in jobs if str(item.get("status") or "") in pending_status]
        failed = [item for item in jobs if str(item.get("status") or "") == "failed"]
        row["pending_jobs"] = len(pending)
        row["failed_jobs"] = len(failed)
        if pending:
            row["reason"] = f"已有 {len(pending)} 个转存任务已提交，正在等待光鸭落盘确认"
            row["severity"] = "info"
        elif failed and not row.get("matches"):
            latest = sorted(failed, key=lambda item: str(item.get("updated") or ""))[-1]
            detail = str(latest.get("error") or latest.get("message") or "未知错误")[:180]
            row["reason"] = f"最近转存任务失败：{detail}"
            row["severity"] = "error"
        return row


__all__ = ["GuangYaRuntimeFinalizerMixin"]
