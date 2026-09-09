"""v1.12.23 GYING 搜索卡片真值门禁。

搜索页返回的是模糊召回卡片，其中还可能混入默认推荐内容。订阅自动检索必须先使用
MoviePilot 当前订阅的权威媒体身份筛选卡片，再调用 downurl；详情接口成功本身不能作为
目标资源命中证据。无订阅上下文的人工全局搜索保留原有浏览行为。
"""
from __future__ import annotations

import re
import threading
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterable, List, Optional


_MOVIE_CARD_TYPES_V11223 = {"mv", "movie", "film"}
_SERIES_CARD_TYPES_V11223 = {"tv", "ac", "anime", "animation"}


def _gying_exact_title_key_v11223(value: Any, expected_year: Any = None) -> str:
    text = " ".join(str(value or "").split())
    text = re.sub(
        r"(?i)\s+(?:S(?:eason)?[ ._-]*0*\d{1,2}|第\s*(?:0*\d{1,2}|[一二三四五六七八九十]{1,3})\s*季)\s*$",
        "",
        text,
    ).strip()
    year = str(expected_year or "").strip()
    if re.fullmatch(r"(?:19|20)\d{2}", year):
        escaped_year = re.escape(year)
        text = re.sub(
            rf"(?:\s+{escaped_year}|[（(【\[]\s*{escaped_year}\s*[）)】\]])\s*$",
            "",
            text,
        ).strip()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text.casefold())


def select_gying_detail_cards_v11223(
    cards: Iterable[Dict[str, Any]],
    limit: int,
    matcher: Callable[[Dict[str, Any]], bool],
    expected_kind: Optional[str] = None,
    accepted_titles: Optional[Iterable[str]] = None,
    expected_year: Any = None,
) -> List[Dict[str, Any]]:
    """先遍历并精确筛选所有搜索卡片，最后再应用详情请求上限。"""
    selected: List[Dict[str, Any]] = []
    normalized_kind = str(expected_kind or "").strip().lower()
    accepted_keys = set()
    for value in accepted_titles or []:
        key = _gying_exact_title_key_v11223(value, expected_year=expected_year)
        if key:
            accepted_keys.add(key)
    accepted_compound_keys = {
        left + right
        for left in accepted_keys
        for right in accepted_keys
        if left != right
    }
    for raw in cards or []:
        card = dict(raw or {})
        title = str(card.get("title") or "").strip()
        resource_type = str(card.get("type") or "").strip().lower()
        resource_id = str(card.get("id") or "").strip()
        if not title or not resource_type or not resource_id:
            continue
        if normalized_kind == "movie" and resource_type not in _MOVIE_CARD_TYPES_V11223:
            continue
        if normalized_kind == "series" and resource_type not in _SERIES_CARD_TYPES_V11223:
            continue
        if accepted_keys:
            title_key = _gying_exact_title_key_v11223(title, expected_year=expected_year)
            if title_key not in accepted_keys and title_key not in accepted_compound_keys:
                continue

        probe = {
            **card,
            "search_title": title,
            "name": title,
            "label": " ".join(
                value for value in (title, str(card.get("info") or "").strip()) if value
            ),
        }
        try:
            if matcher(probe):
                selected.append(card)
        except Exception:
            continue
    return selected[: max(0, int(limit or 0))]


