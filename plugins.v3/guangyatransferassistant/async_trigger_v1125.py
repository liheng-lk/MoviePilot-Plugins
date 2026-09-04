"""v1.12.5 异步路由触发上下文保持。

旧 Reliability 队列按订阅 ID 合并任务，但 worker 只捕获启动它的一个 `trigger` 字符串。
当 250ms debounce / worker 执行期间同时到达“频道新增资源、更新日历、新订阅、人工操作”等
不同来源时，后加入的订阅可能被错误地套用第一个任务的 trigger：例如 AiringDue 被当成
channel_event 从而不搜索 GYING，或频道事件被当成主动 Pull 而意外访问观影。

本层放在 Governance 之后、Reliability 队列之前：Governance 先过滤真正要入队的 ID，
这里再为每个 ID 保存其真实 trigger；Reliability 继续负责原有单 worker、pending/active/recheck
与热重载安全。最终 DispatchPolicy 在执行批次时取回 trigger 并按真实来源分组。
"""
from __future__ import annotations

import threading
from typing import Dict, Iterable, List


class GuangYaAsyncTriggerV1125Mixin:
    """只保存异步队列来源意图，不改变底层队列所有权和业务执行。"""

    build_id = "20260904-r51-preview"
    _async_trigger_bucket_limit_v1125 = 8

    def init_plugin(self, config: dict = None) -> None:
        self._async_trigger_lock_v1125 = threading.RLock()
        self._async_route_triggers_v1125: Dict[int, List[str]] = {}
        return super().init_plugin(config)

    @staticmethod
    def _normalize_async_ids_v1125(values: Iterable[int]) -> List[int]:
        result = set()
        for raw in values or []:
            try:
                value = int(raw or 0)
            except (TypeError, ValueError):
                continue
            if value > 0:
                result.add(value)
        return sorted(result)

    def _queue_async_route_check(self, sids: Iterable[int], trigger: str = "后台检查") -> None:
        ids = self._normalize_async_ids_v1125(sids)
        if not ids or not bool(getattr(self, "_enabled", False)):
            return
        current = getattr(self, "_runtime_is_current", None)
        if callable(current) and not bool(current()):
            return

        text = str(trigger or "后台检查")
        lock = getattr(self, "_async_trigger_lock_v1125", None)
        if lock is None:
            lock = threading.RLock()
            self._async_trigger_lock_v1125 = lock
        store = getattr(self, "_async_route_triggers_v1125", None)
        if not isinstance(store, dict):
            store = {}
            self._async_route_triggers_v1125 = store

        with lock:
            for sid in ids:
                bucket = list(store.get(sid) or [])
                # Reliability 的极窄 finally 竞态会以“后台合并补偿”重新拉起已经在 pending
                # 的 ID；若真实 trigger 仍在桶里，不能让这个内部占位名覆盖业务来源。
                if text == "后台合并补偿" and bucket:
                    continue
                if text not in bucket:
                    bucket.append(text)
                limit = max(2, int(getattr(self, "_async_trigger_bucket_limit_v1125", 8) or 8))
                store[sid] = bucket[-limit:]

        return super()._queue_async_route_check(ids, trigger=text)

    @staticmethod
    def _ordered_trigger_values_v1125(values: Iterable[str], fallback: str) -> List[str]:
        rows: List[str] = []
        for raw in values or []:
            value = str(raw or "").strip()
            if value and value not in rows:
                rows.append(value)
        if not rows:
            rows = [str(fallback or "后台检查")]

        # 新订阅自身已经定义“频道 -> 当前应播 Pull”，同一 debounce 内其它自动事件不必重复跑。
        prime = next((value for value in rows if "新订阅资源匹配" in value), "")
        if prime:
            manual = [
                value for value in rows
                if any(token in value.lower() for token in ("手动", "人工", "立即", "api", "控制台", "按钮"))
            ]
            return [prime, *[value for value in manual if value != prime]]

        recovery = next((value for value in rows if "频道故障自动恢复" in value), "")
        channel = [value for value in rows if "频道新增资源" in value]
        active = [
            value for value in rows
            if "观影定时轮询" in value or "更新日历" in value or "airing" in value.lower()
        ]
        others = [value for value in rows if value not in channel and value not in active and value != recovery]

        ordered: List[str] = []
        # 被动频道永远先于主动资源站；恢复事件包含一次强刷，所以可覆盖普通频道触发。
        if recovery:
            ordered.append(recovery)
        else:
            ordered.extend(channel)
        ordered.extend(active)
        ordered.extend(others)
        return ordered or [str(fallback or "后台检查")]

    def _take_async_route_triggers_v1125(self, batch: Iterable[int], fallback: str) -> Dict[int, List[str]]:
        ids = self._normalize_async_ids_v1125(batch)
        lock = getattr(self, "_async_trigger_lock_v1125", None)
        store = getattr(self, "_async_route_triggers_v1125", None)
        if lock is None or not isinstance(store, dict):
            return {sid: [str(fallback or "后台检查")] for sid in ids}

        result: Dict[int, List[str]] = {}
        with lock:
            for sid in ids:
                values = list(store.pop(sid, []) or [])
                result[sid] = self._ordered_trigger_values_v1125(values, fallback)
        return result


__all__ = ["GuangYaAsyncTriggerV1125Mixin"]
