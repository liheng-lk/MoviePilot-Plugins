"""v1.12.17 结构化资源召回 + Telegram 频道定向搜索。

目标：提高“找到候选”的召回率，但绝不放宽最终写盘门禁。

设计来源：
- MoviePilot V3 当前搜索链会先解析 release title；无年份别名候选需要时再用
  MediaChain.recognize_by_meta 做同作品消歧，并缓存同一解析标题的结果；
- PanSou / Telegram Web 搜索使用 ``/s/<channel>?q=<keyword>`` 做频道侧定向检索，
  而不是只依赖最新页游标和历史翻页。

本层只负责 discovery/recall：
1. 搜索阶段把技术标签、语言标签、发布组等从 release title 中剥离，再与 MoviePilot/TMDB
   精确别名比较；明确 TMDB/年份/季冲突仍立即拒绝；
2. 无年份且只通过别名命中的歧义候选，只有 MoviePilot 重新识别为同一 canonical identity
   才允许进入候选；同一解析标题带短时缓存；
3. 对主动检查/新订阅提供有界 Telegram ``?q=`` 定向搜索，结果继续写入既有 7 天频道 cache，
   不修改 channel_cursors，不把旧资源伪造成新频道事件；
4. 5 分钟 channel_event 仍是被动 Push，不为每个订阅主动发起频道关键词搜索；
5. 真正转存前继续由 v1.12.14~v1.12.16 的实际 payload 身份、年份、季、library missing、
   reservation/source claim 与不可分割物理文件栅栏裁决。
"""
from __future__ import annotations

import html
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import PurePosixPath
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from . import legacy as _legacy_module
from .channel_event_v1115 import _entry_key_v1115
from .manual_check_v11211 import GuangYaManualCheckV11211Mixin
from .media_identity_v1111 import (
    explicit_seasons_v1111,
    explicit_years_v1111,
    title_key_v1111,
)


# release title 中一旦出现这些独立 token，后面通常不再属于媒体标题。
# 只用于“召回阶段提取标题前缀”，不是最终媒体身份判断。
_RELEASE_STOP_TOKEN_V11217 = re.compile(
    r"(?ix)^(?:"
    r"readnfo|nfofix|proper|repack|rerip|internal|extended|uncut|complete|全集|全季|"
    r"french|english|german|spanish|italian|japanese|korean|chinese|mandarin|cantonese|multi|dual|"
    r"2160p|1080p|1080i|720p|576p|480p|4k|8k|"
    r"web(?:[-_. ]?dl|rip)?|webrip|bluray|blu[-_. ]?ray|bdrip|brrip|remux|hdtv|uhd|"
    r"x26[45]|h26[45]|hevc|avc|av1|10bit|8bit|hdr10\+?|hdr|dv|dolbyvision|"
    r"aac\d?(?:\.\d)?|ac3|eac3|ddp?\d?(?:\.\d)?|dts(?:hd)?|truehd|atmos|flac|"
    r"chs|cht|chi|eng|jpn|kor|中字|字幕|简中|繁中"
    r")$"
)
_RELEASE_EP_TOKEN_V11217 = re.compile(
    r"(?ix)^(?:s\d{1,2}(?:e\d{1,4}(?:[-~]e?\d{1,4})?)?|e\d{1,4}(?:[-~]e?\d{1,4})?|ep\d{1,4})$"
)
_BRACKET_CONTENT_V11217 = re.compile(r"[【\[（(]([^】\]）)]{2,100})[】\]）)]")
_CJK_LATIN_BOUNDARY_V11217 = re.compile(
    r"(?<=[\u4e00-\u9fff])\s+(?=[A-Za-z])|(?<=[A-Za-z])\s+(?=[\u4e00-\u9fff])"
)
_YEAR_TOKEN_V11217 = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")
_TARGET_SEARCH_STATE_V11217 = "channel_targeted_search_v11217"


def _clean_release_text_v11217(value: Any) -> str:
    text = html.unescape(str(value or "")).replace("\\", "/").strip()
    if not text:
        return ""
    try:
        text = PurePosixPath(text).name or text
    except Exception:
        pass
    text = re.sub(r"\.(?:mkv|mp4|ts|m2ts|avi|mov|wmv|flv|webm|iso|m4v|rmvb|mpg|mpeg)$", "", text, flags=re.I)
    text = re.sub(r"^[\s🎬🎞🎥📺⭐🌈🔥✨💥✅]+", "", text)
    return text.strip(" \t\r\n._-—|/\\")


