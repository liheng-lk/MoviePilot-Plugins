"""2.0.9-r93：同一 GYING 节点 PanSou PoW singleflight。

禁止并发订阅各自重复求解同一节点 challenge；等待首个求解结果并复用会话。
不改写 gying_browser / gying_pow / gying_pansou 核心算法，只在求解入口加锁合并。
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

from .gying_hardening_v193 import canonical_gying_node


class GuangYaPowSingleflightV209Mixin:
    """Per-node PoW singleflight around `_gying_solve_challenge_v1110`."""

    _pow_singleflight_master_v209 = threading.RLock()
    _pow_singleflight_overflow_v209 = threading.RLock()

    def init_plugin(self, config: dict = None) -> None:
        self._pow_singleflight_locks_v209: Dict[str, threading.RLock] = {}
        self._pow_singleflight_results_v209: Dict[str, Dict[str, Any]] = {}
        return super().init_plugin(config)

    def _pow_node_key_v209(self, node: str) -> str:
        return canonical_gying_node(node) or str(node or "").rstrip("/").lower()

    def _pow_lock_for_node_v209(self, node_key: str) -> threading.RLock:
        master = getattr(self, "_pow_singleflight_master_v209", None) or threading.RLock()
        self._pow_singleflight_master_v209 = master
        with master:
            locks = getattr(self, "_pow_singleflight_locks_v209", None)
            if not isinstance(locks, dict):
                locks = {}
                self._pow_singleflight_locks_v209 = locks
            lock = locks.get(node_key)
            if lock is not None:
                return lock
            if len(locks) >= 64:
                return getattr(self, "_pow_singleflight_overflow_v209", None) or threading.RLock()
            lock = threading.RLock()
            locks[node_key] = lock
            return lock

    def _gying_solve_challenge_v1110(
        self,
        session,
        node: str,
        response,
        kind: Optional[str] = None,
    ) -> Dict[str, Any]:
        node_key = self._pow_node_key_v209(node)
        kind_token = str(kind or "")
        # Only coalesce remote_pow / empty kind (resolved inside); still serialize all solves per node.
        lock = self._pow_lock_for_node_v209(node_key or "-")
        with lock:
            cache = getattr(self, "_pow_singleflight_results_v209", None)
            if not isinstance(cache, dict):
                cache = {}
                self._pow_singleflight_results_v209 = cache
            cached = dict(cache.get(node_key) or {})
            try:
                age = time.monotonic() - float(cached.get("at") or 0)
            except (TypeError, ValueError):
                age = 10**9
            # Fresh verified solve within 45s can be reused by waiters on the same node.
            if cached.get("ok") and age < 45:
                bump = getattr(self, "_bump_metric_v209", None)
                if callable(bump):
                    bump("cache_hits")
                return dict(cached.get("result") or {"success": True, "reused": True, "node": node_key})

            bump = getattr(self, "_bump_metric_v209", None)
            if callable(bump):
                bump("pansou_pow_challenges")
            result = dict(
                super()._gying_solve_challenge_v1110(session, node, response, kind=kind_token or kind) or {}
            )
            cache[node_key] = {
                "at": time.monotonic(),
                "ok": True,
                "result": dict(result),
            }
            return result


__all__ = ["GuangYaPowSingleflightV209Mixin"]
