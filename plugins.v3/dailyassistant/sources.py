"""每日助手榜单来源。优先复用 MoviePilot V3 推荐链，少量公共榜单直连官方/公开端点。"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List

from app.chain.recommend import RecommendChain
from app.sdk.config import settings
from app.sdk.logging import logger
from app.sdk.network import RequestUtils
from app.schemas.types import MediaType


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
    # Tencent Video / WeTV 在 TMDB/JustWatch 目录中存在多个区域 provider，OR 组合可提升命中率。
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
        SOURCES.append(SourceSpec(f"{_family}_{_media}", f"{_label} · {_suffix}", _label, "watch_provider", _media, _family))

SOURCES.extend([
    SourceSpec("maoyan_movie", "猫眼 · 电影榜", "猫眼", "maoyan", "movie"),
    SourceSpec("maoyan_tv", "猫眼 · 剧集榜", "猫眼", "maoyan", "tv"),
    SourceSpec("maoyan_variety", "猫眼 · 综艺榜", "猫眼", "maoyan", "variety"),
    SourceSpec("maoyan_mixed", "猫眼 · 混合榜", "猫眼", "maoyan", "mixed"),

    # 豆瓣：补齐 MoviePilot 首页/豆瓣榜单中用户常用的电影与剧集栏目。
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

_YEAR_RE = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")
_DOUBAN_SUBJECT_RE = re.compile(r"(?:subject/|movie/subject/|tv/subject/)(\d{5,})")
_DOUBAN_US_BOX_API_KEY = "0df993c66c0c636e29ecbb5344252a4a"


def _year_value(value: Any) -> Any:
    """把年份字段规整成四位年份；猫眼等来源常返回“2026-09-01 上映”一类文本。"""
    if value is None or value == "":
        return None
    if isinstance(value, int) and 1900 <= value <= 2099:
        return value
    match = _YEAR_RE.search(str(value))
    return int(match.group(1)) if match else value


def _as_dict(item: Any) -> Dict[str, Any]:
    if isinstance(item, dict):
        return dict(item)
    to_dict = getattr(item, "to_dict", None)
    if callable(to_dict):
        try:
            value = to_dict()
            if isinstance(value, dict):
                return dict(value)
        except Exception:
            pass
    result: Dict[str, Any] = {}
    for key in (
        "title", "en_title", "year", "type", "season", "tmdb_id", "imdb_id",
        "douban_id", "bangumi_id", "anilist_id", "media_source", "media_id",
        "vote_average", "poster_path", "poster", "detail_link",
    ):
        value = getattr(item, key, None)
        if value is not None:
            result[key] = value
    return result


def _media_token(value: Any, fallback: str = "") -> str:
    if value == MediaType.MOVIE:
        return "movie"
    if value == MediaType.TV:
        return "tv"
    text = str(getattr(value, "value", value) or "").lower()
    if "movie" in text or text == "电影":
        return "movie"
    if "tv" in text or "series" in text or text == "电视剧":
        return "tv"
    return fallback


def _normalize(rows: Iterable[Any], spec: SourceSpec, limit: int) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    seen = set()
    for raw in rows or []:
        data = _as_dict(raw)
        title = str(data.get("title") or data.get("name") or "").strip()
        if not title:
            continue
        mtype = _media_token(data.get("type"), spec.media if spec.media in {"movie", "tv"} else "")
        if mtype not in {"movie", "tv"}:
            continue
        tmdb_id = data.get("tmdb_id")
        media_source = str(getattr(data.get("media_source"), "value", data.get("media_source")) or "").lower()
        media_id = data.get("media_id")
        if not tmdb_id and media_source in {"tmdb", "themoviedb"}:
            tmdb_id = media_id
        year = _year_value(data.get("year"))
        key = (str(tmdb_id or ""), mtype, title.casefold(), str(year or ""))
        if key in seen:
            continue
        seen.add(key)
        result.append({
            "title": title,
            "year": year,
            "media_type": mtype,
            "season": data.get("season"),
            "tmdb_id": str(tmdb_id or ""),
            "imdb_id": str(data.get("imdb_id") or ""),
            "douban_id": str(data.get("douban_id") or data.get("doubanid") or ""),
            "bangumi_id": str(data.get("bangumi_id") or ""),
            "anilist_id": str(data.get("anilist_id") or ""),
            "vote_average": data.get("vote_average"),
            "poster": data.get("poster_path") or data.get("poster") or "",
            "detail_link": data.get("detail_link") or "",
            "source_key": spec.key,
            "source_label": spec.label,
            "rank": len(result) + 1,
        })
        if len(result) >= max(1, limit):
            break
    return result


def _tmdb_provider(chain: RecommendChain, spec: SourceSpec, limit: int) -> List[Dict[str, Any]]:
    provider = WATCH_PROVIDERS[spec.arg]
    rows: List[Any] = []
    kwargs = {"with_watch_providers": str(provider), "page": 1}
    if spec.media in {"movie", "mixed"}:
        rows.extend(chain.tmdb_movies(**kwargs) or [])
    if spec.media in {"tv", "mixed"}:
        rows.extend(chain.tmdb_tvs(**kwargs) or [])
    return _normalize(rows, spec, limit)


def _tmdb_provider_genre(chain: RecommendChain, spec: SourceSpec, limit: int) -> List[Dict[str, Any]]:
    provider_key, genre = (spec.arg.split(":", 1) + [""])[:2]
    provider = WATCH_PROVIDERS[provider_key]
    rows: List[Any] = []
    kwargs = {"with_watch_providers": str(provider), "with_genres": genre, "page": 1}
    if spec.media in {"movie", "mixed"}:
        rows.extend(chain.tmdb_movies(**kwargs) or [])
    if spec.media in {"tv", "mixed"}:
        rows.extend(chain.tmdb_tvs(**kwargs) or [])
    return _normalize(rows, spec, limit)


def _tmdb_genre(chain: RecommendChain, spec: SourceSpec, limit: int) -> List[Dict[str, Any]]:
    rows: List[Any] = []
    kwargs = {"with_genres": spec.arg, "page": 1}
    if spec.media in {"movie", "mixed"}:
        rows.extend(chain.tmdb_movies(**kwargs) or [])
    if spec.media in {"tv", "mixed"}:
        rows.extend(chain.tmdb_tvs(**kwargs) or [])
    return _normalize(rows, spec, limit)


def _builtin(chain: RecommendChain, spec: SourceSpec, limit: int) -> List[Dict[str, Any]]:
    if spec.kind == "builtin_mixed":
        rows = (chain.douban_movie_hot(page=1, count=limit) or []) + (chain.douban_tv_hot(page=1, count=limit) or [])
    else:
        method = getattr(chain, spec.arg)
        try:
            rows = method(page=1, count=limit) or []
        except TypeError:
            rows = method(page=1) or []
    return _normalize(rows, spec, limit)


def _douban_discover(chain: RecommendChain, spec: SourceSpec, limit: int) -> List[Dict[str, Any]]:
    """复用 MoviePilot 豆瓣发现链；R=最近上映，U=综合/近期热门。"""
    rows: List[Any] = []
    if spec.media in {"movie", "mixed"}:
        rows.extend(chain.douban_movies(sort=spec.arg or "U", tags="", page=1, count=limit) or [])
    if spec.media in {"tv", "mixed"}:
        rows.extend(chain.douban_tvs(sort=spec.arg or "U", tags="", page=1, count=limit) or [])
    return _normalize(rows, spec, limit)


def _douban_subject_id(entry: Dict[str, Any]) -> str:
    direct = entry.get("id") or entry.get("subject_id") or entry.get("douban_id")
    if direct and str(direct).isdigit():
        return str(direct)
    link = str(entry.get("url") or entry.get("uri") or entry.get("alt") or "")
    match = _DOUBAN_SUBJECT_RE.search(link)
    return match.group(1) if match else ""


def _douban_collection(spec: SourceSpec, collection: str, limit: int, proxy: bool) -> List[Dict[str, Any]]:
    """直连豆瓣移动端公开 subject_collection，不依赖 RSSHub。"""
    url = f"https://m.douban.com/rexxar/api/v2/subject_collection/{collection}/items"
    request = RequestUtils(
        headers={
            "Referer": f"https://m.douban.com/subject_collection/{collection}",
            "User-Agent": "Mozilla/5.0 Chrome/131.0 Safari/537.36",
        },
        proxies=settings.PROXY if proxy else None,
    )
    response = request.get_res(url, params={"start": 0, "count": max(1, limit)})
    if response is None or getattr(response, "status_code", 500) >= 400:
        raise RuntimeError(f"豆瓣集合 HTTP {getattr(response, 'status_code', '无响应')}")
    payload = response.json() or {}
    entries = payload.get("subject_collection_items") or payload.get("items") or []
    rows = []
    for entry in entries[:max(1, limit)]:
        entry = entry or {}
        rating = entry.get("rating") or {}
        cover = entry.get("cover") or {}
        subtitle = entry.get("card_subtitle") or entry.get("description") or entry.get("abstract") or ""
        rows.append({
            "title": entry.get("title") or entry.get("name"),
            "year": _year_value(subtitle),
            "type": spec.media,
            "douban_id": _douban_subject_id(entry),
            "vote_average": rating.get("value") if isinstance(rating, dict) else None,
            "poster": (cover.get("url") if isinstance(cover, dict) else "") or entry.get("cover_url") or "",
            "detail_link": entry.get("url") or "",
        })
    return _normalize(rows, spec, limit)


def _douban_recommend(spec: SourceSpec, limit: int, proxy: bool) -> List[Dict[str, Any]]:
    """“豆瓣推荐”采用电影/剧集实时热门集合并行合并，避免混入图书和音乐。"""
    movie_spec = SourceSpec(spec.key, spec.label, spec.family, spec.kind, "movie", "movie_real_time_hotest")
    tv_spec = SourceSpec(spec.key, spec.label, spec.family, spec.kind, "tv", "tv_real_time_hotest")
    rows = _douban_collection(movie_spec, "movie_real_time_hotest", limit, proxy)
    rows.extend(_douban_collection(tv_spec, "tv_real_time_hotest", limit, proxy))
    rows.sort(key=lambda item: (int(item.get("rank") or 9999), item.get("media_type") or ""))
    return rows[:max(1, limit)]


def _douban_us_box(spec: SourceSpec, limit: int, proxy: bool) -> List[Dict[str, Any]]:
    """豆瓣北美票房榜；接口与 RSSHub 当前上游实现保持一致。"""
    request = RequestUtils(
        headers={"User-Agent": "Mozilla/5.0 Chrome/131.0 Safari/537.36"},
        proxies=settings.PROXY if proxy else None,
    )
    response = request.get_res(
        "https://api.douban.com/v2/movie/us_box",
        params={"apikey": _DOUBAN_US_BOX_API_KEY},
    )
    if response is None or getattr(response, "status_code", 500) >= 400:
        raise RuntimeError(f"豆瓣北美票房 HTTP {getattr(response, 'status_code', '无响应')}")
    payload = response.json() or {}
    rows = []
    for wrapper in (payload.get("subjects") or [])[:max(1, limit)]:
        item = (wrapper or {}).get("subject") or wrapper or {}
        rating = item.get("rating") or {}
        images = item.get("images") or {}
        rows.append({
            "title": item.get("title"),
            "year": item.get("year"),
            "type": "movie",
            "douban_id": item.get("id"),
            "vote_average": rating.get("average") if isinstance(rating, dict) else None,
            "poster": images.get("large") if isinstance(images, dict) else "",
            "detail_link": item.get("alt") or "",
        })
    return _normalize(rows, spec, limit)


def _netflix(spec: SourceSpec, limit: int, proxy: bool) -> List[Dict[str, Any]]:
    url = "https://www.netflix.com/tudum/top10/data/all-weeks-global.tsv"
    request = RequestUtils(proxies=settings.PROXY) if proxy else RequestUtils()
    response = request.get_res(url)
    if response is None or getattr(response, "status_code", 500) >= 400:
        raise RuntimeError(f"Netflix HTTP {getattr(response, 'status_code', '无响应')}")
    reader = csv.DictReader(io.StringIO(response.text or ""), delimiter="\t")
    rows = [row for row in reader if isinstance(row, dict)]
    if not rows:
        return []
    latest = max(str(row.get("week") or "") for row in rows)
    filtered = [row for row in rows if str(row.get("week") or "") == latest]
    output = []
    for row in filtered:
        category = str(row.get("category") or "")
        mtype = "movie" if category.startswith("Films") else "tv"
        if spec.media in {"movie", "tv"} and mtype != spec.media:
            continue
        title = str(row.get("show_title") or "").strip()
        if not title:
            continue
        output.append({
            "title": title, "year": None, "media_type": mtype, "season": None,
            "tmdb_id": "", "imdb_id": "", "vote_average": None, "poster": "",
            "detail_link": "https://www.netflix.com/tudum/top10",
            "source_key": spec.key, "source_label": spec.label,
            "rank": int(row.get("weekly_rank") or len(output) + 1),
        })
    output.sort(key=lambda item: int(item.get("rank") or 9999))
    return output[:max(1, limit)]


_IMDB_QUERY = """query Chart($first:Int!,$chartType:ChartType!){
  chartTitles(first:$first,chart:{chartType:$chartType}){
    edges{currentRank node{id titleText{text} releaseYear{year} primaryImage{url}}}
  }
}"""


def _imdb(spec: SourceSpec, limit: int, proxy: bool) -> List[Dict[str, Any]]:
    chart = "MOST_POPULAR_MOVIES" if spec.media == "movie" else "MOST_POPULAR_TV_SHOWS"
    request = RequestUtils(
        headers={
            "content-type": "application/json", "origin": "https://www.imdb.com",
            "referer": "https://www.imdb.com/chart/", "user-agent": "Mozilla/5.0 Chrome/131.0 Safari/537.36",
        },
        proxies=settings.PROXY if proxy else None,
    )
    response = request.post_res(
        "https://api.graphql.imdb.com/",
        json={"query": _IMDB_QUERY, "variables": {"first": max(1, limit), "chartType": chart}},
    )
    if response is None or getattr(response, "status_code", 500) >= 400:
        raise RuntimeError(f"IMDb HTTP {getattr(response, 'status_code', '无响应')}")
    edges = (((response.json() or {}).get("data") or {}).get("chartTitles") or {}).get("edges") or []
    rows = []
    for edge in edges:
        node = (edge or {}).get("node") or {}
        title = ((node.get("titleText") or {}).get("text") or "").strip()
        if not title:
            continue
        rows.append({
            "title": title, "year": (node.get("releaseYear") or {}).get("year"), "type": spec.media,
            "imdb_id": node.get("id"), "poster": (node.get("primaryImage") or {}).get("url") or "",
            "detail_link": f"https://www.imdb.com/title/{node.get('id')}/" if node.get("id") else "",
        })
    return _normalize(rows, spec, limit)


def _maoyan_request(path: str, params: Dict[str, Any], proxy: bool) -> Dict[str, Any]:
    request = RequestUtils(
        headers={"User-Agent": "Mozilla/5.0 Chrome/131.0 Safari/537.36", "Referer": "https://piaofang.maoyan.com/"},
        proxies=settings.PROXY if proxy else None,
    )
    response = request.get_res("https://piaofang.maoyan.com" + path, params=params)
    if response is None or getattr(response, "status_code", 500) >= 400:
        raise RuntimeError(f"猫眼 HTTP {getattr(response, 'status_code', '无响应')}")
    return response.json() or {}


def _maoyan_one(spec: SourceSpec, media: str, limit: int, proxy: bool) -> List[Dict[str, Any]]:
    platform_type = spec.arg if spec.arg.isdigit() else ""
    if media == "movie":
        payload = _maoyan_request("/dashboard-ajax/movie", {}, proxy)
        entries = ((payload.get("movieList") or {}).get("list") or [])
        rows = []
        for entry in entries[:limit]:
            info = (entry or {}).get("movieInfo") or {}
            rows.append({"title": info.get("movieName"), "year": info.get("releaseInfo"), "type": "movie"})
        return _normalize(rows, SourceSpec(spec.key, spec.label, spec.family, spec.kind, "movie", spec.arg), limit)
    series_type = "2" if media == "variety" else "4"
    payload = _maoyan_request(
        "/dashboard/webHeatData",
        {"seriesType": series_type, "platformType": platform_type, "showDate": "2"}, proxy,
    )
    entries = ((payload.get("dataList") or {}).get("list") or [])
    rows = []
    for entry in entries[:limit]:
        info = (entry or {}).get("seriesInfo") or {}
        rows.append({"title": info.get("name"), "year": info.get("releaseInfo"), "type": "tv"})
    return _normalize(rows, SourceSpec(spec.key, spec.label, spec.family, spec.kind, "tv", spec.arg), limit)


def _maoyan(spec: SourceSpec, limit: int, proxy: bool) -> List[Dict[str, Any]]:
    if spec.media == "mixed":
        rows = _maoyan_one(spec, "movie", limit, proxy) + _maoyan_one(spec, "tv", limit, proxy)
        rows.sort(key=lambda item: (item.get("rank") or 9999, item.get("media_type") or ""))
        return rows[:limit]
    return _maoyan_one(spec, spec.media, limit, proxy)


def _anilist(spec: SourceSpec, limit: int) -> List[Dict[str, Any]]:
    from app.chain.anilist import AniListChain
    return _normalize(AniListChain().trending(page=1, count=limit) or [], spec, limit)


def fetch_source(key: str, limit: int = 20, proxy: bool = False) -> Dict[str, Any]:
    spec = SOURCE_MAP.get(str(key or ""))
    if not spec:
        return {"ok": False, "key": key, "label": key, "items": [], "error": "未知榜单"}
    chain = RecommendChain()
    try:
        if spec.kind == "watch_provider":
            items = _tmdb_provider(chain, spec, limit)
        elif spec.kind == "watch_provider_genre":
            items = _tmdb_provider_genre(chain, spec, limit)
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
                (chain.tmdb_trending(page=1) or []) + (chain.douban_movie_hot(page=1, count=limit) or []) +
                (chain.douban_tv_hot(page=1, count=limit) or []), spec, limit,
            )
        else:
            items = []
        return {"ok": True, "key": spec.key, "label": spec.label, "items": items, "error": ""}
    except Exception as err:
        logger.warning("【每日助手】【%s】榜单获取失败: %s", spec.label, err)
        return {"ok": False, "key": spec.key, "label": spec.label, "items": [], "error": str(err)[:300]}


def source_options() -> List[Dict[str, str]]:
    return [{"title": spec.label, "value": spec.key} for spec in SOURCES]
