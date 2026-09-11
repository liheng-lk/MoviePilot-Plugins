"""2.0.9 内部迭代：native audit / library preflight / resource trace / RAW Inbox-first。

不改 version/build_id；不改 r93 日历 / 21:00 / PoW。
"""
from __future__ import annotations

import hashlib
import threading
import time
import uuid
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import urlparse

from .channel_message_scan_v209 import (
    extract_channel_message_blocks_v209,
    page_has_resource_features_v209,
)
from .resource_inbox_v209 import (
    _INBOX_KEY,
    build_inbox_row_from_entry,
    build_inbox_row_from_message_block,
    convert_inbox_row_to_entry,
    extract_message_resource_candidates_v209,
    shadow_match_inbox_for_subscribe,
    summarize_page_extract_stats_v209,
    union_legacy_and_inbox_entries,
    upsert_inbox_rows,
)
from .transfer_diag_v209 import (
    aggregate_subscription_diag,
    classify_transfer_message_v209,
    dedup_candidate_diags,
    enrich_diag,
    finalize_subscription_diag,
    format_diag_log,
    make_diag,
    make_subscription_run_id,
    stable_trace_id,
)


class GuangYaFoundationOpsV209Mixin:
    """Native fail-closed audit + library preflight + resource trace + shadow inbox."""

    _library_snapshot_ttl_v209 = 45
    _resource_trace_max_v209 = 3000

    def init_plugin(self, config: dict = None) -> None:
        self._library_snapshot_lock_v209 = threading.RLock()
        self._library_snapshot_v209: Dict[str, Dict[str, Any]] = {}
        self._resource_trace_lock_v209 = threading.RLock()
        self._transfer_diag_ctx_v209 = threading.local()
        self._subscription_run_seq_lock_v209 = threading.RLock()
        self._subscription_run_seq_v209 = 0
        # Diagnostic-only instance marker (not persisted; not used for business dedup).
        self._instance_id_v209 = uuid.uuid4().hex[:8]
        result = super().init_plugin(config)
        try:
            version = str(getattr(self, "plugin_version", "") or "")
            build = str(getattr(self, "build_id", "") or "")
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【启动】version=%s build=%s instance=%s",
                version,
                build,
                self._instance_id_v209,
            )
        except Exception:
            pass
        return result

    def _instance_id_marker_v209(self) -> str:
        marker = str(getattr(self, "_instance_id_v209", "") or "").strip()
        if marker:
            return marker
        marker = uuid.uuid4().hex[:8]
        self._instance_id_v209 = marker
        return marker

    def _diag_tls_v209(self):
        tls = getattr(self, "_transfer_diag_ctx_v209", None)
        if tls is None:
            tls = threading.local()
            self._transfer_diag_ctx_v209 = tls
        return tls

    def _begin_subscription_run_v209(self, subscribe: Any) -> str:
        sid = int(getattr(subscribe, "id", 0) or 0)
        gen = str(
            getattr(self, "_channel_scan_generation_v209", None)
            or getattr(self, "_refresh_generation_v209", None)
            or getattr(self, "_batch_trigger_v209", None)
            or "manual"
        )
        lock = getattr(self, "_subscription_run_seq_lock_v209", None) or threading.RLock()
        self._subscription_run_seq_lock_v209 = lock
        with lock:
            counter = int(getattr(self, "_subscription_run_seq_v209", 0) or 0) + 1
            self._subscription_run_seq_v209 = counter
        run_id = make_subscription_run_id(sid, gen, counter)
        tls = self._diag_tls_v209()
        previous = getattr(tls, "stack", None)
        if not isinstance(previous, list):
            previous = []
        previous.append({
            "run_id": getattr(tls, "run_id", ""),
            "sid": getattr(tls, "sid", 0),
            "candidate_diags": list(getattr(tls, "candidate_diags", []) or []),
            "episode_claims": dict(getattr(tls, "episode_claims", {}) or {}),
        })
        tls.stack = previous
        tls.run_id = run_id
        tls.sid = sid
        tls.candidate_diags = []
        tls.episode_claims = {}
        # Backward-compatible mirrors for legacy readers (same-thread only).
        self._current_subscription_run_id_v209 = run_id
        self._current_subscription_candidate_diags_v209 = tls.candidate_diags
        return run_id

    def _end_subscription_run_v209(self) -> None:
        tls = self._diag_tls_v209()
        stack = getattr(tls, "stack", None)
        if isinstance(stack, list) and stack:
            prev = stack.pop()
            tls.stack = stack
            tls.run_id = prev.get("run_id") or ""
            tls.sid = prev.get("sid") or 0
            tls.candidate_diags = list(prev.get("candidate_diags") or [])
            tls.episode_claims = dict(prev.get("episode_claims") or {})
        else:
            tls.run_id = ""
            tls.sid = 0
            tls.candidate_diags = []
            tls.episode_claims = {}
        self._current_subscription_run_id_v209 = str(getattr(tls, "run_id", "") or "")
        self._current_subscription_candidate_diags_v209 = list(getattr(tls, "candidate_diags", []) or [])

    def _run_episode_claims_map_v209(self) -> Dict[Tuple[Any, ...], Dict[str, Any]]:
        tls = self._diag_tls_v209()
        claims = getattr(tls, "episode_claims", None)
        if not isinstance(claims, dict):
            claims = {}
            tls.episode_claims = claims
        return claims

    @staticmethod
    def _run_episode_claim_key_v209(season: Any, episode: Any, *, movie: bool = False) -> Tuple[Any, ...]:
        if movie:
            return ("movie-main",)
        try:
            season_i = int(season or 0)
        except (TypeError, ValueError):
            season_i = 0
        try:
            episode_i = int(episode or 0)
        except (TypeError, ValueError):
            episode_i = 0
        return (season_i, episode_i)

    def _claim_run_episodes_v209(
        self,
        *,
        season: Any,
        episodes: Iterable[int],
        candidate_trace_id: str,
        sid: Any = None,
        movie: bool = False,
    ) -> Tuple[List[int], List[int]]:
        """Atomically claim episodes for this subscription_run before submit.

        Returns (claimed_episodes, blocked_episodes).
        """
        claims = self._run_episode_claims_map_v209()
        cand = str(candidate_trace_id or "")
        claimed: List[int] = []
        blocked: List[int] = []
        run_id = self._current_subscription_run_id()
        for raw in episodes or []:
            try:
                ep = int(raw or 0)
            except (TypeError, ValueError):
                continue
            if not movie and ep <= 0:
                continue
            key = self._run_episode_claim_key_v209(season, ep if not movie else 0, movie=movie)
            owner = dict(claims.get(key) or {})
            owner_state = str(owner.get("state") or "")
            owner_cand = str(owner.get("candidate_trace_id") or "")
            if owner_state in {"reserved", "pending", "confirmed"} and owner_cand and owner_cand != cand:
                blocked.append(ep if not movie else 0)
                self._plugin_log(
                    "INFO",
                    "【Episode Claim】sid=%s run=%s episode=%s candidate=%s owner=%s decision=skip_reserved",
                    sid if sid is not None else getattr(self._diag_tls_v209(), "sid", 0),
                    str(run_id or "-")[:40],
                    ("movie-main" if movie else f"S{int(season or 0):02d}E{ep:02d}"),
                    cand[:80],
                    owner_cand[:80],
                )
                continue
            claims[key] = {
                "candidate_trace_id": cand,
                "state": "reserved",
                "sid": int(sid or getattr(self._diag_tls_v209(), "sid", 0) or 0),
                "season": int(season or 0) if not movie else 0,
                "episode": ep if not movie else 0,
                "movie": bool(movie),
            }
            claimed.append(ep if not movie else 0)
        return claimed, blocked

    def _release_run_episodes_v209(
        self,
        *,
        season: Any,
        episodes: Iterable[int],
        candidate_trace_id: str,
        movie: bool = False,
    ) -> int:
        """Release claims after submit failed before task creation."""
        claims = self._run_episode_claims_map_v209()
        cand = str(candidate_trace_id or "")
        released = 0
        for raw in episodes or []:
            try:
                ep = int(raw or 0)
            except (TypeError, ValueError):
                continue
            key = self._run_episode_claim_key_v209(season, ep if not movie else 0, movie=movie)
            owner = dict(claims.get(key) or {})
            if str(owner.get("candidate_trace_id") or "") != cand:
                continue
            if str(owner.get("state") or "") in {"pending", "confirmed"}:
                # Task already created — do not free for same-run dual workers.
                continue
            claims.pop(key, None)
            released += 1
        return released

    def _mark_run_episodes_state_v209(
        self,
        *,
        season: Any,
        episodes: Iterable[int],
        candidate_trace_id: str,
        state: str,
        movie: bool = False,
    ) -> None:
        claims = self._run_episode_claims_map_v209()
        cand = str(candidate_trace_id or "")
        wanted = str(state or "pending")
        for raw in episodes or []:
            try:
                ep = int(raw or 0)
            except (TypeError, ValueError):
                continue
            key = self._run_episode_claim_key_v209(season, ep if not movie else 0, movie=movie)
            owner = dict(claims.get(key) or {})
            if str(owner.get("candidate_trace_id") or "") != cand:
                continue
            owner["state"] = wanted
            claims[key] = owner

    def _filter_planned_by_run_claim_v209(
        self,
        subscribe: Any,
        planned: List[Dict[str, Any]],
        *,
        candidate_trace_id: str,
    ) -> Tuple[List[Dict[str, Any]], List[int], List[int]]:
        """Claim episodes for planned files before submit. Returns (kept, claimed_eps, blocked_eps)."""
        try:
            from .legacy import _episode_numbers as episode_numbers
        except Exception:
            import re

            def episode_numbers(path: Any) -> Tuple[Optional[int], List[int]]:
                value = str(path or "")
                season = None
                episodes: Set[int] = set()
                block = re.search(
                    r"(?i)S(?:eason)?[\s._-]*0*(\d{1,2})[\s._-]*E(?:p(?:isode)?)?[\s._-]*0*(\d{1,3})"
                    r"(?:[\s._-]*(?:-|~|至|到)?[\s._-]*E?(?:p(?:isode)?)?[\s._-]*0*(\d{1,3}))?",
                    value,
                )
                if block:
                    season = int(block.group(1))
                    start = int(block.group(2))
                    end = int(block.group(3)) if block.group(3) else start
                    if end >= start:
                        episodes.update(range(start, end + 1))
                return season, sorted(episodes)

        is_movie = False
        try:
            is_movie = bool(self._is_movie_subscription(subscribe))
        except Exception:
            media_type = str(getattr(subscribe, "type", "") or "").lower()
            is_movie = "movie" in media_type or "电影" in media_type
        try:
            season = int(getattr(subscribe, "season", 0) or 0)
        except (TypeError, ValueError):
            season = 0
        sid = int(getattr(subscribe, "id", 0) or 0)
        kept: List[Dict[str, Any]] = []
        claimed_all: List[int] = []
        blocked_all: List[int] = []
        if is_movie:
            if not planned:
                return [], [], []
            claimed, blocked = self._claim_run_episodes_v209(
                season=0,
                episodes=[0],
                candidate_trace_id=candidate_trace_id,
                sid=sid,
                movie=True,
            )
            if blocked and not claimed:
                return [], [], [0]
            return list(planned), claimed, blocked

        for item in list(planned or []):
            path = str(item.get("effective_path") or item.get("relative_path") or item.get("name") or "")
            file_season, episodes = episode_numbers(path)
            eps = [int(v) for v in (episodes or []) if int(v or 0) > 0]
            use_season = file_season if file_season is not None else season
            if not eps:
                # Unparsed episode numbers: do not claim; keep for existing fence handling.
                kept.append(item)
                continue
            # Indivisible multi-episode file: require claiming every episode, else skip whole file.
            claimed, blocked = self._claim_run_episodes_v209(
                season=use_season,
                episodes=eps,
                candidate_trace_id=candidate_trace_id,
                sid=sid,
                movie=False,
            )
            if blocked and set(blocked) == set(eps):
                blocked_all.extend(blocked)
                continue
            if blocked:
                # Partial overlap on indivisible package — release any partial claim and skip file.
                self._release_run_episodes_v209(
                    season=use_season,
                    episodes=claimed,
                    candidate_trace_id=candidate_trace_id,
                    movie=False,
                )
                blocked_all.extend(blocked)
                continue
            if claimed:
                claimed_all.extend(claimed)
                kept.append(item)
            else:
                blocked_all.extend(eps)
        return kept, sorted(set(claimed_all)), sorted(set(blocked_all))

    def _current_subscription_run_id(self) -> str:
        tls = self._diag_tls_v209()
        return str(getattr(tls, "run_id", None) or getattr(self, "_current_subscription_run_id_v209", "") or "")

    def _append_candidate_diag_v209(self, diag: Dict[str, Any]) -> None:
        tls = self._diag_tls_v209()
        rows = getattr(tls, "candidate_diags", None)
        if not isinstance(rows, list):
            rows = []
            tls.candidate_diags = rows
        row = dict(diag or {})
        run_id = str(getattr(tls, "run_id", "") or "")
        if run_id and not row.get("subscription_run_id"):
            row["subscription_run_id"] = run_id
        # Dedup against authoritative TLS collector.
        key = (
            str(row.get("subscription_run_id") or ""),
            str(row.get("resource_trace_id") or row.get("trace_id") or ""),
            str(row.get("candidate_trace_id") or ""),
            str(row.get("stage") or ""),
            str(row.get("reason_code") or ""),
            str(row.get("state") or ""),
        )
        for existing in rows:
            if (
                str(existing.get("subscription_run_id") or ""),
                str(existing.get("resource_trace_id") or existing.get("trace_id") or ""),
                str(existing.get("candidate_trace_id") or ""),
                str(existing.get("stage") or ""),
                str(existing.get("reason_code") or ""),
                str(existing.get("state") or ""),
            ) == key:
                return
        rows.append(row)
        self._current_subscription_candidate_diags_v209 = rows
        # Persist stage event into Resource Trace Store.
        try:
            entry = {
                "title": str((row.get("evidence") or {}).get("subscribe_title") or ""),
                "message_id": str((row.get("evidence") or {}).get("message_id") or "-"),
                "resource_trace_id": str(row.get("resource_trace_id") or row.get("trace_id") or ""),
                "source_url": str((row.get("evidence") or {}).get("source_url") or ""),
            }
            if entry["resource_trace_id"]:
                self._resource_trace_v209(
                    entry=entry,
                    state=f"{row.get('stage') or 'STAGE'}/{row.get('state') or '-'}",
                    reason=f"{row.get('reason_code') or '-'}|{row.get('candidate_trace_id') or ''}|{str(row.get('message') or '')[:120]}",
                    matched_sid=row.get("sid"),
                )
        except Exception:
            pass

    def _snapshot_candidate_diags_v209(self) -> List[Dict[str, Any]]:
        tls = self._diag_tls_v209()
        return dedup_candidate_diags(list(getattr(tls, "candidate_diags", []) or []))

    # ------------------------------------------------------------------
    # Native search audit + fail-closed leak block
    # ------------------------------------------------------------------
    def _native_audit_source_v209(self, *, manual: Any = False, scheduled_interval: Any = None, sid=None, sids=None) -> str:
        if bool(manual):
            return "manual"
        if scheduled_interval is not None:
            return "scheduled"
        if sid is not None or sids is not None:
            return "api"
        return "unknown"

    def _managed_ids_now_v209(self) -> Set[int]:
        selected = {
            int(value)
            for value in (getattr(self, "_selected_subscriptions", None) or [])
            if str(value).isdigit() and int(value) > 0
        }
        # provisional routes also count as managed ownership for leak purposes
        try:
            provisional = getattr(self, "_provisional_routes", None) or {}
            if isinstance(provisional, dict):
                for key in provisional.keys():
                    # provisional keyed by identity, not always sid; still rely on selected for leak
                    pass
        except Exception:
            pass
        return selected

    def _extract_requested_sids_v209(self, kwargs: Dict[str, Any]) -> List[int]:
        values: List[int] = []
        sid = kwargs.get("sid")
        if sid is not None and str(sid).strip() != "":
            try:
                values.append(int(sid))
            except (TypeError, ValueError):
                pass
        for raw in kwargs.get("sids") or ():
            try:
                value = int(raw)
            except (TypeError, ValueError):
                continue
            if value > 0:
                values.append(value)
        # unique preserve order
        seen = set()
        output = []
        for value in values:
            if value not in seen:
                seen.add(value)
                output.append(value)
        return output

    def _sanitize_native_kwargs_v209(self, kwargs: Dict[str, Any]) -> Tuple[Dict[str, Any], List[int], List[int], List[int]]:
        """Return (clean_kwargs, requested, managed, leaked_removed)."""
        clean = dict(kwargs or {})
        requested = self._extract_requested_sids_v209(clean)
        managed_now = self._managed_ids_now_v209()
        # Also treat currently managed subscriptions by live object check.
        live_managed: Set[int] = set(managed_now)
        for sid in list(requested):
            subscribe = None
            try:
                subscribe = self._find_subscription(sid)
            except Exception:
                subscribe = None
            if self._is_managed_sid(sid) or (subscribe is not None and self._is_managed_subscription(subscribe)):
                live_managed.add(sid)

        leaked = [sid for sid in requested if sid in live_managed]
        native = [sid for sid in requested if sid not in live_managed]
        managed_in_request = list(leaked)

        if "sids" in clean or leaked or len(requested) > 1:
            if native:
                clean["sids"] = tuple(native)
                clean["sid"] = None
            else:
                clean.pop("sids", None)
                clean["sid"] = None
        elif requested:
            # single sid path
            only = requested[0]
            if only in live_managed:
                clean["sid"] = None
            else:
                subscribe = self._find_subscription(only)
                if self._is_managed_sid(only) or (subscribe is not None and self._is_managed_subscription(subscribe)):
                    clean["sid"] = None
                    leaked = [only]
                    managed_in_request = [only]
                    native = []
                else:
                    clean["sid"] = only
        return clean, requested, managed_in_request, leaked

    def _call_original_search(self, original, chain_self, *args, **kwargs):
        clean, requested, managed_hit, leaked = self._sanitize_native_kwargs_v209(dict(kwargs or {}))
        source = self._native_audit_source_v209(
            manual=clean.get("manual"),
            scheduled_interval=clean.get("scheduled_interval"),
            sid=kwargs.get("sid"),
            sids=kwargs.get("sids"),
        )
        native_sids = self._extract_requested_sids_v209(clean)
        self._plugin_log(
            "INFO",
            "【原生审计】source=%s requested_sids=%s managed_sids=%s native_sids=%s managed_leak=%s",
            source,
            ",".join(str(v) for v in requested) or "-",
            ",".join(str(v) for v in managed_hit) or "-",
            ",".join(str(v) for v in native_sids) or "-",
            ",".join(str(v) for v in leaked) or "-",
        )
        if leaked:
            self._plugin_log(
                "ERROR",
                "【原生审计】【泄漏阻断】managed SID 不允许进入 MoviePilot native search：%s",
                ",".join(str(v) for v in leaked),
            )
        # explicit single-sid final recheck
        only = clean.get("sid")
        if only not in (None, ""):
            try:
                only_sid = int(only)
            except (TypeError, ValueError):
                only_sid = 0
            subscribe = self._find_subscription(only_sid) if only_sid else None
            if only_sid and (self._is_managed_sid(only_sid) or (subscribe is not None and self._is_managed_subscription(subscribe))):
                self._plugin_log(
                    "ERROR",
                    "【原生审计】【泄漏阻断】显式 sid=%s 运行时已托管，禁止 native",
                    only_sid,
                )
                return None
        if not native_sids and clean.get("sid") in (None, ""):
            # no remaining native targets after stripping
            if requested:
                return None
        return super()._call_original_search(original, chain_self, *args, **clean)

    # ------------------------------------------------------------------
    # Library preflight snapshot (scan-cycle TTL)
    # ------------------------------------------------------------------
    def _library_snapshot_key_v209(self, subscribe: Any) -> str:
        sid = int(getattr(subscribe, "id", 0) or 0)
        media_id = str(getattr(subscribe, "media_id", None) or getattr(subscribe, "tmdbid", None) or "")
        season = getattr(subscribe, "season", None)
        return f"{sid}:{media_id}:{season}"

    def _library_preflight_v209(self, subscribe: Any, *, force: bool = False) -> Dict[str, Any]:
        key = self._library_snapshot_key_v209(subscribe)
        now = time.time()
        lock = getattr(self, "_library_snapshot_lock_v209", None) or threading.RLock()
        self._library_snapshot_lock_v209 = lock
        with lock:
            cache = getattr(self, "_library_snapshot_v209", None)
            if not isinstance(cache, dict):
                cache = {}
                self._library_snapshot_v209 = cache
            row = dict(cache.get(key) or {})
            if (
                not force
                and row
                and (now - float(row.get("checked_at") or 0)) < float(self._library_snapshot_ttl_v209)
            ):
                return row

        sid = int(getattr(subscribe, "id", 0) or 0)
        is_movie = bool(self._is_movie_subscription(subscribe))
        snapshot: Dict[str, Any] = {
            "subscribe_id": sid,
            "checked_at": now,
            "is_movie": is_movie,
            "library_existing": [],
            "authoritative_missing": [],
            "current_target_satisfied": False,
            "movie_exists": False,
            "completion_pending": False,
            "source": "fallback",
        }

        if is_movie:
            exists = False
            try:
                needs = getattr(self, "_movie_needs_pull_v1125", None)
                if callable(needs):
                    exists = not bool(needs(subscribe))
            except Exception:
                exists = False
            snapshot["movie_exists"] = exists
            snapshot["current_target_satisfied"] = exists
            snapshot["source"] = "movie_needs_pull"
        else:
            missing: Set[int] = set()
            source = "fallback"
            resolver = getattr(self, "_mp_authoritative_missing_episodes_v209", None)
            if callable(resolver):
                try:
                    source, missing = resolver(subscribe)
                except Exception:
                    source, missing = "fallback", set()
            known = source not in {"", "fallback", None}
            if not missing and not known:
                try:
                    sync = dict(self._sync_media_library_progress(subscribe) or {})
                    missing = {int(v) for v in (sync.get("missing") or []) if int(v or 0) > 0}
                    existing = {int(v) for v in (sync.get("existing") or []) if int(v or 0) > 0}
                    snapshot["library_existing"] = sorted(existing)
                    source = "library_sync"
                    known = True
                except Exception:
                    missing = set()
                    known = False
            snapshot["authoritative_missing"] = sorted(missing)
            # episodes=[] is NOT satisfied unless MP explicitly reported complete coverage.
            if missing:
                snapshot["current_target_satisfied"] = False
                snapshot["preflight_state"] = "MISSING"
            elif source in {"used_complete"}:
                snapshot["current_target_satisfied"] = True
                snapshot["preflight_state"] = "SATISFIED"
            elif source in {"used_empty", "fallback", "", None} or not known:
                snapshot["current_target_satisfied"] = False
                snapshot["preflight_state"] = "UNKNOWN"
            else:
                # Legacy/unknown source labels with empty missing: fail-open continue match.
                snapshot["current_target_satisfied"] = False
                snapshot["preflight_state"] = "UNKNOWN"
            snapshot["source"] = source if known else "fallback"

        with lock:
            cache[key] = snapshot
            if len(cache) > 2000:
                ordered = sorted(cache.items(), key=lambda kv: float((kv[1] or {}).get("checked_at") or 0))
                self._library_snapshot_v209 = dict(ordered[-1500:])
        return snapshot

    def _subscriptions_for_new_channel_entries_v1115(self) -> List[int]:
        """Channel event selection: library preflight post-filters candidates.

        Never mutate ``_selected_subscriptions`` — that set is managed ownership truth.
        """
        skip_match_sids: Set[int] = set()
        selected = {
            int(value) for value in (getattr(self, "_selected_subscriptions", None) or [])
            if str(value).isdigit() and int(value) > 0
        }
        for subscribe in self._list_subscriptions("N,R"):
            sid = int(getattr(subscribe, "id", 0) or 0)
            if sid not in selected or not self._is_guangya_route(subscribe):
                continue
            preflight = self._library_preflight_v209(subscribe, force=False)
            if not bool(preflight.get("current_target_satisfied")):
                continue
            skip_match_sids.add(sid)
            self._plugin_log(
                "INFO",
                "【媒体库预检】#%s %s existing=%s missing=- decision=skip_match reason=current_target_satisfied source=%s",
                sid,
                getattr(subscribe, "name", ""),
                ",".join(str(v) for v in (preflight.get("library_existing") or []))
                or ("movie" if preflight.get("movie_exists") else "-"),
                str(preflight.get("source") or "-"),
            )
        candidate_sids = list(super()._subscriptions_for_new_channel_entries_v1115() or [])
        if not skip_match_sids:
            return candidate_sids
        return [sid for sid in candidate_sids if int(sid) not in skip_match_sids]

    def _try_transfer_subscription_inner(
        self,
        subscribe: Any,
        force: bool = False,
        refresh_channel: bool = True,
    ) -> Dict[str, Any]:
        sid = int(getattr(subscribe, "id", 0) or 0)
        run_id = self._begin_subscription_run_v209(subscribe)
        try:
            return self._try_transfer_subscription_inner_body_v209(
                subscribe, force=force, refresh_channel=refresh_channel, run_id=run_id,
            )
        finally:
            self._end_subscription_run_v209()

    def _try_transfer_subscription_inner_body_v209(
        self,
        subscribe: Any,
        force: bool = False,
        refresh_channel: bool = True,
        run_id: str = "",
    ) -> Dict[str, Any]:
        sid = int(getattr(subscribe, "id", 0) or 0)
        preflight = self._library_preflight_v209(subscribe, force=True)
        if bool(preflight.get("completion_pending")):
            self._plugin_log(
                "WARNING",
                "【完成同步】#%s 目标已经满足，但 MoviePilot 活动订阅仍存在；本轮停止资源匹配，等待下一次 completion retry",
                sid,
            )
            result = {
                "success": True,
                "handled": True,
                "already": True,
                "completion_pending": True,
                "message": "completion_pending：目标已满足但订阅仍在活动列表",
                "subscription_run_id": run_id,
                "diag": make_diag(
                    state="PENDING",
                    reason_code="COMPLETION_SYNC_PENDING",
                    stage="COMPLETION",
                    message="completion_pending：目标已满足但订阅仍在活动列表",
                    subscription_run_id=run_id,
                    sid=sid,
                    subscription_level=True,
                ),
            }
            self._trace_transfer_result_v209(subscribe, result)
            return result

        if bool(preflight.get("current_target_satisfied")):
            finished = False
            try:
                finished = bool(self._finish_subscription_if_complete(subscribe))
            except Exception:
                finished = False
            if finished:
                try:
                    selected = [
                        int(v) for v in (getattr(self, "_selected_subscriptions", None) or [])
                        if str(v).isdigit() and int(v) > 0 and int(v) != sid
                    ]
                    self._selected_subscriptions = selected
                    saver = getattr(self, "_remember_route_membership", None)
                    if callable(saver):
                        saver("completion_remove")
                except Exception:
                    pass
                result = {
                    "success": True,
                    "handled": True,
                    "completed": True,
                    "message": "媒体库已满足目标，订阅已完成",
                    "subscription_run_id": run_id,
                    "diag": make_diag(
                        state="SUCCESS",
                        reason_code="SUBSCRIPTION_COMPLETED",
                        stage="COMPLETION",
                        message="媒体库已满足目标，订阅已完成",
                        subscription_run_id=run_id,
                        sid=sid,
                        subscription_level=True,
                    ),
                }
                self._trace_transfer_result_v209(subscribe, result)
                return result
            preflight["completion_pending"] = True
            key = self._library_snapshot_key_v209(subscribe)
            with getattr(self, "_library_snapshot_lock_v209", threading.RLock()):
                cache = getattr(self, "_library_snapshot_v209", {})
                if isinstance(cache, dict):
                    cache[key] = dict(preflight)
            self._plugin_log(
                "WARNING",
                "【完成同步】#%s 目标已经满足，但 MoviePilot 活动订阅仍存在；本轮停止资源匹配，等待下一次 completion retry",
                sid,
            )
            result = {
                "success": True,
                "handled": True,
                "already": True,
                "completion_pending": True,
                "message": "current_target_satisfied；跳过本轮资源匹配",
                "subscription_run_id": run_id,
                "diag": make_diag(
                    state="PENDING",
                    reason_code="COMPLETION_SYNC_PENDING",
                    stage="LIBRARY_PREFLIGHT",
                    message="current_target_satisfied；跳过本轮资源匹配",
                    subscription_run_id=run_id,
                    sid=sid,
                    subscription_level=True,
                ),
            }
            self._trace_transfer_result_v209(subscribe, result)
            return result

        result = dict(super()._try_transfer_subscription_inner(
            subscribe, force=force, refresh_channel=refresh_channel,
        ) or {})
        if (
            not bool(result.get("success"))
            and not bool(result.get("already"))
            and not bool(result.get("completed"))
            and ("暂未匹配" in str(result.get("message") or "") or "没有新链接" in str(result.get("message") or ""))
        ):
            inbox_result = self._try_match_inbox_for_subscribe_v209(subscribe)
            if inbox_result:
                result = dict(inbox_result)
        result.setdefault("subscription_run_id", run_id)
        # Authoritative collector is TLS; result snapshot is for persistence only (deduped).
        collected = self._snapshot_candidate_diags_v209()
        existing = list(result.get("candidate_diags") or []) if isinstance(result.get("candidate_diags"), list) else []
        merged = dedup_candidate_diags(collected + existing)
        if merged:
            result["candidate_diags"] = merged
        self._trace_transfer_result_v209(subscribe, result)
        self._shadow_inbox_compare_v209(subscribe, result)
        return result

    def _try_match_inbox_for_subscribe_v209(self, subscribe: Any) -> Optional[Dict[str, Any]]:
        """If channel_index miss, attempt matcher against persisted Inbox (7d)."""
        try:
            from .legacy import _entry_match_reason
        except Exception:
            return None
        store = self.get_data(_INBOX_KEY) or {}
        hits = shadow_match_inbox_for_subscribe(store, subscribe, _entry_match_reason)
        if not hits:
            diag = make_diag(
                state="NO_RESULT",
                reason_code="NO_LOCAL_RESOURCE",
                stage="MATCH",
                message="当前 managed 订阅中没有满足标题/年份/身份条件的 Inbox 资源",
                evidence={
                    "subscribe_title": getattr(subscribe, "name", ""),
                    "subscribe_year": getattr(subscribe, "year", ""),
                    "subscribe_tmdb": getattr(subscribe, "tmdbid", None) or getattr(subscribe, "media_id", ""),
                    "inbox_count": int((store or {}).get("count") or len((store or {}).get("items") or {})),
                },
                subscription_run_id=str(self._current_subscription_run_id() or ""),
                sid=int(getattr(subscribe, "id", 0) or 0),
                subscription_level=True,
                trace_id=stable_trace_id("inbox-miss", getattr(subscribe, "id", 0)),
            )
            self._plugin_log("INFO", "%s", format_diag_log(diag, media=str(getattr(subscribe, "name", ""))))
            return None
        promoted = []
        for hit in hits[:20]:
            entry = hit.get("entry") or convert_inbox_row_to_entry(hit.get("row") or {})
            promoted.append(entry)
            self._resource_trace_v209(
                entry=entry,
                state="MATCHED",
                reason=str(hit.get("reason") or "inbox_match"),
                matched_sid=int(getattr(subscribe, "id", 0) or 0),
            )
        if promoted:
            self._merge_inbox_entries_into_channel_index_v209(promoted)
            try:
                return dict(super()._try_transfer_subscription_inner(
                    subscribe, force=False, refresh_channel=False,
                ) or {})
            except Exception as err:
                return {
                    "success": False,
                    "handled": True,
                    "message": f"Inbox 已命中但转存入口异常：{str(err)[:160]}",
                    "diag": make_diag(
                        state="FAILED_RETRYABLE",
                        reason_code="TRANSFER_FAILED",
                        stage="SUBMIT",
                        message=str(err)[:200],
                    ),
                }
        return None

    def _merge_inbox_entries_into_channel_index_v209(self, entries: List[Dict[str, Any]]) -> int:
        if not entries:
            return 0
        index = dict(self.get_data("channel_index") or {})
        items = list(index.get("items") or [])
        store = self.get_data(_INBOX_KEY) or {}
        merged = union_legacy_and_inbox_entries(items + list(entries), store if isinstance(store, dict) else {})
        index["items"] = merged
        index["effective_count"] = len(merged)
        index["inbox_merged_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.save_data("channel_index", index)
        return len(merged)

    def _trace_transfer_result_v209(self, subscribe: Any, result: Dict[str, Any]) -> None:
        sid = int(getattr(subscribe, "id", 0) or 0)
        run_id = str(
            result.get("subscription_run_id")
            or self._current_subscription_run_id()
            or make_subscription_run_id(sid, "trace", 0)
        )
        result["subscription_run_id"] = run_id

        candidate_diags = result.get("candidate_diags") if isinstance(result.get("candidate_diags"), list) else None
        if not candidate_diags:
            candidate_diags = self._snapshot_candidate_diags_v209()
        else:
            candidate_diags = dedup_candidate_diags(candidate_diags)
        if candidate_diags:
            result["candidate_diags"] = candidate_diags

        result_diag = result.get("diag") if isinstance(result.get("diag"), dict) else None
        diag = finalize_subscription_diag(
            candidate_diags=candidate_diags,
            result_diag=result_diag,
            result=result,
            subscribe=subscribe,
        )

        carried = str(
            result.get("resource_trace_id")
            or (result.get("entry") or {}).get("resource_trace_id")
            or diag.get("resource_trace_id")
            or diag.get("trace_id")
            or ""
        ).strip()
        if not carried and candidate_diags:
            for row in candidate_diags:
                carried = str((row or {}).get("resource_trace_id") or (row or {}).get("trace_id") or "").strip()
                if carried:
                    break
        diag = enrich_diag(
            diag,
            subscription_run_id=run_id,
            resource_trace_id=carried,
            sid=sid,
        )
        result["diag"] = diag
        if carried:
            result["resource_trace_id"] = carried
        elif diag.get("resource_trace_id"):
            result["resource_trace_id"] = diag["resource_trace_id"]
        self._plugin_log("INFO", "%s", format_diag_log(diag, media=str(getattr(subscribe, "name", ""))))
        entry = {
            "title": getattr(subscribe, "name", ""),
            "message_id": str(result.get("message_id") or "-"),
            "resource_trace_id": str(result.get("resource_trace_id") or diag.get("resource_trace_id") or ""),
            "source_url": str(result.get("source_url") or ""),
        }
        self._resource_trace_v209(
            entry=entry,
            state=str(diag.get("state") or "FAILED"),
            reason=f"{diag.get('reason_code')}|{diag.get('message')}",
            matched_sid=sid,
        )
        record = getattr(self, "_record_transfer_diag_v209", None)
        if callable(record):
            try:
                record(subscribe, diag, final=True)
            except TypeError:
                try:
                    record(subscribe, diag)
                except Exception:
                    pass
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Resource lifecycle trace
    # ------------------------------------------------------------------
    def _resource_trace_id_v209(self, entry: Dict[str, Any]) -> str:
        existing = str(entry.get("resource_trace_id") or entry.get("trace_id") or "").strip()
        if existing:
            return existing
        channel = str(entry.get("source_url") or entry.get("channel") or "")
        message_id = str(entry.get("message_id") or "")
        group_id = str(entry.get("resource_group_id") or entry.get("inbox_id") or "")
        if message_id or group_id:
            return stable_trace_id(channel, message_id, group_id)
        identities = []
        if entry.get("share_url"):
            identities.append(str(entry.get("share_url")))
        for item in entry.get("xunlei_sources") or []:
            identities.append(str((item or {}).get("url") or (item or {}).get("uri") or ""))
        for item in entry.get("external_sources") or []:
            identities.append(str((item or {}).get("uri") or (item or {}).get("identity") or ""))
        return stable_trace_id(channel, *identities)

    def _resource_trace_v209(
        self,
        *,
        entry: Dict[str, Any],
        state: str,
        reason: str,
        matched_sid: Any = None,
        candidates: Optional[Iterable[str]] = None,
    ) -> None:
        trace_id = self._resource_trace_id_v209(entry)
        title = str(entry.get("display_title") or entry.get("title") or entry.get("match_title") or "")[:160]
        channel = str(entry.get("source_url") or entry.get("channel") or "")[-60:]
        message_id = str(entry.get("message_id") or "-")
        cand = list(candidates or entry.get("candidate_types") or [])
        if not cand:
            if entry.get("share_url"):
                cand.append("guangya")
            if entry.get("xunlei_sources"):
                cand.append("xunlei")
            for item in entry.get("external_sources") or []:
                kind = str((item or {}).get("type") or "")
                if kind:
                    cand.append(kind)
        safe_reason = str(reason or "-")[:220]
        for banned in ("pwd=", "passcode=", "password=", "cookie=", "token="):
            if banned in safe_reason.lower():
                safe_reason = safe_reason.lower().split(banned)[0] + "passcode_present=true"
                break
        self._plugin_log(
            "INFO",
            "【频道资源追踪】trace=%s channel=%s message_id=%s title=%s candidates=%s matched_sid=%s state=%s reason=%s",
            trace_id[:120],
            channel or "-",
            message_id,
            title or "-",
            ",".join(str(v) for v in cand) or "-",
            matched_sid if matched_sid not in (None, "") else "-",
            state,
            safe_reason,
        )
        lock = getattr(self, "_resource_trace_lock_v209", None) or threading.RLock()
        self._resource_trace_lock_v209 = lock
        with lock:
            try:
                store = self.get_data("channel_resource_trace_v209") or {}
            except Exception:
                return
            if not isinstance(store, dict):
                store = {}
            items = list(store.get("items") or [])
            items.append({
                "trace": trace_id,
                "channel": channel,
                "message_id": message_id,
                "title": title,
                "candidates": cand,
                "matched_sid": matched_sid,
                "state": state,
                "reason": safe_reason,
                "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            })
            if len(items) > int(self._resource_trace_max_v209):
                items = items[-int(self._resource_trace_max_v209):]
            store["items"] = items
            store["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            try:
                self.save_data("channel_resource_trace_v209", store)
            except Exception:
                pass

    def get_resource_trace(self, resource_id: str = "") -> Dict[str, Any]:
        """Debug API: fetch resource lifecycle traces (no secrets)."""
        store = self.get_data("channel_resource_trace_v209") or {}
        items = list((store or {}).get("items") or [])
        rid = str(resource_id or "").strip()
        if rid:
            items = [
                row for row in items
                if rid in str(row.get("trace") or "") or rid == str(row.get("message_id") or "")
            ]
        return {"count": len(items), "items": items[-200:], "updated_at": (store or {}).get("updated_at")}

    # ------------------------------------------------------------------
    # RAW HTML → Inbox (before legacy) + effective union
    # ------------------------------------------------------------------
    def _channel_slug_from_source_v209(self, source_url: str) -> str:
        try:
            path = (urlparse(str(source_url or "")).path or "").strip("/")
        except Exception:
            path = ""
        return path.split("/")[0] if path else str(source_url or "")[-40:]

    def _ingest_raw_channel_page_v209(self, page_html: str, source_url: str, source_label: str = "") -> Dict[str, Any]:
        """Split messages → extract → upsert Inbox BEFORE legacy parser runs.

        Returns structured page result used by legacy cursor/event bridge.
        """
        generation = str(getattr(self, "_scan_generation_v209", "") or "")
        if not generation:
            generation = f"gen-{int(time.time() * 1000)}"
            self._scan_generation_v209 = generation
        blocks = extract_channel_message_blocks_v209(page_html, source_url)
        rows = []
        actionable = 0
        message_ids: List[int] = []
        for block in blocks:
            mid = str(block.get("message_id") or "")
            if mid.isdigit():
                message_ids.append(int(mid))
            row = build_inbox_row_from_message_block(block)
            row["scan_generation"] = generation
            if row.get("candidates") or row.get("other_urls"):
                rows.append(row)
            if row.get("candidates"):
                actionable += 1
                entry = convert_inbox_row_to_entry(row)
                self._resource_trace_v209(
                    entry=entry,
                    state="CACHED",
                    reason="raw_html_before_legacy",
                    candidates=[str(c.get("type") or "") for c in row.get("candidates") or []],
                )
            elif blocks and page_has_resource_features_v209(block.get("raw_html") or ""):
                self._plugin_log(
                    "INFO",
                    "%s",
                    format_diag_log(
                        make_diag(
                            state="NO_RESULT",
                            reason_code="CHANNEL_NO_ACTIONABLE_URL",
                            stage="DISCOVERY",
                            source=self._channel_slug_from_source_v209(source_url),
                            message="未发现支持的资源链接",
                            evidence={
                                "channel": block.get("channel"),
                                "message_id": block.get("message_id"),
                                "checked": "visible,href,data,clipboard,onclick,json,wrapped",
                                "other_urls": len(row.get("other_urls") or []),
                            },
                            next_action="保留消息至Inbox，等待解析器升级",
                            trace_id=str(row.get("resource_trace_id") or stable_trace_id(block.get("channel"), block.get("message_id"))),
                        ),
                        media=str(row.get("match_title") or row.get("raw_title") or ""),
                    ),
                )
        stats = summarize_page_extract_stats_v209(blocks, rows)
        new_rows: List[Dict[str, Any]] = []
        updated_rows: List[Dict[str, Any]] = []
        if rows:
            try:
                store = self.get_data(_INBOX_KEY) or {}
                updated = upsert_inbox_rows(store if isinstance(store, dict) else {}, rows)
                self.save_data(_INBOX_KEY, updated)
                new_rows = list((updated or {}).get("new_rows") or [])
                updated_rows = list((updated or {}).get("updated_rows") or [])
            except Exception as err:
                self._plugin_log(
                    "WARNING",
                    "%s",
                    format_diag_log(
                        make_diag(
                            state="FAILED_RETRYABLE",
                            reason_code="INBOX_WRITE_FAILED",
                            stage="CACHE",
                            message=f"频道资源已发现但临时资源库写入失败：{str(err)[:160]}",
                            source=self._channel_slug_from_source_v209(source_url),
                        )
                    ),
                )
                raise
        # Features present but zero actionable resources → suspect (legacy also checks).
        parse_suspect = bool(
            blocks and actionable <= 0 and page_has_resource_features_v209(page_html)
        )
        if parse_suspect:
            self._channel_parse_suspect_v209 = True
        max_message_id = max(message_ids) if message_ids else 0
        # Convert ALL actionable page rows to entries for legacy merge (dedup later).
        page_entries = [
            convert_inbox_row_to_entry(row)
            for row in rows
            if row.get("candidates")
        ]
        for entry in page_entries:
            entry["source_url"] = str(source_url or entry.get("source_url") or "")
            entry["source_label"] = str(source_label or entry.get("source_label") or "")
            entry["stale"] = False
            entry["cached_index"] = False
            entry["origin"] = entry.get("origin") or "inbox"
        channel = self._channel_slug_from_source_v209(source_url) or source_label
        self._plugin_log(
            "INFO",
            "【频道原始解析】channel=%s http=local bytes=%s messages=%s guangya=%s xunlei=%s magnet=%s ed2k=%s "
            "unsupported_115=%s hidden_href=%s clipboard=- onclick=- visible=%s inbox_new=%s",
            channel,
            len(str(page_html or "").encode("utf-8", "ignore")),
            stats.get("messages"),
            stats.get("guangya"),
            stats.get("xunlei"),
            stats.get("magnet"),
            stats.get("ed2k"),
            stats.get("other"),
            stats.get("hidden"),
            stats.get("visible"),
            len(new_rows),
        )
        return {
            "channel": channel,
            "stats": stats,
            "new_rows": new_rows,
            "updated_rows": updated_rows,
            "all_rows": rows,
            "entries": page_entries,
            "max_message_id": max_message_id,
            "message_ids": message_ids,
            "parse_suspect": parse_suspect,
            "actionable": actionable,
            "scan_generation": generation,
        }

    def _inbox_dual_write_entries_v209(self, entries: List[Dict[str, Any]]) -> int:
        """Compatibility: also absorb legacy-only entries into Inbox (origin=legacy)."""
        rows = []
        for entry in entries or []:
            if not isinstance(entry, dict):
                continue
            row = build_inbox_row_from_entry(entry)
            if row.get("candidates"):
                rows.append(row)
        if not rows:
            return 0
        store = self.get_data(_INBOX_KEY) or {}
        updated = upsert_inbox_rows(store if isinstance(store, dict) else {}, rows)
        self.save_data(_INBOX_KEY, updated)
        return len(rows)

    def _shadow_inbox_compare_v209(self, subscribe: Any, result: Dict[str, Any]) -> None:
        try:
            from .legacy import _entry_match_reason
        except Exception:
            return
        store = self.get_data(_INBOX_KEY) or {}
        inbox_hits = shadow_match_inbox_for_subscribe(store, subscribe, _entry_match_reason)
        old_matched = bool(result.get("success") or result.get("already") or result.get("completed"))
        message = str(result.get("message") or "")
        old_miss = "暂未匹配" in message or "没有新链接" in message or not old_matched
        if inbox_hits and old_miss:
            hit = inbox_hits[0]
            row = hit.get("row") or {}
            self._plugin_log(
                "WARNING",
                "【Resource Inbox】【发现旧链漏资源】sid=%s media=%s channel=%s message_id=%s candidate_types=%s extractor=%s",
                int(getattr(subscribe, "id", 0) or 0),
                getattr(subscribe, "name", ""),
                str(row.get("channel") or "")[-60:],
                str(row.get("message_id") or "-"),
                ",".join(str(c.get("type") or "") for c in (row.get("candidates") or [])) or "-",
                ",".join(str(c.get("extractor") or "") for c in (row.get("candidates") or []) if c.get("extractor")) or "-",
            )

    def refresh_channels(self, force: bool = False):
        """RAW Inbox-first (via per-page hook) then legacy; union into effective channel_index."""
        self._scan_generation_v209 = f"gen-{int(time.time() * 1000)}"
        result = super().refresh_channels(force=force)
        try:
            index = dict(self.get_data("channel_index") or {})
            legacy_items = list(index.get("items") or [])
            if legacy_items:
                self._inbox_dual_write_entries_v209(legacy_items)
            store = self.get_data(_INBOX_KEY) or {}
            effective = union_legacy_and_inbox_entries(
                legacy_items,
                store if isinstance(store, dict) else {},
            )
            index["items"] = effective
            index["legacy_count"] = len(legacy_items)
            index["effective_count"] = len(effective)
            index["inbox_count"] = int((store or {}).get("count") or len((store or {}).get("items") or {}))
            self.save_data("channel_index", index)
            by_channel: Dict[str, Dict[str, int]] = {}
            for row in ((store or {}).get("items") or {}).values():
                if not isinstance(row, dict):
                    continue
                ch = str(row.get("channel") or row.get("source_url") or "-")[-40:]
                bucket = by_channel.setdefault(ch, {
                    "resource_groups": 0, "guangya": 0, "xunlei": 0,
                    "magnet": 0, "ed2k": 0, "other": 0, "hidden": 0, "visible": 0,
                })
                bucket["resource_groups"] += 1
                for cand in row.get("candidates") or []:
                    kind = str(cand.get("type") or "")
                    if kind in bucket:
                        bucket[kind] += 1
                    extractor = str(cand.get("extractor") or "")
                    if extractor in {"clipboard", "data", "onclick", "javascript", "json", "wrapped_redirect"}:
                        bucket["hidden"] += 1
                    elif extractor in {"href", "visible_text"}:
                        bucket["visible"] += 1
                bucket["other"] += len(row.get("other_urls") or [])
            for channel, bucket in list(by_channel.items())[:12]:
                self._plugin_log(
                    "INFO",
                    "【频道资源统计】channel=%s pages=- messages=- resource_groups=%s guangya=%s xunlei=%s "
                    "magnet=%s ed2k=%s other=%s hidden=%s visible=%s inbox_new=- inbox_updated=- "
                    "legacy_entries=%s effective_entries=%s",
                    channel,
                    bucket.get("resource_groups"),
                    bucket.get("guangya"),
                    bucket.get("xunlei"),
                    bucket.get("magnet"),
                    bucket.get("ed2k"),
                    bucket.get("other"),
                    bucket.get("hidden"),
                    bucket.get("visible"),
                    len(legacy_items),
                    len(effective),
                )
            return effective if effective else result
        except Exception as err:
            self._plugin_log("WARNING", "【Resource Inbox】union/refresh 异常：%s", str(err)[:220])
            return result
        finally:
            self._scan_generation_v209 = ""


__all__ = [
    "GuangYaFoundationOpsV209Mixin",
    "extract_message_resource_candidates_v209",
]