def _release_title_candidates_v11217(value: Any, expected_year: Any = None) -> List[Tuple[str, str]]:
    """从 noisy release name 提取可解释的精确标题候选，不做编辑距离/包含式模糊匹配。"""
    raw = _clean_release_text_v11217(value)
    if not raw:
        return []

    seeds: List[str] = [raw]
    seeds.extend(match.group(1).strip() for match in _BRACKET_CONTENT_V11217.finditer(raw))
    seeds.extend(part.strip() for part in re.split(r"[|／\n]+", raw) if part.strip())

    year = str(expected_year or "").strip()
    normalized = re.sub(r"[._]+", " ", raw)
    tokens = [token for token in re.split(r"\s+", normalized) if token]
    title_tokens: List[str] = []
    for token in tokens:
        stripped = token.strip("[]【】()（）{}<>-—,，;；:：")
        lowered = stripped.casefold()
        if not stripped:
            continue
        if _YEAR_TOKEN_V11217.fullmatch(stripped):
            break
        if _RELEASE_EP_TOKEN_V11217.fullmatch(lowered) or _RELEASE_STOP_TOKEN_V11217.fullmatch(lowered):
            break
        title_tokens.append(stripped)
    if title_tokens:
        seeds.append(" ".join(title_tokens))

    # ``中文标题 English Title 2026`` 是常见资源站展示形态，分别抽取两侧作为候选。
    expanded = list(seeds)
    for seed in seeds:
        clean = re.sub(r"[._]+", " ", seed).strip()
        parts = [part.strip() for part in _CJK_LATIN_BOUNDARY_V11217.split(clean) if part.strip()]
        if len(parts) == 2:
            expanded.extend(parts)
        if year and re.fullmatch(r"(?:19|20)\d{2}", year):
            marker = re.search(rf"(?<!\d){re.escape(year)}(?!\d)", clean)
            if marker and marker.start() > 1:
                expanded.append(clean[:marker.start()].strip(" ._-—|/\\[]【】()（）"))

    result: List[Tuple[str, str]] = []
    seen: Set[str] = set()
    for candidate in expanded:
        cleaned = _clean_release_text_v11217(candidate)
        key = title_key_v1111(cleaned, expected_year=expected_year).casefold()
        if len(key) < 2 or key in seen:
            continue
        seen.add(key)
        result.append((key, cleaned))
    return result


def _channel_query_url_v11217(source_url: str, query: str) -> str:
    """保持用户配置的频道/反代地址，只追加或替换 Telegram Web 的 q 参数。"""
    raw = str(source_url or "").strip()
    if not raw or not str(query or "").strip():
        return raw
    try:
        parsed = urlsplit(raw)
        params = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key != "q"]
        params.append(("q", " ".join(str(query).split())))
        path = parsed.path
        host = (parsed.hostname or "").lower()
        # 官方 Telegram 用户页必须使用 /s/<channel> 才能返回可搜索的公开消息 HTML。
        if host in {"t.me", "telegram.me", "www.t.me", "www.telegram.me"}:
            parts = [part for part in path.split("/") if part]
            if parts and parts[0] != "s":
                path = "/s/" + parts[0]
        return urlunsplit((parsed.scheme or "https", parsed.netloc, path, urlencode(params), ""))
    except Exception:
        joiner = "&" if "?" in raw else "?"
        return f"{raw}{joiner}q={urlencode({'q': query}).split('=', 1)[-1]}"


