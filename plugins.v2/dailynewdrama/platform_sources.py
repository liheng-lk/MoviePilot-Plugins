import datetime
import json
import re
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.log import logger
from app.utils.http import RequestUtils


UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"
CURRENT_YEAR = datetime.date.today().year


def _year(value: Any) -> Optional[int]:
    text = str(value or "")
    m = re.search(r"\b(19\d{2}|20\d{2})\b", text)
    return int(m.group(1)) if m else None


def _status_text(*values: Any) -> str:
    text = " ".join(str(v or "").strip() for v in values if v not in (None, ""))
    return re.sub(r"\s+", " ", text).strip()


def _is_finished(text: str) -> bool:
    t = str(text or "")
    return bool(re.search(r"(?:全\s*\d+\s*集|已完结|完结|收官|大结局)", t))


def _is_ongoing(text: str) -> bool:
    t = str(text or "")
    if _is_finished(t):
        return False
    return bool(re.search(r"(?:更新至\s*\d+|连载|持续更新|每周|更新中|热播中|在播)", t))


def _candidate(platform: str, title: str, year: Any = None, remark: str = "", poster: str = "",
               url: str = "", recent: bool = False, ongoing: bool = False, platform_id: str = "") -> Optional[Dict[str, Any]]:
    title = str(title or "").strip()
    if not title:
        return None
    status = _status_text(remark)
    y = _year(year) or _year(status)
    ongoing = bool(ongoing or _is_ongoing(status)) and not _is_finished(status)
    # 平台“新上线”列表本身可以作为近期依据；普通频道则至少要求本年/上年或明确仍在更新。
    recent = bool(recent or (y is not None and y >= CURRENT_YEAR - 1))
    if not (recent or ongoing):
        return None
    return {
        "title": title,
        "year": y,
        "doubanid": "",
        "air_date": "",
        "source": "platform_ongoing" if ongoing else "platform_recent",
        "source_label": platform + ("·更新中" if ongoing else "·近期上线"),
        "platforms": [platform],
        "platform": platform,
        "platform_id": str(platform_id or ""),
        "platform_url": str(url or ""),
        "platform_remark": status,
        "poster": poster,
        "ongoing": ongoing,
        "recent": recent,
    }


def _request_json(url: str, *, method: str = "GET", params: Optional[dict] = None,
                  payload: Optional[dict] = None, proxy: bool = False,
                  flaresolverr_enabled: bool = False, flaresolverr_url: str = "") -> Tuple[Optional[dict], str]:
    headers = {"User-Agent": UA, "Referer": urllib.parse.urlsplit(url).scheme + "://" + urllib.parse.urlsplit(url).netloc + "/"}
    request = RequestUtils(headers=headers, proxies=settings.PROXY) if proxy else RequestUtils(headers=headers)
    try:
        if method.upper() == "POST":
            res = request.post_res(url, params=params, json=payload)
        else:
            res = request.get_res(url, params=params)
        if res is not None and getattr(res, "status_code", 500) < 400:
            text = res.text or ""
            low = text.lower()
            if "cf-chl-" not in low and not ("cloudflare" in low and "challenge" in low):
                try:
                    return res.json(), "direct"
                except Exception as err:
                    direct_error = f"JSON解析失败: {err}"
            else:
                direct_error = "Cloudflare challenge"
        else:
            direct_error = f"HTTP {getattr(res, 'status_code', '无响应')}"
    except Exception as err:
        direct_error = str(err)

    if not flaresolverr_enabled or not flaresolverr_url:
        return None, direct_error
    try:
        target = url
        if params:
            target += ("&" if "?" in target else "?") + urllib.parse.urlencode(params)
        flare_payload: Dict[str, Any] = {
            "cmd": "request.post" if method.upper() == "POST" else "request.get",
            "url": target,
            "maxTimeout": 60000,
        }
        if method.upper() == "POST" and payload is not None:
            flare_payload["postData"] = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        flare = RequestUtils().post_res(flaresolverr_url.rstrip("/") + "/v1", json=flare_payload)
        if flare is None or getattr(flare, "status_code", 500) >= 400:
            return None, f"{direct_error}; FlareSolverr HTTP {getattr(flare, 'status_code', '无响应')}"
        data = flare.json()
        if str(data.get("status") or "").lower() != "ok":
            return None, f"{direct_error}; FlareSolverr {data.get('message') or '失败'}"
        html = (data.get("solution") or {}).get("response") or ""
        try:
            return json.loads(html), "flaresolverr"
        except Exception as err:
            return None, f"{direct_error}; FlareSolverr JSON解析失败: {err}"
    except Exception as err:
        return None, f"{direct_error}; FlareSolverr {err}"


