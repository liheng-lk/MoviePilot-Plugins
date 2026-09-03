"""光鸭转存助手 v1.12.0：每日助手逐集日历驱动的 due_missing 调度层。

核心目标：
- 不再把 MoviePilot 的“总缺集”直接当成“现在就该搜索的集”；
- 优先读取运行中的每日助手整季日历，缺失时用 MoviePilot TMDB season detail 回退；
- 普通后台轮次只允许 ``due_missing`` 进入光鸭/迅雷/Magnet/ED2K；未来集不访问外部资源站；
- 提前 12 小时进入到期窗口，兼顾资源偷跑；每天一次全员复核仍允许完整缺集搜索；
- 同订阅整条来源链共用 v1.10.24 的 RLock，修复“刚打印冷却、几秒后另一线程又搜索”的竞争；
- 修复旧分享 ``handled=True`` 被误当成“全部缺集已覆盖”：只要 due gap 仍存在就继续 Magnet/ED2K。

日期精度说明：TMDB 标准季详情只有 air_date 时，使用本机时区的默认 20:00 作为估算上映时刻；
数据源若提供 air_at 则按精确时间执行。估算值明确标记 precision=date，不伪装成官方精确时刻。
"""
from __future__ import annotations

import datetime
from contextlib import contextmanager, nullcontext
from typing import Any, Dict, Iterable, List, Optional, Set

from app.chain.media import MediaChain
from app.schemas.types import MediaSource, MediaType
from app.sdk.plugins import PluginManager


