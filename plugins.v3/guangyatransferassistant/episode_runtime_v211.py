"""2.0.11-r95 P0：Episode Runtime Architecture — observation ≠ receipt ≠ reservation.

Breaks Library→Receipt→Missing→Target recursion; migrates polluted library-origin
facts; AiringDue host heartbeat + runtime fallback singleflight; empty-target submit gate.
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterable, Iterator, List, Optional, Set, Tuple


_LIBRARY_ORIGINS = frozenset({
    "library", "emby", "mediaserver", "scan", "media_library", "library_observation",
})
_MIGRATION_MARKER = "episode_facts_migration_v211"
_ACTIVE_INFLIGHT_STATES = frozenset({
    "new", "dispatching", "queued", "submitted", "waiting", "verifying",
    "task_confirmed", "retry", "pending", "running",
})
_TLS = threading.local()


def _positive(values: Any) -> Set[int]:
    out: Set[int] = set()
    for raw in values or []:
        try:
            episode = int(raw)
        except (TypeError, ValueError):
            continue
        if episode > 0:
            out.add(episode)
    return out


def _is_library_origin(origin: Any) -> bool:
    text = str(origin or "").strip().lower()
    if not text:
        return False
    if text in _LIBRARY_ORIGINS:
        return True
    return any(token in text for token in ("library", "emby", "mediaserver", "scan"))


def _context_stack() -> List[Dict[str, Any]]:
    stack = getattr(_TLS, "episode_run_contexts", None)
    if not isinstance(stack, list):
        stack = []
        _TLS.episode_run_contexts = stack
    return stack


class GuangYaEpisodeRuntimeV211Mixin:
    """Runtime supervisor + claim lifecycle + migration + empty-target hard gate."""

    _airing_fallback_stale_seconds_v211 = 15 * 60

    def init_plugin(self, config: dict = None) -> None:
        # Runtime structures BEFORE super() so workers cannot race into facts builders.
        self._episode_runtime_ready_v211 = False
        self._airing_due_lock_v211 = threading.RLock()
        self._airing_due_running_v211 = False
        self._airing_due_owner_v211 = ""
        self._airing_due_cycle_v211 = 0
        self._host_airing_heartbeat_v211 = 0.0
        self._episode_snapshot_tls_v211 = threading.local()
        self._airing_cycle_state_v211: Dict[str, Any] = {}
        if hasattr(self, "_library_sync_reuse_v211"):
            try:
                delattr(self, "_library_sync_reuse_v211")
            except Exception:
                self._library_sync_reuse_v211 = None
        super().init_plugin(config=config)
        self._migrate_library_observation_facts_v211_once()
        self._reopen_library_polluted_superseded_sources_v211()
        self._episode_runtime_ready_v211 = True

    def _episode_runtime_is_ready_v211(self) -> bool:
        return bool(getattr(self, "_episode_runtime_ready_v211", False))

    # ------------------------------------------------------------------
    # AiringDueCycleContext — selector snapshot → transfer reuse
    # ------------------------------------------------------------------
    def _airing_cycle_ensure_v211(self, cycle: int, owner: str) -> Dict[str, Any]:
        state = {
            "cycle_id": int(cycle or 0),
            "owner": str(owner or ""),
            "started_at": time.time(),
            "phase": "select",
            "per_sid": {},
        }
        self._airing_cycle_state_v211 = state
        return state

    def _airing_cycle_current_v211(self) -> Optional[Dict[str, Any]]:
        state = getattr(self, "_airing_cycle_state_v211", None)
        return state if isinstance(state, dict) and state.get("cycle_id") else None

    def _airing_cycle_clear_v211(self) -> None:
        self._airing_cycle_state_v211 = {}

    def _airing_cycle_store_seed_v211(
        self,
        subscribe: Any,
        ctx: Dict[str, Any],
        *,
        gate_result: Optional[Dict[str, Any]] = None,
    ) -> None:
        state = self._airing_cycle_current_v211()
        if not state:
            return
        sid = int(getattr(subscribe, "id", 0) or 0)
        if sid <= 0:
            return
        cycle = int(state.get("cycle_id") or 0)
        seed = dict(ctx or {})
        run_id = str(seed.get("run_id") or "") or f"run:#{sid}:airing:{cycle}"
        seed["run_id"] = run_id
        seed["sid"] = sid
        try:
            seed["season"] = int(getattr(subscribe, "season", 0) or 0)
        except (TypeError, ValueError):
            seed["season"] = 0
        if isinstance(gate_result, dict):
            seed["gate_result"] = dict(gate_result)
            seed["final_target"] = list(gate_result.get("final_target") or seed.get("final_target") or [])
            seed["mp_missing"] = list(gate_result.get("mp_missing") or seed.get("mp_missing") or [])
        seed["selector_done"] = True
        state.setdefault("per_sid", {})[sid] = seed

    def _airing_cycle_seed_for_subscribe_v211(self, subscribe: Any) -> Optional[Dict[str, Any]]:
        state = self._airing_cycle_current_v211()
        if not state:
            return None
        sid = int(getattr(subscribe, "id", 0) or 0)
        row = (state.get("per_sid") or {}).get(sid)
        return dict(row) if isinstance(row, dict) else None

    def _airing_cycle_cached_gate_v211(self, subscribe: Any) -> Optional[Dict[str, Any]]:
        """Second gate call in same AiringDue cycle returns selector result (no Emby #2)."""
        seed = self._airing_cycle_seed_for_subscribe_v211(subscribe)
        if not seed or not seed.get("selector_done"):
            return None
        gate = seed.get("gate_result")
        return dict(gate) if isinstance(gate, dict) else None

    def _begin_subscription_run_v209(self, subscribe: Any) -> str:
        """Stable run:#<sid>:airing:<cycle> while AiringDue cycle is active."""
        state = self._airing_cycle_current_v211()
        if state and bool(getattr(self, "_airing_due_running_v211", False)):
            sid = int(getattr(subscribe, "id", 0) or 0)
            cycle = int(state.get("cycle_id") or 0)
            seed = (state.get("per_sid") or {}).get(sid) or {}
            run_id = str(seed.get("run_id") or "") or f"run:#{sid}:airing:{cycle}"
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
            self._current_subscription_run_id_v209 = run_id
            self._current_subscription_candidate_diags_v209 = tls.candidate_diags
            return run_id
        return super()._begin_subscription_run_v209(subscribe)

    def _mp_authoritative_missing_episodes_v209(self, subscribe: Any):
        """Cache MP missing once per EpisodeFactsContext / AiringDue sid seed."""
        ctx = self._episode_run_context_for_subscribe_v211(subscribe)
        if ctx is not None and ctx.get("mp_missing_resolved"):
            return str(ctx.get("mp_missing_state") or "used_missing"), set(
                int(v) for v in (ctx.get("mp_missing") or []) if int(v or 0) > 0
            )
        seed = self._airing_cycle_seed_for_subscribe_v211(subscribe)
        if seed and seed.get("mp_missing_resolved"):
            return str(seed.get("mp_missing_state") or "used_missing"), set(
                int(v) for v in (seed.get("mp_missing") or []) if int(v or 0) > 0
            )
        source, missing = super()._mp_authoritative_missing_episodes_v209(subscribe)
        payload = {
            "mp_missing_resolved": True,
            "mp_missing_state": str(source or ""),
            "mp_missing": sorted(int(v) for v in (missing or set()) if int(v or 0) > 0),
        }
        if ctx is not None:
            ctx.update(payload)
            ctx["mp_resolve_count"] = int(ctx.get("mp_resolve_count") or 0) + 1
        if seed is not None:
            seed.update(payload)
            state = self._airing_cycle_current_v211()
            if state:
                sid = int(getattr(subscribe, "id", 0) or 0)
                state.setdefault("per_sid", {})[sid] = seed
        return source, set(missing or set())

    def _gying_raw_results(self, keyword: str, force: bool = False):
        """One business-level GYING search per run+keyword+targets (HTTP may still multi-hit)."""
        ctx = self._current_episode_run_context_v211()
        key = None
        if ctx is not None:
            targets = tuple(sorted(int(v) for v in (ctx.get("final_target") or []) if int(v or 0) > 0))
            key = (str(ctx.get("run_id") or ""), str(keyword or "").strip(), targets)
            cache = ctx.setdefault("gying_search_cache", {})
            if key in cache and not force:
                rows, state = cache[key]
                self._plugin_log(
                    "INFO",
                    "【观影】搜索结果复用 run=%s keyword=%s target=%s result_count=%s",
                    key[0] or "-",
                    key[1][:80] or "-",
                    ",".join(f"E{v:02d}" for v in targets) or "-",
                    len(rows or []),
                )
                return list(rows or []), dict(state or {})
        rows, state = super()._gying_raw_results(keyword, force=force)
        if ctx is not None and key is not None:
            ctx.setdefault("gying_search_cache", {})[key] = (list(rows or []), dict(state or {}))
            ctx["gying_business_search_count"] = int(ctx.get("gying_business_search_count") or 0) + 1
        return rows, state

    def _try_transfer_subscription(self, subscribe: Any, force: bool = False, refresh_channel: bool = True):
        """Re-enter selector EpisodeFactsContext for the same AiringDue cycle."""
        if not self._episode_runtime_is_ready_v211():
            return {"success": False, "handled": False, "message": "episode_runtime_not_ready"}
        seed = self._airing_cycle_seed_for_subscribe_v211(subscribe)
        if seed:
            state = self._airing_cycle_current_v211() or {}
            if state:
                state["phase"] = "transfer"
            run_id = str(seed.get("run_id") or "")
            with self._episode_run_context_scope_v211(subscribe, run_id=run_id, seed=seed):
                return super()._try_transfer_subscription(
                    subscribe, force=force, refresh_channel=refresh_channel,
                )
        return super()._try_transfer_subscription(
            subscribe, force=force, refresh_channel=refresh_channel,
        )

    # ------------------------------------------------------------------
    # Per-run EpisodeFactsContext (thread-local — never instance-shared)
    # ------------------------------------------------------------------
    def _run_id_v210(self) -> str:
        ctx = self._current_episode_run_context_v211()
        if isinstance(ctx, dict) and str(ctx.get("run_id") or "").strip():
            return str(ctx.get("run_id") or "")
        return super()._run_id_v210()

    def _current_episode_run_context_v211(self) -> Optional[Dict[str, Any]]:
        stack = _context_stack()
        return stack[-1] if stack else None

    def _episode_run_context_for_subscribe_v211(self, subscribe: Any) -> Optional[Dict[str, Any]]:
        ctx = self._current_episode_run_context_v211()
        if not ctx:
            return None
        sid = int(getattr(subscribe, "id", 0) or 0)
        try:
            season = int(getattr(subscribe, "season", 0) or 0)
        except (TypeError, ValueError):
            season = 0
        if int(ctx.get("sid") or 0) != sid or int(ctx.get("season") or 0) != season:
            return None
        return ctx

    @contextmanager
    def _episode_run_context_scope_v211(
        self,
        subscribe: Any,
        *,
        run_id: str = "",
        seed: Optional[Dict[str, Any]] = None,
    ) -> Iterator[Dict[str, Any]]:
        # Never nest a second context for the same sid/season — that shadows library_sync
        # and forces Emby #2 during transfer.
        existing = self._episode_run_context_for_subscribe_v211(subscribe)
        if existing is not None:
            if isinstance(seed, dict):
                if existing.get("library_sync") is None and isinstance(seed.get("library_sync"), dict):
                    existing["library_sync"] = dict(seed.get("library_sync") or {})
                if not existing.get("run_id") and seed.get("run_id"):
                    existing["run_id"] = str(seed.get("run_id") or "")
                if existing.get("final_target") is None and seed.get("final_target") is not None:
                    existing["final_target"] = list(seed.get("final_target") or [])
            yield existing
            return
        sid = int(getattr(subscribe, "id", 0) or 0)
        try:
            season = int(getattr(subscribe, "season", 0) or 0)
        except (TypeError, ValueError):
            season = 0
        rid = str(run_id or "")
        if not rid and isinstance(seed, dict):
            rid = str(seed.get("run_id") or "")
        if not rid:
            try:
                rid = str(self._run_id_v210() or "")
            except Exception:
                rid = ""
        ctx: Dict[str, Any] = {
            "run_id": rid,
            "sid": sid,
            "season": season,
            "emby_query_count": 0,
            "mp_missing_related_library_calls": 0,
            "post_transfer_calls": 0,
            "library_sync": None,
            "snapshot": None,
        }
        if isinstance(seed, dict):
            ctx.update(seed)
            ctx["sid"] = sid
            ctx["season"] = season
            if rid:
                ctx["run_id"] = rid
        stack = _context_stack()
        stack.append(ctx)
        try:
            yield ctx
        finally:
            if stack and stack[-1] is ctx:
                stack.pop()
            elif ctx in stack:
                stack.remove(ctx)

    def _sync_media_library_progress(self, subscribe: Any) -> Dict[str, Any]:
        """One initial Emby sync per run/cycle; nested callers reuse context or cycle seed."""
        ctx = self._episode_run_context_for_subscribe_v211(subscribe)
        if ctx is not None:
            cached = ctx.get("library_sync")
            if isinstance(cached, dict):
                return dict(cached)
        seed = self._airing_cycle_seed_for_subscribe_v211(subscribe)
        if isinstance(seed, dict):
            cached = seed.get("library_sync")
            if isinstance(cached, dict):
                if ctx is not None:
                    ctx["library_sync"] = dict(cached)
                    ctx["library_state"] = str(seed.get("library_state") or ("OK" if cached.get("success") else "UNKNOWN"))
                    ctx["library_existing"] = list(seed.get("library_existing") or cached.get("existing") or [])
                    ctx["library_gap"] = list(seed.get("library_gap") or cached.get("missing") or [])
                return dict(cached)
        sync = dict(super()._sync_media_library_progress(subscribe) or {})
        if ctx is not None:
            ctx["library_sync"] = dict(sync)
            ctx["emby_query_count"] = int(ctx.get("emby_query_count") or 0) + 1
            ctx["library_state"] = "OK" if bool(sync.get("success")) else "UNKNOWN"
            ctx["library_existing"] = list(sync.get("existing") or [])
            ctx["library_gap"] = list(sync.get("missing") or [])
        if isinstance(seed, dict) and seed.get("library_sync") is None and bool(sync.get("success")):
            seed["library_sync"] = dict(sync)
            state = self._airing_cycle_current_v211()
            if state:
                sid = int(getattr(subscribe, "id", 0) or 0)
                state.setdefault("per_sid", {})[sid] = seed
        return sync

    def _remember_library_sync_in_context_v211(self, subscribe: Any, sync: Dict[str, Any]) -> None:
        ctx = self._episode_run_context_for_subscribe_v211(subscribe)
        if ctx is None or not isinstance(sync, dict):
            return
        if ctx.get("library_sync") is None:
            ctx["library_sync"] = dict(sync)
            ctx["emby_query_count"] = max(1, int(ctx.get("emby_query_count") or 0))
            ctx["library_state"] = "OK" if bool(sync.get("success")) else "UNKNOWN"
            ctx["library_existing"] = list(sync.get("existing") or [])
            ctx["library_gap"] = list(sync.get("missing") or [])

    # ------------------------------------------------------------------
    # Persisted data migration (r95 pollution)
    # ------------------------------------------------------------------
    def _migrate_library_observation_facts_v211_once(self) -> None:
        marker = self.get_data(_MIGRATION_MARKER) or {}
        if isinstance(marker, dict) and bool(marker.get("done")):
            return
        facts = self.get_data("media_facts") or {}
        if not isinstance(facts, dict):
            facts = {}
        removed = 0
        preserved = 0
        scanned = 0
        cleaned: Dict[str, Any] = {}
        for key, row in list(facts.items()):
            scanned += 1
            origin = ""
            if isinstance(row, dict):
                origin = str(row.get("origin") or "")
            if _is_library_origin(origin):
                removed += 1
                continue
            cleaned[key] = row
            if origin:
                preserved += 1
        if removed:
            self.save_data("media_facts", cleaned)
        self.save_data(
            _MIGRATION_MARKER,
            {
                "done": True,
                "at": time.time(),
                "version": str(getattr(self, "plugin_version", "") or ""),
                "build": str(getattr(self, "build_id", "") or ""),
                "scanned": scanned,
                "removed_library_observations": removed,
                "preserved_transfer_receipts": preserved,
            },
        )
        self._plugin_log(
            "INFO",
            "【EpisodeFacts迁移】scanned=%s removed_library_observations=%s "
            "preserved_transfer_receipts=%s version=%s build=%s",
            scanned,
            removed,
            preserved,
            str(getattr(self, "plugin_version", "") or "-"),
            str(getattr(self, "build_id", "") or "-"),
        )

    def _reopen_library_polluted_superseded_sources_v211(self) -> int:
        """Reopen sources wrongly superseded by r95 library-as-receipt pollution."""
        marker = self.get_data("episode_supersede_reopen_v211") or {}
        if isinstance(marker, dict) and bool(marker.get("done")):
            return int(marker.get("reopened") or 0)
        reopened = 0
        try:
            items = dict((self._source_store() or {}).get("items") or {})
        except Exception:
            items = {}
        for source_id, row in list(items.items()):
            if not isinstance(row, dict) or not bool(row.get("superseded_by_receipt")):
                continue
            reason = str(row.get("superseded_reason") or "").lower()
            state = str(row.get("state") or "").strip().lower()
            libraryish = any(token in reason for token in ("library", "emby", "mediaserver", "scan"))
            transferish = any(
                token in reason for token in ("guangya", "xunlei", "magnet", "ed2k", "offline", "viewing", "flash")
            )
            if transferish and not libraryish:
                continue
            if state not in {"disabled", "superseded", "completed", "failed"} and not libraryish:
                continue
            if not libraryish and not reason:
                # Unknown supersede reason with receipt flag — reopen conservatively when disabled.
                if state not in {"disabled", "superseded"}:
                    continue
            try:
                self._update_source(
                    str(source_id),
                    state="new",
                    enabled=True,
                    auto_dispatch=True,
                    superseded_by_receipt=False,
                    superseded_episodes=[],
                    superseded_reason="",
                    next_retry_at=0,
                    reopen_reason="r95_library_receipt_pollution",
                )
                reopened += 1
            except Exception:
                continue
        self.save_data(
            "episode_supersede_reopen_v211",
            {"done": True, "at": time.time(), "reopened": reopened},
        )
        if reopened:
            self._plugin_log(
                "INFO",
                "【EpisodeFacts迁移】reopened_superseded_sources=%s reason=r95_library_receipt_pollution",
                reopened,
            )
        return reopened

    # ------------------------------------------------------------------
    # Claims: NEVER call subscription_missing (breaks Target↔Claim recursion)
    # ------------------------------------------------------------------
    def _active_inflight_claims_v211(self, subscribe_id: int, current_source_id: str = "") -> Set[int]:
        claims: Set[int] = set()
        sid = int(subscribe_id or 0)
        if sid <= 0:
            return claims
        try:
            items = (self._source_store().get("items") or {}).values()
        except Exception:
            return claims
        for row in items:
            if not isinstance(row, dict) or int(row.get("subscribe_id") or 0) != sid:
                continue
            if current_source_id and str(row.get("id") or "") == str(current_source_id):
                continue
            if not bool(row.get("enabled", True)):
                continue
            state = str(row.get("state") or "").strip().lower()
            # completed is NOT an active claim — pending_library owns short protection.
            if state not in _ACTIVE_INFLIGHT_STATES:
                continue
            eps: Set[int] = set()
            for key in ("resolved_episodes", "transfer_episodes", "target_episodes", "episodes"):
                for raw in row.get(key) or []:
                    try:
                        value = int(raw)
                    except (TypeError, ValueError):
                        continue
                    if value > 0:
                        eps.add(value)
                if eps:
                    break
            if eps:
                claims |= eps
        return claims

    def _active_source_claims(self, subscribe_id: int) -> Set[int]:
        return self._active_inflight_claims_v211(subscribe_id)

    def _effective_source_claims_v11222(self, subscribe_id: int, current_source_id: str = "") -> Set[int]:
        return self._active_inflight_claims_v211(subscribe_id, current_source_id=current_source_id)

    def _planner_file_selection(
        self,
        source: Dict[str, Any],
        subscribe: Any,
        resolve_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Plan fileIndexes while excluding the current source from soft claims."""
        tls = getattr(self, "_episode_snapshot_tls_v211", None)
        if tls is None:
            tls = threading.local()
            self._episode_snapshot_tls_v211 = tls
        previous = getattr(tls, "planner_exclude_source_id", None)
        tls.planner_exclude_source_id = str((source or {}).get("id") or "")
        try:
            return super()._planner_file_selection(source, subscribe, resolve_data)
        finally:
            tls.planner_exclude_source_id = previous

    def _pending_reservations(self, subscribe: Any, exclude_job_key: str = "") -> Dict[str, Any]:
        """In-flight jobs only — do NOT union transfer-acquired / library existing."""
        base = dict(super()._pending_reservations(subscribe, exclude_job_key=exclude_job_key) or {})
        base["paths"] = set(base.get("paths") or set())
        # Strip fence's acquired union: reservation != receipt.
        # Keep only true in-flight episode reservations from jobs/sources.
        inflight = set(base.get("episodes") or set())
        # Recompute from transfer_jobs pending statuses only (legacy already does this).
        # Remove acquired that fence may have added.
        try:
            # Prefer job-derived episodes from parent base paths scan already present.
            # Drop anything that is only in acquired facts.
            acquired_fn = getattr(self, "_acquired_episode_facts_v1124", None)
            if callable(acquired_fn):
                acquired = set(acquired_fn(subscribe) or set())
                # Keep intersection with job episodes only — acquired alone must not reserve.
                job_eps = set()
                prefix = ""
                try:
                    prefix = self._media_fact_prefix(subscribe)
                except Exception:
                    prefix = ""
                pending_status = {"submitted", "task_confirmed", "verifying", "waiting", "queued", "dispatching"}
                for key, row in (self.get_data("transfer_jobs") or {}).items():
                    if str(key) == str(exclude_job_key or "") or not isinstance(row, dict):
                        continue
                    if prefix and str(row.get("media") or "") != prefix:
                        continue
                    if str(row.get("status") or "") not in pending_status:
                        continue
                    for raw in row.get("episodes") or []:
                        try:
                            job_eps.add(int(raw))
                        except (TypeError, ValueError):
                            continue
                # Also keep source inflight claims as soft reservation.
                # Exclude the source currently being planned/resolved (TLS), otherwise
                # a state=new row with target_episodes self-blocks Magnet/ED2K select.
                sid = int(getattr(subscribe, "id", 0) or 0)
                exclude_src = ""
                tls = getattr(self, "_episode_snapshot_tls_v211", None)
                if tls is not None:
                    exclude_src = str(getattr(tls, "planner_exclude_source_id", "") or "")
                job_eps |= self._active_inflight_claims_v211(sid, current_source_id=exclude_src)
                base["episodes"] = {int(v) for v in job_eps if int(v or 0) > 0}
                # Do not keep acquired-only reservations.
                _ = acquired
            else:
                base["episodes"] = {int(v) for v in inflight if int(v or 0) > 0}
        except Exception:
            base["episodes"] = {int(v) for v in (base.get("episodes") or set()) if int(v or 0) > 0}
        if self._is_movie_subscription(subscribe):
            try:
                base["movie"] = bool(base.get("movie"))
            except Exception:
                base["movie"] = False
        return base

    # ------------------------------------------------------------------
    # Empty final_target hard submit gate
    # ------------------------------------------------------------------
    def _final_target_allows_submit_v211(self, subscribe: Any, episodes: Iterable[int]) -> Tuple[bool, Set[int], str]:
        if self._is_movie_subscription(subscribe):
            return True, set(), "movie"
        snap_fn = getattr(self, "_episode_target_snapshot_v210", None)
        if not callable(snap_fn):
            return True, _positive(episodes), "no_snapshot"
        snap = snap_fn(subscribe, force_library=False, log=False)
        final = _positive(snap.get("final_target") or [])
        wanted = _positive(episodes)
        if not final:
            return False, set(), "empty_final_target"
        allowed = wanted.intersection(final) if wanted else final
        if wanted and not allowed:
            return False, set(), "episodes_outside_final_target"
        return True, allowed, "ok"

    def _submit_offline_source(self, source_id: str) -> Dict[str, Any]:
        """Hard gate Magnet/ED2K/GuangYa cloud submit when final_target is empty."""
        store = self._source_store()
        source = dict((store.get("items") or {}).get(str(source_id)) or {})
        subscribe = self._find_subscription(int(source.get("subscribe_id") or 0)) if source else None
        if subscribe and not self._is_movie_subscription(subscribe):
            episodes = _positive(source.get("resolved_episodes") or source.get("target_episodes") or [])
            ok, allowed, reason = self._final_target_allows_submit_v211(subscribe, episodes)
            if not ok:
                self._plugin_log(
                    "WARNING",
                    "【提交硬门禁】source=%s sid=%s reason=%s episodes=%s",
                    str(source_id),
                    int(getattr(subscribe, "id", 0) or 0),
                    reason,
                    sorted(episodes)[:40],
                )
                return {
                    "success": True,
                    "handled": True,
                    "skipped": True,
                    "reason": reason,
                    "message": f"empty final_target hard gate: {reason}",
                    "data": source,
                }
            if episodes and allowed and allowed != episodes:
                self._update_source(str(source_id), target_episodes=sorted(allowed), resolved_episodes=sorted(allowed))
        return super()._submit_offline_source(source_id)

    def _dispatch_xunlei_flash(self, subscribe: Any) -> Dict[str, Any]:
        """Hard gate Xunlei when final_target is empty."""
        if subscribe and not self._is_movie_subscription(subscribe):
            ok, allowed, reason = self._final_target_allows_submit_v211(subscribe, [])
            if not ok:
                self._plugin_log(
                    "INFO",
                    "【提交硬门禁】source=xunlei sid=%s reason=%s",
                    int(getattr(subscribe, "id", 0) or 0),
                    reason,
                )
                return {
                    "success": True,
                    "handled": True,
                    "priority": 0,
                    "shares": 0,
                    "attempted_files": 0,
                    "successful_files": 0,
                    "episodes": [],
                    "movie": False,
                    "errors": [],
                    "message": f"empty final_target hard gate: {reason}",
                    "reason": reason,
                }
            if not allowed and reason == "ok":
                # Gate asked for intersection with empty wanted → allowed=final; empty final already handled.
                pass
        return super()._dispatch_xunlei_flash(subscribe)

    # ------------------------------------------------------------------
    # AiringDue host heartbeat + fallback singleflight
    # ------------------------------------------------------------------
    def _begin_airing_due_cycle_v211(self, owner: str) -> Optional[int]:
        lock = getattr(self, "_airing_due_lock_v211", None) or threading.RLock()
        self._airing_due_lock_v211 = lock
        with lock:
            if bool(getattr(self, "_airing_due_running_v211", False)):
                self._plugin_log(
                    "INFO",
                    "【AiringDue跳过】cycle=%s reason=already_running owner=%s active_owner=%s",
                    int(getattr(self, "_airing_due_cycle_v211", 0) or 0),
                    owner,
                    str(getattr(self, "_airing_due_owner_v211", "") or "-"),
                )
                return None
            cycle = int(getattr(self, "_airing_due_cycle_v211", 0) or 0) + 1
            self._airing_due_cycle_v211 = cycle
            self._airing_due_running_v211 = True
            self._airing_due_owner_v211 = str(owner or "")
            self._airing_cycle_ensure_v211(cycle, owner)
            return cycle

    def _end_airing_due_cycle_v211(self) -> None:
        lock = getattr(self, "_airing_due_lock_v211", None) or threading.RLock()
        with lock:
            self._airing_due_running_v211 = False
            self._airing_due_owner_v211 = ""
            self._airing_cycle_clear_v211()

    def _calendar_due_check_v1110(self, minutes: Any = None, owner: str = "host", **kwargs) -> Dict[str, Any]:
        if not self._episode_runtime_is_ready_v211():
            return {"success": False, "skipped": True, "reason": "episode_runtime_not_ready"}
        cycle = self._begin_airing_due_cycle_v211(owner)
        if cycle is None:
            return {"success": True, "skipped": True, "reason": "already_running"}
        started = time.time()
        if str(owner or "") == "host":
            self._host_airing_heartbeat_v211 = time.monotonic()
        try:
            try:
                active = list(self._active_selected_subscriptions_v1125() or [])
            except Exception:
                active = []
            self._plugin_log(
                "INFO",
                "【AiringDue开始】cycle=%s owner=%s active_subscriptions=%s started_at=%s",
                cycle,
                owner,
                len(active),
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started)),
            )
            # Prefer modern dispatch path via MRO super (DispatchPolicy).
            # Selector stores per-sid EpisodeFacts; second gate + transfer reuse them.
            try:
                result = dict(super()._calendar_due_check_v1110() or {})
            except TypeError:
                result = dict(super()._calendar_due_check_v1110() or {})
            elapsed_ms = int((time.time() - started) * 1000)
            selected = result.get("checked") or result.get("selected") or 0
            if isinstance(selected, list):
                selected_n = len(selected)
            else:
                try:
                    selected_n = int(selected or 0)
                except (TypeError, ValueError):
                    selected_n = 0
            self._plugin_log(
                "INFO",
                "【AiringDue筛选】cycle=%s active=%s library_unknown=%s missing=%s "
                "future_only=%s cooldown_active=%s cooldown_due=%s selected=%s elapsed_ms=%s",
                cycle,
                len(active),
                int(result.get("library_unknown") or 0),
                int(result.get("missing") or 0),
                int(result.get("future_only") or 0),
                int(result.get("cooldown_active") or 0),
                int(result.get("cooldown_due") or 0),
                selected_n,
                elapsed_ms,
            )
            result["cycle"] = cycle
            result["owner"] = owner
            result["elapsed_ms"] = elapsed_ms
            result["selected"] = selected_n
            return result
        finally:
            self._end_airing_due_cycle_v211()

    def _runtime_worker_loop(self, generation: int) -> None:
        """Extend built-in supervisor: Channel Tick + AiringDue fallback."""
        stop = getattr(self, "_runtime_stop", None)
        if stop is None:
            return super()._runtime_worker_loop(generation)
        if stop.wait(1.5):
            return
        if not self._runtime_is_current() or not self._enabled:
            return
        if not self._episode_runtime_is_ready_v211():
            return
        try:
            self._plugin_log("INFO", "【光鸭转存助手】【启动检查】内置守护开始首轮缓存检查")
            self._startup_check()
        except Exception as err:
            self._plugin_log("EXCEPTION", "【光鸭转存助手】【启动检查】内置守护首轮执行异常：%s", err)

        while self._enabled and self._runtime_is_current():
            interval = max(60, int(self._refresh_minutes or 5) * 60)
            if stop.wait(interval):
                return
            if not self._runtime_is_current() or not self._enabled:
                return
            if not self._episode_runtime_is_ready_v211():
                continue
            # Channel tick fallback (existing behavior).
            heartbeat = float(getattr(self, "_host_tick_heartbeat", 0.0) or 0.0)
            if not heartbeat or (time.monotonic() - heartbeat) >= interval * 1.5:
                try:
                    self._plugin_log(
                        "WARNING",
                        "【光鸭转存助手】【服务回退】未检测到宿主 Channel Tick 心跳，内置守护执行本轮检查",
                    )
                    self._tick(host_service=False)
                except Exception as err:
                    self._plugin_log("EXCEPTION", "【光鸭转存助手】【服务回退】Channel Tick 异常：%s", err)
            # AiringDue fallback.
            airing_hb = float(getattr(self, "_host_airing_heartbeat_v211", 0.0) or 0.0)
            stale = max(300, int(getattr(self, "_airing_fallback_stale_seconds_v211", 900) or 900))
            if (not airing_hb or (time.monotonic() - airing_hb) >= stale) and bool(
                getattr(self, "_auto_transfer_on_refresh", True)
            ):
                try:
                    self._plugin_log(
                        "WARNING",
                        "【光鸭转存助手】【服务回退】未检测到宿主 AiringDue 心跳（>%ss），内置守护执行 AiringDue",
                        stale,
                    )
                    self._calendar_due_check_v1110(owner="fallback")
                except Exception as err:
                    self._plugin_log("EXCEPTION", "【光鸭转存助手】【服务回退】AiringDue 异常：%s", err)
