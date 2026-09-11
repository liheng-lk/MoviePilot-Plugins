"""2.0.9：统一消息资源提取 + Resource Inbox（RAW HTML 优先，先于 legacy）。"""
from __future__ import annotations

import hashlib
import html
import re
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from .source_types_v180 import normalize_source_uri
from .transfer_diag_v209 import stable_trace_id


_INBOX_KEY = "channel_resource_inbox_v1"
_INBOX_RETENTION_SECONDS = 7 * 24 * 3600
_INBOX_MAX_ROWS = 5000
_DECODE_MAX_CHARS = 2_000_000
_WRAP_MAX_DEPTH = 3

_ATTR_URL_RE = re.compile(
    r"(?i)\b(?:href|data-href|data-url|data-link|data-button-url|data-clipboard-text|"
    r"data-clipboard|data-copy|data-target-url|data-share-url|onclick|value)\s*=\s*([\"'])(.*?)\1"
)
_JS_URL_RE = re.compile(
    r"(?i)(?:window\.open|location\.href\s*=|location\.assign)\s*\(\s*([\"'])(.*?)\1|"
    r"location\.href\s*=\s*([\"'])(.*?)\3"
)
_JSON_URL_RE = re.compile(
    r"(?i)[\"'](?:url|href|link|shareUrl|share_url|downloadUrl|download_url)[\"']\s*:\s*[\"']([^\"']+)[\"']"
)
_WRAP_KEYS = ("url", "target", "redirect", "redirect_uri", "link", "u")
_GUANGYA_HOSTS = frozenset({
    "guangyapan.com",
    "www.guangyapan.com",
    "guangyunav.com",
    "www.guangyunav.com",
})
_GUANGYA_RE = re.compile(
    r"https?://(?:www\.)?(?:guangyapan|guangyunav)\.com/[^\s\"'<>]+",
    re.I,
)
_XUNLEI_RE = re.compile(r"https?://pan\.xunlei\.com/[^\s\"'<>]+", re.I)
_MAGNET_RE = re.compile(r"magnet:\?[^\s\"'<>]+", re.I)
# ED2K filename may contain spaces / CJK / punctuation — do not truncate on whitespace.
_ED2K_RE = re.compile(
    r"ed2k://\|file\|[^|]+\|\d+\|[0-9A-Fa-f]{32}\|/?",
    re.I,
)
_OTHER_HOST_RE = re.compile(
    r"https?://(?:(?:www\.)?(?:115cdn\.com|115\.com|anxia\.com|quark\.cn|pan\.quark\.cn|"
    r"pan\.baidu\.com|aliyundrive\.com|www\.aliyundrive\.com|alipan\.com|www\.alipan\.com|"
    r"123pan\.com|www\.123pan\.com|drive\.uc\.cn)[^\s\"'<>]*)",
    re.I,
)
_PWD_IN_URL_RE = re.compile(r"(?i)[?&](?:pwd|passcode|password|code)=([A-Za-z0-9]{3,12})")
_LABELLED_TITLE_RE = re.compile(
    r"(?im)(?:^|\n)\s*(?:名称|片名|剧名|标题)\s*[：:]\s*([^\n]{2,320})"
)
_SERIES_EMOJI_RE = re.compile(r"(?im)(?:^|\n)\s*(?:📺\s*)?剧集\s*[：:]\s*([^\n]{2,320})")
_MOVIE_EMOJI_RE = re.compile(r"(?im)(?:^|\n)\s*(?:🎬\s*)?电影\s*[：:]\s*([^\n]{2,320})")
_YEAR_RE = re.compile(r"[（(]\s*((?:19|20)\d{2})\s*[）)]|\b((?:19|20)\d{2})\b")
_SEASON_RE = re.compile(r"(?i)\bS(?:eason)?[ ._\-]*0*(\d{1,2})\b|第\s*0*(\d{1,2})\s*季")
_EPISODE_RE = re.compile(
    r"(?i)\bS\d{1,2}\s*E(?:pisode)?[ ._\-]*0*(\d{1,4})\b|"
    r"\bE(?:P|pisode)?[ ._\-]*0*(\d{1,4})\b|"
    r"更至\s*EP?\s*0*(\d{1,4})|"
    r"第\s*0*(\d{1,4})\s*集"
)
_TOTAL_EP_RE = re.compile(r"(?:〖|^|\s)(\d{1,4})\s*集全|全\s*(\d{1,4})\s*集|共\s*(\d{1,4})\s*集")
_TMDB_RE = re.compile(r"(?i)\bTMDB\s*(?:ID)?\s*[：:#]?\s*(\d{2,9})")
_QUALITY_NOISE = re.compile(
    r"(?i)\b(?:2160p|1080p|720p|4k|8k|hdr|dv|web[- ]?dl|webrip|bluray|remux|hevc|x265|x264|高码率|中字)\b"
)


