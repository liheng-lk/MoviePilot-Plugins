"""v1.12.9 电影精确 TMDB 别名补全。

解决“观影能搜到电影，但真实迅雷资源使用英文原名时被最终媒体身份门禁误杀”的问题。
本层不做模糊匹配：只有订阅自身具备明确 TMDB 身份时，才通过 MoviePilot MediaChain
按同一 TMDB ID 取回官方 title/en_title/original_title 等字段作为可信别名。

典型场景：
- MoviePilot 订阅：失控陪审团 (2003), TMDB 11329
- 观影发现：失控陪审团
- 迅雷真实资源：Runaway.Jury.2003.1080p...

旧逻辑最终门禁只看到订阅中文名与真实英文名不一致，会按“真实顶层标题冲突”拒绝。
新逻辑把同一 TMDB 11329 返回的 Runaway Jury 作为精确官方别名后，仍沿用既有
年份、电影季号、真实文件与来源优先级门禁。
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Iterable, List

from app.chain.media import MediaChain
from app.schemas.types import MediaSource, MediaType


class GuangYaMovieIdentityV1129Mixin:
    """仅为电影补充同一 TMDB 身份下的官方标题，不改变既有媒体身份评分规则。"""

    plugin_version = "1.12.9"
    build_id = "20260905-r55"
    _movie_alias_cache_ttl_v1129 = 24 * 60 * 60
    _movie_alias_failure_ttl_v1129 = 10 * 60

    def init_plugin(self, config: dict = None) -> None:
        self._movie_alias_lock_v1129 = threading.RLock()
        self._movie_alias_cache_v1129: Dict[str, Dict[str, Any]] = {}
        return super().init_plugin(config)

    @staticmethod
    def _enum_token_v1129(value: Any) -> str:
        return str(getattr(value, "value", value) or "").strip().lower()

    def _is_movie_v1129(self, subscribe: Any) -> bool:
        checker = getattr(self, "_identity_is_movie_v1111", None)
        if callable(checker):
            try:
                return bool(checker(subscribe))
            except Exception:
                pass
        checker = getattr(self, "_is_movie_subscription", None)
        if callable(checker):
            try:
                return bool(checker(subscribe))
            except Exception:
                pass
        raw = str(getattr(subscribe, "type", "") or "").lower()
        return "movie" in raw or "电影" in raw

    def _movie_tmdb_id_v1129(self, subscribe: Any) -> str:
        if not self._is_movie_v1129(subscribe):
            return ""
        for field in ("tmdb_id", "tmdbid"):
            value = str(getattr(subscribe, field, "") or "").strip()
            if value.isdigit():
                return value
        source = self._enum_token_v1129(getattr(subscribe, "media_source", None))
        media_id = str(getattr(subscribe, "media_id", "") or "").strip()
        if media_id.isdigit() and "tmdb" in source:
            return media_id
        return ""

    @staticmethod
    def _flatten_alias_values_v1129(value: Any) -> Iterable[str]:
        if value in (None, ""):
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            rows: List[str] = []
            for item in value.values():
                rows.extend(GuangYaMovieIdentityV1129Mixin._flatten_alias_values_v1129(item))
            return rows
        if isinstance(value, (list, tuple, set)):
            rows: List[str] = []
            for item in value:
                rows.extend(GuangYaMovieIdentityV1129Mixin._flatten_alias_values_v1129(item))
            return rows
        return [str(value)]

    @classmethod
    def _official_aliases_from_info_v1129(cls, info: Any) -> List[str]:
        values: List[str] = []
        for field in (
            "title", "name", "en_title", "original_title", "original_name",
            "cn_name", "hk_title", "tw_title", "sg_title", "aka", "aliases", "alias",
        ):
            raw = info.get(field) if isinstance(info, dict) else getattr(info, field, None)
            values.extend(cls._flatten_alias_values_v1129(raw))
        result: List[str] = []
        seen = set()
        for raw in values:
            text = str(raw or "").strip()
            key = text.casefold()
            if len(text) < 2 or key in seen:
                continue
            seen.add(key)
            result.append(text)
        return result

    def _movie_tmdb_aliases_v1129(self, subscribe: Any) -> List[str]:
        tmdb_id = self._movie_tmdb_id_v1129(subscribe)
        if not tmdb_id:
            return []

        lock = getattr(self, "_movie_alias_lock_v1129", None)
        if lock is None:
            lock = threading.RLock()
            self._movie_alias_lock_v1129 = lock
        cache = getattr(self, "_movie_alias_cache_v1129", None)
        if not isinstance(cache, dict):
            cache = {}
            self._movie_alias_cache_v1129 = cache

        now = time.time()
        with lock:
            cached = dict(cache.get(tmdb_id) or {})
            try:
                cached_at = float(cached.get("at") or 0)
            except (TypeError, ValueError):
                cached_at = 0.0
            ttl = (
                self._movie_alias_cache_ttl_v1129
                if cached.get("ok")
                else self._movie_alias_failure_ttl_v1129
            )
            if cached_at and now - cached_at < float(ttl):
                return list(cached.get("aliases") or [])

        info = None
        error = ""
        try:
            info = MediaChain().recognize_media(
                mtype=MediaType.MOVIE,
                media_source=MediaSource.TMDB,
                media_id=tmdb_id,
            )
        except Exception as err:
            error = str(err)

        aliases: List[str] = []
        valid = bool(info)
        if info:
            returned_id = str(
                (info.get("tmdb_id") or info.get("media_id") or "")
                if isinstance(info, dict)
                else (getattr(info, "tmdb_id", None) or getattr(info, "media_id", None) or "")
            ).strip()
            if returned_id and returned_id != tmdb_id:
                valid = False
                error = f"TMDB返回身份不一致：期望={tmdb_id} 实际={returned_id}"

            expected_year = str(getattr(subscribe, "year", "") or "").strip()
            actual_year = str(
                (info.get("year") or "") if isinstance(info, dict) else (getattr(info, "year", "") or "")
            ).strip()
            if valid and expected_year and actual_year and expected_year != actual_year:
                valid = False
                error = f"TMDB返回年份不一致：期望={expected_year} 实际={actual_year}"

            if valid:
                aliases = self._official_aliases_from_info_v1129(info)

        with lock:
            cache[tmdb_id] = {
                "at": now,
                "ok": bool(valid and aliases),
                "aliases": list(aliases),
                "error": error[:300],
            }

        if aliases:
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【电影身份v1.12.9】#%s TMDB %s 补充官方别名：%s",
                int(getattr(subscribe, "id", 0) or 0),
                tmdb_id,
                " / ".join(aliases[:6]),
            )
        elif error:
            self._plugin_log(
                "WARNING",
                "【光鸭转存助手】【电影身份v1.12.9】#%s TMDB %s 官方别名读取失败：%s",
                int(getattr(subscribe, "id", 0) or 0),
                tmdb_id,
                error[:260],
            )
        return aliases

    def _identity_aliases_v1111(self, subscribe: Any) -> List[str]:
        aliases = list(super()._identity_aliases_v1111(subscribe) or [])
        if not self._is_movie_v1129(subscribe):
            return aliases

        seen = {str(value or "").strip().casefold() for value in aliases if str(value or "").strip()}
        for value in self._movie_tmdb_aliases_v1129(subscribe):
            text = str(value or "").strip()
            key = text.casefold()
            if text and key not in seen:
                aliases.append(text)
                seen.add(key)
        return aliases


__all__ = ["GuangYaMovieIdentityV1129Mixin"]
