"""2.0.8-r92 production safety：外部补搜入队、识别短缓存、失效 tombstone、失败通知汇总。

不重写身份门禁 / Episode Fence / 迅雷 / GYING；只补齐实机暴露的边界行为。
"""
from __future__ import annotations

import copy
import threading
import time
from typing import Any, Dict, Iterable, List, Optional

from app.chain.media import MediaChain


class GuangYaProductionSafetyV208Mixin:
    """薄安全层：异步 GYING 补搜、同轮识别缓存、分享 tombstone、批次失败通知。"""

    _recognize_cache_ttl_v208 = 90
    _recognize_miss_ttl_v208 = 15
    _external_recall_dedup_seconds_v208 = 180
    _tombstone_expired_ttl_v208 = 12 * 3600
    _tombstone_temp_ttl_v208 = 10 * 60

    def init_plugin(self, config: dict = None) -> None:
        self._recognize_cache_lock_v208 = threading.RLock()
        self._recognize_cache_v208: Dict[str, Dict[str, Any]] = {}
        self._external_recall_lock_v208 = threading.RLock()
        self._external_recall_pending_v208: Dict[str, float] = {}
        self._tombstone_lock_v208 = threading.RLock()
        self._share_tombstone_v208: Dict[str, Dict[str, Any]] = {}
        self._failure_batch_lock_v208 = threading.RLock()
        self._failure_batch_v208: List[Dict[str, Any]] = []
        self._failure_batch_active_v208 = 0
        return super().init_plugin(config)

    @staticmethod
    def _enum_token_v208(value: Any) -> str:
        return str(getattr(value, "value", value) or "").strip().lower()

    @classmethod
    def _normalize_mtype_v208(cls, value: Any) -> str:
        text = cls._enum_token_v208(value)
        if "movie" in text or "电影" in text:
            return "movie"
        if "tv" in text or "剧" in text or "anime" in text or "动漫" in text:
            return "tv"
        return text or "-"

    @classmethod
    def _recognize_cache_key_v208(cls, **kwargs: Any) -> str:
        meta = kwargs.get("meta")
        media_id = str(kwargs.get("media_id") or "").strip()
        if not media_id and meta is not None:
            media_id = str(getattr(meta, "tmdb_id", None) or getattr(meta, "media_id", None) or "").strip()
        media_source = cls._enum_token_v208(kwargs.get("media_source"))
        if not media_source and meta is not None:
            media_source = cls._enum_token_v208(getattr(meta, "media_source", None))
        mtype = cls._normalize_mtype_v208(kwargs.get("mtype"))
        if mtype in {"", "-"} and meta is not None:
            mtype = cls._normalize_mtype_v208(getattr(meta, "type", None))
        title = str(kwargs.get("title") or kwargs.get("name") or "").strip().casefold()
        if not title and meta is not None:
            title = str(getattr(meta, "title", None) or getattr(meta, "name", None) or getattr(meta, "cn_name", None) or "").strip().casefold()
        year = str(kwargs.get("year") or "").strip()
        if not year and meta is not None:
            year = str(getattr(meta, "year", None) or "").strip()
        season = kwargs.get("season")
        if season in (None, "") and meta is not None:
            season = getattr(meta, "begin_season", None)
            if season in (None, ""):
                season = getattr(meta, "season", None)
        try:
            season_token = str(int(season)) if season not in (None, "") else "-"
        except (TypeError, ValueError):
            season_token = "-"

        if media_id:
            source_token = media_source or ("tmdb" if media_id.isdigit() else "id")
            if media_id.isdigit() and (not media_source or "tmdb" in media_source):
                source_token = "tmdb"
            # 有确定 ID 时按 identity 去重；不同季共享同一 MediaInfo identity。
            return f"id:{source_token}:{mtype}:{media_id}"
        if title:
            return f"title:{mtype}:{title}:{year}:s{season_token}"
        return ""

    @staticmethod
    def _clone_recognize_value_v208(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        try:
            return copy.copy(value)
        except Exception:
            return value

    def _recognize_media_cached_v208(self, **kwargs: Any) -> Any:
        key = self._recognize_cache_key_v208(**kwargs)
        if not key:
            return MediaChain().recognize_media(**kwargs)

        now = time.time()
        lock = getattr(self, "_recognize_cache_lock_v208", None) or threading.RLock()
        self._recognize_cache_lock_v208 = lock
        cache = getattr(self, "_recognize_cache_v208", None)
        if not isinstance(cache, dict):
            cache = {}
            self._recognize_cache_v208 = cache
        with lock:
            row = dict(cache.get(key) or {})
            try:
                age = now - float(row.get("at") or 0)
            except (TypeError, ValueError):
                age = 10**9
            ttl = float(self._recognize_cache_ttl_v208 if row.get("value") is not None else self._recognize_miss_ttl_v208)
            if row and age < ttl and "value" in row:
                self._plugin_log("INFO", "【光鸭转存助手】【媒体识别】key=%s cache=hit", key[:120])
                return self._clone_recognize_value_v208(row.get("value"))

        try:
            value = MediaChain().recognize_media(**kwargs)
        except Exception:
            # timeout / DNS / 5xx 等临时失败不写负缓存。
            raise
        with lock:
            cache[key] = {"at": now, "value": value}
            if len(cache) > 256:
                ordered = sorted(cache.items(), key=lambda pair: float((pair[1] or {}).get("at") or 0), reverse=True)[:256]
                self._recognize_cache_v208 = dict(ordered)
        return self._clone_recognize_value_v208(value)

    def _recognize_by_meta_cached_v208(self, meta: Any, **kwargs: Any) -> Any:
        payload = dict(kwargs)
        payload["meta"] = meta
        if "mtype" not in payload and meta is not None:
            payload["mtype"] = getattr(meta, "type", None)
        if "title" not in payload and meta is not None:
            payload["title"] = getattr(meta, "title", None) or getattr(meta, "name", None)
        if "year" not in payload and meta is not None:
            payload["year"] = getattr(meta, "year", None)
        key = self._recognize_cache_key_v208(**payload)
        if not key:
            return MediaChain().recognize_by_meta(meta, **kwargs)
        key = f"meta:{key}"
        now = time.time()
        lock = getattr(self, "_recognize_cache_lock_v208", None) or threading.RLock()
        self._recognize_cache_lock_v208 = lock
        cache = getattr(self, "_recognize_cache_v208", None)
        if not isinstance(cache, dict):
            cache = {}
            self._recognize_cache_v208 = cache
        with lock:
            row = dict(cache.get(key) or {})
            try:
                age = now - float(row.get("at") or 0)
            except (TypeError, ValueError):
                age = 10**9
            ttl = float(self._recognize_cache_ttl_v208 if row.get("value") is not None else self._recognize_miss_ttl_v208)
            if row and age < ttl and "value" in row:
                self._plugin_log("INFO", "【光鸭转存助手】【媒体识别】key=%s cache=hit", key[:120])
                return self._clone_recognize_value_v208(row.get("value"))
        try:
            value = MediaChain().recognize_by_meta(meta, **kwargs)
        except Exception:
            raise
        with lock:
            cache[key] = {"at": now, "value": value}
            if len(cache) > 256:
                ordered = sorted(cache.items(), key=lambda pair: float((pair[1] or {}).get("at") or 0), reverse=True)[:256]
                self._recognize_cache_v208 = dict(ordered)
        return self._clone_recognize_value_v208(value)

    def _enqueue_external_recall_v208(self, subscribe: Any, reason: str = "local_candidates_exhausted") -> bool:
        try:
            sid = int(getattr(subscribe, "id", 0) or 0)
        except (TypeError, ValueError):
            sid = 0
        if sid <= 0:
            return False
        now = time.time()
        lock = getattr(self, "_external_recall_lock_v208", None) or threading.RLock()
        self._external_recall_lock_v208 = lock
        pending = getattr(self, "_external_recall_pending_v208", None)
        if not isinstance(pending, dict):
            pending = {}
            self._external_recall_pending_v208 = pending
        with lock:
            last = float(pending.get(str(sid)) or 0)
            if last and now - last < float(self._external_recall_dedup_seconds_v208):
                self._plugin_log(
                    "INFO",
                    "【光鸭转存助手】【外部补搜】sid=%s reason=%s decision=dedup",
                    sid,
                    str(reason or "")[:120],
                )
                return False
            pending[str(sid)] = now
            if len(pending) > 1000:
                self._external_recall_pending_v208 = dict(
                    sorted(pending.items(), key=lambda pair: float(pair[1] or 0), reverse=True)[:1000]
                )
        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【外部补搜】sid=%s reason=%s decision=enqueue_gying",
            sid,
            str(reason or "")[:120],
        )
        self._queue_async_route_check([sid], trigger="外部补搜·本地候选耗尽")
        return True

    def _share_tombstone_key_v208(self, source_type: str, identity: str) -> str:
        return f"{str(source_type or 'guangya').strip().lower()}|{str(identity or '').strip()}"

    def _is_share_tombstoned_v208(self, source_type: str, identity: str) -> bool:
        key = self._share_tombstone_key_v208(source_type, identity)
        if not key.endswith("|") and key.split("|", 1)[-1]:
            pass
        else:
            return False
        now = time.time()
        lock = getattr(self, "_tombstone_lock_v208", None) or threading.RLock()
        self._tombstone_lock_v208 = lock
        store = getattr(self, "_share_tombstone_v208", None)
        if not isinstance(store, dict):
            store = {}
            self._share_tombstone_v208 = store
        with lock:
            row = dict(store.get(key) or {})
            try:
                until = float(row.get("until") or 0)
            except (TypeError, ValueError):
                until = 0
            if until > now:
                return True
            if key in store:
                store.pop(key, None)
        return False

    def _mark_share_tombstone_v208(self, source_type: str, identity: str, reason: str, *, temporary: bool = False) -> None:
        key = self._share_tombstone_key_v208(source_type, identity)
        if not str(identity or "").strip():
            return
        ttl = self._tombstone_temp_ttl_v208 if temporary else self._tombstone_expired_ttl_v208
        until = time.time() + float(ttl)
        lock = getattr(self, "_tombstone_lock_v208", None) or threading.RLock()
        self._tombstone_lock_v208 = lock
        store = getattr(self, "_share_tombstone_v208", None)
        if not isinstance(store, dict):
            store = {}
            self._share_tombstone_v208 = store
        with lock:
            store[key] = {"until": until, "reason": str(reason or "")[:240], "temporary": bool(temporary)}
            if len(store) > 2000:
                self._share_tombstone_v208 = dict(
                    sorted(store.items(), key=lambda pair: float((pair[1] or {}).get("until") or 0), reverse=True)[:2000]
                )
        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【资源失效】share_id=%s reason=%s ttl=%s",
            str(identity or "")[:80],
            str(reason or "")[:160],
            int(ttl),
        )

    def _begin_failure_batch_v208(self) -> None:
        lock = getattr(self, "_failure_batch_lock_v208", None) or threading.RLock()
        self._failure_batch_lock_v208 = lock
        with lock:
            self._failure_batch_active_v208 = int(getattr(self, "_failure_batch_active_v208", 0) or 0) + 1
            if not isinstance(getattr(self, "_failure_batch_v208", None), list):
                self._failure_batch_v208 = []

    def _queue_failure_notice_v208(self, subscribe: Any, message: str, *, level: str = "retryable") -> bool:
        """返回 True 表示已进入批次缓冲，调用方不要再即时推送。"""
        text = str(message or "")
        hard = level == "error" or any(
            token in text for token in ("认证", "登录", "Authorization", "token 无效", "全局不可用", "API 不可用")
        )
        if hard:
            return False
        lock = getattr(self, "_failure_batch_lock_v208", None) or threading.RLock()
        self._failure_batch_lock_v208 = lock
        with lock:
            if int(getattr(self, "_failure_batch_active_v208", 0) or 0) <= 0:
                return False
            rows = getattr(self, "_failure_batch_v208", None)
            if not isinstance(rows, list):
                rows = []
                self._failure_batch_v208 = rows
            rows.append({
                "sid": int(getattr(subscribe, "id", 0) or 0),
                "name": str(getattr(subscribe, "name", "") or ""),
                "message": text[:240],
            })
            return True

    def _flush_failure_batch_v208(self) -> None:
        lock = getattr(self, "_failure_batch_lock_v208", None) or threading.RLock()
        self._failure_batch_lock_v208 = lock
        with lock:
            active = int(getattr(self, "_failure_batch_active_v208", 0) or 0)
            if active > 0:
                self._failure_batch_active_v208 = active - 1
            if int(getattr(self, "_failure_batch_active_v208", 0) or 0) > 0:
                return
            rows = list(getattr(self, "_failure_batch_v208", None) or [])
            self._failure_batch_v208 = []
        if not rows or not bool(getattr(self, "_notify", False)):
            return
        samples = []
        for row in rows[:8]:
            samples.append(f"#{row.get('sid')} {row.get('name')}: {row.get('message')}")
        text = (
            f"本轮处理：{len(rows)}\n"
            f"失败/待补搜：{len(rows)}\n"
            + "\n".join(samples)
            + ("\n..." if len(rows) > 8 else "")
        )
        try:
            try:
                from app.schemas.types import NotificationType
                mtype = NotificationType.Plugin
            except Exception:
                mtype = "Plugin"
            self.post_message(mtype=mtype, title="⚠️ 光鸭转存检查完成", text=text[:1800])
        except Exception as err:
            self._plugin_log("WARNING", "【光鸭转存助手】【通知】批次汇总发送失败：%s", err)

    def _run_v1115_mode_batch(self, batch: List[int], trigger: str, mode: str, force: bool = False) -> None:
        self._begin_failure_batch_v208()
        try:
            return super()._run_v1115_mode_batch(batch, trigger, mode, force=force)
        finally:
            self._flush_failure_batch_v208()


__all__ = ["GuangYaProductionSafetyV208Mixin"]
