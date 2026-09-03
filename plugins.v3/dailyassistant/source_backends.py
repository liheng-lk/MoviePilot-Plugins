"""每日助手榜单后端实现。来源目录与调度保留在 sources.py。"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import replace
from typing import Any, Dict, Iterable, List

from bs4 import BeautifulSoup

from app.chain.recommend import RecommendChain
from app.sdk.config import settings
from app.sdk.network import RequestUtils
from app.schemas.types import MediaType

YEAR_RE = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")
DOUBAN_SUBJECT_RE = re.compile(r"(?:/subject/|(?:movie|tv)/)(\d{5,})(?:/|$|\?)")


def year_value(value: Any) -> Any:
    if value is None or value == "":
        return None
    if isinstance(value, int) and 1900 <= value <= 2099:
        return value
    match = YEAR_RE.search(str(value))
    return int(match.group(1)) if match else value


def as_dict(item: Any) -> Dict[str, Any]:
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
        "title", "name", "en_title", "year", "type", "season", "tmdb_id", "imdb_id",
        "douban_id", "doubanid", "bangumi_id", "anilist_id", "media_source", "media_id",
        "vote_average", "poster_path", "poster", "detail_link",
    ):
        value = getattr(item, key, None)
        if value is not None:
            result[key] = value
    return result


def media_token(value: Any, fallback: str = "") -> str:
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


def normalize(rows: Iterable[Any], spec: Any, limit: int) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    seen = set()
    for raw in rows or []:
        data = as_dict(raw)
        title = str(data.get("title") or data.get("name") or "").strip()
        if not title:
            continue
        mtype = media_token(data.get("type"), spec.media if spec.media in {"movie", "tv"} else "")
        if mtype not in {"movie", "tv"}:
            continue
        tmdb_id = data.get("tmdb_id")
        media_source = str(getattr(data.get("media_source"), "value", data.get("media_source")) or "").lower()
        if not tmdb_id and media_source in {"tmdb", "themoviedb"}:
            tmdb_id = data.get("media_id")
        year = year_value(data.get("year"))
        identity = (str(tmdb_id or ""), mtype, title.casefold(), str(year or ""))
        if identity in seen:
            continue
        seen.add(identity)
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


def tmdb_provider(chain: RecommendChain, spec: Any, limit: int, providers: Dict[str, Any]) -> List[Dict[str, Any]]:
    provider = providers[spec.arg]
    kwargs = {"with_watch_providers": str(provider), "page": 1}
    rows: List[Any] = []
    if spec.media in {"movie", "mixed"}:
        rows.extend(chain.tmdb_movies(**kwargs) or [])
    if spec.media in {"tv", "mixed"}:
        rows.extend(chain.tmdb_tvs(**kwargs) or [])
    return normalize(rows, spec, limit)


def tmdb_provider_genre(chain: RecommendChain, spec: Any, limit: int, providers: Dict[str, Any]) -> List[Dict[str, Any]]:
    provider_key, genre = (spec.arg.split(":", 1) + [""])[:2]
    kwargs = {"with_watch_providers": str(providers[provider_key]), "with_genres": genre, "page": 1}
    rows: List[Any] = []
    if spec.media in {"movie", "mixed"}:
        rows.extend(chain.tmdb_movies(**kwargs) or [])
    if spec.media in {"tv", "mixed"}:
        rows.extend(chain.tmdb_tvs(**kwargs) or [])
    return normalize(rows, spec, limit)


def tmdb_genre(chain: RecommendChain, spec: Any, limit: int) -> List[Dict[str, Any]]:
    kwargs = {"with_genres": spec.arg, "page": 1}
    rows: List[Any] = []
    if spec.media in {"movie", "mixed"}:
        rows.extend(chain.tmdb_movies(**kwargs) or [])
    if spec.media in {"tv", "mixed"}:
        rows.extend(chain.tmdb_tvs(**kwargs) or [])
    return normalize(rows, spec, limit)


def builtin(chain: RecommendChain, spec: Any, limit: int) -> List[Dict[str, Any]]:
    if spec.kind == "builtin_mixed":
        rows = (chain.douban_movie_hot(page=1, count=limit) or []) + (chain.douban_tv_hot(page=1, count=limit) or [])
    else:
        method = getattr(chain, spec.arg)
        try:
            rows = method(page=1, count=limit) or []
        except TypeError:
            rows = method(page=1) or []
    return normalize(rows, spec, limit)


def douban_discover(chain: RecommendChain, spec: Any, limit: int) -> List[Dict[str, Any]]:
    rows: List[Any] = []
    if spec.media in {"movie", "mixed"}:
        rows.extend(chain.douban_movies(sort=spec.arg or "U", tags="", page=1, count=limit) or [])
    if spec.media in {"tv", "mixed"}:
        rows.extend(chain.douban_tvs(sort=spec.arg or "U", tags="", page=1, count=limit) or [])
    return normalize(rows, spec, limit)


def douban_subject_id(entry: Dict[str, Any]) -> str:
    direct = entry.get("id") or entry.get("subject_id") or entry.get("douban_id")
    if direct and str(direct).isdigit():
        return str(direct)
    link = str(entry.get("url") or entry.get("uri") or entry.get("alt") or "")
    match = DOUBAN_SUBJECT_RE.search(link)
    return match.group(1) if match else ""


def douban_collection(spec: Any, collection: str, limit: int, proxy: bool) -> List[Dict[str, Any]]:
    url = f"https://m.douban.com/rexxar/api/v2/subject_collection/{collection}/items"
    request = RequestUtils(
        headers={"Referer": f"https://m.douban.com/subject_collection/{collection}", "User-Agent": "Mozilla/5.0 Chrome/131.0 Safari/537.36"},
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
            "year": year_value(subtitle),
            "type": spec.media,
            "douban_id": douban_subject_id(entry),
            "vote_average": rating.get("value") if isinstance(rating, dict) else None,
            "poster": (cover.get("url") if isinstance(cover, dict) else "") or entry.get("cover_url") or "",
            "detail_link": entry.get("url") or "",
        })
    return normalize(rows, spec, limit)


def douban_recommend(spec: Any, limit: int, proxy: bool) -> List[Dict[str, Any]]:
    movie_spec = replace(spec, media="movie", arg="movie_real_time_hotest")
    tv_spec = replace(spec, media="tv", arg="tv_real_time_hotest")
    rows = douban_collection(movie_spec, "movie_real_time_hotest", limit, proxy)
    rows.extend(douban_collection(tv_spec, "tv_real_time_hotest", limit, proxy))
    rows.sort(key=lambda item: (int(item.get("rank") or 9999), item.get("media_type") or ""))
    return rows[:max(1, limit)]


def douban_us_box(spec: Any, limit: int, proxy: bool) -> List[Dict[str, Any]]:
    """旧 v2/movie/us_box 已实测 HTTP 400，改抓豆瓣 chart 页的当前北美票房模块。"""
    request = RequestUtils(
        headers={
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 Version/15.0 Mobile/15E148 Safari/604.1",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://movie.douban.com/",
        },
        proxies=settings.PROXY if proxy else None,
    )
    response = request.get_res("https://movie.douban.com/chart/")
    if response is None or getattr(response, "status_code", 500) >= 400:
        raise RuntimeError(f"豆瓣北美票房页 HTTP {getattr(response, 'status_code', '无响应')}")
    soup = BeautifulSoup(response.text or "", "html.parser")
    target = None
    for heading in soup.find_all("h2"):
        if "北美票房榜" in heading.get_text(" ", strip=True):
            target = heading.find_next_sibling("ul") or heading.find_next("ul")
            break
    if target is None:
        raise RuntimeError("豆瓣北美票房页面结构已变化：未找到榜单")
    rows = []
    for li in target.find_all("li", recursive=False):
        anchor = li.select_one(".box_chart a[href*='/subject/']") or li.select_one("a[href*='/subject/']")
        if not anchor:
            continue
        href = str(anchor.get("href") or "")
        title = str(anchor.get("title") or anchor.get_text(" ", strip=True) or "").strip()
        if not title:
            continue
        subject_match = re.search(r"/subject/(\d+)", href)
        image = li.find("img")
        poster = ""
        if image:
            raw = str(image.get("data-src") or image.get("data-original") or image.get("src") or "")
            if raw and not any(marker in raw for marker in ("box_new.png", "box_hot.png", "/pics/box_", "/f/vendors/")):
                poster = "https:" + raw if raw.startswith("//") else raw
        rows.append({"title": title, "year": None, "type": "movie", "douban_id": subject_match.group(1) if subject_match else "", "poster": poster, "detail_link": href})
        if len(rows) >= max(1, limit):
            break
    if not rows:
        raise RuntimeError("豆瓣北美票房页面结构已变化：榜单为空")
    return normalize(rows, spec, limit)


def netflix(spec: Any, limit: int, proxy: bool) -> List[Dict[str, Any]]:
    url = "https://www.netflix.com/tudum/top10/data/all-weeks-global.tsv"
    response = (RequestUtils(proxies=settings.PROXY) if proxy else RequestUtils()).get_res(url)
    if response is None or getattr(response, "status_code", 500) >= 400:
        raise RuntimeError(f"Netflix HTTP {getattr(response, 'status_code', '无响应')}")
    rows = [row for row in csv.DictReader(io.StringIO(response.text or ""), delimiter="\t") if isinstance(row, dict)]
    if not rows:
        return []
    latest = max(str(row.get("week") or "") for row in rows)
    output = []
    for row in rows:
        if str(row.get("week") or "") != latest:
            continue
        mtype = "movie" if str(row.get("category") or "").startswith("Films") else "tv"
        if spec.media in {"movie", "tv"} and spec.media != mtype:
            continue
        title = str(row.get("show_title") or "").strip()
        if title:
            output.append({"title": title, "year": None, "media_type": mtype, "tmdb_id": "", "imdb_id": "", "vote_average": None, "poster": "", "detail_link": "https://www.netflix.com/tudum/top10", "source_key": spec.key, "source_label": spec.label, "rank": int(row.get("weekly_rank") or len(output) + 1)})
    output.sort(key=lambda item: int(item.get("rank") or 9999))
    return output[:max(1, limit)]


def imdb(spec: Any, limit: int, proxy: bool) -> List[Dict[str, Any]]:
    chart = "MOST_POPULAR_MOVIES" if spec.media == "movie" else "MOST_POPULAR_TV_SHOWS"
    query = f"""query MoviemeterChart($first: Int!, $sort: AdvancedTitleSearchSort) {{
      chartTitles(first: $first, chart: {{ chartType: {chart} }}, sort: $sort) {{
        edges {{ currentRank node {{ id titleText {{ text }} releaseYear {{ year }} primaryImage {{ url }} }} }}
      }}
    }}"""
    request = RequestUtils(
        headers={"content-type": "application/json", "origin": "https://www.imdb.com", "referer": "https://www.imdb.com/chart/moviemeter/", "user-agent": "Mozilla/5.0 Chrome/131.0 Safari/537.36", "accept-language": "en-US,en;q=0.9"},
        proxies=settings.PROXY if proxy else None,
    )
    response = request.post_res("https://api.graphql.imdb.com/", json={"query": query, "variables": {"first": max(1, limit), "sort": {"sortBy": "POPULARITY", "sortOrder": "ASC"}}})
    if response is None or getattr(response, "status_code", 500) >= 400:
        raise RuntimeError(f"IMDb HTTP {getattr(response, 'status_code', '无响应')}")
    edges = (((response.json() or {}).get("data") or {}).get("chartTitles") or {}).get("edges") or []
    rows = []
    for edge in edges:
        node = (edge or {}).get("node") or {}
        title = ((node.get("titleText") or {}).get("text") or "").strip()
        if title:
            rows.append({"title": title, "year": (node.get("releaseYear") or {}).get("year"), "type": spec.media, "imdb_id": node.get("id"), "poster": (node.get("primaryImage") or {}).get("url") or "", "detail_link": f"https://www.imdb.com/title/{node.get('id')}/" if node.get("id") else ""})
    return normalize(rows, spec, limit)


def maoyan_request(path: str, params: Dict[str, Any], proxy: bool) -> Dict[str, Any]:
    request = RequestUtils(headers={"User-Agent": "Mozilla/5.0 Chrome/131.0 Safari/537.36", "Referer": "https://piaofang.maoyan.com/"}, proxies=settings.PROXY if proxy else None)
    response = request.get_res("https://piaofang.maoyan.com" + path, params=params)
    if response is None or getattr(response, "status_code", 500) >= 400:
        raise RuntimeError(f"猫眼 HTTP {getattr(response, 'status_code', '无响应')}")
    return response.json() or {}


def maoyan_one(spec: Any, media: str, limit: int, proxy: bool) -> List[Dict[str, Any]]:
    platform_type = spec.arg if str(spec.arg).isdigit() else ""
    if media == "movie":
        entries = ((maoyan_request("/dashboard-ajax/movie", {}, proxy).get("movieList") or {}).get("list") or [])
        rows = [{"title": ((entry or {}).get("movieInfo") or {}).get("movieName"), "year": ((entry or {}).get("movieInfo") or {}).get("releaseInfo"), "type": "movie"} for entry in entries[:limit]]
        return normalize(rows, replace(spec, media="movie"), limit)
    series_type = "2" if media == "variety" else "4"
    entries = ((maoyan_request("/dashboard/webHeatData", {"seriesType": series_type, "platformType": platform_type, "showDate": "2"}, proxy).get("dataList") or {}).get("list") or [])
    rows = [{"title": ((entry or {}).get("seriesInfo") or {}).get("name"), "year": ((entry or {}).get("seriesInfo") or {}).get("releaseInfo"), "type": "tv"} for entry in entries[:limit]]
    return normalize(rows, replace(spec, media="tv"), limit)


def maoyan(spec: Any, limit: int, proxy: bool) -> List[Dict[str, Any]]:
    if spec.media == "mixed":
        rows = maoyan_one(spec, "movie", limit, proxy) + maoyan_one(spec, "tv", limit, proxy)
        rows.sort(key=lambda item: (item.get("rank") or 9999, item.get("media_type") or ""))
        return rows[:limit]
    return maoyan_one(spec, spec.media, limit, proxy)


def anilist(spec: Any, limit: int) -> List[Dict[str, Any]]:
    from app.chain.anilist import AniListChain
    return normalize(AniListChain().trending(page=1, count=limit) or [], spec, limit)