def _is_guangya_host(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    if not host:
        return False
    if host in _GUANGYA_HOSTS:
        return True
    return host.endswith(".guangyapan.com") or host.endswith(".guangyunav.com")


def _guangya_identity(url: str) -> str:
    path = ""
    try:
        parsed = urlparse(str(url or "").split("#", 1)[0])
        path = parsed.path or ""
    except Exception:
        path = str(url or "").split("?", 1)[0].split("#", 1)[0]
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2 and parts[-2].lower() in {"s", "share"}:
        return parts[-1].split("?")[0]
    return (parts[-1] if parts else "").split("?")[0]


def _normalize_guangya_uri(raw: str) -> str:
    text = str(raw or "").split("#", 1)[0].strip()
    if "guangyapan.com" in text.lower():
        try:
            from .legacy import _canonical_share_url
            canonical = _canonical_share_url(text)
            if canonical:
                return canonical
        except Exception:
            pass
    try:
        parsed = urlparse(text)
        if parsed.scheme and parsed.netloc and parsed.path:
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
    except Exception:
        pass
    return text


def _decode_blob(value: Any) -> str:
    current = html.unescape(str(value or ""))
    if len(current) > _DECODE_MAX_CHARS:
        current = current[:_DECODE_MAX_CHARS]
    current = current.replace("\\/", "/").replace("\\u002F", "/").replace("\\u002f", "/")
    for _ in range(3):
        decoded = unquote(current)
        if decoded == current:
            break
        current = decoded
        if len(current) > _DECODE_MAX_CHARS:
            current = current[:_DECODE_MAX_CHARS]
            break
    return current


def _unwrap_redirect(url: str, depth: int = 0) -> str:
    text = str(url or "").strip()
    if not text or depth >= _WRAP_MAX_DEPTH or len(text) > 8000:
        return text
    try:
        parsed = urlparse(text)
    except Exception:
        return text
    if not parsed.query:
        return text
    params = parse_qs(parsed.query)
    for key in _WRAP_KEYS:
        values = params.get(key) or []
        if not values:
            continue
        inner = _decode_blob(values[0])
        if inner and inner != text and (
            inner.startswith("http")
            or inner.startswith("magnet:")
            or inner.lower().startswith("ed2k:")
        ):
            return _unwrap_redirect(inner, depth + 1)
    return text


def _classify_other_url(url: str) -> Optional[Dict[str, str]]:
    raw = _unwrap_redirect(_decode_blob(url))
    if not raw.lower().startswith("http"):
        return None
    try:
        host = (urlparse(raw).hostname or "").lower()
    except Exception:
        return None
    label = ""
    if "115" in host or host.endswith("anxia.com"):
        label = "115"
    elif "quark" in host:
        label = "quark"
    elif "baidu" in host:
        label = "baidu"
    elif "aliyun" in host or "alipan" in host:
        label = "aliyun"
    elif "123pan" in host:
        label = "123"
    elif "uc.cn" in host:
        label = "uc"
    if not label:
        return None
    return {"kind": label, "uri": raw.split("#", 1)[0][:800], "actionable": "false"}


def _classify_protocol(url: str) -> Tuple[str, str, str]:
    """Return (type, uri, identity). type empty if unsupported."""
    raw = _unwrap_redirect(_decode_blob(url))
    if not raw:
        return "", "", ""
    lower = raw.lower()
    if lower.startswith("magnet:"):
        try:
            normalized = normalize_source_uri(raw)
            return "magnet", str(normalized.get("uri") or raw), str(normalized.get("identity") or "")
        except Exception:
            matched = re.search(r"(?i)urn:btih:([0-9a-z]+)", raw)
            identity = (matched.group(1).lower() if matched else raw[:80])
            return "magnet", raw, identity
    if lower.startswith("ed2k:"):
        try:
            normalized = normalize_source_uri(raw)
            return "ed2k", str(normalized.get("uri") or raw), str(normalized.get("identity") or "")
        except Exception:
            parts = raw.split("|")
            digest = parts[4].lower() if len(parts) >= 5 else raw[:80]
            return "ed2k", raw, digest
    if _is_guangya_host(raw):
        uri = _normalize_guangya_uri(raw)
        identity = _guangya_identity(uri) or _guangya_identity(raw)
        if identity:
            return "guangya", uri, identity
    if "pan.xunlei.com" in lower:
        identity = raw.split("?")[0].rstrip("/").split("/")[-1]
        uri = raw.split("#", 1)[0]
        return "xunlei", uri, identity
    return "", "", ""


def _collect_raw_urls(context_html: str, context_text: str) -> List[Tuple[str, str]]:
    """Return list of (url, extractor)."""
    raw_html = str(context_html or "")
    raw_text = str(context_text or "")
    decoded_html = _decode_blob(raw_html)
    decoded_text = _decode_blob(raw_text)
    found: List[Tuple[str, str]] = []

    def add(url: str, extractor: str) -> None:
        url = str(url or "").strip()
        if url:
            found.append((url, extractor))

    blob = decoded_text + "\n" + decoded_html
    for matched in _GUANGYA_RE.finditer(blob):
        add(matched.group(0), "visible_text")
    for matched in _XUNLEI_RE.finditer(blob):
        add(matched.group(0), "visible_text")
    for matched in _MAGNET_RE.finditer(blob):
        add(matched.group(0), "visible_text")
    for matched in _ED2K_RE.finditer(blob):
        add(matched.group(0), "visible_text")
    for matched in _OTHER_HOST_RE.finditer(blob):
        add(matched.group(0), "visible_text")

    for matched in _ATTR_URL_RE.finditer(raw_html):
        attr = matched.group(0).split("=", 1)[0].strip().lower()
        value = _decode_blob(matched.group(2))
        extractor = "href"
        if "clipboard" in attr or "copy" in attr:
            extractor = "clipboard"
        elif attr.startswith("data-"):
            extractor = "data"
        elif attr == "onclick":
            extractor = "onclick"
        elif attr == "value":
            extractor = "data"
        add(value, extractor)
        for nested in (
            _GUANGYA_RE.findall(value)
            + _XUNLEI_RE.findall(value)
            + _MAGNET_RE.findall(value)
            + _ED2K_RE.findall(value)
            + _OTHER_HOST_RE.findall(value)
        ):
            add(nested, extractor)

    for matched in _JS_URL_RE.finditer(raw_html):
        value = matched.group(2) or matched.group(4) or ""
        add(_decode_blob(value), "javascript")

    for matched in _JSON_URL_RE.finditer(raw_html):
        add(_decode_blob(matched.group(1)), "json")

    return found


def extract_message_resource_candidates_v209(
    context_html: str,
    context_text: str = "",
) -> List[Dict[str, Any]]:
    """统一消息级资源提取器：直接吃原始 message HTML。"""
    by_key: Dict[str, Dict[str, Any]] = {}
    other_urls: List[Dict[str, str]] = []
    other_seen: set = set()
    rank = {
        "clipboard": 5,
        "onclick": 4,
        "javascript": 4,
        "json": 4,
        "data": 3,
        "href": 2,
        "wrapped_redirect": 2,
        "visible_text": 1,
    }
    for url, extractor in _collect_raw_urls(context_html, context_text):
        unwrapped = _unwrap_redirect(url)
        kind, uri, identity = _classify_protocol(unwrapped)
        if kind and identity:
            key = f"{kind}:{identity}"
            final_extractor = (
                "wrapped_redirect"
                if unwrapped != url and extractor in {"href", "data", "visible_text"}
                else extractor
            )
            row = {
                "type": kind,
                "uri": uri,
                "identity": identity,
                "passcode": "",
                "extractor": final_extractor,
            }
            if kind == "xunlei":
                pwd = _PWD_IN_URL_RE.search(uri) or _PWD_IN_URL_RE.search(unwrapped)
                if pwd:
                    row["passcode"] = pwd.group(1)
            previous = by_key.get(key)
            if previous is None or rank.get(final_extractor, 0) > rank.get(str(previous.get("extractor") or ""), 0):
                by_key[key] = row
            continue
        other = _classify_other_url(unwrapped)
        if other:
            okey = f"{other.get('kind')}:{other.get('uri')}"
            if okey not in other_seen:
                other_seen.add(okey)
                other_urls.append(other)
    rows = list(by_key.values())
    for row in rows:
        row.setdefault("_other_urls", other_urls)
    if not rows and other_urls:
        return [{
            "type": "",
            "uri": "",
            "identity": "",
            "passcode": "",
            "extractor": "",
            "_other_urls": other_urls,
            "_diagnostic_only": True,
        }]
    return rows


def extract_message_resources_bundle_v209(
    context_html: str,
    context_text: str = "",
) -> Dict[str, Any]:
    """Return actionable candidates + other_urls for one message."""
    extracted = extract_message_resource_candidates_v209(context_html, context_text)
    other_urls: List[Dict[str, str]] = []
    candidates: List[Dict[str, Any]] = []
    for item in extracted:
        if item.get("_other_urls") and not other_urls:
            other_urls = list(item.get("_other_urls") or [])
        if item.get("_diagnostic_only") or not item.get("type"):
            continue
        clean = {k: v for k, v in item.items() if not str(k).startswith("_")}
        candidates.append(clean)
    return {"candidates": candidates, "other_urls": other_urls}


def _message_passcode(context_text: str, kind: str) -> str:
    text = str(context_text or "")
    if kind == "xunlei":
        matched = re.search(r"(?i)(?:pwd|passcode|password|密码|提取码)[:：\s]*([A-Za-z0-9]{4,8})", text)
        return str(matched.group(1) if matched else "")
    if kind == "guangya":
        matched = re.search(r"(?i)(?:code|pwd|密码|提取码)[:：\s]*([A-Za-z0-9]{3,12})", text)
        return str(matched.group(1) if matched else "")
    return ""


def enrich_candidates_with_local_passcode(candidates: List[Dict[str, Any]], context_text: str) -> List[Dict[str, Any]]:
    """验证码严格 message-local。"""
    output = []
    for row in candidates or []:
        item = dict(row)
        kind = str(item.get("type") or "")
        if kind in {"xunlei", "guangya"} and not item.get("passcode"):
            item["passcode"] = _message_passcode(context_text, kind)
        output.append(item)
    return output


def _strip_title_noise(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"〖[^〗]*〗", " ", text)
    text = re.sub(r"【[^】]*】", " ", text)
    text = _QUALITY_NOISE.sub(" ", text)
    text = re.sub(r"(?i)\bS\d{1,2}\s*E\d{1,4}\b", " ", text)
    text = re.sub(r"第\s*\d{1,3}\s*季", " ", text)
    text = re.sub(r"更至\s*EP?\d{1,4}", " ", text, flags=re.I)
    text = re.sub(r"[（(]\s*(?:19|20)\d{2}\s*[）)]", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -/|")
    return text[:200]


def _title_candidates_from_raw(raw_title: str) -> List[str]:
    cleaned = _strip_title_noise(raw_title)
    if not cleaned:
        return []
    parts = re.split(r"[/／|｜]", cleaned)
    out = []
    seen = set()
    for part in parts:
        token = part.strip()
        if not token or token in seen:
            continue
        seen.add(token)
        out.append(token)
    # Only keep the joined form when it is NOT an alias-separator compound.
    if cleaned not in seen and not re.search(r"[/／|｜]", cleaned):
        out.insert(0, cleaned)
    return out[:8]


def parse_message_title_metadata_v209(visible_text: str) -> Dict[str, Any]:
    """Parse channel title templates into structured metadata (message-local)."""
    text = str(visible_text or "")
    raw_title = ""
    type_hint = ""
    labelled = _LABELLED_TITLE_RE.search(text)
    series = _SERIES_EMOJI_RE.search(text)
    movie = _MOVIE_EMOJI_RE.search(text)
    if labelled:
        raw_title = labelled.group(1).strip()
    elif series:
        raw_title = series.group(1).strip()
        type_hint = "tv"
    elif movie:
        raw_title = movie.group(1).strip()
        type_hint = "movie"
    else:
        for line in text.splitlines()[:8]:
            line = line.strip()
            if not line or re.match(
                r"^(?:类型|TMDB|画质|质量|集数|大小|分享|简介|迅雷|磁力|密码|提取码|115)\s*[：:]",
                line,
                re.I,
            ):
                continue
            if re.search(r"[（(](?:19|20)\d{2}[）)]|\b(?:19|20)\d{2}\b", line):
                raw_title = line
                break
    year = ""
    year_match = _YEAR_RE.search(raw_title) or _YEAR_RE.search(text[:400])
    if year_match:
        year = year_match.group(1) or year_match.group(2) or ""
    season_hint = None
    season_match = _SEASON_RE.search(raw_title) or _SEASON_RE.search(text[:500])
    if season_match:
        season_hint = int(season_match.group(1) or season_match.group(2) or 0) or None
    episode_hint = ""
    ep_match = _EPISODE_RE.search(raw_title) or _EPISODE_RE.search(text[:500])
    if ep_match:
        if re.search(r"(?i)S\d+", ep_match.group(0) or ""):
            episode_hint = ep_match.group(0)
        else:
            num = next((g for g in ep_match.groups() if g), "")
            if num:
                episode_hint = f"E{int(num)}"
    total_episode_hint = None
    total_match = _TOTAL_EP_RE.search(raw_title) or _TOTAL_EP_RE.search(text[:400])
    if total_match:
        total_episode_hint = int(next(g for g in total_match.groups() if g))
    tmdb_id = ""
    tmdb_match = _TMDB_RE.search(text)
    if tmdb_match:
        tmdb_id = tmdb_match.group(1)
    match_title = _strip_title_noise(raw_title)
    title_candidates = _title_candidates_from_raw(raw_title or match_title)
    if match_title and ("/" in match_title or "／" in match_title):
        match_title = title_candidates[0] if title_candidates else re.split(r"[/／]", match_title)[0].strip()
    return {
        "raw_title": (raw_title or match_title)[:300],
        "match_title": match_title[:200],
        "title_candidates": title_candidates,
        "media_type_hint": type_hint,
        "tmdb_id": tmdb_id,
        "year": year,
        "season_hint": season_hint,
        "episode_hint": episode_hint,
        "total_episode_hint": total_episode_hint,
    }


def build_inbox_row_from_message_block(
    block: Dict[str, Any],
    *,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Build one ResourceGroup inbox row from a raw message block."""
    now = float(now if now is not None else time.time())
    raw_html = str(block.get("raw_html") or "")
    visible_text = str(block.get("visible_text") or "")
    bundle = extract_message_resources_bundle_v209(raw_html, visible_text)
    candidates = enrich_candidates_with_local_passcode(bundle.get("candidates") or [], visible_text)
    other_urls = list(bundle.get("other_urls") or [])
    meta = parse_message_title_metadata_v209(visible_text)
    channel = str(block.get("channel") or block.get("source_url") or "")
    source_url = str(block.get("source_url") or channel)
    message_id = str(block.get("message_id") or "")
    group_id = f"{channel}:{message_id}" if message_id else hashlib.sha1(
        f"{channel}|{meta.get('raw_title')}|{len(candidates)}".encode("utf-8", "ignore")
    ).hexdigest()[:20]
    raw_hash = hashlib.sha1(
        f"{channel}|{message_id}|{meta.get('raw_title')}|{len(candidates)}|{len(other_urls)}".encode("utf-8", "ignore")
    ).hexdigest()[:20]
    provenance = [{
        "channel": channel,
        "message_id": message_id,
        "extractor": ",".join(sorted({str(c.get("extractor") or "") for c in candidates if c.get("extractor")})) or "raw",
    }]
    trace_id = stable_trace_id(channel, message_id, group_id, raw_hash)
    return {
        "inbox_id": group_id,
        "channel": channel,
        "source_url": source_url,
        "message_id": message_id,
        "resource_group_id": group_id,
        "resource_trace_id": trace_id,
        "raw_title": meta.get("raw_title") or "",
        "match_title": meta.get("match_title") or "",
        "title_candidates": list(meta.get("title_candidates") or []),
        "media_type_hint": meta.get("media_type_hint") or "",
        "tmdb_id": meta.get("tmdb_id") or "",
        "year": meta.get("year") or "",
        "season_hint": meta.get("season_hint"),
        "episode_hint": meta.get("episode_hint") or "",
        "total_episode_hint": meta.get("total_episode_hint"),
        "candidates": candidates,
        "other_urls": other_urls,
        "provenance": provenance,
        "discovered_at": now,
        "last_seen_at": now,
        "expires_at": now + _INBOX_RETENTION_SECONDS,
        "raw_hash": raw_hash,
        "origin": "inbox",
    }


def build_inbox_row_from_entry(entry: Dict[str, Any], *, now: Optional[float] = None) -> Dict[str, Any]:
    now = float(now if now is not None else time.time())
    channel = str(entry.get("source_url") or entry.get("channel") or "")
    message_id = str(entry.get("message_id") or "")
    group_id = str(entry.get("resource_group_id") or "")
    title = str(entry.get("display_title") or entry.get("title") or entry.get("match_title") or "")[:300]
    candidates: List[Dict[str, Any]] = []
    share = str(entry.get("share_url") or "").strip()
    if share:
        kind, uri, identity = _classify_protocol(share)
        if kind:
            candidates.append({
                "type": kind,
                "uri": uri,
                "identity": identity,
                "passcode": str(entry.get("share_code") or entry.get("passcode") or ""),
                "extractor": str(entry.get("link_style") or "visible_text"),
            })
    for item in entry.get("xunlei_sources") or []:
        if not isinstance(item, dict):
            continue
        uri = str(item.get("url") or item.get("uri") or "")
        kind, uri, identity = _classify_protocol(uri)
        if kind:
            candidates.append({
                "type": kind,
                "uri": uri,
                "identity": identity,
                "passcode": str(item.get("passcode") or item.get("pwd") or ""),
                "extractor": str(item.get("extractor") or "href"),
            })
    for item in entry.get("external_sources") or []:
        if not isinstance(item, dict):
            continue
        candidates.append({
            "type": str(item.get("type") or ""),
            "uri": str(item.get("uri") or ""),
            "identity": str(item.get("identity") or ""),
            "passcode": str(item.get("passcode") or ""),
            "extractor": str(item.get("extractor") or "visible_text"),
        })
    context_html = str(entry.get("context_html") or entry.get("html") or "")
    context_text = str(entry.get("text") or "")
    other_urls: List[Dict[str, str]] = []
    if context_html or context_text:
        bundle = extract_message_resources_bundle_v209(context_html, context_text)
        extracted = enrich_candidates_with_local_passcode(bundle.get("candidates") or [], context_text)
        other_urls = list(bundle.get("other_urls") or [])
        seen = {f"{c.get('type')}:{c.get('identity')}" for c in candidates}
        for item in extracted:
            key = f"{item.get('type')}:{item.get('identity')}"
            if key not in seen:
                seen.add(key)
                candidates.append(item)
    meta = parse_message_title_metadata_v209(context_text or title)
    raw_hash = hashlib.sha1(
        f"{channel}|{message_id}|{group_id}|{title}|{len(candidates)}".encode("utf-8", "ignore")
    ).hexdigest()[:20]
    inbox_id = group_id or f"{channel}:{message_id}:{raw_hash}"
    return {
        "inbox_id": inbox_id,
        "channel": channel,
        "source_url": channel,
        "message_id": message_id,
        "resource_group_id": group_id or inbox_id,
        "raw_title": meta.get("raw_title") or title,
        "match_title": meta.get("match_title") or title,
        "title_candidates": list(meta.get("title_candidates") or ([title] if title else [])),
        "media_type_hint": meta.get("media_type_hint") or "",
        "tmdb_id": str(entry.get("tmdb_id") or meta.get("tmdb_id") or ""),
        "year": str(entry.get("year") or entry.get("year_hint") or meta.get("year") or ""),
        "season_hint": entry.get("season_hint") or entry.get("season") or meta.get("season_hint"),
        "episode_hint": entry.get("episode_hint") or meta.get("episode_hint") or "",
        "total_episode_hint": entry.get("total_episode_hint") or meta.get("total_episode_hint"),
        "candidates": [c for c in candidates if c.get("type")],
        "other_urls": other_urls,
        "provenance": [{"channel": channel, "message_id": message_id, "extractor": "legacy_entry"}],
        "discovered_at": now,
        "last_seen_at": now,
        "expires_at": now + _INBOX_RETENTION_SECONDS,
        "raw_hash": raw_hash,
        "origin": "legacy",
    }


def upsert_inbox_rows(store: Dict[str, Any], rows: Iterable[Dict[str, Any]], *, now: Optional[float] = None) -> Dict[str, Any]:
    now = float(now if now is not None else time.time())
    items = dict(store.get("items") or {}) if isinstance(store, dict) else {}
    stats = {"new": 0, "updated": 0}
    new_rows: List[Dict[str, Any]] = []
    updated_rows: List[Dict[str, Any]] = []
    identity_index: Dict[str, str] = {}
    for existing_id, existing in items.items():
        for cand in (existing or {}).get("candidates") or []:
            if not isinstance(cand, dict):
                continue
            if cand.get("type") and cand.get("identity"):
                identity_index[f"{cand.get('type')}:{cand.get('identity')}"] = existing_id

    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if not row.get("candidates") and not row.get("other_urls"):
            continue
        inbox_id = str(row.get("inbox_id") or "")
        if not inbox_id:
            continue
        merge_into = inbox_id
        for cand in row.get("candidates") or []:
            if not isinstance(cand, dict):
                continue
            ikey = f"{cand.get('type')}:{cand.get('identity')}"
            prev_id = identity_index.get(ikey)
            if prev_id and prev_id in items:
                merge_into = prev_id
                break
        previous = dict(items.get(merge_into) or {})
        is_new = not previous
        merged = dict(previous)
        merged.update({
            k: v for k, v in row.items()
            if k not in {"discovered_at", "candidates", "provenance", "other_urls"}
        })
        if previous.get("discovered_at"):
            merged["discovered_at"] = previous.get("discovered_at")
        else:
            merged["discovered_at"] = row.get("discovered_at") or now
        merged["last_seen_at"] = now
        merged["expires_at"] = now + _INBOX_RETENTION_SECONDS
        merged["inbox_id"] = merge_into
        seen: Dict[str, Dict[str, Any]] = {}
        candidates: List[Dict[str, Any]] = []
        for item in list(previous.get("candidates") or []) + list(row.get("candidates") or []):
            if not isinstance(item, dict) or not item.get("type"):
                continue
            key = f"{item.get('type')}:{item.get('identity')}"
            existing = seen.get(key)
            if existing is None:
                seen[key] = dict(item)
                candidates.append(seen[key])
            else:
                if item.get("passcode") and not existing.get("passcode"):
                    existing["passcode"] = item.get("passcode")
                if item.get("uri") and not existing.get("uri"):
                    existing["uri"] = item.get("uri")
        merged["candidates"] = candidates
        other = list(previous.get("other_urls") or [])
        oseen = {f"{o.get('kind')}:{o.get('uri')}" for o in other if isinstance(o, dict)}
        for item in row.get("other_urls") or []:
            if not isinstance(item, dict):
                continue
            key = f"{item.get('kind')}:{item.get('uri')}"
            if key not in oseen:
                oseen.add(key)
                other.append(item)
        merged["other_urls"] = other
        prov = list(previous.get("provenance") or [])
        pseen = {f"{p.get('channel')}|{p.get('message_id')}" for p in prov if isinstance(p, dict)}
        for item in row.get("provenance") or []:
            if not isinstance(item, dict):
                continue
            key = f"{item.get('channel')}|{item.get('message_id')}"
            if key not in pseen:
                pseen.add(key)
                prov.append(item)
        merged["provenance"] = prov
        if previous.get("origin") and row.get("origin") and previous.get("origin") != row.get("origin"):
            merged["origin"] = "both"
        elif not merged.get("origin"):
            merged["origin"] = row.get("origin") or "inbox"
        # Keep stable resource_trace_id across refreshes.
        if previous.get("resource_trace_id"):
            merged["resource_trace_id"] = previous.get("resource_trace_id")
        elif not merged.get("resource_trace_id"):
            merged["resource_trace_id"] = stable_trace_id(
                merged.get("channel"), merged.get("message_id"), merge_into, merged.get("raw_hash"),
            )
        items[merge_into] = merged
        for cand in candidates:
            identity_index[f"{cand.get('type')}:{cand.get('identity')}"] = merge_into
        if is_new:
            stats["new"] += 1
            new_rows.append(merged)
        else:
            stats["updated"] += 1
            updated_rows.append(merged)

    alive = {
        key: value
        for key, value in items.items()
        if float((value or {}).get("expires_at") or 0) >= now
    }
    if len(alive) > _INBOX_MAX_ROWS:
        ordered = sorted(alive.items(), key=lambda kv: float((kv[1] or {}).get("last_seen_at") or 0))
        alive = dict(ordered[-_INBOX_MAX_ROWS:])
    return {
        "updated_at": now,
        "count": len(alive),
        "items": alive,
        "stats": stats,
        "new_rows": new_rows,
        "updated_rows": updated_rows,
    }


def convert_inbox_row_to_entry(row: Dict[str, Any]) -> Dict[str, Any]:
    """Convert inbox ResourceGroup into legacy-compatible channel entry schema."""
    candidates = [c for c in (row.get("candidates") or []) if isinstance(c, dict) and c.get("type")]
    guangya = next((c for c in candidates if c.get("type") == "guangya"), None)
    xunlei_sources = [
        {
            "url": c.get("uri"),
            "uri": c.get("uri"),
            "passcode": c.get("passcode"),
            "extractor": c.get("extractor"),
            "identity": c.get("identity"),
        }
        for c in candidates if c.get("type") == "xunlei"
    ]
    external_sources = [
        {
            "type": c.get("type"),
            "uri": c.get("uri"),
            "identity": c.get("identity"),
            "passcode": c.get("passcode"),
            "extractor": c.get("extractor"),
        }
        for c in candidates if c.get("type") in {"magnet", "ed2k"}
    ]
    title = str(row.get("match_title") or row.get("raw_title") or "")
    episode_hint = str(row.get("episode_hint") or "")
    text_parts = [str(row.get("raw_title") or title)]
    if episode_hint:
        text_parts.append(episode_hint)
    if row.get("year"):
        text_parts.append(str(row.get("year")))
    return {
        "share_url": str((guangya or {}).get("uri") or ""),
        "share_id": str((guangya or {}).get("identity") or ""),
        "text": "\n".join(p for p in text_parts if p)[:2200],
        "source_url": str(row.get("source_url") or row.get("channel") or ""),
        "source_label": str(row.get("channel") or ""),
        "priority": 0 if "regeng" in str(row.get("channel") or "").lower() else 1,
        "link_style": str((guangya or {}).get("extractor") or "inbox"),
        "stale": False,
        # False so ChannelCursorEvent can treat fresh Inbox-only rows as live events.
        "cached_index": False,
        "message_id": str(row.get("message_id") or ""),
        "display_title": title,
        "match_title": title,
        "title_candidates": list(row.get("title_candidates") or []),
        "tmdb_id": str(row.get("tmdb_id") or ""),
        "year": row.get("year") or "",
        "year_hint": int(row["year"]) if str(row.get("year") or "").isdigit() else None,
        "season_hint": row.get("season_hint"),
        "episode_hint": episode_hint,
        "total_episode_hint": row.get("total_episode_hint"),
        "resource_group_id": str(row.get("resource_group_id") or row.get("inbox_id") or ""),
        "resource_trace_id": str(row.get("resource_trace_id") or ""),
        "xunlei_sources": xunlei_sources,
        "external_sources": external_sources,
        "other_urls": list(row.get("other_urls") or []),
        "candidate_types": [str(c.get("type")) for c in candidates],
        "provenance": list(row.get("provenance") or []),
        "origin": str(row.get("origin") or "inbox"),
        "inbox_id": str(row.get("inbox_id") or ""),
    }


def union_legacy_and_inbox_entries(
    legacy_entries: Iterable[Dict[str, Any]],
    inbox_store: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Union legacy channel_index entries with inbox-converted entries; dedup by protocol identity."""
    by_identity: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []

    def _identities(entry: Dict[str, Any]) -> List[str]:
        keys = []
        share = str(entry.get("share_url") or "")
        if share:
            kind, _uri, identity = _classify_protocol(share)
            if kind and identity:
                keys.append(f"{kind}:{identity}")
        for item in entry.get("xunlei_sources") or []:
            if isinstance(item, dict):
                kind, _uri, identity = _classify_protocol(str(item.get("url") or item.get("uri") or ""))
                if kind and identity:
                    keys.append(f"{kind}:{identity}")
        for item in entry.get("external_sources") or []:
            if isinstance(item, dict) and item.get("type") and item.get("identity"):
                keys.append(f"{item.get('type')}:{item.get('identity')}")
        return keys

    def _merge(entry: Dict[str, Any], origin: str) -> None:
        keys = _identities(entry)
        if not keys:
            fallback = str(entry.get("resource_group_id") or entry.get("inbox_id") or "")
            if not fallback:
                return
            keys = [f"group:{fallback}"]
        primary = keys[0]
        existing_key = None
        for key in keys:
            if key in by_identity:
                existing_key = key
                break
        if existing_key is None:
            row = dict(entry)
            row["origin"] = origin
            by_identity[primary] = row
            for key in keys:
                by_identity[key] = row
            order.append(primary)
            return
        current = by_identity[existing_key]
        if origin == "inbox" and current.get("origin") == "legacy":
            current["origin"] = "both"
        elif origin == "legacy" and current.get("origin") == "inbox":
            current["origin"] = "both"
        if entry.get("share_url") and not current.get("share_url"):
            current["share_url"] = entry.get("share_url")
            current["share_id"] = entry.get("share_id")
        if entry.get("xunlei_sources"):
            existing = list(current.get("xunlei_sources") or [])
            seen = {str(x.get("url") or x.get("uri") or "") for x in existing}
            for item in entry.get("xunlei_sources") or []:
                uri = str((item or {}).get("url") or (item or {}).get("uri") or "")
                if uri and uri not in seen:
                    existing.append(item)
                    seen.add(uri)
            current["xunlei_sources"] = existing
        if entry.get("external_sources"):
            existing = list(current.get("external_sources") or [])
            seen = {f"{x.get('type')}:{x.get('identity')}" for x in existing}
            for item in entry.get("external_sources") or []:
                key = f"{(item or {}).get('type')}:{(item or {}).get('identity')}"
                if key not in seen:
                    existing.append(item)
                    seen.add(key)
            current["external_sources"] = existing
        prov = list(current.get("provenance") or [])
        pseen = {f"{p.get('channel')}|{p.get('message_id')}" for p in prov if isinstance(p, dict)}
        for item in entry.get("provenance") or []:
            if not isinstance(item, dict):
                continue
            key = f"{item.get('channel')}|{item.get('message_id')}"
            if key not in pseen:
                pseen.add(key)
                prov.append(item)
        current["provenance"] = prov
        for key in keys:
            by_identity[key] = current

    for entry in legacy_entries or []:
        if isinstance(entry, dict):
            tagged = dict(entry)
            tagged.setdefault("origin", "legacy")
            _merge(tagged, "legacy")
    items = (inbox_store or {}).get("items") or {}
    for row in items.values():
        if not isinstance(row, dict) or not row.get("candidates"):
            continue
        _merge(convert_inbox_row_to_entry(row), "inbox")

    result = []
    seen_obj = set()
    for key in order:
        row = by_identity.get(key)
        if row is None:
            continue
        obj_id = id(row)
        if obj_id in seen_obj:
            continue
        seen_obj.add(obj_id)
        result.append(row)
    return result


def shadow_match_inbox_for_subscribe(store: Dict[str, Any], subscribe: Any, matcher) -> List[Dict[str, Any]]:
    """Return inbox rows matcher(subscribe, synthetic_entry) accepts."""
    hits = []
    items = (store or {}).get("items") or {}
    for row in items.values():
        if not isinstance(row, dict) or not row.get("candidates"):
            continue
        synthetic = convert_inbox_row_to_entry(row)
        try:
            matched, reason = matcher(synthetic, subscribe)
        except Exception:
            matched, reason = False, "matcher_error"
        if matched:
            hits.append({"inbox_id": row.get("inbox_id"), "reason": reason, "row": row, "entry": synthetic})
    return hits


def summarize_page_extract_stats_v209(blocks: List[Dict[str, Any]], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    guangya = xunlei = magnet = ed2k = other = hidden = visible = 0
    for row in rows or []:
        for cand in row.get("candidates") or []:
            kind = str(cand.get("type") or "")
            if kind == "guangya":
                guangya += 1
            elif kind == "xunlei":
                xunlei += 1
            elif kind == "magnet":
                magnet += 1
            elif kind == "ed2k":
                ed2k += 1
            extractor = str(cand.get("extractor") or "")
            if extractor in {"clipboard", "data", "onclick", "javascript", "json", "wrapped_redirect"}:
                hidden += 1
            elif extractor in {"href", "visible_text"}:
                visible += 1
        other += len(row.get("other_urls") or [])
    return {
        "messages": len(blocks or []),
        "resource_groups": len(rows or []),
        "guangya": guangya,
        "xunlei": xunlei,
        "magnet": magnet,
        "ed2k": ed2k,
        "other": other,
        "hidden": hidden,
        "visible": visible,
    }


__all__ = [
    "extract_message_resource_candidates_v209",
    "extract_message_resources_bundle_v209",
    "enrich_candidates_with_local_passcode",
    "parse_message_title_metadata_v209",
    "build_inbox_row_from_message_block",
    "build_inbox_row_from_entry",
    "convert_inbox_row_to_entry",
    "union_legacy_and_inbox_entries",
    "upsert_inbox_rows",
    "shadow_match_inbox_for_subscribe",
    "summarize_page_extract_stats_v209",
    "_INBOX_KEY",
    "_INBOX_RETENTION_SECONDS",
    "_INBOX_MAX_ROWS",
]
