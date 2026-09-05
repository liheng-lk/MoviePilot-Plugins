"""v1.12.14 核心资源链统一收口。

目标不是再为单个资源打补丁，而是建立所有来源共同的不变量：
1. 发现：频道与观影都可以贡献 GuangYa / Xunlei / Magnet / ED2K；
2. 识别：搜索标题只是发现证据，真正写盘前必须使用分享文件/resolve 文件做最终身份判断；
3. 缺口：TV 最终允许集只允许由 MoviePilot 媒体库事实、成功事实、reservation、其它来源 claim
   继续缩小，任何中间缓存都不能把已有集重新放回；
4. 物理文件：一个不可分割视频的全部集号必须属于最终允许集。E09-E11 只缺 E11 时整文件拒绝；
5. 幂等：同一规则同时覆盖 GuangYa 直接分享、Xunlei、Magnet、ED2K，来源切换不能绕过。

本层嵌套在 ManualCheck 与 v1.12.13 Xunlei fence 之间，不移动最终插件顶层 MRO。
"""
from __future__ import annotations

import copy
import hashlib
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from app.chain.media import MediaChain
from app.schemas.types import MediaSource, MediaType

from .episode_resolver_v190 import AUTO_SELECT_CONFIDENCE, reliable_episode_set, resolve_episode
from .legacy import (
    _canonical_share_url,
    _entry_match_reason,
    _is_subtitle,
    _is_video,
    _share_identity,
)
from .media_identity_v1111 import assess_media_identity_v1111, title_key_v1111
from .xunlei_existing_fence_v11213 import GuangYaXunleiExistingEpisodeFenceV11213Mixin


_ACTIVE_EXTERNAL_STATES_V11214 = {"new", "retry", "dispatching", "submitted", "queued", "waiting", "completed"}
_GENERIC_SHARE_ROOTS_V11214 = {
    "season", "season1", "season2", "s01", "s02", "tv", "movie", "movies", "video", "videos", "media",
    "电视剧", "电影", "视频", "资源", "全集", "全季",
}


def _positive_episode_set_v11214(values: Iterable[Any]) -> Set[int]:
    result: Set[int] = set()
    for raw in values or []:
        try:
            value = int(raw or 0)
        except (TypeError, ValueError):
            continue
        if value > 0:
            result.add(value)
    return result


def _physical_episode_subset_v11214(episodes: Iterable[Any], allowed: Iterable[Any]) -> bool:
    """物理文件只能在“全部集号都属于允许集”时写盘；交集非空远远不够。"""
    actual = _positive_episode_set_v11214(episodes)
    target = _positive_episode_set_v11214(allowed)
    return bool(actual and target and actual.issubset(target))


