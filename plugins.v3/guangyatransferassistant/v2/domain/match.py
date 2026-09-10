"""统一匹配引擎：accept/reject + 可解释 reason code。"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any, Optional

from .media import MediaIdentity


# 拒绝码：运行台与轨迹共用。
TITLE_NOISE = "TITLE_NOISE"
TMDB_MISMATCH = "TMDB_MISMATCH"
SEASON_MISMATCH = "SEASON_MISMATCH"
YEAR_MISMATCH = "YEAR_MISMATCH"
NO_EXECUTABLE_LINK = "NO_EXECUTABLE_LINK"
UNSUPPORTED_LINK = "UNSUPPORTED_LINK"
ALREADY_COVERED = "ALREADY_COVERED"
NO_TITLE = "NO_TITLE"
ACCEPT = "ACCEPT"

_UNSUPPORTED_HOSTS = (
    "123865.com",
    "123684.com",
    "123pan.com",
    "115cdn.com",
    "115.com",
    "anxia.com",
    "pan.baidu.com",
    "aliyundrive.com",
    "alipan.com",
    "pan.quark.cn",
)

_YEAR_TAIL = re.compile(r"[（(]\s*(?:19\d{2}|20\d{2})\s*[）)].*$")
_HDHIVE_PREFIX = re.compile(r"^\[\s*(?:剧集|电影|动漫|动画|综艺)[^\]]{0,40}\]\s*", re.I)
_BRACKET_TAG = re.compile(r"【[^】]{0,80}】")
_QUALITY_TAIL = re.compile(
    r"(?i)\s*(?:"
    r"4K|8K|2160p|1080p|720p|480p|HDR10\+?|DV|Dolby|Atmos|"
    r"WEB-?DL|WEBRip|BluRay|REMUX|H\.?265|H\.?264|HEVC|AAC|DDP|"
    r"更新至\s*\d+\s*集|更新到\s*\d+\s*集|更至\s*\d+\s*集|"
    r"全\s*\d+\s*集|全季|全集|剧情|奇幻|古装|喜剧|动作|爱情|"
    r"高码率|内封|简繁英"
    r").*$"
)


def clean_channel_title(value: Any) -> str:
    title = html.unescape(str(value or "")).strip()
    title = re.sub(r"^[\s🎬🎞🎥📺]+", "", title).strip()
    title = re.sub(r"^(?:电影|剧集|电视剧|动漫|动画)\s*[：:]\s*", "", title, flags=re.I).strip()
    title = _HDHIVE_PREFIX.sub("", title).strip()
    title = _BRACKET_TAG.sub(" ", title)
    title = re.sub(r"\s+", " ", title).strip()
    if _YEAR_TAIL.search(title):
        title = _YEAR_TAIL.sub("", title).strip()
    else:
        title = _QUALITY_TAIL.sub("", title).strip()
    title = re.sub(r"\s*(?:已?更新|更新中|已?完结|完结|全集|全季)\s*$", "", title, flags=re.I).strip()
    return title[:300]


def title_key(value: Any, expected_year: Any = None) -> str:
    text = clean_channel_title(value)
    year = str(expected_year or "").strip()
    if year and re.fullmatch(r"(?:19|20)\d{2}", year):
        text = re.sub(rf"(?<!\d){re.escape(year)}(?!\d)", " ", text)
    text = re.sub(r"(?i)\bS(?:eason)?[ ._\-]*0*\d{1,2}(?:[ ._\-]*E(?:pisode)?[ ._\-]*0*\d{1,4})?", " ", text)
    text = re.sub(r"第\s*[0-9一二三四五六七八九十]{1,3}\s*(?:季|集|话)", " ", text)
    tokens = []
    noise = {
        "2160p", "1080p", "720p", "4k", "8k", "web", "webdl", "webrip", "bluray", "remux",
        "hdtv", "x264", "x265", "h264", "h265", "hevc", "avc", "hdr", "dv", "aac", "dts",
        "complete", "全集", "全季", "中字", "字幕",
    }
    for token in re.split(r"[^0-9A-Za-z\u4e00-\u9fff]+", text):
        lowered = token.casefold().strip()
        if not lowered or lowered in noise:
            continue
        tokens.append(lowered)
    return "".join(tokens)


def explicit_seasons(text: Any) -> set[int]:
    seasons = set()
    value = html.unescape(str(text or ""))
    for matched in re.findall(r"(?i)\bS(?:eason)?[ ._\-]*0*(\d{1,2})(?=E|[^0-9]|$)", value):
        try:
            seasons.add(int(matched))
        except (TypeError, ValueError):
            pass
    for matched in re.findall(r"第\s*0*(\d{1,2})\s*季", value):
        try:
            seasons.add(int(matched))
        except (TypeError, ValueError):
            pass
    return {value for value in seasons if 0 <= value <= 99}


@dataclass
class MatchResult:
    accepted: bool
    reason_code: str
    message: str = ""
    cleaned_title: str = ""

    def as_dict(self) -> dict:
        return {
            "accepted": self.accepted,
            "reason_code": self.reason_code,
            "message": self.message,
            "cleaned_title": self.cleaned_title,
        }


class MatchEngine:
    """频道条目 / 外部候选的统一身份门禁。"""

    def classify_links(self, entry: dict) -> MatchResult:
        share = str(entry.get("share_url") or "").strip()
        externals = list(entry.get("external_sources") or [])
        xunlei = list(entry.get("xunlei_sources") or [])
        blob = " ".join(
            [
                share,
                str(entry.get("text") or ""),
                *[str(item.get("uri") or "") for item in externals],
                *[str(item.get("uri") or "") for item in xunlei],
            ]
        ).lower()
        if any(host in blob for host in _UNSUPPORTED_HOSTS) and not (share or externals or xunlei):
            return MatchResult(False, UNSUPPORTED_LINK, "仅有不可转存到光鸭的网盘链接")
        if share or externals or xunlei:
            return MatchResult(True, ACCEPT, "存在可执行来源")
        # 纯文本无链接
        if any(host in blob for host in _UNSUPPORTED_HOSTS):
            return MatchResult(False, UNSUPPORTED_LINK, "链接类型不受支持")
        return MatchResult(False, NO_EXECUTABLE_LINK, "未发现光鸭/迅雷/Magnet/ED2K 可执行链接")

    def match_entry(self, entry: dict, identity: MediaIdentity, *, already_covered: bool = False) -> MatchResult:
        if already_covered:
            return MatchResult(False, ALREADY_COVERED, "缺口已被媒体库/在途/claim 覆盖")

        link = self.classify_links(entry)
        if not link.accepted:
            return link

        display = clean_channel_title(entry.get("display_title") or "")
        if not display:
            # 从正文再抽一次
            text = str(entry.get("text") or "")
            labelled = re.search(r"(?im)(?:^|\n)\s*(?:名称|片名|剧名|标题)\s*[：:]\s*([^\n]{2,320})", text)
            if labelled:
                display = clean_channel_title(labelled.group(1))
            if not display:
                for line in text.splitlines():
                    line = line.strip()
                    if re.search(r"[（(](?:19\d{2}|20\d{2})[）)]", line):
                        display = clean_channel_title(line)
                        if display:
                            break
        if not display:
            return MatchResult(False, NO_TITLE, "频道条目缺少可解析标题", cleaned_title="")

        entry_tmdb = str(entry.get("tmdb_id") or "").strip()
        source = str(identity.media_source or "").lower()
        comparable = bool(entry_tmdb and identity.media_id and ("tmdb" in source or "themoviedb" in source))
        if comparable and entry_tmdb != identity.media_id:
            return MatchResult(False, TMDB_MISMATCH, f"TMDB 冲突 entry={entry_tmdb} sub={identity.media_id}", display)

        seasons = explicit_seasons(" ".join([str(entry.get("text") or ""), display, str(entry.get("episode_hint") or "")]))
        if identity.season and seasons and identity.season not in seasons:
            return MatchResult(False, SEASON_MISMATCH, f"季号冲突 want={identity.season} got={sorted(seasons)}", display)

        if comparable:
            return MatchResult(True, ACCEPT, "TMDB 精确匹配", display)

        expected = title_key(identity.name, identity.year)
        actual = title_key(display, identity.year)
        if not expected or expected != actual:
            # 噪声标题常见：清洗后仍对不上
            if actual and expected and (expected in actual or actual in expected):
                # 2.0 仍坚持强相等，避免模糊误转；记 TITLE_NOISE
                return MatchResult(False, TITLE_NOISE, f"标题未强匹配 expect={identity.name} got={display}", display)
            return MatchResult(False, TITLE_NOISE, f"标题未匹配 expect={identity.name} got={display}", display)

        if identity.year:
            years = {int(v) for v in re.findall(r"\b(19\d{2}|20\d{2})\b", str(entry.get("text") or ""))}
            hinted = entry.get("year_hint")
            if hinted:
                try:
                    years.add(int(hinted))
                except (TypeError, ValueError):
                    pass
            title_years = {int(v) for v in re.findall(r"\b(19\d{2}|20\d{2})\b", identity.name)}
            years -= title_years
            if years and identity.year not in years:
                return MatchResult(False, YEAR_MISMATCH, f"年份冲突 want={identity.year} got={sorted(years)}", display)

        return MatchResult(True, ACCEPT, "标题/年份/季匹配", display)
