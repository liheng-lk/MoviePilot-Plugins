"""每日助手榜单目录与统一调度。具体网络实现位于 source_backends.py。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from app.chain.recommend import RecommendChain
from app.sdk.logging import logger

from .source_backends import (
    anilist as _anilist,
    builtin as _builtin,
    douban_collection as _douban_collection,
    douban_discover as _douban_discover,
    douban_recommend as _douban_recommend,
    douban_subject_id as _douban_subject_id,
    douban_us_box as _douban_us_box,
    imdb as _imdb,
    maoyan as _maoyan,
    netflix as _netflix,
    normalize as _normalize,
    tmdb_genre as _tmdb_genre,
    tmdb_provider as _tmdb_provider,
    tmdb_provider_genre as _tmdb_provider_genre,
    year_value as _year_value,
)


@dataclass(frozen=True)
class SourceSpec:
    key: str
    label: str
    family: str
    kind: str
    media: str = "mixed"
    arg: str = ""


WATCH_PROVIDERS = {
    "netflix": 8,
    "prime": 9,
    "amazon": 10,
    "hulu": 15,
    "crunchyroll": 283,
    "disney": 337,
    "appletv": 350,
    "hbo": 1899,
    # Tencent Video / WeTV 在 TMDB/JustWatch 目录存在多个区域 provider，OR 组合提升命中率。
    "tencent": "623|1170",
}

SOURCES: List[SourceSpec] = [
    SourceSpec("documentary", "纪录片", "类型", "tmdb_genre", "mixed", "99"),
    SourceSpec("anime", "日漫", "动画", "builtin", "tv", "douban_tv_animation"),
    SourceSpec("variety", "综艺", "类型", "tmdb_genre", "tv", "10764"),
    SourceSpec("netflix_movie", "Netflix · 电影榜", "Netflix", "netflix", "movie"),
    SourceSpec("netflix_tv", "Netflix · 剧集榜", "Netflix", "netflix", "tv"),
    SourceSpec("netflix_mixed", "Netflix · 混合榜", "Netflix", "netflix", "mixed"),
]

for _family, _label in (
    ("hbo", "HBO / Max"),
    ("appletv", "Apple TV+"),
    ("disney", "Disney+"),
    ("crunchyroll", "Crunchyroll"),
    ("prime", "Amazon Prime"),
    ("amazon", "Amazon"),
    ("hulu", "Hulu"),
):
    for _media, _suffix in (("movie", "电影榜"), ("tv", "剧集榜"), ("mixed", "混合榜")):
        SOURCES.append(
            SourceSpec(
                f"{_family}_{_media}",
                f"{_label} · {_suffix}",
                _label,
                "watch_provider",
                _media,
                _family,
            )
        )

SOURCES.extend([
    SourceSpec("maoyan_movie", "猫眼 · 电影榜", "猫眼", "maoyan", "movie"),
    SourceSpec("maoyan_tv", "猫眼 · 剧集榜", "猫眼", "maoyan", "tv"),
    SourceSpec("maoyan_variety", "猫眼 · 综艺榜", "猫眼", "maoyan", "variety"),
    SourceSpec("maoyan_mixed", "猫眼 · 混合榜", "猫眼", "maoyan", "mixed"),

    SourceSpec("douban_showing", "豆瓣 · 正在上映", "豆瓣", "builtin", "movie", "douban_movie_showing"),
    SourceSpec("douban_coming", "豆瓣 · 即将上映", "豆瓣", "douban_collection", "movie", "movie_soon"),
    SourceSpec("douban_new_movies", "豆瓣 · 新片榜", "豆瓣", "douban_discover", "movie", "R"),
    SourceSpec("douban_weekly_movie", "豆瓣 · 一周口碑榜", "豆瓣", "douban_collection", "movie", "movie_weekly_best"),
    SourceSpec("douban_us_box", "豆瓣 · 北美票房榜", "豆瓣", "douban_us_box", "movie"),
    SourceSpec("douban_movie_hot", "豆瓣 · 热门电影", "豆瓣", "builtin", "movie", "douban_movie_hot"),
    SourceSpec("douban_tv_recent", "豆瓣 · 剧集近期值得看", "豆瓣", "douban_collection", "tv", "tv_real_time_hotest"),
    SourceSpec("douban_tv_hot", "豆瓣 · 热门剧集", "豆瓣", "builtin", "tv", "douban_tv_hot"),
    SourceSpec("douban_weekly_cn", "豆瓣 · 华语口碑剧", "豆瓣", "builtin", "tv", "douban_tv_weekly_chinese"),
    SourceSpec("douban_weekly_global", "豆瓣 · 全球口碑剧", "豆瓣", "builtin", "tv", "douban_tv_weekly_global"),
    SourceSpec("douban_animation", "豆瓣 · 动画榜", "豆瓣", "builtin", "tv", "douban_tv_animation"),
    SourceSpec("douban_top250", "豆瓣 · 电影 TOP250", "豆瓣", "builtin", "movie", "douban_movie_top250"),
    SourceSpec("douban_recommend", "豆瓣 · 推荐", "豆瓣", "douban_recommend", "mixed"),
    SourceSpec("douban_mixed", "豆瓣 · 混合榜", "豆瓣", "builtin_mixed", "mixed", "douban_hot"),

    SourceSpec("imdb_movie", "热门 · IMDb 热门电影", "热门", "imdb", "movie"),
    SourceSpec("imdb_tv", "热门 · IMDb 热门剧集", "热门", "imdb", "tv"),
    SourceSpec("tmdb_trending", "热门 · TMDB 趋势", "热门", "builtin", "mixed", "tmdb_trending"),
    SourceSpec("anilist_trending", "热门 · AniList 热门", "热门", "anilist", "tv"),
    SourceSpec("bangumi_calendar", "热门 · Bangumi 今日动漫", "热门", "builtin", "tv", "bangumi_calendar"),
    SourceSpec("popular_mixed", "热门 · 混合榜", "热门", "popular_mixed", "mixed"),

    SourceSpec("tencent_hot", "腾讯视频 · 热播", "腾讯视频", "maoyan", "tv", "3"),
    SourceSpec("tencent_movie", "腾讯视频 · 电影", "腾讯视频", "watch_provider", "movie", "tencent"),
    SourceSpec("tencent_tv", "腾讯视频 · 电视剧", "腾讯视频", "maoyan", "tv", "3"),
    SourceSpec("tencent_variety", "腾讯视频 · 综艺", "腾讯视频", "maoyan", "variety", "3"),
    SourceSpec("tencent_kids", "腾讯视频 · 少儿", "腾讯视频", "watch_provider_genre", "tv", "tencent:10751"),
])

SOURCE_MAP = {item.key: item for item in SOURCES}
DEFAULT_SOURCE_KEYS = [
    "netflix_movie", "netflix_tv", "hbo_tv", "appletv_tv", "disney_tv",
    "crunchyroll_tv", "prime_movie", "prime_tv", "hulu_tv",
    "maoyan_movie", "maoyan_tv",
    "douban_showing", "douban_coming", "douban_new_movies", "douban_weekly_movie",
    "douban_movie_hot", "douban_tv_recent", "douban_tv_hot",
    "tmdb_trending", "anilist_trending", "bangumi_calendar",
    "tencent_hot", "tencent_tv",
]


def fetch_source(key: str, limit: int = 20, proxy: bool = False) -> Dict[str, Any]:
    spec = SOURCE_MAP.get(str(key or ""))
    if not spec:
        return {"ok": False, "key": key, "label": key, "items": [], "error": "未知榜单"}

    chain = RecommendChain()
    try:
        if spec.kind == "watch_provider":
            items = _tmdb_provider(chain, spec, limit, WATCH_PROVIDERS)
        elif spec.kind == "watch_provider_genre":
            items = _tmdb_provider_genre(chain, spec, limit, WATCH_PROVIDERS)
        elif spec.kind == "tmdb_genre":
            items = _tmdb_genre(chain, spec, limit)
        elif spec.kind in {"builtin", "builtin_mixed"}:
            items = _builtin(chain, spec, limit)
        elif spec.kind == "douban_discover":
            items = _douban_discover(chain, spec, limit)
        elif spec.kind == "douban_collection":
            items = _douban_collection(spec, spec.arg, limit, proxy)
        elif spec.kind == "douban_recommend":
            items = _douban_recommend(spec, limit, proxy)
        elif spec.kind == "douban_us_box":
            items = _douban_us_box(spec, limit, proxy)
        elif spec.kind == "netflix":
            items = _netflix(spec, limit, proxy)
        elif spec.kind == "imdb":
            items = _imdb(spec, limit, proxy)
        elif spec.kind == "maoyan":
            items = _maoyan(spec, limit, proxy)
        elif spec.kind == "anilist":
            items = _anilist(spec, limit)
        elif spec.kind == "popular_mixed":
            items = _normalize(
                (chain.tmdb_trending(page=1) or [])
                + (chain.douban_movie_hot(page=1, count=limit) or [])
                + (chain.douban_tv_hot(page=1, count=limit) or []),
                spec,
                limit,
            )
        else:
            items = []
        return {"ok": True, "key": spec.key, "label": spec.label, "items": items, "error": ""}
    except Exception as err:
        logger.warning("【每日助手】【%s】榜单获取失败: %s", spec.label, err)
        return {"ok": False, "key": spec.key, "label": spec.label, "items": [], "error": str(err)[:300]}


def source_options() -> List[Dict[str, str]]:
    return [{"title": spec.label, "value": spec.key} for spec in SOURCES]