class GuangYaGyingSearchTruthV11223Mixin:
    """给协议层提供订阅上下文感知的 downurl 前置卡片筛选。"""

    plugin_version = "1.12.23"
    build_id = "20260909-r70"
    _gying_search_lock_master_v11223 = threading.RLock()
    _gying_search_overflow_lock_v11223 = threading.RLock()

    def init_plugin(self, config: dict = None) -> None:
        super().init_plugin(config)
        marker_key = "gying_search_truth_release_v11223"
        try:
            previous = self.get_data(marker_key) or {}
        except Exception:
            previous = {}
        if isinstance(previous, dict) and str(previous.get("build") or "") == self.build_id:
            return
        # 旧版把来源健康和媒体命中混为一谈；升级时清除这份误导性的持久搜索结果。
        self.save_data("provider_search_last", {})
        self.save_data(marker_key, {"build": self.build_id})

    def _gying_target_subscribe_v11223(self) -> Any:
        getter = getattr(self, "_gying_alias_subscribe_v11212", None)
        if not callable(getter):
            return None
        try:
            return getter()
        except Exception:
            return None

    def _gying_search_cache_key_v11223(self, keyword: str, subscribe: Any = None) -> str:
        clean = " ".join(str(keyword or "").split())
        if subscribe is None:
            subscribe = self._gying_target_subscribe_v11223()
        if subscribe is None:
            return clean
        sid = str(getattr(subscribe, "id", "") or "0")
        tmdb_id = str(getattr(subscribe, "tmdbid", "") or getattr(subscribe, "tmdb_id", "") or "")
        year = str(getattr(subscribe, "year", "") or "")
        season = str(getattr(subscribe, "season", "") or "0")
        media_type = str(getattr(subscribe, "type", "") or "")
        return f"v11223|sub={sid}|tmdb={tmdb_id}|year={year}|season={season}|type={media_type}|q={clean}"

    def _gying_search_lock_for_v11223(self, cache_key: str):
        with self._gying_search_lock_master_v11223:
            locks = getattr(self, "_gying_search_locks_v11223", None)
            if not isinstance(locks, dict):
                locks = {}
                self._gying_search_locks_v11223 = locks
            lock = locks.get(cache_key)
            if lock is not None:
                return lock
            if len(locks) >= 256:
                return self._gying_search_overflow_lock_v11223
            lock = threading.RLock()
            locks[cache_key] = lock
            return lock

    @contextmanager
    def _gying_search_singleflight_v11223(self, keyword: str):
        cache_key = self._gying_search_cache_key_v11223(keyword)
        lock = self._gying_search_lock_for_v11223(cache_key)
        with lock:
            yield

    def _gying_raw_results(self, keyword: str, force: bool = False):
        cache_key = self._gying_search_cache_key_v11223(keyword)
        cache = getattr(self, "_gying_search_cache", None)
        before_entry = cache.get(cache_key) if isinstance(cache, dict) else None
        with self._gying_search_singleflight_v11223(keyword):
            current_entry = cache.get(cache_key) if isinstance(cache, dict) else None
            # 两个强制刷新真正重叠时，后进入锁的一方复用前一方刚写入的完整快照。
            # 非重叠的后续人工强制刷新仍会正常发起新请求。
            effective_force = bool(force and current_entry is before_entry)
            return super()._gying_raw_results(keyword, force=effective_force)

    def _gying_xunlei_precise_variant_v1125(self, keyword: str):
        with self._gying_search_singleflight_v11223(keyword):
            return super()._gying_xunlei_precise_variant_v1125(keyword)

    def _gying_select_detail_cards_v11223(
        self,
        keyword: str,
        cards: Iterable[Dict[str, Any]],
        limit: int,
    ) -> List[Dict[str, Any]]:
        raw_cards = [dict(row or {}) for row in cards or []]
        subscribe = self._gying_target_subscribe_v11223()
        if subscribe is None:
            return raw_cards[: max(0, int(limit or 0))]

        matcher = getattr(self, "_provider_candidate_matches", None)
        if not callable(matcher):
            return []

        checker = getattr(self, "_is_movie_subscription", None)
        try:
            is_movie = bool(checker(subscribe)) if callable(checker) else False
        except Exception:
            is_movie = False
        if not callable(checker):
            media_type = str(getattr(subscribe, "type", "") or "").casefold()
            is_movie = "movie" in media_type or "电影" in media_type
        expected_kind = "movie" if is_movie else "series"

        accepted_titles: List[str] = [keyword]
        for field in ("name", "title", "original_name", "original_title", "en_name", "cn_name"):
            value = getattr(subscribe, field, None)
            if isinstance(value, (list, tuple, set)):
                accepted_titles.extend(str(item or "") for item in value)
            elif value:
                accepted_titles.append(str(value))
        alias_getter = getattr(self, "_match_aliases_v11217", None)
        if callable(alias_getter):
            try:
                accepted_titles.extend(str(value or "") for value in alias_getter(subscribe) or [])
            except Exception:
                pass

        return select_gying_detail_cards_v11223(
            raw_cards,
            limit,
            lambda candidate: bool(matcher(subscribe, candidate)),
            expected_kind=expected_kind,
            accepted_titles=accepted_titles,
            expected_year=getattr(subscribe, "year", None),
        )


__all__ = [
    "GuangYaGyingSearchTruthV11223Mixin",
    "select_gying_detail_cards_v11223",
]
