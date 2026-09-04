"""光鸭自动整理持久状态机。

该模块只负责自动整理状态，不依赖 MoviePilot 业务对象。扫描器、识别桥和 MoviePilot
最终回执通过同一套原子状态转换协作，避免 ``seen/pending`` 的读改写竞态，也避免
“已经进入队列”被误当成“已经整理完成”。

v3.6.14 起状态事务采用 dirty-write：仍在同一把锁内完成 read/modify/compare/write，
但 callback 没有改变规范化状态时不再整份重写 JSON。旧/非规范 schema 首次 mutate 仍会
按原语义写回规范化结构，因此只优化稳定运行期的空写，不改变迁移和状态转换行为。
"""

from __future__ import annotations

import copy
import threading
import time
from typing import Any, Callable, Dict, Iterable, Optional


class OrganizerStateStore:
    """JSON 可持久化的自动整理状态仓库。"""

    schema_version = 3
    blocked_recheck_seconds = 600

    def __init__(
        self,
        *,
        read: Callable[[str], Any],
        write: Callable[[str, Any], None],
        key: str,
        lock: Optional[Any] = None,
    ) -> None:
        self._read = read
        self._write = write
        self._key = key
        self._lock = lock or threading.RLock()

    @classmethod
    def normalize(cls, raw: Any) -> Dict[str, Any]:
        """把 schema v3 数据补齐默认字段；旧 schema 由显式迁移函数处理。"""
        raw = dict(raw or {}) if isinstance(raw, dict) else {}
        is_v3 = int(raw.get("schema_version") or 0) >= cls.schema_version
        return {
            "schema_version": cls.schema_version,
            "completed": dict(raw.get("completed") or {}) if is_v3 else {},
            "ignored": dict(raw.get("ignored") or {}) if is_v3 else {},
            "blocked": dict(raw.get("blocked") or {}) if is_v3 else {},
            "stabilizing": dict(raw.get("stabilizing") or ({} if is_v3 else raw.get("pending") or {})),
            "inflight": dict(raw.get("inflight") or {}) if is_v3 else {},
            "retry": dict(raw.get("retry") or {}) if is_v3 else {},
            "monitor_path": str(raw.get("monitor_path") or ""),
            "updated_at": raw.get("updated_at"),
            "migration": raw.get("migration"),
        }

    def load(self) -> Dict[str, Any]:
        with self._lock:
            return self.normalize(self._read(self._key))

    def save(self, state: Dict[str, Any]) -> Dict[str, Any]:
        normalized = self.normalize(state)
        with self._lock:
            self._write(self._key, normalized)
        return normalized

    def mutate(self, callback: Callable[[Dict[str, Any]], Any]) -> Any:
        """锁内原子事务；仅状态真实变化或底层数据尚未规范化时持久化。"""
        with self._lock:
            # backend 可能返回其内部对象本身。先 deepcopy，避免 callback 修改嵌套 row 时
            # 连带改动“读取前快照”，导致 dirty 比较失真。
            raw = copy.deepcopy(self._read(self._key))
            state = self.normalize(raw)
            before = copy.deepcopy(state)
            # 保留旧 mutate 的规范化副作用：旧/残缺 schema 即使 callback 不改状态，
            # 第一次仍会写成标准 schema v3；已经规范化的数据才有资格走零写入。
            canonical_dirty = raw != before
            result = callback(state)
            after = self.normalize(state)
            if canonical_dirty or after != before:
                self._write(self._key, after)
            return result

    @staticmethod
    def _row_fingerprint(row: Any) -> str:
        return str(row.get("fingerprint") or "") if isinstance(row, dict) else ""

    @classmethod
    def _drop_other_versions(cls, state: Dict[str, Any], path: str, fingerprint: str) -> None:
        """路径内容发生变化时，旧版本状态不得阻断新版本。"""
        for name in ("completed", "ignored"):
            mapping = state[name]
            if path in mapping and str(mapping.get(path) or "") != fingerprint:
                mapping.pop(path, None)
        for name in ("blocked", "stabilizing", "inflight", "retry"):
            mapping = state[name]
            if path in mapping and cls._row_fingerprint(mapping.get(path)) != fingerprint:
                mapping.pop(path, None)

    def reconcile_inventory(self, inventory_paths: Iterable[str], *, truncated: bool) -> None:
        """完整扫描时清理源目录已消失状态；截断扫描绝不误删。"""
        if truncated:
            return
        inventory = set(inventory_paths)

        def _apply(state: Dict[str, Any]) -> None:
            for name in ("completed", "ignored", "blocked", "stabilizing", "inflight", "retry"):
                state[name] = {
                    path: row for path, row in state[name].items() if path in inventory
                }

        self.mutate(_apply)

    def classify(
        self,
        *,
        path: str,
        fingerprint: str,
        now: float,
        stability_seconds: float,
        inflight_lease_seconds: float,
    ) -> str:
        """返回 ``completed/ignored/blocked/inflight/retry_wait/stabilizing/ready``。"""

        def _apply(state: Dict[str, Any]) -> str:
            self._drop_other_versions(state, path, fingerprint)
            if state["completed"].get(path) == fingerprint:
                return "completed"
            if state["ignored"].get(path) == fingerprint:
                return "ignored"
            blocked = state["blocked"].get(path)
            if self._row_fingerprint(blocked) == fingerprint:
                if float(blocked.get("recheck_at") or 0) > now:
                    return "blocked"
                # 用户可能已经在 MoviePilot 中清理失败记录或调整设置，周期性重新预检。
                state["blocked"].pop(path, None)
                return "ready"

            inflight = state["inflight"].get(path)
            if self._row_fingerprint(inflight) == fingerprint:
                submitted_at = float(inflight.get("submitted_at") or 0)
                if submitted_at and now - submitted_at < inflight_lease_seconds:
                    return "inflight"
                attempts = max(int(inflight.get("attempts") or 1), 1)
                state["inflight"].pop(path, None)
                state["retry"][path] = {
                    "fingerprint": fingerprint,
                    "attempts": attempts,
                    "retry_at": now,
                    "last_error": "MoviePilot 最终回执超时，自动恢复",
                }

            retry = state["retry"].get(path)
            if self._row_fingerprint(retry) == fingerprint:
                if float(retry.get("retry_at") or 0) > now:
                    return "retry_wait"
                return "ready"

            row = state["stabilizing"].get(path)
            if self._row_fingerprint(row) != fingerprint:
                row = {"fingerprint": fingerprint, "first_seen": now}
                state["stabilizing"][path] = row
            first_seen = float(row.get("first_seen") or now)
            if now - first_seen < max(float(stability_seconds), 0.0):
                return "stabilizing"
            return "ready"

        return self.mutate(_apply)

    def mark_submitting(
        self,
        *,
        path: str,
        fingerprint: str,
        now: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        """调用 MoviePilot 前先占有 in-flight，消除快速回执与扫描线程竞态。"""

        def _apply(state: Dict[str, Any]) -> int:
            self._drop_other_versions(state, path, fingerprint)
            if state["completed"].get(path) == fingerprint:
                return 0
            previous = state["retry"].pop(path, None) or state["inflight"].get(path) or {}
            attempts = max(int(previous.get("attempts") or 0) + 1, 1)
            row = {
                "fingerprint": fingerprint,
                "submitted_at": now,
                "attempts": attempts,
            }
            if metadata:
                row.update(metadata)
            state["inflight"][path] = row
            state["blocked"].pop(path, None)
            state["stabilizing"].pop(path, None)
            return attempts

        return int(self.mutate(_apply) or 0)

    @staticmethod
    def retry_delay(attempts: int) -> int:
        """失败重试指数退避，最长 1 小时，但不永久放弃。"""
        attempts = max(int(attempts or 1), 1)
        return min(60 * (2 ** min(attempts - 1, 6)), 3600)

    def mark_deferred(
        self,
        *,
        path: str,
        fingerprint: str,
        now: float,
        reason: str,
    ) -> Dict[str, Any]:
        """MP 暂未接收入队时进入可恢复等待，而不是永久写成 seen。"""

        def _apply(state: Dict[str, Any]) -> Dict[str, Any]:
            if state["completed"].get(path) == fingerprint:
                return {"attempts": 0, "retry_at": 0, "delay": 0}
            inflight = state["inflight"].pop(path, None) or {}
            previous = state["retry"].get(path) or {}
            attempts = max(int(inflight.get("attempts") or previous.get("attempts") or 1), 1)
            delay = self.retry_delay(attempts)
            row = {
                "fingerprint": fingerprint,
                "attempts": attempts,
                "retry_at": now + delay,
                "last_error": reason,
            }
            state["retry"][path] = row
            state["blocked"].pop(path, None)
            state["stabilizing"].pop(path, None)
            return {"attempts": attempts, "retry_at": row["retry_at"], "delay": delay}

        return dict(self.mutate(_apply) or {})

    def mark_ignored(self, *, path: str, fingerprint: str) -> None:
        """仅对 MP 明确不支持的扩展名等永久候选门控做忽略。"""

        def _apply(state: Dict[str, Any]) -> None:
            self._drop_other_versions(state, path, fingerprint)
            state["ignored"][path] = fingerprint
            state["blocked"].pop(path, None)
            for name in ("stabilizing", "inflight", "retry"):
                state[name].pop(path, None)

        self.mutate(_apply)

    def mark_blocked(
        self,
        *,
        path: str,
        fingerprint: str,
        reason: str,
        now: float,
    ) -> None:
        """MP 明确表示重试预算耗尽时暂停提交，并周期性重新确认。"""

        def _apply(state: Dict[str, Any]) -> None:
            self._drop_other_versions(state, path, fingerprint)
            state["blocked"][path] = {
                "fingerprint": fingerprint,
                "reason": reason,
                "recheck_at": now + self.blocked_recheck_seconds,
            }
            for name in ("stabilizing", "inflight", "retry"):
                state[name].pop(path, None)

        self.mutate(_apply)

    def clear_blocked(self) -> int:
        """人工修复 MoviePilot 历史/配置后，可立即重新预检所有 blocked 项。"""
        def _apply(state: Dict[str, Any]) -> int:
            count = len(state["blocked"])
            state["blocked"] = {}
            return count

        return int(self.mutate(_apply) or 0)

    def mark_completed(self, *, path: str, fingerprint: str) -> None:
        def _apply(state: Dict[str, Any]) -> None:
            self._drop_other_versions(state, path, fingerprint)
            state["completed"][path] = fingerprint
            state["ignored"].pop(path, None)
            state["blocked"].pop(path, None)
            for name in ("stabilizing", "inflight", "retry"):
                state[name].pop(path, None)

        self.mutate(_apply)

    def mark_failed(
        self,
        *,
        path: str,
        fingerprint: str,
        now: float,
        reason: str,
    ) -> Dict[str, Any]:
        """最终失败后进入可观察的退避重试状态。"""
        return self.mark_deferred(
            path=path,
            fingerprint=fingerprint,
            now=now,
            reason=reason,
        )

    def reset_for_monitor_path(self, monitor_path: str) -> None:
        self.save({"schema_version": self.schema_version, "monitor_path": monitor_path})

    def set_metadata(self, **kwargs: Any) -> None:
        def _apply(state: Dict[str, Any]) -> None:
            state.update(kwargs)

        self.mutate(_apply)

    def stats(self) -> Dict[str, int]:
        state = self.load()
        return {
            "completed": len(state["completed"]),
            "ignored": len(state["ignored"]),
            "blocked": len(state["blocked"]),
            "stabilizing": len(state["stabilizing"]),
            "inflight": len(state["inflight"]),
            "retry_wait": len(state["retry"]),
        }

    def migrate_from_v322(self, *, monitor_path: str) -> Dict[str, int]:
        """升级旧状态；v3.2.x 的 seen 只代表“曾提交”，因此必须重新确认。"""
        with self._lock:
            raw = self._read(self._key)
            old = dict(raw or {}) if isinstance(raw, dict) else {}
            if int(old.get("schema_version") or 0) >= self.schema_version:
                normalized = self.normalize(old)
            else:
                normalized = {
                    "schema_version": self.schema_version,
                    "completed": {},
                    "ignored": {},
                    "blocked": {},
                    "stabilizing": dict(old.get("pending") or {}),
                    "inflight": {},
                    "retry": {},
                    "monitor_path": monitor_path,
                    "updated_at": old.get("updated_at"),
                    "migration": "v3.3.0-reconfirm-v32-seen",
                }
                for path, fingerprint in dict(old.get("seen") or {}).items():
                    normalized["retry"][path] = {
                        "fingerprint": str(fingerprint or ""),
                        "attempts": 0,
                        "retry_at": 0,
                        "last_error": "v3.3.0 升级重新确认旧版 submitted/seen 状态",
                    }
            normalized["monitor_path"] = monitor_path
            normalized["migration"] = normalized.get("migration") or "v3.3.0-state-machine"
            normalized["updated_at"] = time.time()
            self._write(self._key, normalized)
            return {
                "completed": len(normalized["completed"]),
                "blocked": len(normalized["blocked"]),
                "stabilizing": len(normalized["stabilizing"]),
                "inflight": len(normalized["inflight"]),
                "retry_wait": len(normalized["retry"]),
            }


__all__ = ["OrganizerStateStore"]