def fetch_tencent(proxy: bool = False, flaresolverr_enabled: bool = False, flaresolverr_url: str = "") -> Tuple[List[Dict[str, Any]], str]:
    url = "https://pbaccess.video.qq.com/trpc.universal_backend_service.page_server_rpc.PageServer/GetPageData"
    params = {"video_appid": "1000005", "vplatform": "2", "vversion_name": "8.9.10", "new_mark_label_enabled": "1"}
    body = {"page_params": {"channel_id": "100113", "filter_params": "sort=75", "page_type": "channel_operation", "page_id": "channel_list_second_page"}}
    data, via = _request_json(url, method="POST", params=params, payload=body, proxy=proxy,
                              flaresolverr_enabled=flaresolverr_enabled, flaresolverr_url=flaresolverr_url)
    if not data:
        return [], via
    result: List[Dict[str, Any]] = []
    modules = ((data.get("data") or {}).get("module_list_datas") or [])
    for module in modules:
        for m in module.get("module_datas") or []:
            for item in (((m.get("item_data_lists") or {}).get("item_datas")) or []):
                p = item.get("item_params") or {}
                cid = p.get("cid") or item.get("id")
                title = p.get("mz_title") or p.get("title")
                if not title or not cid:
                    continue
                tag = {}
                try:
                    tag = json.loads(p.get("uni_imgtag") or p.get("imgtag") or "{}")
                except Exception:
                    pass
                year = (tag.get("tag_2") or {}).get("text") or p.get("publish_date")
                remark = _status_text((tag.get("tag_4") or {}).get("text"), p.get("episode_updated"), p.get("sub_title"), p.get("rec_subtitle"))
                item_out = _candidate("腾讯视频", title, year, remark, p.get("new_pic_vt") or p.get("image_url") or "",
                                      f"https://v.qq.com/x/cover/{cid}.html", ongoing=_is_ongoing(remark), platform_id=cid)
                if item_out:
                    result.append(item_out)
    return _dedupe(result), via


def fetch_iqiyi(proxy: bool = False, flaresolverr_enabled: bool = False, flaresolverr_url: str = "") -> Tuple[List[Dict[str, Any]], str]:
    url = "https://pcw-api.iqiyi.com/search/recommend/list"
    params = {"channel_id": 2, "data_type": 1, "page_id": 1, "ret_num": 48, "mode": 4}
    data, via = _request_json(url, params=params, proxy=proxy, flaresolverr_enabled=flaresolverr_enabled, flaresolverr_url=flaresolverr_url)
    if not data:
        return [], via
    result: List[Dict[str, Any]] = []

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            title = obj.get("name") or obj.get("title") or obj.get("albumName")
            aid = obj.get("albumId") or obj.get("album_id") or obj.get("qipuId") or obj.get("id")
            if title and aid:
                remark = _status_text(obj.get("latestOrder"), obj.get("latest_order"), obj.get("updateStrategy"), obj.get("period"), obj.get("description"), obj.get("subtitle"))
                latest = obj.get("latestOrder") or obj.get("latest_order")
                total = obj.get("videoCount") or obj.get("video_count") or obj.get("total")
                ongoing = False
                try:
                    ongoing = bool(latest and total and int(latest) < int(total))
                except Exception:
                    ongoing = _is_ongoing(remark)
                out = _candidate("爱奇艺", title, obj.get("year") or obj.get("publishTime"), remark,
                                 obj.get("imageUrl") or obj.get("image_url") or obj.get("poster") or "",
                                 obj.get("pageUrl") or obj.get("url") or f"https://www.iqiyi.com/a_{aid}.html",
                                 recent=True, ongoing=ongoing, platform_id=aid)
                if out:
                    result.append(out)
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    walk(data.get("data") or data)
    return _dedupe(result), via


def fetch_mgtv(proxy: bool = False, flaresolverr_enabled: bool = False, flaresolverr_url: str = "") -> Tuple[List[Dict[str, Any]], str]:
    url = "https://pianku.api.mgtv.com/rider/list/pcweb/v3"
    params = {"allowedRC": "1", "platform": "pcweb", "channelId": "2", "pn": "1", "pc": "80", "hudong": "1", "_support": "10000000"}
    data, via = _request_json(url, params=params, proxy=proxy, flaresolverr_enabled=flaresolverr_enabled, flaresolverr_url=flaresolverr_url)
    if not data:
        return [], via
    docs = ((data.get("data") or {}).get("hitDocs") or [])
    result: List[Dict[str, Any]] = []
    for item in docs:
        title = item.get("title")
        clip = item.get("clipId") or item.get("id")
        remark = _status_text(item.get("updateInfo"), item.get("desc"), item.get("subtitle"), item.get("lastUpdate"), item.get("rightText"))
        out = _candidate("芒果TV", title, item.get("year"), remark, item.get("img") or item.get("image") or "",
                         f"https://www.mgtv.com/b/{clip}.html" if clip else "", ongoing=_is_ongoing(remark), platform_id=clip)
        if out:
            result.append(out)
    return _dedupe(result), via