class GuangYaSearchRecallV11217Mixin(GuangYaManualCheckV11211Mixin):
    """在最终硬门禁之前提高 GYING 与频道的候选召回率。"""

    plugin_version = "1.12.17"
    build_id = "20260906-r64"
    _search_query_limit_v11217 = 8
    _channel_query_limit_v11217 = 4
    _channel_target_cooldown_v11217 = 45 * 60
    _channel_target_failure_cooldown_v11217 = 5 * 60
    _same_work_cache_ttl_v11217 = 6 * 60 * 60
    _same_work_failure_ttl_v11217 = 30 * 60

    def init_plugin(self, config: dict = None) -> None:
        self._search_recall_lock_v11217 = threading.RLock()
        self._same_work_cache_v11217: Dict[Tuple[str, str], Dict[str, Any]] = {}
        return super().init_plugin(config)

    # ------------------------------------------------------------------
    # Canonical identity / aliases
    # ------------------------------------------------------------------
    @staticmethod
    def _source_token_v11217(value: Any) -> str:
        return str(getattr(value, "value", value) or "").strip().lower()

    def _canonical_identity_v11217(self, subscribe: Any) -> Tuple[str, str]:
        for field in ("tmdb_id", "tmdbid"):
            value = str(getattr(subscribe, field, "") or "").strip()
            if value.isdigit():
                return "tmdb", value
        source = self._source_token_v11217(getattr(subscribe, "media_source", None))
        media_id = str(getattr(subscribe, "media_id", "") or "").strip()
        if media_id:
            if "tmdb" in source and media_id.isdigit():
                return "tmdb", media_id
            if "imdb" in source:
                return "imdb", media_id.lower()
        imdb_id = str(getattr(subscribe, "imdb_id", "") or "").strip().lower()
        if imdb_id:
            return "imdb", imdb_id
        return "", ""

    def _match_aliases_v11217(self, subscribe: Any) -> List[str]:
        aliases: List[str] = []
        getter = getattr(self, "_identity_aliases_v1111", None)
        if callable(getter):
            try:
                aliases.extend(str(value or "").strip() for value in (getter(subscribe) or []))
            except Exception:
                pass
        primary = str(getattr(subscribe, "name", "") or "").strip()
        if primary:
            aliases.insert(0, primary)

        is_movie = False
        checker = getattr(self, "_is_movie_subscription", None)
        try:
            is_movie = bool(checker(subscribe)) if callable(checker) else False
        except Exception:
            is_movie = False
        if not is_movie:
            tv_alias_getter = getattr(self, "_tv_tmdb_aliases_v11214", None)
            if callable(tv_alias_getter):
                try:
                    aliases.extend(str(value or "").strip() for value in (tv_alias_getter(subscribe) or []))
                except Exception:
                    pass

        result: List[str] = []
        seen = set()
        for value in aliases:
            text = " ".join(str(value or "").split())
            key = text.casefold()
            if len(text) < 2 or key in seen:
                continue
            seen.add(key)
            result.append(text)
        return result

    @staticmethod
    def _row_explicit_identity_v11217(row: Dict[str, Any]) -> Tuple[str, str]:
        tmdb = str(row.get("tmdb_id") or row.get("tmdbid") or "").strip()
        if tmdb.isdigit():
            return "tmdb", tmdb
        imdb = str(row.get("imdb_id") or row.get("imdbid") or "").strip().lower()
        if imdb:
            return "imdb", imdb
        source = str(row.get("media_source") or "").strip().lower()
        media_id = str(row.get("media_id") or "").strip()
        if media_id and "tmdb" in source and media_id.isdigit():
            return "tmdb", media_id
        if media_id and "imdb" in source:
            return "imdb", media_id.lower()
        return "", ""

    def _scope_conflict_v11217(self, subscribe: Any, values: Iterable[Any], aliases: Sequence[str]) -> Tuple[bool, str]:
        rows = [value for value in values or [] if str(value or "").strip()]
        expected_year = str(getattr(subscribe, "year", "") or "").strip()
        years = explicit_years_v1111(rows, aliases)
        if expected_year and years and expected_year not in years:
            return True, f"年份冲突：期望={expected_year} 实际={sorted(years)}"

        checker = getattr(self, "_is_movie_subscription", None)
        try:
            is_movie = bool(checker(subscribe)) if callable(checker) else False
        except Exception:
            is_movie = False
        seasons = explicit_seasons_v1111(rows)
        if is_movie and seasons:
            return True, f"电影候选出现季号：{sorted(seasons)}"
        try:
            expected_season = int(getattr(subscribe, "season", 0) or 0)
        except (TypeError, ValueError):
            expected_season = 0
        if not is_movie and expected_season > 0 and seasons and expected_season not in seasons:
            return True, f"季号冲突：期望=S{expected_season:02d} 实际={sorted(seasons)}"
        return False, ""

    # ------------------------------------------------------------------
    # MoviePilot same-work disambiguation (only for alias/no-year ambiguity)
    # ------------------------------------------------------------------
    def _same_work_disambiguation_v11217(self, subscribe: Any, release_title: str) -> Tuple[bool, str]:
        identity = self._canonical_identity_v11217(subscribe)
        if not identity[0] or not identity[1]:
            return False, "无 canonical identity，歧义别名不自动放行"
        expected_year = str(getattr(subscribe, "year", "") or "").strip()
        candidates = _release_title_candidates_v11217(release_title, expected_year)
        parsed_title = candidates[0][1] if candidates else _clean_release_text_v11217(release_title)
        key = (identity[0] + ":" + identity[1], title_key_v1111(parsed_title, expected_year=None).casefold())
        if not key[1]:
            return False, "无法构造同作品消歧键"

        lock = getattr(self, "_search_recall_lock_v11217", None)
        if lock is None:
            lock = threading.RLock()
            self._search_recall_lock_v11217 = lock
        cache = getattr(self, "_same_work_cache_v11217", None)
        if not isinstance(cache, dict):
            cache = {}
            self._same_work_cache_v11217 = cache
        now = time.time()
        with lock:
            stored = dict(cache.get(key) or {})
            try:
                at = float(stored.get("at") or 0)
            except (TypeError, ValueError):
                at = 0.0
            ttl = self._same_work_cache_ttl_v11217 if stored.get("ok") else self._same_work_failure_ttl_v11217
            if at and now - at < ttl:
                return bool(stored.get("ok")), str(stored.get("reason") or "同作品消歧缓存")

        ok = False
        reason = "MoviePilot 无法确认同一作品"
        try:
            from app.chain.media import MediaChain
            from app.domain.metainfo import MetaInfo
            from app.schemas.types import MediaType

            checker = getattr(self, "_is_movie_subscription", None)
            is_movie = bool(checker(subscribe)) if callable(checker) else False
            meta = MetaInfo(title=parsed_title, mtype=MediaType.MOVIE if is_movie else MediaType.TV)
            candidate = MediaChain().recognize_by_meta(meta, obtain_images=False)
            if candidate:
                cand_tmdb = str(getattr(candidate, "tmdb_id", None) or "").strip()
                cand_imdb = str(getattr(candidate, "imdb_id", None) or "").strip().lower()
                cand_source = self._source_token_v11217(getattr(candidate, "media_source", None))
                cand_media_id = str(getattr(candidate, "media_id", "") or "").strip()
                if identity[0] == "tmdb":
                    actual = cand_tmdb or (cand_media_id if "tmdb" in cand_source else "")
                    ok = bool(actual and actual == identity[1])
                    reason = f"MoviePilot 同作品消歧：TMDB {actual or '-'} {'命中' if ok else '不匹配'}"
                elif identity[0] == "imdb":
                    actual = cand_imdb or (cand_media_id.lower() if "imdb" in cand_source else "")
                    ok = bool(actual and actual == identity[1])
                    reason = f"MoviePilot 同作品消歧：IMDb {actual or '-'} {'命中' if ok else '不匹配'}"
        except Exception as err:
            reason = f"MoviePilot 同作品消歧不可用：{str(err)[:180]}"

        with lock:
            cache[key] = {"at": now, "ok": ok, "reason": reason[:260]}
        return ok, reason

    # ------------------------------------------------------------------
    # Structured discovery matcher
    # ------------------------------------------------------------------
    def _structured_candidate_match_v11217(self, subscribe: Any, row: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        row = dict(row or {})
        aliases = self._match_aliases_v11217(subscribe)
        year = str(getattr(subscribe, "year", "") or "").strip()
        if not aliases:
            return False, {"reason": "订阅没有可用标题别名", "score": 0}

        expected_identity = self._canonical_identity_v11217(subscribe)
        actual_identity = self._row_explicit_identity_v11217(row)
        if actual_identity[0] and expected_identity[0] == actual_identity[0] and expected_identity[1]:
            if actual_identity[1] != expected_identity[1]:
                return False, {"reason": f"明确 {actual_identity[0].upper()} 身份冲突", "score": 0}

        evidences = [row.get("search_title"), row.get("name"), row.get("label"), row.get("display_title"), row.get("text")]
        conflict, conflict_reason = self._scope_conflict_v11217(subscribe, [*evidences, row.get("year"), row.get("year_hint")], aliases)
        if conflict:
            return False, {"reason": conflict_reason, "score": 0}

        # 明确 canonical id 相同是最高级 discovery 证据；最终真实 payload 仍会再次验证。
        if expected_identity[0] and actual_identity == expected_identity:
            return True, {
                "reason": f"明确 {expected_identity[0].upper()} identity 命中",
                "score": 100,
                "matched_alias": str(getattr(subscribe, "name", "") or ""),
            }

        alias_map: Dict[str, str] = {}
        for alias in aliases:
            for key, _ in _release_title_candidates_v11217(alias, year):
                alias_map.setdefault(key, alias)
            direct = title_key_v1111(alias, expected_year=year).casefold()
            if direct:
                alias_map.setdefault(direct, alias)
        if not alias_map:
            return False, {"reason": "别名无法规范化", "score": 0}

        matched_key = ""
        matched_alias = ""
        matched_evidence = ""
        for evidence in evidences:
            if not str(evidence or "").strip():
                continue
            for key, cleaned in _release_title_candidates_v11217(evidence, year):
                if key in alias_map:
                    matched_key = key
                    matched_alias = alias_map[key]
                    matched_evidence = cleaned
                    break
            if matched_key:
                break
        if not matched_key:
            return False, {"reason": "结构化标题未命中官方别名", "score": 0}

        candidate_years = explicit_years_v1111(evidences, aliases)
        primary_keys = {
            key for key, _ in _release_title_candidates_v11217(getattr(subscribe, "name", ""), year)
        }
        # 无年份、仅通过别名命中时容易遇到同名作品；复用 MoviePilot 自身识别做 canonical 消歧。
        if year and not candidate_years and matched_key not in primary_keys:
            ok, disambiguation = self._same_work_disambiguation_v11217(subscribe, matched_evidence or matched_alias)
            if not ok:
                return False, {"reason": disambiguation, "score": 0, "matched_alias": matched_alias}
            return True, {
                "reason": f"结构化精确别名 + {disambiguation}",
                "score": 92,
                "matched_alias": matched_alias,
                "parsed_title": matched_evidence,
            }

        score = 80
        if year and candidate_years and year in candidate_years:
            score += 10
        try:
            season = int(getattr(subscribe, "season", 0) or 0)
        except (TypeError, ValueError):
            season = 0
        seasons = explicit_seasons_v1111(evidences)
        if season > 0 and season in seasons:
            score += 8
        return True, {
            "reason": "结构化 release title 精确命中官方别名",
            "score": min(99, score),
            "matched_alias": matched_alias,
            "parsed_title": matched_evidence,
        }

    def _provider_candidate_matches(self, subscribe: Any, row: Dict[str, Any]) -> bool:
        try:
            if bool(super()._provider_candidate_matches(subscribe, row)):
                return True
        except Exception:
            pass
        matched, detail = self._structured_candidate_match_v11217(subscribe, row)
        if matched:
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【资源召回v1.12.17】#%s %s 搜索候选由结构化匹配救回：alias=%s score=%s reason=%s",
                int(getattr(subscribe, "id", 0) or 0),
                str(getattr(subscribe, "name", "") or ""),
                str(detail.get("matched_alias") or "-")[:100],
                int(detail.get("score") or 0),
                str(detail.get("reason") or "")[:220],
            )
        return bool(matched)

    # ------------------------------------------------------------------
    # Query recall: keep old exact queries, append bounded canonical variants.
    # ------------------------------------------------------------------
    def _gying_alias_keywords_v11212(self, subscribe: Any, primary: str) -> List[str]:
        rows = list(super()._gying_alias_keywords_v11212(subscribe, primary) or [])
        if subscribe is None:
            return rows
        aliases = self._match_aliases_v11217(subscribe)
        year = str(getattr(subscribe, "year", "") or "").strip()
        checker = getattr(self, "_is_movie_subscription", None)
        try:
            is_movie = bool(checker(subscribe)) if callable(checker) else False
        except Exception:
            is_movie = False
        try:
            season = int(getattr(subscribe, "season", 0) or 0)
        except (TypeError, ValueError):
            season = 0

        seen = {re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").casefold()) for value in rows}
        for alias in aliases:
            variants = [alias]
            if year:
                variants.append(f"{alias} {year}")
            if not is_movie and season > 0:
                variants.append(f"{alias} S{season:02d}")
                if year:
                    variants.append(f"{alias} {year} S{season:02d}")
            for value in variants:
                clean = " ".join(value.split())
                key = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", clean.casefold())
                if len(key) < 2 or key in seen:
                    continue
                seen.add(key)
                rows.append(clean)
                if len(rows) >= max(4, int(self._search_query_limit_v11217)):
                    return rows
        return rows

    # ------------------------------------------------------------------
    # Channel match promotion: verified discovery is rewritten to canonical discovery fields
    # so old channel consumers can reuse it; original text stays untouched for final validation.
    # ------------------------------------------------------------------
    def _promote_channel_entry_v11217(self, entry: Dict[str, Any], subscribe: Any, detail: Dict[str, Any]) -> Dict[str, Any]:
        row = dict(entry or {})
        original_title = str(row.get("display_title") or "").strip()
        matched_alias = str(detail.get("matched_alias") or getattr(subscribe, "name", "") or "").strip()
        if original_title and original_title != matched_alias:
            row["display_title_raw_v11217"] = original_title[:320]
        if matched_alias:
            row["display_title"] = matched_alias
        identity = self._canonical_identity_v11217(subscribe)
        if identity[0] == "tmdb" and identity[1].isdigit():
            row["tmdb_id"] = identity[1]
        elif identity[0] == "imdb" and identity[1]:
            row["imdb_id"] = identity[1]
        row["identity_verified_v11217"] = True
        row["match_score_v11217"] = int(detail.get("score") or 0)
        row["match_reason_v11217"] = str(detail.get("reason") or "")[:260]
        return row

    def _merge_channel_index_v11217(self, rows: Iterable[Dict[str, Any]]) -> int:
        rows = [dict(row) for row in rows or [] if isinstance(row, dict)]
        if not rows:
            return 0
        index = dict(self.get_data("channel_index") or {})
        items = [dict(row) for row in (index.get("items") or []) if isinstance(row, dict)]
        positions = {_entry_key_v1115(row): pos for pos, row in enumerate(items) if _entry_key_v1115(row)}
        changed = 0
        for row in rows:
            key = _entry_key_v1115(row)
            if not key:
                continue
            row["stale"] = False
            row["cached_index"] = True
            if key in positions:
                pos = positions[key]
                if items[pos] != row:
                    items[pos] = row
                    changed += 1
            else:
                positions[key] = len(items)
                items.append(row)
                changed += 1
        if changed:
            index["items"] = items
            index["search_recall_v11217"] = True
            self.save_data("channel_index", index)
        return changed

    def _cached_matches_for_subscription(self, subscribe: Any):
        pairs = list(super()._cached_matches_for_subscription(subscribe) or [])
        seen = {_entry_key_v1115(row) for row, _ in pairs if isinstance(row, dict)}
        candidates: List[Dict[str, Any]] = []
        candidates.extend(
            dict(row) for row in ((self.get_data("channel_index") or {}).get("items") or []) if isinstance(row, dict)
        )
        cache_reader = getattr(self, "_channel_cache_rows_v1115", None)
        if callable(cache_reader):
            try:
                candidates.extend(dict(row) for row in (cache_reader() or []) if isinstance(row, dict))
            except Exception:
                pass

        promoted: List[Dict[str, Any]] = []
        for row in candidates:
            key = _entry_key_v1115(row)
            if not key or key in seen:
                continue
            matched, detail = self._structured_candidate_match_v11217(subscribe, row)
            if not matched:
                continue
            promoted_row = self._promote_channel_entry_v11217(row, subscribe, detail)
            promoted.append(promoted_row)
            pairs.append((promoted_row, f"v1.12.17 structured recall: {detail.get('reason') or 'matched'}"))
            seen.add(key)
        if promoted:
            refresher = getattr(self, "_refresh_channel_cache_v1115", None)
            if callable(refresher):
                try:
                    refresher(promoted)
                except Exception:
                    pass
            self._merge_channel_index_v11217(promoted)
        pairs.sort(
            key=lambda pair: (
                int((pair[0] or {}).get("match_score_v11217") or 0),
                float((pair[0] or {}).get("cache_seen_at") or (pair[0] or {}).get("cache_added_at") or 0),
            ),
            reverse=True,
        )
        return pairs

    def _subscriptions_for_new_channel_entries_v1115(self) -> List[int]:
        matched_ids = set(super()._subscriptions_for_new_channel_entries_v1115() or [])
        entries = [dict(row) for row in (getattr(self, "_channel_new_entries_v1115", []) or []) if isinstance(row, dict)]
        if not entries:
            return sorted(matched_ids)
        selected = {
            int(value) for value in (getattr(self, "_selected_subscriptions", []) or [])
            if str(value).isdigit() and int(value) > 0
        }
        promoted: List[Dict[str, Any]] = []
        for subscribe in self._list_subscriptions("N,R") or []:
            sid = int(getattr(subscribe, "id", 0) or 0)
            if sid in matched_ids or sid not in selected or not self._is_guangya_route(subscribe):
                continue
            for entry in entries:
                matched, detail = self._structured_candidate_match_v11217(subscribe, entry)
                if not matched:
                    continue
                try:
                    if not bool(self._entry_can_cover_missing_v1115(entry, subscribe)):
                        continue
                except Exception:
                    continue
                promoted.append(self._promote_channel_entry_v11217(entry, subscribe, detail))
                matched_ids.add(sid)
                break
        if promoted:
            self._merge_channel_index_v11217(promoted)
        return sorted(matched_ids)

    # ------------------------------------------------------------------
    # Bounded Telegram channel-side ?q= search
    # ------------------------------------------------------------------
    def _channel_queries_v11217(self, subscribe: Any) -> List[str]:
        aliases = self._match_aliases_v11217(subscribe)
        year = str(getattr(subscribe, "year", "") or "").strip()
        result: List[str] = []
        seen = set()
        for alias in aliases:
            variants = [alias]
            if year:
                variants.append(f"{alias} {year}")
            for value in variants:
                clean = " ".join(value.split())
                key = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", clean.casefold())
                if len(key) < 2 or key in seen:
                    continue
                seen.add(key)
                result.append(clean)
                if len(result) >= max(2, int(self._channel_query_limit_v11217)):
                    return result
        return result

    def _channel_target_state_v11217(self) -> Dict[str, Any]:
        try:
            raw = self.get_data(_TARGET_SEARCH_STATE_V11217) or {}
        except Exception:
            raw = {}
        return dict(raw) if isinstance(raw, dict) else {}

    def _channel_target_due_v11217(self, subscribe: Any, force: bool) -> bool:
        if force:
            return True
        sid = str(int(getattr(subscribe, "id", 0) or 0))
        row = dict(self._channel_target_state_v11217().get(sid) or {})
        try:
            last_at = float(row.get("last_at") or 0)
        except (TypeError, ValueError):
            last_at = 0.0
        if not last_at:
            return True
        cooldown = self._channel_target_cooldown_v11217 if row.get("ok") else self._channel_target_failure_cooldown_v11217
        return time.time() - last_at >= float(cooldown)

    def _save_channel_target_result_v11217(self, subscribe: Any, *, ok: bool, found: int, queries: int, errors: int) -> None:
        sid = str(int(getattr(subscribe, "id", 0) or 0))
        lock = getattr(self, "_search_recall_lock_v11217", None)
        if lock is None:
            lock = threading.RLock()
            self._search_recall_lock_v11217 = lock
        with lock:
            state = self._channel_target_state_v11217()
            state[sid] = {
                "last_at": time.time(),
                "ok": bool(ok),
                "found": int(found),
                "queries": int(queries),
                "errors": int(errors),
            }
            if len(state) > 1000:
                ordered = sorted(
                    state.items(), key=lambda pair: float((pair[1] or {}).get("last_at") or 0), reverse=True
                )[:1000]
                state = dict(ordered)
            self.save_data(_TARGET_SEARCH_STATE_V11217, state)

    def _fetch_channel_query_v11217(self, source_url: str, query: str) -> Tuple[List[Dict[str, Any]], str]:
        request_cls = getattr(_legacy_module, "RequestUtils", None)
        extractor = getattr(_legacy_module, "_extract_channel_entries", None)
        settings_obj = getattr(_legacy_module, "settings", None)
        if request_cls is None or not callable(extractor):
            return [], "频道请求/解析器不可用"
        search_url = _channel_query_url_v11217(source_url, query)
        try:
            if bool(getattr(self, "_proxy", False)) and settings_obj is not None:
                request = request_cls(proxies=getattr(settings_obj, "PROXY", None))
            else:
                request = request_cls()
            response = request.get_res(search_url)
            status = int(getattr(response, "status_code", 200) or 200) if response is not None else 0
            if response is None or status >= 400:
                return [], f"HTTP {status or 'no-response'}"
            page_html = str(getattr(response, "text", "") or "")
            labeler = getattr(self, "_channel_label_v11215", None)
            label = labeler(source_url) if callable(labeler) else "频道"
            rows = [
                dict(row) for row in (extractor(page_html, source_url, label) or []) if isinstance(row, dict)
            ]
            for row in rows:
                row["targeted_query_v11217"] = query
                row["targeted_search_v11217"] = True
            return rows, ""
        except Exception as err:
            return [], str(err)[:180]

    def _targeted_channel_search_v11217(self, subscribe: Any, force: bool = False) -> Dict[str, Any]:
        sid = int(getattr(subscribe, "id", 0) or 0)
        if sid <= 0 or not self._channel_target_due_v11217(subscribe, force):
            return {"searched": False, "matched": 0, "rows": 0, "errors": []}
        queries = self._channel_queries_v11217(subscribe)
        sources = [str(value or "").strip() for value in (self._source_urls() or []) if str(value or "").strip()]
        if not queries or not sources:
            return {"searched": False, "matched": 0, "rows": 0, "errors": []}

        tasks = [(source, query) for source in sources for query in queries]
        all_rows: List[Dict[str, Any]] = []
        errors: List[str] = []
        workers = max(1, min(4, len(tasks)))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="guangya-channel-search") as pool:
            futures = {pool.submit(self._fetch_channel_query_v11217, source, query): (source, query) for source, query in tasks}
            for future in as_completed(futures):
                source, query = futures[future]
                try:
                    rows, error = future.result()
                except Exception as err:
                    rows, error = [], str(err)
                all_rows.extend(rows or [])
                if error:
                    errors.append(f"{source.split('?', 1)[0]} | {query}: {error[:120]}")

        accepted: List[Dict[str, Any]] = []
        seen = set()
        for row in all_rows:
            matched, detail = self._structured_candidate_match_v11217(subscribe, row)
            if not matched:
                continue
            promoted = self._promote_channel_entry_v11217(row, subscribe, detail)
            key = _entry_key_v1115(promoted)
            if not key or key in seen:
                continue
            seen.add(key)
            accepted.append(promoted)

        if accepted:
            refresher = getattr(self, "_refresh_channel_cache_v1115", None)
            if callable(refresher):
                try:
                    refresher(accepted)
                except Exception:
                    pass
            self._merge_channel_index_v11217(accepted)

        network_ok = len(errors) < len(tasks)
        self._save_channel_target_result_v11217(
            subscribe, ok=network_ok, found=len(accepted), queries=len(tasks), errors=len(errors)
        )
        self._plugin_log(
            "INFO" if network_ok else "WARNING",
            "【光鸭转存助手】【频道定向搜索v1.12.17】#%s %s：channels=%s queries=%s raw=%s matched=%s errors=%s；不修改频道游标",
            sid,
            str(getattr(subscribe, "name", "") or ""),
            len(sources),
            len(tasks),
            len(all_rows),
            len(accepted),
            len(errors),
        )
        return {
            "searched": True,
            "matched": len(accepted),
            "rows": len(all_rows),
            "errors": errors[:8],
            "queries": len(tasks),
        }

    def _history_backfill_for_subscriptions_v11215(self, subscriptions: Iterable[Any]) -> Dict[str, Any]:
        rows = [subscribe for subscribe in (subscriptions or []) if subscribe is not None]
        targeted_matched = 0
        for subscribe in rows:
            try:
                if not self._channel_passive_gap_v11215(subscribe):
                    continue
                if self._cached_matches_for_subscription(subscribe):
                    continue
                result = self._targeted_channel_search_v11217(subscribe, force=True)
                targeted_matched += int(result.get("matched") or 0)
            except Exception as err:
                self._plugin_log(
                    "WARNING",
                    "【光鸭转存助手】【频道定向搜索v1.12.17】#%s 新订阅定向搜索异常，继续既有有界历史回溯：%s",
                    int(getattr(subscribe, "id", 0) or 0),
                    str(err)[:180],
                )

        remaining = []
        for subscribe in rows:
            try:
                if self._cached_matches_for_subscription(subscribe):
                    continue
            except Exception:
                pass
            remaining.append(subscribe)
        result = dict(super()._history_backfill_for_subscriptions_v11215(remaining) or {})
        result["targeted_matched_v11217"] = targeted_matched
        return result

    def _try_transfer_subscription_inner(self, subscribe: Any, force: bool = False, refresh_channel: bool = True):
        # 5 分钟 channel_event 永远保持被动；只有主动 Pull/人工 force 才补频道侧 q 搜索。
        mode_reader = getattr(self, "_route_mode_v11214", None)
        try:
            mode = str(mode_reader() if callable(mode_reader) else "")
        except Exception:
            mode = ""
        should_target = bool(force) or mode in {"airing_pull", "daily_repair_pull", "viewing_poll"}
        if should_target and mode != "channel_event":
            try:
                gap_reader = getattr(self, "_channel_passive_gap_v11215", None)
                has_gap = bool(gap_reader(subscribe)) if callable(gap_reader) else True
                if has_gap and not self._cached_matches_for_subscription(subscribe):
                    self._targeted_channel_search_v11217(subscribe, force=bool(force))
            except Exception as err:
                self._plugin_log(
                    "WARNING",
                    "【光鸭转存助手】【频道定向搜索v1.12.17】#%s 主动检查定向搜索异常，继续原完整来源链：%s",
                    int(getattr(subscribe, "id", 0) or 0),
                    str(err)[:180],
                )
        return super()._try_transfer_subscription_inner(subscribe, force=force, refresh_channel=refresh_channel)


__all__ = [
    "GuangYaSearchRecallV11217Mixin",
    "_channel_query_url_v11217",
    "_release_title_candidates_v11217",
]
