"""2.0.10-r94：统一 Episode Target Resolver（Emby 实际库为准 + 可观测性）。

唯一权威输出：_episode_target_snapshot_v210()
- Emby query success 时：existing/gap 仅来自媒体库，note 不得掩盖 gap
- final_target = emby_gap ∩ calendar_due − reserved − claimed − pending_library
- MP missing 为辅助事实，不能硬删除 Emby+calendar 已确认的 due gap
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


_PENDING_LIBRARY_KEY_V210 = "pending_library_confirmation_v210"
_PENDING_LIBRARY_TTL_SECONDS_V210 = 20 * 60
_LIBRARY_SNAPSHOT_TTL_SECONDS_V210 = 45


def _positive_eps(values: Any) -> Set[int]:
    out: Set[int] = set()
    for raw in values or []:
        try:
            episode = int(raw)
        except (TypeError, ValueError):
            continue
        if episode > 0:
            out.add(episode)
    return out


def _fmt_eps(values: Iterable[int]) -> str:
    items = sorted(int(v) for v in values if int(v or 0) > 0)
    return ",".join(f"E{v:02d}" for v in items) or "-"


class GuangYaEpisodeTargetV210Mixin:
    """Per-run Emby-first episode target snapshot + pending library confirmation."""

    _pending_library_ttl_v210 = _PENDING_LIBRARY_TTL_SECONDS_V210
    _library_snapshot_ttl_v210 = _LIBRARY_SNAPSHOT_TTL_SECONDS_V210

    def init_plugin(self, config: dict = None) -> None:
        super().init_plugin(config=config)
        self._episode_target_lock_v210 = threading.RLock()
        self._episode_target_cache_v210: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _subscription_bounds_v210(self, subscribe: Any) -> Tuple[int, int, Set[int]]:
        try:
            start = max(1, int(getattr(subscribe, "start_episode", 0) or 1))
        except (TypeError, ValueError):
            start = 1
        try:
            total = int(getattr(subscribe, "total_episode", 0) or 0)
        except (TypeError, ValueError):
            total = 0
        if total < start:
            return start, 0, set()
        return start, total, set(range(start, total + 1))

    def _note_episodes_v210(self, subscribe: Any) -> Set[int]:
        return _positive_eps(getattr(subscribe, "note", None) or [])

    def _run_id_v210(self) -> str:
        getter = getattr(self, "_current_subscription_run_id", None)
        if callable(getter):
            try:
                return str(getter() or "")
            except Exception:
                pass
        return str(getattr(self, "_current_subscription_run_id_v209", "") or "")

    def _target_cache_key_v210(self, subscribe: Any) -> str:
        sid = int(getattr(subscribe, "id", 0) or 0)
        try:
            season = int(getattr(subscribe, "season", 0) or 0)
        except (TypeError, ValueError):
            season = 0
        run_id = self._run_id_v210() or "-"
        return f"{sid}:{season}:{run_id}"

    # ------------------------------------------------------------------
    # Pending library confirmation (scan lag protection)
    # ------------------------------------------------------------------
    def _pending_library_store_v210(self) -> Dict[str, Any]:
        store = self.get_data(_PENDING_LIBRARY_KEY_V210) or {}
        return dict(store) if isinstance(store, dict) else {}

    def _pending_library_episodes_v210(self, subscribe: Any) -> Set[int]:
        sid = int(getattr(subscribe, "id", 0) or 0)
        try:
            season = int(getattr(subscribe, "season", 0) or 0)
        except (TypeError, ValueError):
            season = 0
        now = time.time()
        store = self._pending_library_store_v210()
        items = dict(store.get("items") or {})
        pending: Set[int] = set()
        changed = False
        for key, row in list(items.items()):
            if not isinstance(row, dict):
                items.pop(key, None)
                changed = True
                continue
            try:
                expires = float(row.get("expires_at") or 0)
            except (TypeError, ValueError):
                expires = 0
            if expires and expires < now:
                # Keep expired rows briefly for observability; exclude from pending set.
                continue
            if int(row.get("subscribe_id") or 0) != sid:
                continue
            if int(row.get("season") or 0) != season:
                continue
            if str(row.get("state") or "") not in {"PENDING_LIBRARY_CONFIRMATION", "pending", ""}:
                continue
            pending |= _positive_eps(row.get("episodes") or [])
        if changed:
            store["items"] = items
            self.save_data(_PENDING_LIBRARY_KEY_V210, store)
        return pending

    def _mark_pending_library_confirmation_v210(
        self,
        subscribe: Any,
        episodes: Iterable[int],
        *,
        source: str = "",
        task_id: str = "",
    ) -> None:
        eps = sorted(_positive_eps(episodes))
        if not eps:
            return
        sid = int(getattr(subscribe, "id", 0) or 0)
        try:
            season = int(getattr(subscribe, "season", 0) or 0)
        except (TypeError, ValueError):
            season = 0
        now = time.time()
        ttl = max(300, int(getattr(self, "_pending_library_ttl_v210", _PENDING_LIBRARY_TTL_SECONDS_V210) or 1200))
        store = self._pending_library_store_v210()
        items = dict(store.get("items") or {})
        key = f"{sid}:{season}:{','.join(str(v) for v in eps)}"
        items[key] = {
            "subscribe_id": sid,
            "season": season,
            "episodes": eps,
            "source": str(source or "")[:80],
            "task_id": str(task_id or "")[:120],
            "confirmed_at": now,
            "expires_at": now + ttl,
            "state": "PENDING_LIBRARY_CONFIRMATION",
            "run_id": self._run_id_v210(),
        }
        # Prune old rows.
        if len(items) > 2000:
            ordered = sorted(items.items(), key=lambda kv: float((kv[1] or {}).get("confirmed_at") or 0))
            items = dict(ordered[-1500:])
        store["items"] = items
        self.save_data(_PENDING_LIBRARY_KEY_V210, store)

    def _clear_pending_library_confirmed_v210(self, subscribe: Any, existing: Set[int]) -> Set[int]:
        """Clear pending episodes that Emby now shows; return still-pending."""
        sid = int(getattr(subscribe, "id", 0) or 0)
        try:
            season = int(getattr(subscribe, "season", 0) or 0)
        except (TypeError, ValueError):
            season = 0
        store = self._pending_library_store_v210()
        items = dict(store.get("items") or {})
        still: Set[int] = set()
        changed = False
        now = time.time()
        for key, row in list(items.items()):
            if not isinstance(row, dict):
                items.pop(key, None)
                changed = True
                continue
            if int(row.get("subscribe_id") or 0) != sid or int(row.get("season") or 0) != season:
                continue
            eps = _positive_eps(row.get("episodes") or [])
            confirmed = eps.intersection(existing)
            remain = eps - existing
            if confirmed:
                changed = True
                if remain:
                    row = dict(row)
                    row["episodes"] = sorted(remain)
                    items[key] = row
                else:
                    items.pop(key, None)
            try:
                expires = float(row.get("expires_at") or 0)
            except (TypeError, ValueError):
                expires = 0
            if remain and (not expires or expires >= now):
                still |= remain
            elif remain and expires and expires < now:
                self._plugin_log(
                    "WARNING",
                    "【Emby入库核验】run=%s sid=%s season=S%02d still_missing=%s state=LIBRARY_INGEST_NOT_CONFIRMED",
                    self._run_id_v210() or "-",
                    sid,
                    season,
                    _fmt_eps(remain),
                )
        if changed:
            store["items"] = items
            self.save_data(_PENDING_LIBRARY_KEY_V210, store)
        return still

    # ------------------------------------------------------------------
    # Library sync: Emby actual must not be masked by note
    # ------------------------------------------------------------------
    def _sync_media_library_progress(self, subscribe: Any) -> Dict[str, Any]:
        result = dict(super()._sync_media_library_progress(subscribe) or {})
        if self._is_movie_subscription(subscribe):
            return result
        start, total, bounds = self._subscription_bounds_v210(subscribe)
        if not bounds:
            return result
        # Always recompute missing from returned existing when query succeeded.
        if bool(result.get("success")):
            existing = _positive_eps(result.get("existing") or [])
            # Defensive: never invent existing from note.
            note = self._note_episodes_v210(subscribe)
            gap = bounds - existing
            result["existing"] = sorted(existing)
            result["missing"] = sorted(gap)
            result["note"] = sorted(note.intersection(bounds))
            result["note_only"] = sorted((note.intersection(bounds)) - existing)
            result["library_only"] = sorted(existing - note)
            result["library_state"] = "OK"
            result["bounds"] = sorted(bounds)
        else:
            result["library_state"] = "UNKNOWN"
            result.setdefault("existing", [])
            # Fail closed for transfer: do not claim all-missing as actionable list.
            result["missing"] = []
            result["note"] = sorted(self._note_episodes_v210(subscribe).intersection(bounds))
            result["note_only"] = []
            result["library_only"] = []
            result["bounds"] = sorted(bounds)
        return result

    # ------------------------------------------------------------------
    # Unified snapshot
    # ------------------------------------------------------------------
    def _episode_target_snapshot_v210(
        self,
        subscribe: Any,
        *,
        current_source_id: str = "",
        force_library: bool = False,
        log: bool = True,
    ) -> Dict[str, Any]:
        sid = int(getattr(subscribe, "id", 0) or 0)
        try:
            season = int(getattr(subscribe, "season", 0) or 0)
        except (TypeError, ValueError):
            season = 0
        run_id = self._run_id_v210() or "-"
        media = str(getattr(subscribe, "name", "") or "")[:120]
        start, total, bounds = self._subscription_bounds_v210(subscribe)

        if self._is_movie_subscription(subscribe):
            snap = {
                "success": True,
                "subscribe_id": sid,
                "season": season,
                "media": media,
                "run_id": run_id,
                "start_episode": start,
                "total_episode": total,
                "subscription_bounds": [],
                "library_state": "OK",
                "emby_existing": [],
                "emby_gap": [],
                "mp_missing_state": "movie",
                "mp_missing": [],
                "calendar_state": "N/A",
                "calendar_due": [],
                "calendar_future": [],
                "calendar_undated": [],
                "reserved": [],
                "claimed": [],
                "pending_library": [],
                "emby_gap_override": [],
                "mp_stale_missing": [],
                "note": [],
                "note_only": [],
                "final_target": [],
                "decision": "movie",
                "reason": "movie_subscription",
            }
            return snap

        cache_key = self._target_cache_key_v210(subscribe)
        lock = getattr(self, "_episode_target_lock_v210", None) or threading.RLock()
        self._episode_target_lock_v210 = lock
        now = time.time()
        with lock:
            cache = getattr(self, "_episode_target_cache_v210", None)
            if not isinstance(cache, dict):
                cache = {}
                self._episode_target_cache_v210 = cache
            if not force_library:
                hit = dict(cache.get(cache_key) or {})
                if hit and (now - float(hit.get("checked_at") or 0)) < float(self._library_snapshot_ttl_v210):
                    return hit

        # 1) Emby / media library facts
        try:
            sync = dict(self._sync_media_library_progress(subscribe) or {})
        except Exception as err:
            sync = {"success": False, "existing": [], "missing": [], "message": str(err)[:220]}

        library_ok = bool(sync.get("success"))
        library_state = "OK" if library_ok else "UNKNOWN"
        emby_existing = _positive_eps(sync.get("existing") or []) if library_ok else set()
        emby_gap = (bounds - emby_existing) if library_ok else set()
        note = _positive_eps(sync.get("note") or self._note_episodes_v210(subscribe)).intersection(bounds)
        note_only = (note - emby_existing) if library_ok else set()

        if library_ok:
            self._clear_pending_library_confirmed_v210(subscribe, emby_existing)

        # 2) MP missing (auxiliary)
        mp_state = "fallback"
        mp_missing: Set[int] = set()
        resolver = getattr(self, "_mp_authoritative_missing_episodes_v209", None)
        if callable(resolver):
            try:
                mp_state, mp_missing = resolver(subscribe)
                mp_missing = _positive_eps(mp_missing)
            except Exception:
                mp_state, mp_missing = "fallback", set()

        # 3) Calendar due / future
        calendar_state = "UNKNOWN"
        calendar_due: Set[int] = set()
        calendar_future: Set[int] = set()
        calendar_undated: Set[int] = set()
        next_future = 0
        next_air_at = ""
        try:
            import datetime as _dt
            calendar = dict(self._refresh_airing_calendar_v1120(force=False) or {})
            item = self._calendar_item_for_v1120(subscribe, calendar) or {}
            now_dt = _dt.datetime.now()
            split = self._split_calendar_due_future_v209(item, subscribe, now_dt, candidate_episodes=None)
            calendar_due = _positive_eps(split.get("due") or [])
            calendar_future = _positive_eps(split.get("future") or [])
            calendar_state = "OK" if bool(split.get("calendar_available")) else "UNKNOWN"
            next_future = int(split.get("next_episode") or 0)
            next_air_at = str(split.get("next_air_at") or "")
            # Undated in-bound episodes: present in item without air time.
            dated = calendar_due | calendar_future
            for row in item.get("episodes") or []:
                if not isinstance(row, dict):
                    continue
                try:
                    ep = int(row.get("episode") or row.get("episode_number") or 0)
                except (TypeError, ValueError):
                    continue
                if ep in bounds and ep not in dated:
                    air = self._episode_air_at_v1120(row) if hasattr(self, "_episode_air_at_v1120") else None
                    if air is None:
                        calendar_undated.add(ep)
        except Exception:
            calendar_state = "UNKNOWN"

        # 4) Reservations / claims / pending library
        reserved: Set[int] = set()
        claimed: Set[int] = set()
        try:
            reservations = dict(self._pending_reservations(subscribe) or {})
            reserved = _positive_eps(reservations.get("episodes") or [])
        except Exception:
            reserved = set()
        try:
            claimed = _positive_eps(self._active_source_claims(sid) or [])
        except Exception:
            claimed = set()
        if current_source_id:
            helper = getattr(self, "_other_source_claims_v11214", None)
            if callable(helper):
                try:
                    claimed = _positive_eps(helper(sid, current_source_id=current_source_id))
                except Exception:
                    pass
        pending_library = self._pending_library_episodes_v210(subscribe)

        # 5) Final target algorithm
        emby_gap_override: Set[int] = set()
        mp_stale_missing: Set[int] = set()
        final_target: Set[int] = set()
        decision = "unknown"
        reason = "insufficient_evidence"

        if library_ok and calendar_state == "OK":
            actual_due_gap = emby_gap.intersection(calendar_due)
            # MP missing cannot delete Emby+due gaps.
            if mp_missing:
                stale = mp_missing.intersection(emby_existing)
                mp_stale_missing |= stale
                # Emby gap episodes not in MP missing but due → override
                emby_gap_override |= (actual_due_gap - mp_missing)
            final_target = set(actual_due_gap)
            decision = "search_missing" if final_target else "skip_caught_up"
            reason = "emby_actual_gap_intersect_calendar_due"
            if calendar_future and not final_target and not (emby_gap - calendar_future - calendar_due):
                decision = "skip_future"
                reason = "caught_up_waiting_future"
        elif library_ok and calendar_state != "OK" and mp_missing:
            final_target = emby_gap.intersection(mp_missing)
            decision = "search_mp_missing_fallback"
            reason = "calendar_unknown_use_mp_missing_cap"
        elif library_ok and calendar_state != "OK" and not mp_missing:
            final_target = set()
            decision = "continue_match"
            reason = "emby_gap_without_due_evidence"
            if not emby_gap:
                decision = "skip_complete"
                reason = "emby_complete_without_calendar"
        elif not library_ok:
            # UNKNOWN library: no completion, no mass submit from empty existing.
            if mp_missing and calendar_state == "OK":
                final_target = mp_missing.intersection(calendar_due)
                decision = "search_mp_calendar_failopen"
                reason = "library_unknown_mp_and_calendar"
            else:
                final_target = set()
                decision = "continue_match"
                reason = "library_unknown_fail_safe"

        before_subtract = set(final_target)
        final_target = final_target - reserved - claimed - pending_library
        if before_subtract and not final_target and (reserved or claimed or pending_library):
            decision = "skip_reserved_or_pending"
            reason = "targets_covered_by_reservation_claim_or_pending_library"

        snap = {
            "success": library_ok or bool(final_target) or decision in {"continue_match", "skip_future", "skip_complete"},
            "checked_at": now,
            "subscribe_id": sid,
            "season": season,
            "media": media,
            "run_id": run_id,
            "start_episode": start,
            "total_episode": total,
            "subscription_bounds": sorted(bounds),
            "library_state": library_state,
            "emby_existing": sorted(emby_existing),
            "emby_gap": sorted(emby_gap),
            "mp_missing_state": str(mp_state or ""),
            "mp_missing": sorted(mp_missing),
            "calendar_state": calendar_state,
            "calendar_due": sorted(calendar_due),
            "calendar_future": sorted(calendar_future),
            "calendar_undated": sorted(calendar_undated),
            "next_future": next_future,
            "next_air_at": next_air_at,
            "reserved": sorted(reserved),
            "claimed": sorted(claimed),
            "pending_library": sorted(pending_library),
            "emby_gap_override": sorted(emby_gap_override),
            "mp_stale_missing": sorted(mp_stale_missing),
            "note": sorted(note),
            "note_only": sorted(note_only),
            "final_target": sorted(final_target),
            "decision": decision,
            "reason": reason,
        }

        with lock:
            cache[cache_key] = dict(snap)
            if len(cache) > 500:
                ordered = sorted(cache.items(), key=lambda kv: float((kv[1] or {}).get("checked_at") or 0))
                self._episode_target_cache_v210 = dict(ordered[-400:])

        if log:
            self._log_episode_target_facts_v210(snap)
        return snap

    def _log_episode_target_facts_v210(self, snap: Dict[str, Any]) -> None:
        run_id = str(snap.get("run_id") or "-")
        sid = int(snap.get("subscribe_id") or 0)
        season = int(snap.get("season") or 0)
        media = str(snap.get("media") or "-")
        bounds = snap.get("subscription_bounds") or []
        bound_text = "-"
        if bounds:
            bound_text = f"E{int(min(bounds)):02d}-E{int(max(bounds)):02d}"

        self._plugin_log(
            "INFO",
            "【Emby剧集事实】run=%s sid=%s media=%s season=S%02d query_success=%s bounds=%s "
            "existing=%s gap=%s note=%s note_only=%s library_only=%s",
            run_id,
            sid,
            media,
            season,
            str(snap.get("library_state") or "") == "OK",
            bound_text,
            _fmt_eps(snap.get("emby_existing") or []),
            _fmt_eps(snap.get("emby_gap") or []),
            _fmt_eps(snap.get("note") or []),
            _fmt_eps(snap.get("note_only") or []),
            _fmt_eps(set(snap.get("emby_existing") or []) - set(snap.get("note") or [])),
        )
        self._plugin_log(
            "INFO",
            "【MP剧集事实】run=%s sid=%s mp_state=%s mp_missing=%s",
            run_id,
            sid,
            str(snap.get("mp_missing_state") or "-"),
            _fmt_eps(snap.get("mp_missing") or []),
        )
        self._plugin_log(
            "INFO",
            "【播出日历事实】run=%s sid=%s due=%s future=%s undated=%s next_future=E%02d @ %s",
            run_id,
            sid,
            _fmt_eps(snap.get("calendar_due") or []),
            _fmt_eps(snap.get("calendar_future") or []),
            _fmt_eps(snap.get("calendar_undated") or []),
            int(snap.get("next_future") or 0),
            str(snap.get("next_air_at") or "未知"),
        )
        self._plugin_log(
            "INFO",
            "【剧集目标计算】run=%s sid=%s media=%s season=S%02d bounds=%s "
            "emby_existing=%s emby_gap=%s mp_missing=%s calendar_due=%s calendar_future=%s "
            "reserved=%s claimed=%s pending_library=%s emby_gap_override=%s mp_stale_missing=%s "
            "final_target=%s decision=%s reason=%s",
            run_id,
            sid,
            media,
            season,
            bound_text,
            _fmt_eps(snap.get("emby_existing") or []),
            _fmt_eps(snap.get("emby_gap") or []),
            _fmt_eps(snap.get("mp_missing") or []),
            _fmt_eps(snap.get("calendar_due") or []),
            _fmt_eps(snap.get("calendar_future") or []),
            _fmt_eps(snap.get("reserved") or []),
            _fmt_eps(snap.get("claimed") or []),
            _fmt_eps(snap.get("pending_library") or []),
            _fmt_eps(snap.get("emby_gap_override") or []),
            _fmt_eps(snap.get("mp_stale_missing") or []),
            _fmt_eps(snap.get("final_target") or []),
            str(snap.get("decision") or "-"),
            str(snap.get("reason") or "-"),
        )

    def _final_target_episodes_v210(
        self,
        subscribe: Any,
        *,
        current_source_id: str = "",
        force_library: bool = False,
    ) -> List[int]:
        snap = self._episode_target_snapshot_v210(
            subscribe,
            current_source_id=current_source_id,
            force_library=force_library,
            log=True,
        )
        return list(snap.get("final_target") or [])

    # ------------------------------------------------------------------
    # Production overrides — single final_target for all sources
    # ------------------------------------------------------------------
    def _airing_gate_v1120(self, subscribe: Any, payload: Dict[str, Any] = None) -> Dict[str, Any]:
        result = dict(super()._airing_gate_v1120(subscribe, payload=payload) or {})
        if self._is_movie_subscription(subscribe):
            return result
        snap = self._episode_target_snapshot_v210(subscribe, force_library=False, log=True)
        final = _positive_eps(snap.get("final_target") or [])
        result["emby_existing"] = list(snap.get("emby_existing") or [])
        result["emby_gap"] = list(snap.get("emby_gap") or [])
        result["final_target"] = sorted(final)
        result["library_state"] = str(snap.get("library_state") or "")
        result["pending_library"] = list(snap.get("pending_library") or [])

        decision = str(snap.get("decision") or "")
        if final:
            ready: Set[int] = set()
            air_dates = {}
            try:
                calendar = payload or self._refresh_airing_calendar_v1120(force=False)
                item = self._calendar_item_for_v1120(subscribe, calendar) or {}
                for row in item.get("episodes") or []:
                    if not isinstance(row, dict):
                        continue
                    try:
                        ep = int(row.get("episode") or row.get("episode_number") or 0)
                    except (TypeError, ValueError):
                        continue
                    if ep in final:
                        air_dates[ep] = str(row.get("air_date") or row.get("air_at") or "")
            except Exception:
                air_dates = {}
            sid = int(getattr(subscribe, "id", 0) or 0)
            season = int(getattr(subscribe, "season", 0) or 0)
            for episode in sorted(final):
                checker = getattr(self, "_episode_ready_for_external_v209", None)
                if callable(checker):
                    try:
                        if checker(sid, season, episode, air_dates.get(episode, "")):
                            ready.add(episode)
                        continue
                    except Exception:
                        pass
                ready.add(episode)
            if ready:
                result["target_episodes"] = sorted(ready)
                result["due_uncovered"] = sorted(ready)
                result["due_missing"] = sorted(final)
                result["decision"] = "search_due"
                result["preflight_state"] = "MISSING"
                result["covered"] = False
                return result

        if decision == "skip_future":
            result["decision"] = "skip_future"
            result["preflight_state"] = "SATISFIED"
            result["target_episodes"] = []
            result["due_uncovered"] = []
            result["covered"] = True
            result["next_episode"] = int(snap.get("next_future") or 0)
            result["next_air_at"] = str(snap.get("next_air_at") or "")
            return result
        if decision == "skip_complete":
            result["decision"] = "skip_complete"
            result["preflight_state"] = "SATISFIED"
            result["target_episodes"] = []
            result["due_uncovered"] = []
            result["covered"] = True
            return result
        if decision in {"continue_match", "search_mp_calendar_failopen", "search_mp_missing_fallback"}:
            if not final and decision == "continue_match":
                result["decision"] = "continue_match"
                result["preflight_state"] = "UNKNOWN"
                result["covered"] = False
            return result
        return result

    def _authoritative_missing_v11214(self, subscribe: Any, *, current_source_id: str = "") -> Set[int]:
        if self._is_movie_subscription(subscribe):
            return set()
        snap = self._episode_target_snapshot_v210(
            subscribe,
            current_source_id=current_source_id,
            force_library=False,
            log=True,
        )
        if str(snap.get("library_state") or "") != "OK" and not snap.get("final_target"):
            if str(snap.get("decision") or "") not in {"search_mp_calendar_failopen"}:
                raise RuntimeError(
                    "MoviePilot 媒体库缺集事实读取失败，最终写盘 fail closed："
                    + str(snap.get("reason") or "library_unknown")
                )
        return set(int(v) for v in (snap.get("final_target") or []) if int(v) > 0)

    def _xunlei_authoritative_missing_v11213(
        self,
        subscribe: Any,
    ) -> Tuple[Optional[Set[int]], Dict[str, Any]]:
        snap = self._episode_target_snapshot_v210(subscribe, force_library=False, log=True)
        sync = {
            "success": str(snap.get("library_state") or "") == "OK",
            "existing": list(snap.get("emby_existing") or []),
            "missing": list(snap.get("emby_gap") or []),
            "final_target": list(snap.get("final_target") or []),
            "message": str(snap.get("reason") or ""),
        }
        if str(snap.get("library_state") or "") != "OK" and not snap.get("final_target"):
            return None, sync
        return set(int(v) for v in (snap.get("final_target") or []) if int(v) > 0), sync

    def _subscription_missing_episodes(self, subscribe: Any) -> List[int]:
        """Unified final_target base + layered due/xunlei/acquired filters."""
        if self._is_movie_subscription(subscribe):
            return list(super()._subscription_missing_episodes(subscribe) or [])

        snap = self._episode_target_snapshot_v210(subscribe, force_library=False, log=False)
        base = _positive_eps(snap.get("final_target") or [])

        acquired_fn = getattr(self, "_acquired_episode_facts_v1124", None)
        if callable(acquired_fn):
            try:
                base -= _positive_eps(acquired_fn(subscribe) or [])
            except Exception:
                pass

        # DispatchPolicy thread-local due scope.
        local_getter = getattr(self, "_airing_scope_local_value_v1125", None)
        if callable(local_getter):
            try:
                local = local_getter()
                scope = getattr(local, "scope", None) if local is not None else None
                if isinstance(scope, dict):
                    sid = int(getattr(subscribe, "id", 0) or 0)
                    if sid == int(scope.get("subscribe_id") or 0):
                        base &= _positive_eps(scope.get("episodes") or [])
            except Exception:
                pass

        # Legacy shared due scope.
        scope = getattr(self, "_airing_due_scope_v1120", None)
        if isinstance(scope, dict):
            sid = int(getattr(subscribe, "id", 0) or 0)
            if sid == int(scope.get("subscribe_id") or 0):
                base &= _positive_eps(scope.get("episodes") or [])

        # Xunlei physical fence scope.
        try:
            getter = getattr(self, "_xunlei_fence_scope_value_v11213", None)
            if callable(getter):
                xscope = getter(subscribe)
                if xscope:
                    base &= _positive_eps(xscope.get("allowed") or [])
        except Exception:
            pass

        return sorted(base)

    def _subscription_episode_progress(self, subscribe: Any) -> Tuple[int, int, int]:
        if self._is_movie_subscription(subscribe):
            return super()._subscription_episode_progress(subscribe)
        start, total, bounds = self._subscription_bounds_v210(subscribe)
        if not bounds:
            return 0, 0, 0
        snap = self._episode_target_snapshot_v210(subscribe, force_library=True, log=False)
        if str(snap.get("library_state") or "") == "OK":
            existing = _positive_eps(snap.get("emby_existing") or [])
            return len(existing), len(bounds), len(bounds - existing)
        # Library UNKNOWN: never report complete via stale note.
        return 0, len(bounds), len(bounds)

    def _remember_episode_facts(self, subscribe: Any, episodes: Iterable[int], origin: str = "library") -> int:
        changed = int(super()._remember_episode_facts(subscribe, episodes, origin=origin) or 0)
        origin_text = str(origin or "").lower()
        if (
            not self._is_movie_subscription(subscribe)
            and episodes
            and origin_text
            and origin_text != "library"
            and "library" not in origin_text
        ):
            try:
                self._mark_pending_library_confirmation_v210(
                    subscribe,
                    episodes,
                    source=origin_text[:80],
                )
                self._plugin_log(
                    "INFO",
                    "【Emby入库核验】run=%s sid=%s season=S%02d episodes=%s state=PENDING_LIBRARY_CONFIRMATION origin=%s",
                    self._run_id_v210() or "-",
                    int(getattr(subscribe, "id", 0) or 0),
                    int(getattr(subscribe, "season", 0) or 0),
                    _fmt_eps(episodes),
                    origin_text[:80],
                )
            except Exception:
                pass
        return changed

    def _finish_subscription_if_complete(
        self,
        subscribe: Any,
        channel_state: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if self._is_movie_subscription(subscribe):
            return bool(super()._finish_subscription_if_complete(subscribe, channel_state=channel_state))
        # Fresh Emby verification is mandatory for TV completion.
        snap = self._episode_target_snapshot_v210(subscribe, force_library=True, log=True)
        if str(snap.get("library_state") or "") != "OK":
            self._plugin_log(
                "INFO",
                "【转存运行结果】run=%s sid=%s media=%s state=LIBRARY_UNKNOWN reason=block_completion",
                snap.get("run_id") or "-",
                snap.get("subscribe_id") or 0,
                snap.get("media") or "-",
            )
            return False
        gap = _positive_eps(snap.get("emby_gap") or [])
        pending = _positive_eps(snap.get("pending_library") or [])
        if gap or pending:
            self._plugin_log(
                "INFO",
                "【转存运行结果】run=%s sid=%s media=%s remaining_actual_gap=%s pending_library=%s "
                "state=NOT_COMPLETE reason=emby_actual_incomplete",
                snap.get("run_id") or "-",
                snap.get("subscribe_id") or 0,
                snap.get("media") or "-",
                _fmt_eps(gap),
                _fmt_eps(pending),
            )
            return False
        return bool(super()._finish_subscription_if_complete(subscribe, channel_state=channel_state))