class GuangYaAiringSchedulerV1120Mixin:
    """更新日历 -> due_missing -> 来源执行的最外层调度权威。"""

    plugin_version = "1.12.0"
    build_id = "20260903-r44"
    _calendar_refresh_hours_v1120 = 6
    _calendar_default_hour_v1120 = 20
    _calendar_early_hours_v1120 = 12

    def init_plugin(self, config: dict = None) -> None:
        config = dict(config or {})
        try:
            self._calendar_default_hour_v1120 = max(0, min(23, int(config.get("calendar_default_hour", 20) or 20)))
        except (TypeError, ValueError):
            self._calendar_default_hour_v1120 = 20
        try:
            self._calendar_early_hours_v1120 = max(0, min(72, int(config.get("calendar_early_hours", 12) or 12)))
        except (TypeError, ValueError):
            self._calendar_early_hours_v1120 = 12
        self._airing_due_scope_v1120: Optional[Dict[str, Any]] = None
        self._airing_due_force_v1120 = False
        return super().init_plugin(config)

    @staticmethod
    def _calendar_value_v1120(obj: Any, field: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(field, default)
        return getattr(obj, field, default)

    @staticmethod
    def _positive_int_set_v1120(values: Iterable[Any]) -> Set[int]:
        result: Set[int] = set()
        for raw in values or []:
            try:
                value = int(raw or 0)
            except (TypeError, ValueError):
                continue
            if value > 0:
                result.add(value)
        return result

    def _calendar_requests_v1120(self) -> List[Dict[str, Any]]:
        selected = {
            int(value) for value in (getattr(self, "_selected_subscriptions", []) or [])
            if str(value).isdigit() and int(value) > 0
        }
        rows: List[Dict[str, Any]] = []
        for subscribe in self._list_subscriptions(None) or []:
            sid = int(getattr(subscribe, "id", 0) or 0)
            if sid not in selected or self._is_movie_subscription(subscribe):
                continue
            if str(getattr(subscribe, "state", "") or "") not in {"N", "R"}:
                continue
            tmdb_id = str(self._subscription_tmdb_id_v1110(subscribe) or "").strip()
            if not tmdb_id.isdigit():
                continue
            try:
                season = int(getattr(subscribe, "season", 0) or 1)
            except (TypeError, ValueError):
                season = 1
            rows.append({
                "subscribe_id": sid,
                "title": str(getattr(subscribe, "name", "") or ""),
                "year": str(getattr(subscribe, "year", "") or ""),
                "tmdb_id": tmdb_id,
                "season": max(1, season),
            })
        return rows

    @staticmethod
    def _calendar_episode_rows_v1120(detail: Any, season: int) -> List[Dict[str, Any]]:
        episodes = detail.get("episodes") if isinstance(detail, dict) else getattr(detail, "episodes", [])
        rows: List[Dict[str, Any]] = []
        for raw in episodes or []:
            getter = raw.get if isinstance(raw, dict) else lambda key, default=None: getattr(raw, key, default)
            try:
                episode = int(getter("episode_number", 0) or 0)
            except (TypeError, ValueError):
                episode = 0
            try:
                season_number = int(getter("season_number", season) or season)
            except (TypeError, ValueError):
                season_number = season
            if episode <= 0 or season_number != season:
                continue
            air_date = str(getter("air_date", "") or "").strip()
            air_at = str(
                getter("air_at", "")
                or getter("air_datetime", "")
                or getter("release_at", "")
                or ""
            ).strip()
            if "T" in air_date and not air_at:
                air_at = air_date
                air_date = air_date[:10]
            elif air_date:
                air_date = air_date[:10]
            rows.append({
                "episode": episode,
                "season": season_number,
                "air_date": air_date,
                "air_at": air_at,
                "precision": "datetime" if air_at else ("date" if air_date else "unknown"),
                "name": str(getter("name", "") or "")[:180],
            })
        rows.sort(key=lambda row: int(row.get("episode") or 0))
        return rows

    def _calendar_local_fallback_v1120(self, request: Dict[str, Any], force: bool) -> Dict[str, Any]:
        chain = MediaChain()
        tmdb_id = str(request.get("tmdb_id") or "")
        season = int(request.get("season") or 1)
        episodes: List[Dict[str, Any]] = []
        error = ""
        try:
            detail = chain.tmdb_info(tmdbid=int(tmdb_id), mtype=MediaType.TV, season=season)
            episodes = self._calendar_episode_rows_v1120(detail or {}, season)
        except Exception as err:
            error = str(err)[:220]
        if not episodes:
            try:
                try:
                    info = chain.recognize_media(
                        mtype=MediaType.TV,
                        media_source=MediaSource.TMDB,
                        media_id=tmdb_id,
                        cache=not force,
                    )
                except TypeError:
                    info = chain.recognize_media(
                        mtype=MediaType.TV,
                        media_source=MediaSource.TMDB,
                        media_id=tmdb_id,
                    )
            except Exception as err:
                info = None
                error = error or str(err)[:220]
            next_episode = getattr(info, "next_episode_to_air", None) if info else None
            if next_episode:
                episodes = self._calendar_episode_rows_v1120({"episodes": [next_episode]}, season)
        return {
            **request,
            "episodes": episodes,
            "episode_count": len(episodes),
            "provider": "guangya_tmdb_fallback",
            "fetched_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "error": error,
        }

    @staticmethod
    def _calendar_stale_v1120(payload: Dict[str, Any]) -> bool:
        try:
            updated = datetime.datetime.fromisoformat(str(payload.get("updated_at") or ""))
        except (TypeError, ValueError):
            return True
        return datetime.datetime.now() - updated >= datetime.timedelta(
            hours=GuangYaAiringSchedulerV1120Mixin._calendar_refresh_hours_v1120
        )

    def _dailyassistant_calendar_v1120(
        self,
        requests: List[Dict[str, Any]],
        force: bool,
    ) -> Dict[int, Dict[str, Any]]:
        try:
            manager = PluginManager()
            running = getattr(manager, "running_plugins", None) or {}
            daily = running.get("DailyAssistant") if isinstance(running, dict) else None
        except Exception:
            daily = None
        provider = getattr(daily, "get_airing_schedule_snapshot", None) if daily else None
        if not callable(provider):
            return {}
        try:
            snapshot = dict(provider(requests=requests, force=force) or {})
        except TypeError:
            snapshot = dict(provider(requests, force=force) or {})
        except Exception as err:
            self._plugin_log("WARNING", "【光鸭转存助手】【更新日历】读取每日助手逐集日历失败，回退 MoviePilot TMDB：%s", err)
            return {}
        result: Dict[int, Dict[str, Any]] = {}
        for item in snapshot.get("items") or []:
            if not isinstance(item, dict):
                continue
            sid = int(item.get("subscribe_id") or 0)
            if sid > 0:
                result[sid] = dict(item)
        return result

    def _refresh_airing_calendar_v1120(self, force: bool = False) -> Dict[str, Any]:
        current = self.get_data("airing_calendar_v1120") or {}
        if (
            not force
            and isinstance(current, dict)
            and current.get("subscriptions")
            and not self._calendar_stale_v1120(current)
        ):
            return current

        requests = self._calendar_requests_v1120()
        daily_rows = self._dailyassistant_calendar_v1120(requests, force=force)
        subscriptions: List[Dict[str, Any]] = []
        daily_count = fallback_count = 0
        errors: List[str] = []
        for request in requests:
            sid = int(request.get("subscribe_id") or 0)
            item = daily_rows.get(sid)
            if item and list(item.get("episodes") or []):
                row = {**request, **item}
                row["provider"] = str(item.get("provider") or "dailyassistant")
                daily_count += 1
            else:
                row = self._calendar_local_fallback_v1120(request, force=force)
                fallback_count += 1
            if row.get("error"):
                errors.append(f"#{sid} {request.get('title')}: {row.get('error')}")
            subscriptions.append(row)

        payload = {
            "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "count": len(subscriptions),
            "dailyassistant": daily_count,
            "fallback": fallback_count,
            "subscriptions": subscriptions,
            "errors": errors[:30],
        }
        self.save_data("airing_calendar_v1120", payload)
        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【更新日历v2】逐集日历刷新：订阅=%s 每日助手=%s TMDB回退=%s 异常=%s",
            len(subscriptions), daily_count, fallback_count, len(errors),
        )
        return payload

    def _raw_subscription_missing_v1120(self, subscribe: Any) -> List[int]:
        previous = getattr(self, "_airing_due_scope_v1120", None)
        self._airing_due_scope_v1120 = None
        try:
            return sorted(self._positive_int_set_v1120(super()._subscription_missing_episodes(subscribe) or []))
        finally:
            self._airing_due_scope_v1120 = previous

    def _subscription_missing_episodes(self, subscribe: Any) -> List[int]:
        values = sorted(self._positive_int_set_v1120(super()._subscription_missing_episodes(subscribe) or []))
        scope = getattr(self, "_airing_due_scope_v1120", None)
        if not isinstance(scope, dict):
            return values
        sid = int(getattr(subscribe, "id", 0) or 0)
        if sid != int(scope.get("subscribe_id") or 0):
            return values
        allowed = self._positive_int_set_v1120(scope.get("episodes") or [])
        return [value for value in values if value in allowed]

    @contextmanager
    def _due_scope_v1120(self, subscribe: Any, episodes: Iterable[int]):
        previous = getattr(self, "_airing_due_scope_v1120", None)
        self._airing_due_scope_v1120 = {
            "subscribe_id": int(getattr(subscribe, "id", 0) or 0),
            "episodes": sorted(self._positive_int_set_v1120(episodes)),
        }
        try:
            yield
        finally:
            self._airing_due_scope_v1120 = previous

    @contextmanager
    def _without_due_scope_v1120(self):
        previous = getattr(self, "_airing_due_scope_v1120", None)
        self._airing_due_scope_v1120 = None
        try:
            yield
        finally:
            self._airing_due_scope_v1120 = previous

    def _sync_media_facts_progress(self, subscribe: Any) -> int:
        with self._without_due_scope_v1120():
            return super()._sync_media_facts_progress(subscribe)

    def _finish_subscription_if_complete(self, subscribe: Any) -> bool:
        with self._without_due_scope_v1120():
            return bool(super()._finish_subscription_if_complete(subscribe))

    def _commit_episode_receipt_v1124(self, subscribe: Any, episodes: Iterable[int], origin: str) -> None:
        with self._without_due_scope_v1120():
            return super()._commit_episode_receipt_v1124(subscribe, episodes, origin)

    def _episode_air_at_v1120(self, row: Dict[str, Any]) -> Optional[datetime.datetime]:
        raw_at = str(row.get("air_at") or "").strip()
        if raw_at:
            try:
                parsed = datetime.datetime.fromisoformat(raw_at.replace("Z", "+00:00"))
                if parsed.tzinfo is not None:
                    parsed = parsed.astimezone().replace(tzinfo=None)
                return parsed
            except ValueError:
                pass
        raw_date = str(row.get("air_date") or "").strip()[:10]
        if not raw_date:
            return None
        try:
            day = datetime.date.fromisoformat(raw_date)
        except ValueError:
            return None
        return datetime.datetime.combine(
            day,
            datetime.time(hour=int(getattr(self, "_calendar_default_hour_v1120", 20) or 20)),
        )

    def _calendar_item_for_v1120(self, subscribe: Any, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        sid = int(getattr(subscribe, "id", 0) or 0)
        for item in payload.get("subscriptions") or []:
            if isinstance(item, dict) and int(item.get("subscribe_id") or 0) == sid:
                return dict(item)
        return None

    def _airing_gate_v1120(self, subscribe: Any, payload: Dict[str, Any] = None) -> Dict[str, Any]:
        raw_missing = set(self._raw_subscription_missing_v1120(subscribe))
        sid = int(getattr(subscribe, "id", 0) or 0)
        if not raw_missing:
            return {
                "subscribe_id": sid,
                "calendar_available": True,
                "raw_missing": [],
                "due_missing": [],
                "due_uncovered": [],
                "future_missing": [],
                "unscheduled_missing": [],
                "covered": True,
            }

        calendar = payload or self._refresh_airing_calendar_v1120(force=False)
        item = self._calendar_item_for_v1120(subscribe, calendar)
        episodes = list((item or {}).get("episodes") or [])
        now = datetime.datetime.now()
        early = datetime.timedelta(hours=int(getattr(self, "_calendar_early_hours_v1120", 12) or 12))
        scheduled: Dict[int, Dict[str, Any]] = {}
        due: Set[int] = set()
        future: Set[int] = set()
        for row in episodes:
            if not isinstance(row, dict):
                continue
            try:
                episode = int(row.get("episode") or row.get("episode_number") or 0)
            except (TypeError, ValueError):
                continue
            if episode <= 0 or episode not in raw_missing:
                continue
            air_at = self._episode_air_at_v1120(row)
            if not air_at:
                continue
            normalized = dict(row)
            normalized["air_at_effective"] = air_at.isoformat(timespec="minutes")
            normalized["early_at"] = (air_at - early).isoformat(timespec="minutes")
            scheduled[episode] = normalized
            if now >= air_at - early:
                due.add(episode)
            else:
                future.add(episode)

        unscheduled = set(raw_missing) - set(scheduled)
        # 若更大的集号已经进入应播窗口，则更小但缺日期的集不应被“未知排期”永久挡住。
        max_due = max(due) if due else 0
        implied_due = {episode for episode in unscheduled if max_due and episode <= max_due}
        due.update(implied_due)
        unscheduled -= implied_due

        try:
            reservations = dict(self._pending_reservations(subscribe) or {})
            reserved = self._positive_int_set_v1120(reservations.get("episodes") or [])
        except Exception:
            reserved = set()
        try:
            claimed = self._positive_int_set_v1120(self._active_source_claims(sid) or [])
        except Exception:
            claimed = set()
        due_uncovered = due - reserved - claimed

        next_episode = 0
        next_air_at = ""
        next_precision = ""
        candidates = [
            (episode, self._episode_air_at_v1120(row), str(row.get("precision") or "date"))
            for episode, row in scheduled.items()
        ]
        candidates = [row for row in candidates if row[1] is not None]
        if candidates:
            episode, air_at, precision = min(candidates, key=lambda row: (row[1], row[0]))
            next_episode = int(episode)
            next_air_at = air_at.isoformat(timespec="minutes") if air_at else ""
            next_precision = precision

        result = {
            "subscribe_id": sid,
            "name": str(getattr(subscribe, "name", "") or ""),
            "calendar_available": bool(scheduled),
            "calendar_provider": str((item or {}).get("provider") or ""),
            "raw_missing": sorted(raw_missing),
            "due_missing": sorted(due),
            "due_uncovered": sorted(due_uncovered),
            "reserved": sorted(reserved.intersection(raw_missing)),
            "claimed": sorted(claimed.intersection(raw_missing)),
            "future_missing": sorted(future),
            "unscheduled_missing": sorted(unscheduled),
            "next_episode": next_episode,
            "next_air_at": next_air_at,
            "next_precision": next_precision,
            "early_hours": int(getattr(self, "_calendar_early_hours_v1120", 12) or 12),
            "default_hour": int(getattr(self, "_calendar_default_hour_v1120", 20) or 20),
            "checked_at": now.isoformat(timespec="seconds"),
        }
        state = self.get_data("airing_gate_state_v1120") or {}
        if not isinstance(state, dict):
            state = {}
        previous = dict(state.get(str(sid)) or {})
        state[str(sid)] = result
        if len(state) > 1000:
            state = dict(list(state.items())[-1000:])
        self.save_data("airing_gate_state_v1120", state)
        signature_fields = ("due_uncovered", "future_missing", "unscheduled_missing", "next_episode", "next_air_at")
        if any(previous.get(key) != result.get(key) for key in signature_fields):
            if result["due_uncovered"]:
                self._plugin_log(
                    "INFO",
                    "【光鸭转存助手】【更新日历v2】#%s %s 当前应补=%s；未来=%s；未排期=%s",
                    sid,
                    result["name"],
                    ",".join(f"E{v:02d}" for v in result["due_uncovered"]) or "无",
                    ",".join(f"E{v:02d}" for v in result["future_missing"]) or "无",
                    ",".join(f"E{v:02d}" for v in result["unscheduled_missing"]) or "无",
                )
            else:
                self._plugin_log(
                    "INFO",
                    "【光鸭转存助手】【更新日历v2】#%s %s 已追平当前播出进度；未来=%s；下一集=E%s @ %s precision=%s，本轮不访问外部资源站",
                    sid,
                    result["name"],
                    ",".join(f"E{v:02d}" for v in result["future_missing"]) or "无",
                    f"{next_episode:02d}" if next_episode else "--",
                    next_air_at or "未知",
                    next_precision or "unknown",
                )
        return result

    def _refresh_airing_calendar_v1110(self, force: bool = False) -> Dict[str, Any]:
        """兼容旧页面合同：v1.11.0 卡片继续显示每个订阅的下一缺集，但底层来自整季日历。"""
        full = self._refresh_airing_calendar_v1120(force=force)
        rows: List[Dict[str, Any]] = []
        for item in full.get("subscriptions") or []:
            if not isinstance(item, dict):
                continue
            sid = int(item.get("subscribe_id") or 0)
            subscribe = self._find_subscription(sid) if sid else None
            if not subscribe:
                continue
            missing = set(self._raw_subscription_missing_v1120(subscribe))
            scheduled = []
            for episode_row in item.get("episodes") or []:
                if not isinstance(episode_row, dict):
                    continue
                episode = int(episode_row.get("episode") or 0)
                if episode not in missing:
                    continue
                air_at = self._episode_air_at_v1120(episode_row)
                if not air_at:
                    continue
                scheduled.append((air_at, episode, episode_row))
            if not scheduled:
                continue
            air_at, episode, episode_row = min(scheduled, key=lambda row: (row[0], row[1]))
            rows.append({
                "subscribe_id": sid,
                "name": str(item.get("title") or getattr(subscribe, "name", "") or ""),
                "year": str(item.get("year") or getattr(subscribe, "year", "") or ""),
                "tmdb_id": str(item.get("tmdb_id") or ""),
                "season": int(item.get("season") or getattr(subscribe, "season", 0) or 1),
                "episode": episode,
                "air_date": str(episode_row.get("air_date") or air_at.date().isoformat()),
                "air_at": air_at.isoformat(timespec="minutes"),
                "precision": str(episode_row.get("precision") or "date"),
                "missing": sorted(missing),
                "target_missing": True,
            })
        rows.sort(key=lambda row: (str(row.get("air_at") or row.get("air_date") or ""), int(row.get("subscribe_id") or 0)))
        payload = {
            "updated_at": str(full.get("updated_at") or datetime.datetime.now().isoformat(timespec="seconds")),
            "count": len(rows),
            "items": rows,
            "errors": list(full.get("errors") or [])[:30],
            "engine": "v1.12.0-full-season-calendar",
        }
        self.save_data("airing_calendar_v1110", payload)
        return payload

    def _calendar_due_check_v1110(self) -> Dict[str, Any]:
        """每小时只检查真正进入提前窗口的订阅；同一订阅仍至少间隔两小时。"""
        payload = self._refresh_airing_calendar_v1120(force=False)
        state = self.get_data("airing_check_state_v1110") or {}
        if not isinstance(state, dict):
            state = {}
        now = datetime.datetime.now()
        checked = skipped = 0
        results: List[Dict[str, Any]] = []
        for item in payload.get("subscriptions") or []:
            if not isinstance(item, dict):
                continue
            sid = int(item.get("subscribe_id") or 0)
            subscribe = self._find_subscription(sid) if sid else None
            if not subscribe or not self._is_guangya_route(subscribe):
                continue
            gate = self._airing_gate_v1120(subscribe, payload=payload)
            if not gate.get("due_uncovered"):
                skipped += 1
                continue
            row_state = state.get(str(sid)) if isinstance(state.get(str(sid)), dict) else {}
            try:
                last = datetime.datetime.fromisoformat(str(row_state.get("checked_at") or ""))
            except (TypeError, ValueError):
                last = None
            cooldown_hours = int(getattr(self, "_calendar_per_sub_cooldown_hours_v1110", 2) or 2)
            if last and now - last < datetime.timedelta(hours=cooldown_hours):
                skipped += 1
                continue
            previous_force = bool(getattr(self, "_airing_due_force_v1120", False))
            self._airing_due_force_v1120 = True
            try:
                result = dict(self._try_transfer_subscription(subscribe, force=True, refresh_channel=False) or {})
            except Exception as err:
                result = {"success": False, "message": str(err)[:300]}
            finally:
                self._airing_due_force_v1120 = previous_force
            state[str(sid)] = {
                "checked_at": now.isoformat(timespec="seconds"),
                "episodes": list(gate.get("due_uncovered") or []),
            }
            results.append({
                "subscribe_id": sid,
                "episodes": list(gate.get("due_uncovered") or []),
                "success": bool(result.get("success")),
                "message": str(result.get("message") or "")[:300],
            })
            checked += 1
        self.save_data("airing_check_state_v1110", state)
        if checked:
            self._plugin_log("INFO", "【光鸭转存助手】【更新日历v2】到期检查完成：执行=%s 跳过=%s", checked, skipped)
        return {"success": True, "checked": checked, "skipped": skipped, "results": results}

    def _run_airing_subscription_v1120(
        self,
        subscribe: Any,
        *,
        force: bool,
        refresh_channel: bool,
    ) -> Dict[str, Any]:
        if self._is_movie_subscription(subscribe):
            return dict(super()._try_transfer_subscription(
                subscribe,
                force=force,
                refresh_channel=refresh_channel,
            ) or {})

        due_force = bool(getattr(self, "_airing_due_force_v1120", False))
        # 人工强制/每日全员复核保留一次完整补漏；日历到期服务虽然 force=True，仍只允许 due 集。
        if force and not due_force:
            return dict(super()._try_transfer_subscription(
                subscribe,
                force=True,
                refresh_channel=refresh_channel,
            ) or {})

        gate = self._airing_gate_v1120(subscribe)
        if not bool(gate.get("calendar_available")):
            # 上游日历完全不可用时保持既有可靠性，不因第三方数据故障冻结追更。
            result = dict(super()._try_transfer_subscription(
                subscribe,
                force=force,
                refresh_channel=refresh_channel,
            ) or {})
            result["calendar_gate"] = gate
            result["calendar_fallback_legacy"] = True
            return result

        due = list(gate.get("due_uncovered") or [])
        if not due:
            return {
                "success": True,
                "handled": True,
                "calendar_wait": True,
                "calendar_gate": gate,
                "message": (
                    "已追平当前播出进度；"
                    f"未来集={','.join('E%02d' % int(v) for v in (gate.get('future_missing') or [])) or '无'}；"
                    f"下一集=E{int(gate.get('next_episode') or 0):02d} @ {gate.get('next_air_at') or '未知'}"
                ),
            }

        with self._due_scope_v1120(subscribe, due):
            result = dict(super()._try_transfer_subscription(
                subscribe,
                force=force,
                refresh_channel=refresh_channel,
            ) or {})
        result["calendar_gate"] = gate
        result["due_scope"] = due
        return result

    def _try_transfer_subscription(
        self,
        subscribe: Any,
        force: bool = False,
        refresh_channel: bool = True,
    ) -> Dict[str, Any]:
        """把整条来源链放进同订阅 RLock，再执行日历门禁。"""
        lock_getter = getattr(self, "_episode_fence_lock_v1124", None)
        lock = lock_getter(subscribe) if callable(lock_getter) else nullcontext()
        with lock:
            return self._run_airing_subscription_v1120(
                subscribe,
                force=force,
                refresh_channel=refresh_channel,
            )

    def _try_transfer_subscription_inner(
        self,
        subscribe: Any,
        force: bool = False,
        refresh_channel: bool = True,
    ) -> Dict[str, Any]:
        """handled 只表示前序入口处理过，不再等价于 due gap 已全部覆盖。"""
        result = dict(super()._try_transfer_subscription_inner(
            subscribe,
            force=force,
            refresh_channel=refresh_channel,
        ) or {})
        if self._is_movie_subscription(subscribe) or result.get("viewing_external"):
            return result
        if not bool(result.get("handled")):
            return result
        gap_method = getattr(self, "_viewing_gap_v1113", None)
        if not callable(gap_method):
            return result
        gap = dict(gap_method(subscribe) or {})
        if bool(gap.get("covered")):
            return result
        uncovered = list(gap.get("uncovered") or [])
        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【覆盖修正】#%s 前序 handled=True 但当前 due gap 仍未覆盖=%s；继续 Magnet/ED2K，而不是把‘旧链接已处理’误当成‘集数已齐’",
            int(getattr(subscribe, "id", 0) or 0),
            ",".join(f"E{int(v):02d}" for v in uncovered) or "movie",
        )
        try:
            viewing = dict(self._dispatch_viewing_external_v1113(subscribe) or {})
        except Exception as err:
            viewing = {"success": False, "actions": [], "message": str(err)[:300]}
        if viewing.get("actions"):
            return {
                **result,
                "success": True,
                "handled": True,
                "viewing_external": viewing,
                "message": f"{str(result.get('message') or '前序来源已检查')}；{viewing.get('message') or '继续补齐 due gap'}",
            }
        return {**result, "viewing_external": viewing}


__all__ = ["GuangYaAiringSchedulerV1120Mixin"]
