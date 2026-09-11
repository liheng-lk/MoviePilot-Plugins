"""2.0.9-r93：MoviePilot 原生日历驱动精确追更。

优先级：MP Native Calendar ∩ MP authoritative missing − reserved − claimed。
白天 AiringDue 只主动外搜最终目标集；日历失败时不退化为全量 GYING。
每日兜底默认 21:00，可配置 daily_reconcile_cron。
"""
from __future__ import annotations

import datetime
import inspect
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from apscheduler.triggers.cron import CronTrigger


class GuangYaCalendarDrivenV209Mixin:
    """MP 原生日历 + authoritative missing + 21:00 兜底 + episode backoff。"""

    _calendar_refresh_hours_v209 = 6
    _calendar_date_active_hour_v209 = 18
    _daily_reconcile_cron_v209 = "0 21 * * *"
    _episode_retry_offsets_v209 = (0, 30 * 60, 90 * 60)
    _gying_concurrency_v209 = 2
    _external_search_budget_seconds_v209 = 90
    _node_degrade_seconds_v209 = 15 * 60

    def init_plugin(self, config: dict = None) -> None:
        cfg = dict(config or {})
        try:
            self._calendar_date_active_hour_v209 = max(
                0, min(23, int(cfg.get("calendar_date_active_hour", self._calendar_date_active_hour_v209) or 18))
            )
        except (TypeError, ValueError):
            self._calendar_date_active_hour_v209 = 18
        cron = str(cfg.get("daily_reconcile_cron") or self._daily_reconcile_cron_v209 or "").strip()
        self._daily_reconcile_cron_v209 = cron or "0 21 * * *"
        try:
            CronTrigger.from_crontab(self._daily_reconcile_cron_v209)
        except Exception:
            self._daily_reconcile_cron_v209 = "0 21 * * *"

        self._episode_search_lock_v209 = threading.RLock()
        self._metrics_lock_v209 = threading.RLock()
        self._gying_slot_v209 = threading.Semaphore(int(self._gying_concurrency_v209 or 2))
        self._node_degrade_v209: Dict[str, float] = {}
        if not isinstance(getattr(self, "_r93_metrics_v209", None), dict):
            self._r93_metrics_v209 = self._empty_metrics_v209()
        return super().init_plugin(config)

    @staticmethod
    def _empty_metrics_v209() -> Dict[str, int]:
        return {
            "calendar_checked": 0,
            "due_subscriptions": 0,
            "due_episodes": 0,
            "channel_hits": 0,
            "external_searches": 0,
            "gying_queries": 0,
            "pansou_pow_challenges": 0,
            "cache_hits": 0,
            "skipped_future": 0,
            "skipped_covered": 0,
            "daily_reconcile_remaining": 0,
        }

    def _bump_metric_v209(self, key: str, amount: int = 1) -> None:
        lock = getattr(self, "_metrics_lock_v209", None) or threading.RLock()
        self._metrics_lock_v209 = lock
        with lock:
            metrics = getattr(self, "_r93_metrics_v209", None)
            if not isinstance(metrics, dict):
                metrics = self._empty_metrics_v209()
                self._r93_metrics_v209 = metrics
            metrics[key] = int(metrics.get(key) or 0) + int(amount)

    # ------------------------------------------------------------------
    # Config UI
    # ------------------------------------------------------------------
    def get_form(self):
        form, defaults = super().get_form()
        defaults = dict(defaults or {})
        defaults.setdefault("daily_reconcile_cron", getattr(self, "_daily_reconcile_cron_v209", "0 21 * * *"))
        defaults.setdefault("calendar_date_active_hour", int(getattr(self, "_calendar_date_active_hour_v209", 18) or 18))
        section_builder = getattr(self, "_section", None)
        field_builder = getattr(self, "_field", None)
        if not callable(section_builder) or not callable(field_builder):
            return form, defaults
        try:
            content = form[0]["content"]
        except (IndexError, KeyError, TypeError):
            return form, defaults
        # Merge into existing 更新日历 section when present.
        for row in content:
            if not isinstance(row, dict):
                continue
            try:
                title = ((row.get("content") or [{}])[0].get("content") or [{}])[0].get("text")
            except Exception:
                title = None
            if title != "更新日历":
                continue
            try:
                body = row["content"][1]["content"]
                if not isinstance(body, list):
                    break
                body.append({
                    "component": "VRow",
                    "content": [
                        field_builder(
                            "calendar_date_active_hour",
                            "仅日期精度的主动检查起始小时",
                            md=6,
                            type="number",
                            min="0",
                            max="23",
                            hint="只有 air_date、没有 air_at 时，当天到该小时后才允许主动 GYING；默认 18。",
                            **{"persistent-hint": True},
                        ),
                        field_builder(
                            "daily_reconcile_cron",
                            "每日全员兜底 Cron",
                            md=6,
                            hint="默认 0 21 * * *（每天 21:00）。非法值回退到 21:00。",
                            **{"persistent-hint": True},
                        ),
                    ],
                })
            except Exception:
                pass
            break
        return form, defaults

    def _save_config(self) -> None:
        super()._save_config()
        config = self.get_config() or {}
        config = dict(config) if isinstance(config, dict) else {}
        config.update({
            "daily_reconcile_cron": str(getattr(self, "_daily_reconcile_cron_v209", "0 21 * * *") or "0 21 * * *"),
            "calendar_date_active_hour": int(getattr(self, "_calendar_date_active_hour_v209", 18) or 18),
        })
        self.update_config(config)

    # ------------------------------------------------------------------
    # Services: replace 04:10 DailyCatchup with configurable 21:00 DailyReconcile
    # ------------------------------------------------------------------
    def get_service(self) -> List[Dict[str, Any]]:
        services = list(super().get_service() or [])
        if not getattr(self, "_enabled", False):
            return services
        cron = str(getattr(self, "_daily_reconcile_cron_v209", "0 21 * * *") or "0 21 * * *")
        try:
            trigger = CronTrigger.from_crontab(cron)
        except Exception:
            cron = "0 21 * * *"
            trigger = CronTrigger.from_crontab(cron)
            self._daily_reconcile_cron_v209 = cron

        filtered: List[Dict[str, Any]] = []
        for row in services:
            if not isinstance(row, dict):
                filtered.append(row)
                continue
            sid = str(row.get("id") or "")
            if sid in {"GuangYaTransferAssistantDailyCatchup", "GuangYaTransferAssistantDailyReconcile"}:
                continue
            filtered.append(row)
        filtered.append({
            "id": "GuangYaTransferAssistantDailyReconcile",
            "name": "光鸭转存助手每日21点全员兜底",
            "trigger": trigger,
            "func": self._daily_full_catchup_v1110,
            "kwargs": {},
        })
        return filtered

    # ------------------------------------------------------------------
    # Capability detection (no broad TypeError ABI fallback)
    # ------------------------------------------------------------------
    @staticmethod
    def _callable_accepts_kw_v209(fn: Any, name: str) -> bool:
        if not callable(fn):
            return False
        try:
            params = inspect.signature(fn).parameters
        except (TypeError, ValueError):
            return False
        if name in params:
            return True
        return any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())

    def _mp_has_resolve_missing_v209(self) -> bool:
        try:
            from app.chain.subscribe import SubscribeChain
            return callable(getattr(SubscribeChain(), "resolve_subscribe_missing", None))
        except Exception:
            return False

    def _mp_has_tmdb_episodes_v209(self) -> bool:
        try:
            from app.chain.tmdb import TmdbChain
            return callable(getattr(TmdbChain(), "tmdb_episodes", None))
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Authoritative missing via SubscribeChain.resolve_subscribe_missing
    # ------------------------------------------------------------------
    def _mp_authoritative_missing_episodes_v209(self, subscribe: Any) -> Tuple[str, Set[int]]:
        """Return (source, missing_episodes).

        source meanings:
        - used_complete: MP positively reports coverage / exist_flag
        - used_missing: MP returned an explicit non-empty missing list
        - used_empty: MP returned NotExistMediaInfo-style empty episodes (NOT satisfied)
        - fallback: library/logical intersection fallback
        - movie: movie subscription
        """
        if self._is_movie_subscription(subscribe):
            return "movie", set()
        # Prefer MP resolve_subscribe_missing when available.
        if self._mp_has_resolve_missing_v209():
            try:
                from app.chain.subscribe import SubscribeChain
                try:
                    from app.application.subscription.contract import build_subscribe_meta
                except Exception:
                    from app.chain.subscribe import build_subscribe_meta  # type: ignore

                meta = build_subscribe_meta(subscribe)
                recognize = getattr(self, "_recognize_media_cached_v208", None)
                kwargs = {
                    "meta": meta,
                    "mtype": getattr(meta, "type", None),
                    "media_source": getattr(subscribe, "media_source", None),
                    "media_id": getattr(subscribe, "media_id", None),
                    "cache": False,
                }
                if self._callable_accepts_kw_v209(recognize or (lambda **k: None), "episode_group"):
                    kwargs["episode_group"] = getattr(subscribe, "episode_group", None)
                if callable(recognize):
                    mediainfo = recognize(**kwargs)
                else:
                    from app.chain.media import MediaChain
                    mediainfo = MediaChain().recognize_media(**kwargs)
                if mediainfo is not None:
                    chain = SubscribeChain()
                    method = chain.resolve_subscribe_missing
                    call_kwargs: Dict[str, Any] = {
                        "subscribe": subscribe,
                        "meta": meta,
                        "mediainfo": mediainfo,
                    }
                    if self._callable_accepts_kw_v209(method, "best_version_accept_downloaded"):
                        call_kwargs["best_version_accept_downloaded"] = False
                    exist_flag, no_exists = method(**call_kwargs)
                    if exist_flag:
                        return "used_complete", set()
                    season = int(getattr(subscribe, "season", 0) or 0)
                    missing: Set[int] = set()
                    saw_season_detail = False
                    total_episode_hint = 0
                    for season_map in (no_exists or {}).values():
                        if not isinstance(season_map, dict):
                            continue
                        detail = season_map.get(season)
                        if detail is None:
                            detail = season_map.get(str(season))
                        if detail is None:
                            continue
                        saw_season_detail = True
                        episodes = getattr(detail, "episodes", None)
                        if episodes is None and isinstance(detail, dict):
                            episodes = detail.get("episodes")
                        try:
                            total_episode_hint = int(
                                getattr(detail, "total_episode", None)
                                or (detail.get("total_episode") if isinstance(detail, dict) else 0)
                                or 0
                            )
                        except (TypeError, ValueError):
                            total_episode_hint = 0
                        for value in episodes or []:
                            try:
                                episode = int(value)
                            except (TypeError, ValueError):
                                continue
                            if episode > 0:
                                missing.add(episode)
                    if missing:
                        return "used_missing", missing
                    # Empty episode list with a season detail / total hint is UNKNOWN, not complete.
                    if saw_season_detail:
                        try:
                            sub_total = int(getattr(subscribe, "total_episode", 0) or 0)
                        except (TypeError, ValueError):
                            sub_total = 0
                        if total_episode_hint > 0 or sub_total > 0 or season > 0:
                            return "used_empty", set()
                    # No usable season detail → treat as empty/unknown rather than complete.
                    return "used_empty", set()
            except Exception as err:
                self._plugin_log(
                    "WARNING",
                    "【光鸭转存助手】【MP订阅日历】resolve_subscribe_missing 不可用，回退媒体库同步：%s",
                    str(err)[:220],
                )

        # Fallback: prefer Emby/library missing. Logical/note missing is auxiliary only —
        # never hard-cap Emby gaps away via intersection.
        try:
            ctx = None
            getter = getattr(self, "_episode_run_context_for_subscribe_v211", None)
            if callable(getter):
                try:
                    ctx = getter(subscribe)
                except Exception:
                    ctx = None
            if isinstance(ctx, dict) and isinstance(ctx.get("library_sync"), dict):
                sync = dict(ctx.get("library_sync") or {})
            else:
                before = int(ctx.get("emby_query_count") or 0) if isinstance(ctx, dict) else 0
                sync = dict(self._sync_media_library_progress(subscribe) or {})
                if isinstance(ctx, dict) and int(ctx.get("emby_query_count") or 0) > before:
                    ctx["mp_missing_related_library_calls"] = int(
                        ctx.get("mp_missing_related_library_calls") or 0
                    ) + 1
            if not bool(sync.get("success")):
                library_missing = set()
            else:
                library_missing = {
                    int(v) for v in (sync.get("missing") or []) if int(v or 0) > 0
                }
        except Exception:
            library_missing = set()
        try:
            logical = set(self._raw_subscription_missing_v1120(subscribe) or [])
        except Exception:
            logical = set()
        if library_missing:
            return "fallback", set(library_missing)
        if logical:
            return "fallback", set(logical)
        return "fallback", set()

    # ------------------------------------------------------------------
    # MP Native calendar provider (same identity + episode_group as cache_calendar)
    # ------------------------------------------------------------------
    def _mp_native_calendar_for_request_v209(self, request: Dict[str, Any], force: bool) -> Dict[str, Any]:
        sid = int(request.get("subscribe_id") or 0)
        subscribe = self._find_subscription(sid) if sid else None
        season = int(request.get("season") or getattr(subscribe, "season", 1) or 1)
        episode_group = getattr(subscribe, "episode_group", None) if subscribe is not None else request.get("episode_group")
        tmdb_id = str(request.get("tmdb_id") or "").strip()
        row = {
            **request,
            "season": season,
            "episode_group": episode_group,
            "provider": "moviepilot_native",
            "episodes": [],
            "error": "",
        }
        if not self._mp_has_tmdb_episodes_v209():
            row["error"] = "tmdb_episodes_unavailable"
            row["provider"] = "unavailable"
            return row
        try:
            from app.chain.tmdb import TmdbChain
            from app.chain.media import MediaChain
            from app.schemas.types import MediaSource, MediaType

            recognize = getattr(self, "_recognize_media_cached_v208", None)
            recognize_kwargs: Dict[str, Any] = {
                "mtype": MediaType.TV,
                "media_source": getattr(subscribe, "media_source", None) or MediaSource.TMDB,
                "media_id": getattr(subscribe, "media_id", None) or tmdb_id,
                "cache": not force,
            }
            if callable(recognize):
                target = recognize
            else:
                target = MediaChain().recognize_media
            if self._callable_accepts_kw_v209(target, "episode_group"):
                recognize_kwargs["episode_group"] = episode_group
            mediainfo = target(**recognize_kwargs)
            resolved_tmdb = int(getattr(mediainfo, "tmdb_id", 0) or 0) if mediainfo else 0
            if resolved_tmdb <= 0 and tmdb_id.isdigit():
                resolved_tmdb = int(tmdb_id)
            if resolved_tmdb <= 0:
                row["error"] = "recognize_failed"
                return row

            episodes_fn = TmdbChain().tmdb_episodes
            ep_kwargs: Dict[str, Any] = {"tmdbid": resolved_tmdb, "season": season}
            if self._callable_accepts_kw_v209(episodes_fn, "episode_group"):
                ep_kwargs["episode_group"] = episode_group
            raw_episodes = episodes_fn(**ep_kwargs) or []
            episodes = self._calendar_episode_rows_v1120({"episodes": raw_episodes}, season)
            # If list-of-objects, also try direct list helper
            if not episodes and isinstance(raw_episodes, list):
                episodes = self._calendar_episode_rows_v1120(raw_episodes, season)
            row["episodes"] = episodes
            row["episode_count"] = len(episodes)
            row["tmdb_id"] = str(resolved_tmdb)
            row["fetched_at"] = datetime.datetime.now().isoformat(timespec="seconds")
            return row
        except Exception as err:
            row["error"] = str(err)[:220]
            return row

    def _refresh_airing_calendar_v1120(self, force: bool = False) -> Dict[str, Any]:
        current = self.get_data("airing_calendar_v1120") or {}
        if (
            not force
            and isinstance(current, dict)
            and current.get("subscriptions")
            and not self._calendar_stale_v1120(current)
        ):
            self._bump_metric_v209("cache_hits")
            return current

        requests = self._calendar_requests_v1120()
        subscriptions: List[Dict[str, Any]] = []
        native_count = daily_count = fallback_count = 0
        errors: List[str] = []

        # Priority 1: MoviePilot native (same recognize + episode_group + tmdb_episodes).
        native_ok = self._mp_has_tmdb_episodes_v209()
        for request in requests:
            sid = int(request.get("subscribe_id") or 0)
            row: Optional[Dict[str, Any]] = None
            if native_ok:
                candidate = self._mp_native_calendar_for_request_v209(request, force=force)
                if list(candidate.get("episodes") or []):
                    row = candidate
                    native_count += 1
            if row is None:
                # Priority 2: DailyAssistant only as schedule enrichment, never identity authority.
                daily_rows = self._dailyassistant_calendar_v1120([request], force=force)
                item = daily_rows.get(sid)
                if item and list(item.get("episodes") or []):
                    row = {**request, **item}
                    row["provider"] = str(item.get("provider") or "dailyassistant")
                    # Preserve subscribe episode_group even if DailyAssistant omits it.
                    subscribe = self._find_subscription(sid) if sid else None
                    if subscribe is not None:
                        row["episode_group"] = getattr(subscribe, "episode_group", None)
                        row["media_source"] = getattr(subscribe, "media_source", None)
                        row["media_id"] = getattr(subscribe, "media_id", None)
                    daily_count += 1
            if row is None:
                row = self._calendar_local_fallback_v1120(request, force=force)
                # Ensure episode_group is preserved on TMDB fallback path.
                subscribe = self._find_subscription(sid) if sid else None
                if subscribe is not None:
                    row["episode_group"] = getattr(subscribe, "episode_group", None)
                fallback_count += 1
            if row.get("error"):
                errors.append(f"#{sid} {request.get('title')}: {row.get('error')}")
            subscriptions.append(row)

        payload = {
            "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "count": len(subscriptions),
            "moviepilot_native": native_count,
            "dailyassistant": daily_count,
            "fallback": fallback_count,
            "subscriptions": subscriptions,
            "errors": errors[:30],
        }
        self.save_data("airing_calendar_v1120", payload)
        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【MP订阅日历】刷新：订阅=%s native=%s daily=%s fallback=%s 异常=%s",
            len(subscriptions),
            native_count,
            daily_count,
            fallback_count,
            len(errors),
        )
        return payload

    def _calendar_local_fallback_v1120(self, request: Dict[str, Any], force: bool) -> Dict[str, Any]:
        """Preserve episode_group on TMDB fallback recognize/episode fetch."""
        sid = int(request.get("subscribe_id") or 0)
        subscribe = self._find_subscription(sid) if sid else None
        episode_group = getattr(subscribe, "episode_group", None) if subscribe is not None else None
        # Prefer TmdbChain.tmdb_episodes with episode_group when available.
        if self._mp_has_tmdb_episodes_v209():
            enriched = dict(request)
            if episode_group is not None:
                enriched["episode_group"] = episode_group
            native = self._mp_native_calendar_for_request_v209(enriched, force=force)
            if list(native.get("episodes") or []):
                native["provider"] = "guangya_tmdb_fallback"
                return native
        row = dict(super()._calendar_local_fallback_v1120(request, force=force) or {})
        if episode_group is not None:
            row["episode_group"] = episode_group
        return row

    # ------------------------------------------------------------------
    # Episode search state / backoff
    # ------------------------------------------------------------------
    def _episode_state_key_v209(self, sid: int, season: int, episode: int, air_date: str) -> str:
        return f"{int(sid)}:{int(season)}:{int(episode)}:{str(air_date or '')[:10]}"

    def _load_episode_search_state_v209(self) -> Dict[str, Any]:
        state = self.get_data("calendar_episode_search_v209") or {}
        return dict(state) if isinstance(state, dict) else {}

    def _save_episode_search_state_v209(self, state: Dict[str, Any]) -> None:
        if len(state) > 4000:
            # Keep newest-ish by next_retry_at / last_attempt string sort fallback.
            items = sorted(
                state.items(),
                key=lambda kv: str((kv[1] or {}).get("last_attempt") or ""),
            )
            state = dict(items[-3500:])
        self.save_data("calendar_episode_search_v209", state)

    def _episode_ready_for_external_v209(
        self,
        sid: int,
        season: int,
        episode: int,
        air_date: str,
        *,
        force: bool = False,
    ) -> bool:
        if force:
            return True
        key = self._episode_state_key_v209(sid, season, episode, air_date)
        lock = getattr(self, "_episode_search_lock_v209", None) or threading.RLock()
        self._episode_search_lock_v209 = lock
        with lock:
            state = self._load_episode_search_state_v209()
            row = dict(state.get(key) or {})
            if bool(row.get("completed")):
                return False
            next_retry = str(row.get("next_retry_at") or "").strip()
            if not next_retry:
                return True
            try:
                ready_at = datetime.datetime.fromisoformat(next_retry)
            except ValueError:
                return True
            return datetime.datetime.now() >= ready_at

    def _mark_episode_attempt_v209(
        self,
        sid: int,
        season: int,
        episode: int,
        air_date: str,
        *,
        result: str,
        provider: str = "gying",
        completed: bool = False,
    ) -> None:
        key = self._episode_state_key_v209(sid, season, episode, air_date)
        now = datetime.datetime.now()
        lock = getattr(self, "_episode_search_lock_v209", None) or threading.RLock()
        self._episode_search_lock_v209 = lock
        with lock:
            state = self._load_episode_search_state_v209()
            row = dict(state.get(key) or {})
            attempts = int(row.get("attempts") or 0) + 1
            offsets = list(getattr(self, "_episode_retry_offsets_v209", (0, 1800, 5400)) or (0, 1800, 5400))
            if completed or result in {"success", "covered", "pending"}:
                next_retry_at = ""
                completed = True
            elif attempts >= len(offsets):
                # Wait for channel push or 21:00 reconcile.
                next_retry_at = (now + datetime.timedelta(hours=12)).isoformat(timespec="seconds")
            else:
                delay = int(offsets[min(attempts, len(offsets) - 1)])
                next_retry_at = (now + datetime.timedelta(seconds=delay)).isoformat(timespec="seconds")
            state[key] = {
                "last_attempt": now.isoformat(timespec="seconds"),
                "last_result": str(result or "")[:80],
                "next_retry_at": next_retry_at,
                "attempts": attempts,
                "completed": bool(completed),
                "provider": str(provider or "")[:40],
            }
            self._save_episode_search_state_v209(state)

    # ------------------------------------------------------------------
    # Precision-aware due window
    # ------------------------------------------------------------------
    def _episode_is_actively_due_v209(self, row: Dict[str, Any], now: datetime.datetime) -> bool:
        precision = str(row.get("precision") or "").strip().lower()
        air_at = self._episode_air_at_v1120(row)
        if air_at is None:
            return False
        if precision == "datetime" or str(row.get("air_at") or "").strip():
            early_minutes = 45
            return now >= (air_at - datetime.timedelta(minutes=early_minutes))
        # date-only: do not use the old 12-hour early GYING window.
        active_hour = int(getattr(self, "_calendar_date_active_hour_v209", 18) or 18)
        day = air_at.date()
        if now.date() < day:
            return False
        if now.date() > day:
            return True
        return now.hour >= active_hour

    def _subscription_episode_bounds_v209(self, subscribe: Any) -> Tuple[int, int]:
        try:
            start = max(1, int(getattr(subscribe, "start_episode", 0) or 1))
        except (TypeError, ValueError):
            start = 1
        try:
            total = max(0, int(getattr(subscribe, "total_episode", 0) or 0))
        except (TypeError, ValueError):
            total = 0
        return start, total

    def _library_existing_episodes_v209(self, subscribe: Any) -> Set[int]:
        """Emby/library success (including empty) wins; note only when library query failed."""
        # Prefer per-run context — do not open a second Emby query inside airing gate.
        getter = getattr(self, "_episode_run_context_for_subscribe_v211", None)
        if callable(getter):
            try:
                ctx = getter(subscribe)
            except Exception:
                ctx = None
            if isinstance(ctx, dict):
                if isinstance(ctx.get("library_sync"), dict):
                    sync = dict(ctx.get("library_sync") or {})
                    if bool(sync.get("success")):
                        return {int(v) for v in (sync.get("existing") or []) if int(v or 0) > 0}
                existing = ctx.get("library_existing")
                if existing is not None and str(ctx.get("library_state") or "") == "OK":
                    return {int(v) for v in (existing or []) if int(v or 0) > 0}
                snap = ctx.get("snapshot")
                if isinstance(snap, dict) and str(snap.get("library_state") or "") == "OK":
                    return {int(v) for v in (snap.get("emby_existing") or []) if int(v or 0) > 0}
        try:
            sync = dict(self._sync_media_library_progress(subscribe) or {})
            if bool(sync.get("success")):
                return {int(v) for v in (sync.get("existing") or []) if int(v or 0) > 0}
        except Exception:
            pass
        # Fail-soft UI only: never treat note as Emby truth for transfer targeting.
        try:
            notes = getattr(subscribe, "note", None) or []
            return {int(v) for v in notes if int(v or 0) > 0}
        except Exception:
            return set()

    def _split_calendar_due_future_v209(
        self,
        item: Dict[str, Any],
        subscribe: Any,
        now: datetime.datetime,
        *,
        candidate_episodes: Optional[Set[int]] = None,
    ) -> Dict[str, Any]:
        """Unify air_time <= now → due/aired; air_time > now → future; next from future only."""
        start, total = self._subscription_episode_bounds_v209(subscribe)
        due: Set[int] = set()
        future: Set[int] = set()
        air_dates: Dict[int, str] = {}
        future_air: Dict[int, datetime.datetime] = {}
        dated = 0
        for row in (item or {}).get("episodes") or []:
            if not isinstance(row, dict):
                continue
            try:
                episode = int(row.get("episode") or row.get("episode_number") or 0)
            except (TypeError, ValueError):
                continue
            if episode <= 0:
                continue
            if episode < start:
                continue
            if total and episode > total:
                continue
            if candidate_episodes is not None and episode not in candidate_episodes:
                continue
            air_at = self._episode_air_at_v1120(row)
            if air_at is None:
                continue
            dated += 1
            air_dates[episode] = str(row.get("air_date") or "")[:10] or air_at.strftime("%Y-%m-%d")
            # Past/present air times are always due candidates; future only when strictly later.
            if air_at <= now or self._episode_is_actively_due_v209(row, now):
                due.add(episode)
            else:
                future.add(episode)
                future_air[episode] = air_at
        next_episode = 0
        next_air_at = ""
        if future_air:
            episode, air_at = min(future_air.items(), key=lambda pair: (pair[1], pair[0]))
            next_episode = int(episode)
            next_air_at = air_at.isoformat(timespec="minutes")
        return {
            "due": due,
            "future": future,
            "air_dates": air_dates,
            "next_episode": next_episode,
            "next_air_at": next_air_at,
            "dated_count": dated,
            "calendar_available": dated > 0,
        }

    # ------------------------------------------------------------------
    # Gate: calendar due ∩ MP missing − reserved − claimed
    # ------------------------------------------------------------------
    def _airing_gate_v1120(self, subscribe: Any, payload: Dict[str, Any] = None) -> Dict[str, Any]:
        result = dict(super()._airing_gate_v1120(subscribe, payload=payload) or {})
        self._bump_metric_v209("calendar_checked")
        sid = int(getattr(subscribe, "id", 0) or 0)
        name = str(getattr(subscribe, "name", "") or "")
        season = int(getattr(subscribe, "season", 0) or 1)

        if self._is_movie_subscription(subscribe):
            return result

        missing_source, missing_mp = self._mp_authoritative_missing_episodes_v209(subscribe)
        result["missing_mp"] = sorted(missing_mp)
        result["missing_source"] = missing_source

        # True MP complete coverage only — decide before calendar I/O.
        # Emby actual gap still wins: stale MP complete / note must not skip forever.
        if missing_source == "used_complete" and not missing_mp:
            existing = self._library_existing_episodes_v209(subscribe)
            start, total = self._subscription_episode_bounds_v209(subscribe)
            bounds = set(range(start, total + 1)) if total >= start else set()
            emby_gap = bounds - existing if bounds else set()
            # Only trust MP complete when Emby also shows no gap with real coverage.
            library_ok_empty_gap = bool(bounds) and not emby_gap and bool(existing)
            if library_ok_empty_gap or (not bounds):
                result["due_missing"] = []
                result["due_uncovered"] = []
                result["target_episodes"] = []
                result["decision"] = "skip_complete"
                result["preflight_state"] = "SATISFIED"
                result["covered"] = True
                result["next_episode"] = 0
                result["next_air_at"] = ""
                self._bump_metric_v209("skipped_covered")
                self._plugin_log(
                    "INFO",
                    "【MP订阅日历】#%s %s S%02d existing=%s mp_missing=- calendar_due=- calendar_future=- "
                    "reserved=- claimed=- final_target=- state=SATISFIED decision=skip_complete provider=%s",
                    sid,
                    name,
                    season,
                    ",".join(f"E{int(v):02d}" for v in sorted(existing)) or "-",
                    str(result.get("calendar_provider") or missing_source or "-"),
                )
                return result
            # Fall through: MP says complete but Emby still has gaps / empty library.

        calendar = payload or self._refresh_airing_calendar_v1120(force=False)
        item = self._calendar_item_for_v1120(subscribe, calendar) or {}
        now = datetime.datetime.now()

        try:
            reservations = dict(self._pending_reservations(subscribe) or {})
            reserved = {int(v) for v in (reservations.get("episodes") or []) if int(v or 0) > 0}
        except Exception:
            reserved = set()
        try:
            claimed = {int(v) for v in (self._active_source_claims(sid) or []) if int(v or 0) > 0}
        except Exception:
            claimed = set()
        existing = self._library_existing_episodes_v209(subscribe)

        # Candidate universe: explicit MP missing, else subscription bounds / calendar.
        if missing_mp:
            candidates: Optional[Set[int]] = set(missing_mp)
        elif missing_source == "used_empty":
            candidates = None  # all in-bound calendar episodes
        else:
            candidates = set(missing_mp) if missing_mp else None

        split = self._split_calendar_due_future_v209(
            item, subscribe, now, candidate_episodes=candidates if missing_mp else None,
        )
        # When MP missing is empty/unknown, still evaluate full calendar due/future.
        if not missing_mp:
            split = self._split_calendar_due_future_v209(item, subscribe, now, candidate_episodes=None)

        due_calendar: Set[int] = set(split["due"])
        future_set: Set[int] = set(split["future"])
        air_dates: Dict[int, str] = dict(split["air_dates"])
        calendar_available = bool(split["calendar_available"]) or bool(item.get("episodes"))

        # Effective missing for targeting: Emby gap ∩ calendar due.
        # MP missing is auxiliary and must NOT hard-delete Emby+due gaps.
        start, total = self._subscription_episode_bounds_v209(subscribe)
        emby_gap = set(range(start, total + 1)) - existing if total >= start else set()
        if calendar_available and emby_gap:
            effective_missing = set(due_calendar).intersection(emby_gap)
        elif calendar_available and missing_mp:
            effective_missing = set(due_calendar).intersection(missing_mp)
        elif calendar_available:
            effective_missing = set(due_calendar) - existing
        else:
            effective_missing = set()

        target = set(effective_missing) - reserved - claimed
        # Never re-narrow with missing_mp intersection when Emby gap is known.

        ready_target: Set[int] = set()
        for episode in sorted(target):
            if self._episode_ready_for_external_v209(sid, season, episode, air_dates.get(episode, "")):
                ready_target.add(episode)
            else:
                self._bump_metric_v209("skipped_covered")

        result["due_calendar"] = sorted(due_calendar)
        result["due_missing"] = sorted(due_calendar.intersection(effective_missing or due_calendar))
        result["due_uncovered"] = sorted(ready_target)
        result["target_episodes"] = sorted(ready_target)
        result["reserved"] = sorted(reserved)
        result["claimed"] = sorted(claimed)
        result["future_missing"] = sorted(future_set)
        result["calendar_available"] = calendar_available or bool(result.get("calendar_available"))
        result["calendar_provider"] = str(item.get("provider") or result.get("calendar_provider") or "")
        result["episode_group"] = getattr(subscribe, "episode_group", None)
        result["library_existing"] = sorted(existing)
        result["next_episode"] = int(split.get("next_episode") or 0)
        result["next_air_at"] = str(split.get("next_air_at") or "")
        result["covered"] = not ready_target

        # UNKNOWN: empty MP list, no trustworthy calendar dates, no positive coverage.
        if not missing_mp and missing_source != "used_complete" and not calendar_available:
            result["decision"] = "continue_match"
            result["preflight_state"] = "UNKNOWN"
            result["covered"] = False
            self._plugin_log(
                "INFO",
                "【MP订阅日历】#%s %s S%02d existing=%s mp_missing=- calendar_due=- calendar_future=- "
                "reserved=%s claimed=%s final_target=- state=UNKNOWN "
                "reason=mp_missing_empty_without_coverage_evidence decision=continue_match provider=%s",
                sid,
                name,
                season,
                ",".join(f"E{int(v):02d}" for v in sorted(existing)) or "-",
                ",".join(f"E{int(v):02d}" for v in sorted(reserved)) or "-",
                ",".join(f"E{int(v):02d}" for v in sorted(claimed)) or "-",
                str(result.get("calendar_provider") or missing_source or "-"),
            )
            return result

        if ready_target:
            result["decision"] = "search_due"
            result["preflight_state"] = "MISSING"
            result["covered"] = False
            self._bump_metric_v209("due_subscriptions")
            self._bump_metric_v209("due_episodes", len(ready_target))
            self._plugin_log(
                "INFO",
                "【MP订阅日历】#%s %s S%02d existing=%s mp_missing=%s calendar_due=%s calendar_future=%s "
                "reserved=%s claimed=%s final_target=%s state=MISSING decision=%s provider=%s",
                sid,
                name,
                season,
                ",".join(f"E{int(v):02d}" for v in sorted(existing)) or "-",
                ",".join(f"E{int(v):02d}" for v in sorted(missing_mp)) or "-",
                ",".join(f"E{int(v):02d}" for v in sorted(due_calendar)) or "-",
                ",".join(f"E{int(v):02d}" for v in sorted(future_set)) or "-",
                ",".join(f"E{int(v):02d}" for v in sorted(reserved)) or "-",
                ",".join(f"E{int(v):02d}" for v in sorted(claimed)) or "-",
                ",".join(f"E{int(v):02d}" for v in sorted(ready_target)) or "-",
                result["decision"],
                str(result.get("calendar_provider") or "moviepilot_native"),
            )
            return result

        # No ready targets: either caught up with future remaining, or truly complete.
        if future_set:
            result["decision"] = "skip_future"
            result["preflight_state"] = "SATISFIED"
            self._bump_metric_v209("skipped_future")
            self._plugin_log(
                "INFO",
                "【MP订阅日历】#%s %s existing=%s mp_missing=%s calendar_due=%s calendar_future=%s "
                "final_target=- state=SATISFIED decision=skip_future next_future=E%s @ %s",
                sid,
                name,
                ",".join(f"E{int(v):02d}" for v in sorted(existing)) or "-",
                ",".join(f"E{int(v):02d}" for v in sorted(missing_mp)) or "-",
                ",".join(f"E{int(v):02d}" for v in sorted(due_calendar)) or "-",
                ",".join(f"E{int(v):02d}" for v in sorted(future_set)) or "-",
                f"{int(result.get('next_episode') or 0):02d}" if result.get("next_episode") else "--",
                str(result.get("next_air_at") or "未知"),
            )
            return result

        if missing_mp and not due_calendar and not future_set:
            # Explicit missing remains but calendar couldn't classify — continue matching.
            result["decision"] = "continue_match"
            result["preflight_state"] = "UNKNOWN"
            result["covered"] = False
            result["target_episodes"] = sorted(set(missing_mp) - reserved - claimed)
            result["due_uncovered"] = list(result["target_episodes"])
            self._plugin_log(
                "INFO",
                "【MP订阅日历】#%s %s mp_missing=%s calendar unavailable/undated state=UNKNOWN decision=continue_match",
                sid,
                name,
                ",".join(f"E{int(v):02d}" for v in sorted(missing_mp)) or "-",
            )
            return result

        # Due aired but not yet ready / not covered — never claim complete on used_empty.
        pending_due = set(due_calendar) - existing - reserved - claimed
        if missing_source in {"used_empty", "fallback"} and pending_due:
            result["decision"] = "continue_match"
            result["preflight_state"] = "MISSING"
            result["covered"] = False
            result["target_episodes"] = sorted(pending_due)
            result["due_uncovered"] = sorted(pending_due)
            self._plugin_log(
                "INFO",
                "【MP订阅日历】#%s %s S%02d existing=%s mp_missing=- calendar_due=%s calendar_future=%s "
                "reserved=%s claimed=%s final_target=%s state=MISSING "
                "reason=due_pending_without_ready decision=continue_match provider=%s",
                sid,
                name,
                season,
                ",".join(f"E{int(v):02d}" for v in sorted(existing)) or "-",
                ",".join(f"E{int(v):02d}" for v in sorted(due_calendar)) or "-",
                ",".join(f"E{int(v):02d}" for v in sorted(future_set)) or "-",
                ",".join(f"E{int(v):02d}" for v in sorted(reserved)) or "-",
                ",".join(f"E{int(v):02d}" for v in sorted(claimed)) or "-",
                ",".join(f"E{int(v):02d}" for v in sorted(pending_due)) or "-",
                str(result.get("calendar_provider") or missing_source or "-"),
            )
            return result

        # Covered current due with no future: only then skip_complete.
        result["decision"] = "skip_complete"
        result["preflight_state"] = "SATISFIED"
        self._plugin_log(
            "INFO",
            "【MP订阅日历】#%s %s S%02d existing=%s mp_missing=%s calendar_due=%s reserved=%s claimed=%s "
            "final_target=- state=SATISFIED decision=skip_complete provider=%s",
            sid,
            name,
            season,
            ",".join(f"E{int(v):02d}" for v in sorted(existing)) or "-",
            ",".join(f"E{int(v):02d}" for v in sorted(missing_mp)) or "-",
            ",".join(f"E{int(v):02d}" for v in sorted(due_calendar)) or "-",
            ",".join(f"E{int(v):02d}" for v in sorted(reserved)) or "-",
            ",".join(f"E{int(v):02d}" for v in sorted(claimed)) or "-",
            str(result.get("calendar_provider") or missing_source or "-"),
        )
        return result

    # ------------------------------------------------------------------
    # Daytime selector: calendar failure must NOT open all-missing GYING
    # ------------------------------------------------------------------
    def _smart_pull_due_ids_v1125(self) -> List[int]:
        rows = self._active_selected_subscriptions_v1125()
        try:
            state = dict(self._external_search_state_v1114() or {})
        except Exception:
            state = {}
        now = time.time()

        cooldown_rows = []
        for subscribe in rows:
            sid = int(getattr(subscribe, "id", 0) or 0)
            if sid <= 0:
                continue
            checker = getattr(self, "_external_cooldown_due_v1125", None)
            try:
                if callable(checker) and not checker(sid, state, now):
                    self._plugin_log(
                        "INFO",
                        "【主动检索选择】sid=%s state=- decision=- cooldown_due=False selected=False",
                        sid,
                    )
                    continue
            except Exception as err:
                self._plugin_log(
                    "WARNING",
                    "【检索治理异常】sid=%s checker=_external_cooldown_due_v1125 exception_type=%s detail=%s",
                    sid,
                    type(err).__name__,
                    str(err)[:220],
                )
                # Fail closed: skip this sid for this tick rather than bypass cooldown.
                continue
            cooldown_rows.append(subscribe)
        if not cooldown_rows:
            return []

        calendar: Optional[Dict[str, Any]] = None
        calendar_failed = False
        if any(not self._is_movie_subscription(subscribe) for subscribe in cooldown_rows):
            try:
                calendar = dict(self._refresh_airing_calendar_v1120(force=False) or {})
            except Exception:
                calendar = None
                calendar_failed = True

        due: List[int] = []
        for subscribe in cooldown_rows:
            sid = int(getattr(subscribe, "id", 0) or 0)
            if sid <= 0:
                continue
            media = str(getattr(subscribe, "name", "") or "")[:120]
            if self._is_movie_subscription(subscribe):
                selected = bool(self._movie_needs_pull_v1125(subscribe))
                self._plugin_log(
                    "INFO",
                    "【主动检索选择】sid=%s media=%s state=MOVIE decision=movie_needs_pull "
                    "target_episodes=- due_uncovered=- cooldown_due=True selected=%s",
                    sid,
                    media or "-",
                    selected,
                )
                if selected:
                    due.append(sid)
                continue
            if calendar_failed or calendar is None:
                # Fail-safe daytime: no active external search; channel push still runs elsewhere.
                self._plugin_log(
                    "INFO",
                    "【主动检索选择】sid=%s media=%s state=UNKNOWN decision=calendar_unavailable "
                    "target_episodes=- due_uncovered=- cooldown_due=True selected=False",
                    sid,
                    media or "-",
                )
                continue
            try:
                gate = dict(self._airing_gate_v1120(subscribe, payload=calendar) or {})
            except Exception as err:
                self._plugin_log(
                    "WARNING",
                    "【检索治理异常】sid=%s checker=_airing_gate_v1120 exception_type=%s detail=%s",
                    sid,
                    type(err).__name__,
                    str(err)[:220],
                )
                continue

            decision = str(gate.get("decision") or "")
            preflight = str(gate.get("preflight_state") or "")
            targets = self._positive_ids_v1125(gate.get("target_episodes") or [])
            due_eps = self._positive_ids_v1125(gate.get("due_uncovered") or [])
            final_eps = self._positive_ids_v1125(gate.get("final_target") or [])
            has_targets = bool(due_eps or targets or final_eps)
            # MISSING with targets only. UNKNOWN/continue_match with empty target → no GYING.
            selected = False
            if decision in {"search", "search_due", "search_missing", "search_mp_calendar_fallback", "search_mp_missing_fallback"} and has_targets:
                selected = True
            elif preflight == "MISSING" and has_targets:
                selected = True
            elif decision == "unknown_no_due_target":
                selected = False
            elif (decision == "continue_match" or preflight == "UNKNOWN") and has_targets:
                selected = True
            elif decision in {"skip_future", "skip_complete"} or preflight == "SATISFIED":
                selected = False
            elif has_targets:
                selected = True

            self._plugin_log(
                "INFO",
                "【主动检索选择】sid=%s media=%s state=%s decision=%s target_episodes=%s "
                "due_uncovered=%s cooldown_due=True selected=%s",
                sid,
                media or "-",
                preflight or "-",
                decision or "-",
                ",".join(str(v) for v in targets) or "-",
                ",".join(str(v) for v in due_eps) or "-",
                selected,
            )
            if selected:
                due.append(sid)
        return sorted(set(due))

    # ------------------------------------------------------------------
    # Daily 21:00 reconcile
    # ------------------------------------------------------------------
    def _daily_reconcile_remaining_v209(self, subscribe: Any, calendar: Dict[str, Any]) -> bool:
        if self._is_movie_subscription(subscribe):
            return bool(self._movie_needs_pull_v1125(subscribe))

        missing_source, missing_mp = self._mp_authoritative_missing_episodes_v209(subscribe)
        if not missing_mp:
            # Empty list is not complete unless MP explicitly reported coverage.
            if missing_source == "used_complete":
                return False
            if missing_source in {"used_empty", "fallback"}:
                return True
            return False
        try:
            reservations = dict(self._pending_reservations(subscribe) or {})
            reserved = {int(v) for v in (reservations.get("episodes") or []) if int(v or 0) > 0}
        except Exception:
            reserved = set()
        sid = int(getattr(subscribe, "id", 0) or 0)
        try:
            claimed = {int(v) for v in (self._active_source_claims(sid) or []) if int(v or 0) > 0}
        except Exception:
            claimed = set()
        uncovered = set(missing_mp) - reserved - claimed
        if not uncovered:
            return False

        item = self._calendar_item_for_v1120(subscribe, calendar) or {}
        now = datetime.datetime.now()
        future_only: Set[int] = set()
        scheduled: Set[int] = set()
        past_aired: Set[int] = set()
        for row in item.get("episodes") or []:
            if not isinstance(row, dict):
                continue
            try:
                episode = int(row.get("episode") or 0)
            except (TypeError, ValueError):
                continue
            if episode <= 0:
                continue
            scheduled.add(episode)
            air_at = self._episode_air_at_v1120(row)
            if air_at is None:
                continue
            if air_at.date() > now.date():
                future_only.add(episode)
            elif air_at.date() < now.date() or self._episode_is_actively_due_v209(row, now):
                past_aired.add(episode)

        # Today due / past aired / unscheduled historical gaps stay; pure future is skipped.
        remaining = set()
        for episode in uncovered:
            if episode in future_only and episode not in past_aired:
                continue
            if episode in scheduled and episode in future_only:
                continue
            # Unscheduled: include if any later episode already aired (overdue gap).
            if episode not in scheduled:
                if past_aired and episode < max(past_aired):
                    remaining.add(episode)
                elif not scheduled:
                    remaining.add(episode)
                continue
            remaining.add(episode)
        _ = missing_source
        return bool(remaining)

    def _daily_full_catchup_v1110(self) -> Dict[str, Any]:
        started = datetime.datetime.now()
        # Phase 0: refresh native calendar facts once.
        try:
            calendar = dict(self._refresh_airing_calendar_v1120(force=True) or {})
        except Exception as err:
            self._plugin_log(
                "WARNING",
                "【每日21点兜底】日历刷新失败，允许 DailyAssistant/TMDB fallback：%s",
                str(err)[:220],
            )
            try:
                calendar = dict(super()._refresh_airing_calendar_v1120(force=True) or {})
            except Exception:
                calendar = {"subscriptions": []}

        try:
            self.refresh_channels(force=True)
        except Exception as err:
            self._plugin_log(
                "WARNING",
                "【每日21点兜底】频道强制刷新失败，继续使用缓存：%s",
                str(err)[:220],
            )

        initial_rows = self._active_selected_subscriptions_v1125()
        initial_ids = [int(getattr(subscribe, "id", 0) or 0) for subscribe in initial_rows]
        movie_n = sum(1 for s in initial_rows if self._is_movie_subscription(s))
        tv_n = max(0, len(initial_rows) - movie_n)
        self._plugin_log(
            "INFO",
            "【每日21点兜底】managed=%s movie=%s tv=%s",
            len(initial_rows),
            movie_n,
            tv_n,
        )

        # Phase 1: channel only, no GYING.
        covered_after_channel = 0
        if initial_ids:
            self._run_v1115_mode_batch(initial_ids, "每日21点兜底·频道阶段", "channel_event", force=False)

        # Phase 2: recompute remaining (exclude pure future + pending covered).
        remaining: List[int] = []
        future_skipped = pending_skipped = 0
        for subscribe in self._active_selected_subscriptions_v1125():
            sid = int(getattr(subscribe, "id", 0) or 0)
            fresh = self._find_subscription(sid) or subscribe
            if self._is_movie_subscription(fresh):
                if self._movie_needs_pull_v1125(fresh):
                    # pending/reservation/source claim already handled inside movie_needs_pull
                    remaining.append(sid)
                else:
                    covered_after_channel += 1
                continue
            try:
                reservations = dict(self._pending_reservations(fresh) or {})
                reserved = {int(v) for v in (reservations.get("episodes") or []) if int(v or 0) > 0}
            except Exception:
                reserved = set()
            try:
                claimed = {int(v) for v in (self._active_source_claims(sid) or []) if int(v or 0) > 0}
            except Exception:
                claimed = set()
            _, missing_mp = self._mp_authoritative_missing_episodes_v209(fresh)
            if not missing_mp:
                covered_after_channel += 1
                continue
            if missing_mp and missing_mp.issubset(reserved.union(claimed)):
                pending_skipped += 1
                continue
            if self._daily_reconcile_remaining_v209(fresh, calendar):
                remaining.append(sid)
            else:
                # either covered or future-only
                gate = {}
                try:
                    gate = dict(self._airing_gate_v1120(fresh, payload=calendar) or {})
                except Exception:
                    gate = {}
                if gate.get("decision") == "skip_future" or gate.get("future_missing"):
                    future_skipped += 1
                else:
                    covered_after_channel += 1

        self._plugin_log(
            "INFO",
            "【每日21点兜底】阶段1频道：checked=%s covered=%s；阶段2真实缺口：remaining=%s future_skipped=%s pending_skipped=%s",
            len(initial_ids),
            covered_after_channel,
            len(remaining),
            future_skipped,
            pending_skipped,
        )
        self._bump_metric_v209("daily_reconcile_remaining", len(remaining))

        # Phase 3: GYING only for remaining, force=True, bounded concurrency.
        gying_success = 0
        if remaining:
            self._run_v1115_mode_batch(
                remaining,
                "每日21点兜底·GYING阶段",
                "daily_repair_pull",
                force=True,
            )
            for sid in remaining:
                subscribe = self._find_subscription(sid)
                if not subscribe:
                    continue
                if self._is_movie_subscription(subscribe):
                    if not self._movie_needs_pull_v1125(subscribe):
                        gying_success += 1
                else:
                    _, missing_mp = self._mp_authoritative_missing_episodes_v209(subscribe)
                    if not missing_mp:
                        gying_success += 1

        still_missing = max(0, len(remaining) - gying_success)
        self._plugin_log(
            "INFO",
            "【每日21点兜底】阶段3GYING：attempted=%s success=%s still_missing=%s elapsed=%ss",
            len(remaining),
            gying_success,
            still_missing,
            int((datetime.datetime.now() - started).total_seconds()),
        )
        payload = {
            "at": started.isoformat(timespec="seconds"),
            "managed": len(initial_ids),
            "movie": movie_n,
            "tv": tv_n,
            "channel_checked": len(initial_ids),
            "channel_covered": covered_after_channel,
            "remaining": len(remaining),
            "future_skipped": future_skipped,
            "pending_skipped": pending_skipped,
            "gying_attempted": len(remaining),
            "gying_success": gying_success,
            "still_missing": still_missing,
            "cron": str(getattr(self, "_daily_reconcile_cron_v209", "0 21 * * *")),
        }
        try:
            self.save_data("daily_reconcile_v209", payload)
        except Exception:
            pass
        return payload

    def _run_v1115_mode_batch(self, batch: List[int], trigger: str, mode: str, force: bool = False) -> None:
        if str(mode) != "daily_repair_pull":
            return super()._run_v1115_mode_batch(batch, trigger, mode, force=force)
        # Bound concurrent GYING work across nested workers using a process-local semaphore.
        # The default batch loop is sequential; this still protects overlapping reconcile/airing.
        slot = getattr(self, "_gying_slot_v209", None)
        if slot is None:
            slot = threading.Semaphore(int(self._gying_concurrency_v209 or 2))
            self._gying_slot_v209 = slot
        for sid in list(batch or []):
            if not self._runtime_is_current() or not self._enabled:
                return
            with slot:
                self._bump_metric_v209("external_searches")
                self._bump_metric_v209("gying_queries")
                started = time.monotonic()
                try:
                    super()._run_v1115_mode_batch([sid], trigger, mode, force=force)
                finally:
                    budget = float(getattr(self, "_external_search_budget_seconds_v209", 90) or 90)
                    elapsed = time.monotonic() - started
                    if elapsed > budget:
                        self._plugin_log(
                            "WARNING",
                            "【每日21点兜底】#%s 单订阅 external search 超时预算=%ss 实际=%.1fs",
                            sid,
                            int(budget),
                            elapsed,
                        )


__all__ = ["GuangYaCalendarDrivenV209Mixin"]
