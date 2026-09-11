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
        """Return (source, missing_episodes). source is used|fallback."""
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
                        return "used", set()
                    season = int(getattr(subscribe, "season", 0) or 0)
                    missing: Set[int] = set()
                    for season_map in (no_exists or {}).values():
                        if not isinstance(season_map, dict):
                            continue
                        detail = season_map.get(season)
                        if detail is None:
                            detail = season_map.get(str(season))
                        if detail is None:
                            continue
                        episodes = getattr(detail, "episodes", None)
                        if episodes is None and isinstance(detail, dict):
                            episodes = detail.get("episodes")
                        for value in episodes or []:
                            try:
                                episode = int(value)
                            except (TypeError, ValueError):
                                continue
                            if episode > 0:
                                missing.add(episode)
                    return "used", missing
            except Exception as err:
                self._plugin_log(
                    "WARNING",
                    "【光鸭转存助手】【MP订阅日历】resolve_subscribe_missing 不可用，回退媒体库同步：%s",
                    str(err)[:220],
                )

        # Fallback: existing library sync + logical missing intersection.
        try:
            sync = dict(self._sync_media_library_progress(subscribe) or {})
            library_missing = {
                int(v) for v in (sync.get("missing") or []) if int(v or 0) > 0
            }
        except Exception:
            library_missing = set()
        try:
            logical = set(self._raw_subscription_missing_v1120(subscribe) or [])
        except Exception:
            logical = set()
        if library_missing and logical:
            return "fallback", set(library_missing).intersection(logical)
        return "fallback", set(library_missing or logical)

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

        if not missing_mp:
            result["due_missing"] = []
            result["due_uncovered"] = []
            result["target_episodes"] = []
            result["decision"] = "skip_complete"
            result["covered"] = True
            self._bump_metric_v209("skipped_covered")
            self._plugin_log(
                "INFO",
                "【MP订阅日历】#%s %s S%02d 今日应播=%s MP真实缺失=- reserved=- claimed=- 最终目标=- decision=skip_complete provider=%s",
                sid,
                name,
                season,
                ",".join(f"E{int(v):02d}" for v in (result.get("due_missing") or [])) or "-",
                str(result.get("calendar_provider") or missing_source or "-"),
            )
            return result

        # Recompute due with precision rules, then intersect MP missing.
        calendar = payload or self._refresh_airing_calendar_v1120(force=False)
        item = self._calendar_item_for_v1120(subscribe, calendar) or {}
        now = datetime.datetime.now()
        due_calendar: Set[int] = set()
        future_map: Dict[int, str] = {}
        air_dates: Dict[int, str] = {}
        for row in item.get("episodes") or []:
            if not isinstance(row, dict):
                continue
            try:
                episode = int(row.get("episode") or row.get("episode_number") or 0)
            except (TypeError, ValueError):
                continue
            if episode <= 0 or episode not in missing_mp:
                continue
            air_dates[episode] = str(row.get("air_date") or "")[:10]
            if self._episode_is_actively_due_v209(row, now):
                due_calendar.add(episode)
            else:
                air_at = self._episode_air_at_v1120(row)
                future_map[episode] = air_at.strftime("%m-%d") if air_at else "?"

        try:
            reservations = dict(self._pending_reservations(subscribe) or {})
            reserved = {int(v) for v in (reservations.get("episodes") or []) if int(v or 0) > 0}
        except Exception:
            reserved = set()
        try:
            claimed = {int(v) for v in (self._active_source_claims(sid) or []) if int(v or 0) > 0}
        except Exception:
            claimed = set()

        target = set(due_calendar).intersection(missing_mp) - reserved - claimed
        # Episode backoff: drop not-ready episodes from active external targets.
        ready_target: Set[int] = set()
        for episode in sorted(target):
            if self._episode_ready_for_external_v209(sid, season, episode, air_dates.get(episode, "")):
                ready_target.add(episode)
            else:
                self._bump_metric_v209("skipped_covered")

        result["due_calendar"] = sorted(due_calendar)
        result["due_missing"] = sorted(due_calendar.intersection(missing_mp))
        result["due_uncovered"] = sorted(ready_target)
        result["target_episodes"] = sorted(ready_target)
        result["reserved"] = sorted(reserved.intersection(missing_mp))
        result["claimed"] = sorted(claimed.intersection(missing_mp))
        result["future_missing"] = sorted(set(future_map) | set(result.get("future_missing") or []))
        result["calendar_available"] = bool(item.get("episodes")) or bool(result.get("calendar_available"))
        result["calendar_provider"] = str(item.get("provider") or result.get("calendar_provider") or "")
        result["episode_group"] = getattr(subscribe, "episode_group", None)
        result["covered"] = not ready_target

        if not ready_target and future_map:
            result["decision"] = "skip_future"
            self._bump_metric_v209("skipped_future")
            self._plugin_log(
                "INFO",
                "【MP订阅日历】#%s %s 当前缺失=%s 今日应播=- 未来=%s decision=skip_future",
                sid,
                name,
                ",".join(f"E{int(v):02d}" for v in sorted(missing_mp)) or "-",
                ",".join(f"E{ep:02d}@{future_map[ep]}" for ep in sorted(future_map)) or "-",
            )
        elif not ready_target:
            result["decision"] = "skip_complete"
            self._plugin_log(
                "INFO",
                "【MP订阅日历】#%s %s 今日应播=%s MP真实缺失=%s reserved=%s claimed=%s 最终目标=- decision=skip_complete provider=%s",
                sid,
                name,
                ",".join(f"E{int(v):02d}" for v in sorted(due_calendar)) or "-",
                ",".join(f"E{int(v):02d}" for v in sorted(missing_mp)) or "-",
                ",".join(f"E{int(v):02d}" for v in sorted(reserved.intersection(missing_mp))) or "-",
                ",".join(f"E{int(v):02d}" for v in sorted(claimed.intersection(missing_mp))) or "-",
                str(result.get("calendar_provider") or missing_source or "-"),
            )
        else:
            result["decision"] = "search"
            self._bump_metric_v209("due_subscriptions")
            self._bump_metric_v209("due_episodes", len(ready_target))
            self._plugin_log(
                "INFO",
                "【MP订阅日历】#%s %s S%02d 今日应播=%s MP真实缺失=%s reserved=%s claimed=%s 最终目标=%s provider=%s",
                sid,
                name,
                season,
                ",".join(f"E{int(v):02d}" for v in sorted(due_calendar)) or "-",
                ",".join(f"E{int(v):02d}" for v in sorted(missing_mp)) or "-",
                ",".join(f"E{int(v):02d}" for v in sorted(reserved.intersection(missing_mp))) or "-",
                ",".join(f"E{int(v):02d}" for v in sorted(claimed.intersection(missing_mp))) or "-",
                ",".join(f"E{int(v):02d}" for v in sorted(ready_target)) or "-",
                str(result.get("calendar_provider") or "moviepilot_native"),
            )
        return result

    # ------------------------------------------------------------------
    # Daytime selector: calendar failure must NOT open all-missing GYING
    # ------------------------------------------------------------------
    def _smart_pull_due_ids_v1125(self) -> List[int]:
        rows = self._active_selected_subscriptions_v1125()
        cooldown_rows = []
        for subscribe in rows:
            checker = getattr(self, "_external_cooldown_due_v1125", None)
            try:
                if callable(checker) and not checker(subscribe):
                    continue
            except Exception:
                pass
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
            if self._is_movie_subscription(subscribe):
                if self._movie_needs_pull_v1125(subscribe):
                    due.append(sid)
                continue
            if calendar_failed or calendar is None:
                # Fail-safe daytime: no active external search; channel push still runs elsewhere.
                continue
            try:
                gate = dict(self._airing_gate_v1120(subscribe, payload=calendar) or {})
            except Exception:
                continue
            if self._positive_ids_v1125(gate.get("due_uncovered") or gate.get("target_episodes") or []):
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