class GuangYaCorePipelineV11214Mixin(GuangYaXunleiExistingEpisodeFenceV11213Mixin):
    """统一来源发现、TV 官方别名召回和最终物理文件缺集栅栏。"""

    plugin_version = "1.12.14"
    build_id = "20260905-r60"
    _tv_alias_cache_ttl_v11214 = 24 * 60 * 60
    _tv_alias_failure_ttl_v11214 = 10 * 60

    def init_plugin(self, config: dict = None) -> None:
        self._core_pipeline_local_v11214 = threading.local()
        self._tv_alias_lock_v11214 = threading.RLock()
        self._tv_alias_cache_v11214: Dict[str, Dict[str, Any]] = {}
        return super().init_plugin(config)

    # ------------------------------------------------------------------
    # Thread-local provider entries: GYING GuangYa share enters legacy direct-share chain
    # without polluting persistent Telegram channel_index.
    # ------------------------------------------------------------------
    def _core_local_v11214(self) -> threading.local:
        local = getattr(self, "_core_pipeline_local_v11214", None)
        if local is None:
            local = threading.local()
            self._core_pipeline_local_v11214 = local
        return local

    def get_data(self, key: str):
        base = super().get_data(key)
        if str(key or "") != "channel_index":
            return base
        local = getattr(self, "_core_pipeline_local_v11214", None)
        extras = list(getattr(local, "provider_share_entries", []) or []) if local is not None else []
        if not extras:
            return base
        payload = copy.deepcopy(base) if isinstance(base, dict) else {}
        items = list(payload.get("items") or [])
        seen = {
            (_share_identity(str(row.get("share_url") or "")), str(row.get("resource_group_id") or ""))
            for row in items if isinstance(row, dict)
        }
        for raw in extras:
            row = dict(raw or {})
            marker = (_share_identity(str(row.get("share_url") or "")), str(row.get("resource_group_id") or ""))
            if marker[0] and marker not in seen:
                seen.add(marker)
                items.append(row)
        payload["items"] = items
        return payload

    def _route_mode_v11214(self) -> str:
        reader = getattr(self, "_route_source_mode_value_v1115", None)
        try:
            return str(reader() if callable(reader) else getattr(self, "_route_source_mode_v1115", "") or "")
        except Exception:
            return ""

    def _try_transfer_subscription_inner(self, subscribe: Any, force: bool = False, refresh_channel: bool = True):
        local = self._core_local_v11214()
        previous_entries = getattr(local, "provider_share_entries", None)
        previous_subscribe = getattr(local, "subscribe", None)
        local.provider_share_entries = []
        local.subscribe = subscribe
        try:
            return super()._try_transfer_subscription_inner(subscribe, force=force, refresh_channel=refresh_channel)
        finally:
            if previous_entries is None:
                try:
                    delattr(local, "provider_share_entries")
                except AttributeError:
                    pass
            else:
                local.provider_share_entries = previous_entries
            if previous_subscribe is None:
                try:
                    delattr(local, "subscribe")
                except AttributeError:
                    pass
            else:
                local.subscribe = previous_subscribe

    # ------------------------------------------------------------------
    # Channel Xunlei -> existing Xunlei flash chain. First attempt consumes channel arrivals;
    # passive channel mode never falls through into a network GYING search.
    # ------------------------------------------------------------------
    def _channel_xunlei_candidates_v11214(self, subscribe: Any) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        seen = set()
        for entry in list((super().get_data("channel_index") or {}).get("items") or []):
            if not isinstance(entry, dict) or entry.get("stale"):
                continue
            rows = list(entry.get("xunlei_sources") or [])
            if not rows:
                continue
            try:
                matched, _ = _entry_match_reason(entry, subscribe)
            except Exception:
                matched = False
            if not matched:
                continue
            discovery_title = str(entry.get("display_title") or "").strip()
            if not discovery_title:
                discovery_title = str(getattr(subscribe, "name", "") or "").strip()
            for raw in rows:
                if not isinstance(raw, dict):
                    continue
                share_id = str(raw.get("share_id") or raw.get("identity") or "").strip()
                passcode = str(raw.get("passcode") or "").strip()
                if not share_id or (share_id, passcode) in seen:
                    continue
                seen.add((share_id, passcode))
                candidates.append({
                    "type": "xunlei",
                    "uri": str(raw.get("uri") or "").strip(),
                    "identity": share_id,
                    "share_id": share_id,
                    "passcode": passcode,
                    "name": discovery_title,
                    "search_title": discovery_title,
                    "year": entry.get("year_hint"),
                    "provider": "channel",
                    "source_label": str(entry.get("source_label") or "频道"),
                    "message_id": str(entry.get("message_id") or ""),
                    "resource_group_id": str(entry.get("resource_group_id") or ""),
                })
        return candidates

    def _dispatch_xunlei_flash(self, subscribe: Any) -> Dict[str, Any]:
        local = self._core_local_v11214()
        previous = getattr(local, "xunlei_round", None)
        local.xunlei_round = {
            "subscribe": subscribe,
            "channel_consumed": False,
            "mode": self._route_mode_v11214(),
        }
        try:
            result = dict(super()._dispatch_xunlei_flash(subscribe) or {})
            if not result.get("handled") and self._route_mode_v11214() != "channel_event":
                self._hydrate_viewing_guangya_shares_v11214(subscribe)
            return result
        finally:
            if previous is None:
                try:
                    delattr(local, "xunlei_round")
                except AttributeError:
                    pass
            else:
                local.xunlei_round = previous

    def _search_viewing_xunlei(self, keyword: str):
        local = getattr(self, "_core_pipeline_local_v11214", None)
        round_state = getattr(local, "xunlei_round", None) if local is not None else None
        if isinstance(round_state, dict):
            subscribe = round_state.get("subscribe")
            if not round_state.get("channel_consumed"):
                round_state["channel_consumed"] = True
                rows = self._channel_xunlei_candidates_v11214(subscribe) if subscribe is not None else []
                if rows:
                    return rows, {
                        "provider": "channel_xunlei",
                        "success": True,
                        "channel_only": round_state.get("mode") == "channel_event",
                        "resources": len(rows),
                        "message": f"频道找到 {len(rows)} 个迅雷分享候选",
                    }
            if str(round_state.get("mode") or "") == "channel_event":
                return [], {
                    "provider": "channel_xunlei",
                    "success": True,
                    "channel_only": True,
                    "resources": 0,
                    "message": "频道事件未找到可用迅雷分享；不主动访问 GYING",
                }
        return super()._search_viewing_xunlei(keyword)

    # ------------------------------------------------------------------
    # GYING panlist GuangYa share -> temporary direct-share entry.
    # ------------------------------------------------------------------
    def _hydrate_viewing_guangya_shares_v11214(self, subscribe: Any) -> int:
        if not bool(getattr(self, "_viewing_enabled", False)):
            return 0
        keyword = str(self._provider_keyword(subscribe) or "").strip()
        if not keyword:
            return 0
        try:
            rows, state = self._gying_raw_results(keyword, force=False)
        except Exception as err:
            self._plugin_log("WARNING", "【光鸭转存助手】【观影光鸭分享v1.12.14】读取 GYING 结果失败：%s", str(err)[:240])
            return 0
        if not bool((state or {}).get("success")):
            return 0

        entries: List[Dict[str, Any]] = []
        seen = set()
        for raw in rows or []:
            if not isinstance(raw, dict):
                continue
            search_title = str(raw.get("search_title") or raw.get("name") or "").strip()
            discovery = {
                "search_title": search_title,
                "name": str(raw.get("name") or search_title),
                "year": raw.get("year"),
            }
            try:
                if not self._provider_candidate_matches(subscribe, discovery):
                    continue
            except Exception:
                continue
            value = str(raw.get("url") or raw.get("uri") or "").strip()
            share_url = _canonical_share_url(value, f"{search_title} {raw.get('name') or ''}")
            share_key = _share_identity(share_url)
            if not share_key or share_key in seen:
                continue
            seen.add(share_key)
            sid = int(getattr(subscribe, "id", 0) or 0)
            group_id = hashlib.sha256(f"viewing-guangya|{sid}|{share_key}".encode("utf-8")).hexdigest()[:24]
            entry = {
                "share_url": share_url,
                "share_id": share_key.split("|", 1)[0],
                "text": "\n".join(value for value in (search_title, str(raw.get("name") or "")) if value)[:2200],
                "source_url": "provider://viewing",
                "source_label": "观影光鸭分享",
                "priority": 0,
                "link_style": "观影网盘",
                "stale": False,
                "cached_index": True,
                "display_title": search_title or str(getattr(subscribe, "name", "") or ""),
                "year_hint": raw.get("year"),
                "episode_hint": "",
                "message_id": f"viewing-{group_id}",
                "resource_group_id": group_id,
                "external_sources": [],
                "candidate_types": ["guangya"],
                "provider_origin_v11214": True,
            }
            source = str(getattr(subscribe, "media_source", "") or "").lower()
            media_id = str(getattr(subscribe, "media_id", "") or "").strip()
            # 只在订阅本身就是 TMDB 精确身份且 GYING discovery 已通过 provider matcher 时附加该身份。
            # 最终真实分享文件仍会经过下面的 actual-content gate，TMDB discovery 不能覆盖硬冲突。
            if media_id.isdigit() and "tmdb" in source:
                entry["tmdb_id"] = media_id
            entries.append(entry)

        local = self._core_local_v11214()
        local.provider_share_entries = entries
        if entries:
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【观影光鸭分享v1.12.14】#%s %s 发现 %s 个光鸭分享，进入直接转存候选",
                getattr(subscribe, "id", 0), getattr(subscribe, "name", ""), len(entries),
            )
        return len(entries)

    # ------------------------------------------------------------------
    # Exact TMDB official aliases for TV/anime GYING recall.
    # ------------------------------------------------------------------
    @staticmethod
    def _tmdb_id_tv_v11214(subscribe: Any) -> str:
        raw_type = str(getattr(subscribe, "type", "") or "").lower()
        if "movie" in raw_type or "电影" in str(getattr(subscribe, "type", "") or ""):
            return ""
        for field in ("tmdb_id", "tmdbid"):
            value = str(getattr(subscribe, field, "") or "").strip()
            if value.isdigit():
                return value
        source = str(getattr(getattr(subscribe, "media_source", None), "value", getattr(subscribe, "media_source", "")) or "").lower()
        media_id = str(getattr(subscribe, "media_id", "") or "").strip()
        return media_id if media_id.isdigit() and "tmdb" in source else ""

    @staticmethod
    def _flatten_aliases_v11214(value: Any) -> List[str]:
        if value in (None, ""):
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            output: List[str] = []
            for item in value.values():
                output.extend(GuangYaCorePipelineV11214Mixin._flatten_aliases_v11214(item))
            return output
        if isinstance(value, (list, tuple, set)):
            output: List[str] = []
            for item in value:
                output.extend(GuangYaCorePipelineV11214Mixin._flatten_aliases_v11214(item))
            return output
        return [str(value)]

    def _tv_tmdb_aliases_v11214(self, subscribe: Any) -> List[str]:
        tmdb_id = self._tmdb_id_tv_v11214(subscribe)
        if not tmdb_id:
            return []
        key = f"tv:{tmdb_id}"
        now = time.time()
        lock = getattr(self, "_tv_alias_lock_v11214", None) or threading.RLock()
        self._tv_alias_lock_v11214 = lock
        cache = getattr(self, "_tv_alias_cache_v11214", None)
        if not isinstance(cache, dict):
            cache = {}
            self._tv_alias_cache_v11214 = cache
        with lock:
            cached = dict(cache.get(key) or {})
            try:
                age = now - float(cached.get("at") or 0)
            except (TypeError, ValueError):
                age = 10**9
            ttl = self._tv_alias_cache_ttl_v11214 if cached.get("ok") else self._tv_alias_failure_ttl_v11214
            if cached and age < float(ttl):
                return list(cached.get("aliases") or [])

        info = None
        error = ""
        try:
            info = MediaChain().recognize_media(mtype=MediaType.TV, media_source=MediaSource.TMDB, media_id=tmdb_id)
        except Exception as err:
            error = str(err)
        valid = bool(info)
        aliases: List[str] = []
        if info:
            returned_id = str(
                (info.get("tmdb_id") or info.get("media_id") or "") if isinstance(info, dict)
                else (getattr(info, "tmdb_id", None) or getattr(info, "media_id", None) or "")
            ).strip()
            if returned_id and returned_id != tmdb_id:
                valid = False
                error = f"TMDB返回身份不一致：期望={tmdb_id} 实际={returned_id}"
            if valid:
                values: List[str] = []
                for field in ("title", "name", "en_title", "original_title", "original_name", "cn_name", "hk_title", "tw_title", "aka", "aliases", "alias"):
                    raw = info.get(field) if isinstance(info, dict) else getattr(info, field, None)
                    values.extend(self._flatten_aliases_v11214(raw))
                seen = set()
                for raw in values:
                    text = " ".join(str(raw or "").split())
                    token = text.casefold()
                    if len(text) >= 2 and token not in seen:
                        seen.add(token)
                        aliases.append(text)
        with lock:
            cache[key] = {"at": now, "ok": bool(valid and aliases), "aliases": aliases, "error": error[:240]}
        return aliases if valid else []

    def _gying_alias_keywords_v11212(self, subscribe: Any, primary: str) -> List[str]:
        rows = list(super()._gying_alias_keywords_v11212(subscribe, primary) or [])
        if subscribe is None or self._is_movie_subscription(subscribe):
            return rows
        aliases = self._tv_tmdb_aliases_v11214(subscribe)
        if not aliases:
            return rows
        year = str(getattr(subscribe, "year", "") or "").strip()
        try:
            season = int(getattr(subscribe, "season", 0) or 0)
        except (TypeError, ValueError):
            season = 0
        seen = {re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").casefold()) for value in rows}
        limit = max(2, int(getattr(self, "_gying_alias_query_limit_v11212", 4) or 4))
        for alias in aliases:
            title = " ".join(str(alias or "").split())
            if not title:
                continue
            parts = [title]
            if year:
                parts.append(year)
            if season > 0:
                parts.append(f"S{season:02d}")
            candidate = " ".join(parts)
            token = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", candidate.casefold())
            if token and token not in seen:
                seen.add(token)
                rows.append(candidate)
            if len(rows) >= limit:
                break
        return rows

    # ------------------------------------------------------------------
    # Authoritative TV gap. This is used at the final physical-file boundary.
    # ------------------------------------------------------------------
    def _other_source_claims_v11214(self, subscribe_id: int, current_source_id: str = "") -> Set[int]:
        claims: Set[int] = set()
        try:
            items = (self._source_store() or {}).get("items") or {}
        except Exception:
            return claims
        for source_id, row in items.items():
            if not isinstance(row, dict) or int(row.get("subscribe_id") or 0) != int(subscribe_id or 0):
                continue
            if str(source_id or row.get("id") or "") == str(current_source_id or ""):
                continue
            if str(row.get("state") or "new") not in _ACTIVE_EXTERNAL_STATES_V11214:
                continue
            claims.update(_positive_episode_set_v11214(row.get("resolved_episodes") or row.get("target_episodes") or []))
        return claims

    def _authoritative_missing_v11214(self, subscribe: Any, *, current_source_id: str = "") -> Set[int]:
        if self._is_movie_subscription(subscribe):
            return set()
        # Reuse v1.12.13 fail-closed library reader; it both refreshes MoviePilot and validates the returned gap.
        library_missing = set(self._library_missing_v11213(subscribe))
        logical_missing = _positive_episode_set_v11214(self._subscription_missing_episodes(subscribe) or [])
        if logical_missing:
            allowed = library_missing.intersection(logical_missing)
        else:
            allowed = set(library_missing)
        try:
            reservations = self._pending_reservations(subscribe)
            allowed -= _positive_episode_set_v11214((reservations or {}).get("episodes") or [])
        except Exception:
            pass
        sid = int(getattr(subscribe, "id", 0) or 0)
        allowed -= self._other_source_claims_v11214(sid, current_source_id=current_source_id)
        return allowed

    def _resolved_episode_set_v11214(self, subscribe: Any, name: str, package_paths: Sequence[str], episode_hint: str = "") -> Set[int]:
        result = resolve_episode(
            str(name or ""),
            package_paths=list(package_paths or []),
            season_hint=getattr(subscribe, "season", None),
            episode_hint=str(episode_hint or ""),
        )
        threshold = float(getattr(self, "_episode_auto_confidence", AUTO_SELECT_CONFIDENCE) or AUTO_SELECT_CONFIDENCE)
        return set(reliable_episode_set(result, threshold))

    # ------------------------------------------------------------------
    # GuangYa direct share: actual-content hard conflict + authoritative physical subset.
    # ------------------------------------------------------------------
    @staticmethod
    def _direct_share_primary_roots_v11214(paths: Sequence[str], expected_year: Any = None) -> List[str]:
        roots = {
            str(path or "").replace("\\", "/").split("/", 1)[0].strip()
            for path in paths or [] if "/" in str(path or "").replace("\\", "/")
        }
        if len(roots) != 1:
            return []
        root = next(iter(roots))
        key = title_key_v1111(root, expected_year=expected_year).casefold()
        if len(key) < 3 or key in _GENERIC_SHARE_ROOTS_V11214 or re.fullmatch(r"s\d{1,2}|season\d{1,2}", key):
            return []
        return [root]

    def _plan_incremental_files(self, probe: Dict[str, Any], assets: Dict[str, Any], subscribe: Any = None, target_path: str = "", stats: Optional[Dict[str, Any]] = None):
        if subscribe is None or self._is_movie_subscription(subscribe):
            return super()._plan_incremental_files(probe, assets, subscribe=subscribe, target_path=target_path, stats=stats)

        video_paths = [
            str(row.get("relative_path") or row.get("name") or "")
            for row in (probe.get("files") or []) if isinstance(row, dict)
            and _is_video(str(row.get("relative_path") or row.get("name") or ""))
        ]
        aliases = list(self._identity_aliases_v1111(subscribe) or []) if hasattr(self, "_identity_aliases_v1111") else [str(getattr(subscribe, "name", "") or "")]
        assessment = assess_media_identity_v1111(
            aliases=aliases,
            expected_year=getattr(subscribe, "year", None),
            expected_season=getattr(subscribe, "season", None),
            is_movie=False,
            primary_evidences=self._direct_share_primary_roots_v11214(video_paths, getattr(subscribe, "year", None)),
            file_evidences=video_paths[:300],
            discovery_evidences=(),
            threshold=100,
        )
        if assessment.get("hard_conflict"):
            self._plugin_log(
                "WARNING",
                "【光鸭转存助手】【最终身份v1.12.14】#%s %s 光鸭分享真实内容硬冲突，拒绝写盘：%s",
                getattr(subscribe, "id", 0), getattr(subscribe, "name", ""), str(assessment.get("reason") or "")[:320],
            )
            if stats is not None:
                stats.clear()
                stats.update({"total": len(probe.get("files") or []), "eligible": 0, "episode": len(video_paths), "identity_reject_v11214": 1})
            return []

        allowed = self._authoritative_missing_v11214(subscribe)
        planned = list(super()._plan_incremental_files(probe, assets, subscribe=subscribe, target_path=target_path, stats=stats) or [])
        if not planned:
            return planned
        package_paths = [str(row.get("relative_path") or row.get("name") or "") for row in (probe.get("files") or []) if isinstance(row, dict)]
        safe_videos: List[Dict[str, Any]] = []
        safe_video_eps: Set[int] = set()
        for row in planned:
            path = str(row.get("effective_path") or row.get("relative_path") or row.get("name") or "")
            if not _is_video(path):
                continue
            episodes = self._resolved_episode_set_v11214(subscribe, path, package_paths)
            if _physical_episode_subset_v11214(episodes, allowed):
                safe_videos.append(row)
                safe_video_eps.update(episodes)
            else:
                self._plugin_log(
                    "WARNING",
                    "【光鸭转存助手】【物理缺集栅栏v1.12.14】光鸭分享拒绝不可分割文件：%s actual=%s allowed=%s",
                    path[:220], sorted(episodes), sorted(allowed),
                )
        if not safe_videos:
            return []
        safe: List[Dict[str, Any]] = list(safe_videos)
        parents = {
            str(row.get("effective_path") or row.get("relative_path") or row.get("name") or "").replace("\\", "/").rsplit("/", 1)[0].lower()
            for row in safe_videos
        }
        for row in planned:
            path = str(row.get("effective_path") or row.get("relative_path") or row.get("name") or "")
            if not _is_subtitle(path):
                continue
            episodes = self._resolved_episode_set_v11214(subscribe, path, package_paths)
            parent = path.replace("\\", "/").rsplit("/", 1)[0].lower() if "/" in path.replace("\\", "/") else ""
            if episodes:
                if _physical_episode_subset_v11214(episodes, allowed) and episodes.intersection(safe_video_eps):
                    safe.append(row)
            elif len(safe_videos) == 1 and parent in parents:
                safe.append(row)
        return safe

    # ------------------------------------------------------------------
    # Magnet / ED2K: final physical file set must be a subset of authoritative missing.
    # ------------------------------------------------------------------
    def _resolve_offline_source(self, source: Dict[str, Any], subscribe: Any) -> Dict[str, Any]:
        result = dict(super()._resolve_offline_source(source, subscribe) or {})
        if self._is_movie_subscription(subscribe):
            return result

        source_id = str(source.get("id") or "")
        allowed = self._authoritative_missing_v11214(subscribe, current_source_id=source_id)
        resolve_data = result.get("resolve_data") if isinstance(result.get("resolve_data"), dict) else {}
        rows = self._media_rows(resolve_data)
        media_rows = [row for row in rows if row.get("video") or row.get("subtitle")]
        package_paths = [str(row.get("name") or "") for row in media_rows]
        selected = {int(v) for v in (result.get("selected_indexes") or [])}
        episode_hint = str(source.get("episode_hint") or "")

        # ED2K single-file resolve may not expose btResInfo.subfiles.
        if not media_rows:
            actual_name = str(result.get("resolved_name") or source.get("name") or "").strip()
            episodes = self._resolved_episode_set_v11214(subscribe, actual_name, [actual_name] if actual_name else [], episode_hint)
            if not _physical_episode_subset_v11214(episodes, allowed):
                raise RuntimeError(
                    f"EPISODE_AMBIGUOUS:物理缺集栅栏拒绝 {source.get('type') or '外部来源'} 文件："
                    f"{actual_name or '-'} actual={sorted(episodes)} allowed={sorted(allowed)}"
                )
            if source_id:
                self._update_source(source_id, resolved_episodes=sorted(episodes))
            result["physical_episodes_v11214"] = sorted(episodes)
            return result

        safe_video_indexes: Set[int] = set()
        safe_video_eps: Set[int] = set()
        resolutions: Dict[int, Set[int]] = {}
        for row in media_rows:
            index = int(row.get("index") or 0)
            if selected and index not in selected:
                continue
            episodes = self._resolved_episode_set_v11214(subscribe, str(row.get("name") or ""), package_paths, episode_hint)
            resolutions[index] = episodes
            if row.get("video") and _physical_episode_subset_v11214(episodes, allowed):
                safe_video_indexes.add(index)
                safe_video_eps.update(episodes)
            elif row.get("video"):
                self._plugin_log(
                    "WARNING",
                    "【光鸭转存助手】【物理缺集栅栏v1.12.14】%s 拒绝不可分割文件：%s actual=%s allowed=%s",
                    str(source.get("type") or "外部来源"), str(row.get("name") or "")[:220], sorted(episodes), sorted(allowed),
                )
        if not safe_video_indexes:
            raise RuntimeError("EPISODE_AMBIGUOUS:解析成功但没有物理文件能够完整落在当前真实缺集集合内")

        safe_indexes: Set[int] = set(safe_video_indexes)
        safe_parents = {
            str(row.get("name") or "").replace("\\", "/").rsplit("/", 1)[0].lower()
            for row in media_rows if int(row.get("index") or 0) in safe_video_indexes
        }
        for row in media_rows:
            if not row.get("subtitle"):
                continue
            index = int(row.get("index") or 0)
            if selected and index not in selected:
                continue
            episodes = resolutions.get(index)
            if episodes is None:
                episodes = self._resolved_episode_set_v11214(subscribe, str(row.get("name") or ""), package_paths, episode_hint)
            parent = str(row.get("name") or "").replace("\\", "/").rsplit("/", 1)[0].lower() if "/" in str(row.get("name") or "").replace("\\", "/") else ""
            if episodes:
                if _physical_episode_subset_v11214(episodes, allowed) and episodes.intersection(safe_video_eps):
                    safe_indexes.add(index)
            elif len(safe_video_indexes) == 1 and parent in safe_parents:
                safe_indexes.add(index)

        result["selected_indexes"] = sorted(safe_indexes)
        result["physical_episodes_v11214"] = sorted(safe_video_eps)
        if source_id:
            self._update_source(
                source_id,
                resolved_episodes=sorted(safe_video_eps),
                selected_indexes=sorted(safe_indexes),
            )
        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【物理缺集栅栏v1.12.14】#%s %s source=%s allowed=%s physical=%s indexes=%s",
            getattr(subscribe, "id", 0), getattr(subscribe, "name", ""), str(source.get("type") or ""),
            sorted(allowed), sorted(safe_video_eps), sorted(safe_indexes),
        )
        return result


__all__ = [
    "GuangYaCorePipelineV11214Mixin",
    "_physical_episode_subset_v11214",
]