def fetch_bilibili(proxy: bool = False, flaresolverr_enabled: bool = False, flaresolverr_url: str = "") -> Tuple[List[Dict[str, Any]], str]:
    url = "https://api.bilibili.com/pgc/season/index/result"
    params = {"season_type": 5, "type": 1, "page": 1, "pagesize": 50, "is_finish": 0}
    data, via = _request_json(url, params=params, proxy=proxy, flaresolverr_enabled=flaresolverr_enabled, flaresolverr_url=flaresolverr_url)
    if not data:
        return [], via
    entries = ((data.get("data") or {}).get("list") or [])
    result: List[Dict[str, Any]] = []
    for item in entries:
        title = item.get("title")
        media_id = item.get("media_id") or item.get("season_id")
        remark = _status_text(item.get("index_show"), item.get("order"), item.get("new_ep"), item.get("subtitle"))
        out = _candidate("哔哩哔哩", title, item.get("year") or item.get("release_date"), remark,
                         item.get("cover") or "", f"https://www.bilibili.com/bangumi/media/md{media_id}" if media_id else "",
                         ongoing=True, platform_id=media_id)
        if out:
            result.append(out)
    return _dedupe(result), via


def fetch_youku(proxy: bool = False, flaresolverr_enabled: bool = False, flaresolverr_url: str = "") -> Tuple[List[Dict[str, Any]], str]:
    base = "https://www.youku.com/category/data"
    base_params = {"params": json.dumps({"type": "电视剧"}, ensure_ascii=False, separators=(",", ":")), "optionRefresh": 1, "pageNo": 1}
    first, via = _request_json(base, params=base_params, proxy=proxy, flaresolverr_enabled=flaresolverr_enabled, flaresolverr_url=flaresolverr_url)
    if not first:
        return [], via
    filter_data = ((first.get("data") or {}).get("filterData") or {})
    session = filter_data.get("session")
    data = first
    if session:
        params = {"session": json.dumps(session, ensure_ascii=False, separators=(",", ":")), "params": base_params["params"], "pageNo": 1}
        second, via2 = _request_json(base, params=params, proxy=proxy, flaresolverr_enabled=flaresolverr_enabled, flaresolverr_url=flaresolverr_url)
        if second:
            data, via = second, via2
    rows = (((data.get("data") or {}).get("filterData") or {}).get("listData") or [])
    result: List[Dict[str, Any]] = []
    for item in rows:
        title = item.get("title")
        link = item.get("videoLink") or ""
        sid = ""
        if "s=" in link:
            sid = link.split("s=")[-1].split("&", 1)[0]
        remark = _status_text(item.get("summary"), item.get("rightTagText"), item.get("updateNotice"))
        out = _candidate("优酷", title, item.get("rightTagText"), remark, item.get("img") or "", link,
                         ongoing=_is_ongoing(remark), platform_id=sid)
        if out:
            result.append(out)
    return _dedupe(result), via


def _dedupe(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    result = []
    for item in items:
        key = (str(item.get("title") or "").strip().lower(), item.get("year"))
        if not key[0] or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


PROVIDERS = {
    "tencent": ("腾讯视频", fetch_tencent),
    "iqiyi": ("爱奇艺", fetch_iqiyi),
    "youku": ("优酷", fetch_youku),
    "mgtv": ("芒果TV", fetch_mgtv),
    "bilibili": ("哔哩哔哩", fetch_bilibili),
}


def fetch_platform_sources(enabled: Dict[str, bool], *, proxy: bool = False,
                           flaresolverr_enabled: bool = False, flaresolverr_url: str = "") -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    items: List[Dict[str, Any]] = []
    status: Dict[str, Dict[str, Any]] = {}
    for key, (name, func) in PROVIDERS.items():
        if not enabled.get(key, True):
            status[name] = {"ok": True, "count": 0, "via": "disabled", "error": ""}
            continue
        try:
            rows, via = func(proxy=proxy, flaresolverr_enabled=flaresolverr_enabled, flaresolverr_url=flaresolverr_url)
            ok = bool(rows)
            status[name] = {"ok": ok, "count": len(rows), "via": via, "error": "" if ok else via}
            items.extend(rows)
            logger.info("【每日新剧助手】【%s】获取 %s 条，通道=%s", name, len(rows), via)
        except Exception as err:
            status[name] = {"ok": False, "count": 0, "via": "error", "error": str(err)}
            logger.warning("【每日新剧助手】【%s】获取失败: %s", name, err)
    return items, status
