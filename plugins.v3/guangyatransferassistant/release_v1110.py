"""光鸭转存助手 v1.11.0 发布层。

在 v1.10.24 跨来源集级终止栅栏之上补齐长期追更闭环：
- 每天固定执行一次“全员缺集复核”，即使当天频道没有新消息，也会重新核对所有固定路线订阅；
- 使用 MoviePilot/TMDB 的 next_episode_to_air 生成下一集更新日历；
- 日历中今天、昨天或明天播出的剧，每小时进入一次轻量到期检查，单订阅至少间隔 2 小时，兼顾提前放出；
- 所有日历/全员复核仍经过现有缺集、在途 reservation、成功集终态与质量门禁，不会绕过 v1.10.24 防重复。
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

from apscheduler.triggers.cron import CronTrigger

from app.chain.media import MediaChain
from app.schemas.types import MediaSource, MediaType


class GuangYaReleaseV1110Mixin:
    """v1.11.0 更新日历 + 每日全员补漏。"""

    plugin_version = "1.11.0"
    build_id = "20260903-r41"
    _daily_catchup_cron_v1110 = "10 4 * * *"
    _calendar_refresh_hours_v1110 = 6
    _calendar_due_check_minutes_v1110 = 60
    _calendar_per_sub_cooldown_hours_v1110 = 2
    _calendar_due_limit_v1110 = 20

    def get_service(self) -> List[Dict[str, Any]]:
        services = list(super().get_service() or [])
        if not self._enabled:
            return services
        try:
            catchup_trigger = CronTrigger.from_crontab(self._daily_catchup_cron_v1110)
        except Exception:
            catchup_trigger = CronTrigger.from_crontab("10 4 * * *")
        services.append({
            "id": "GuangYaTransferAssistantDailyCatchup",
            "name": "光鸭转存助手每日全员缺集复核",
            "trigger": catchup_trigger,
            "func": self._daily_full_catchup_v1110,
            "kwargs": {},
        })
        services.append({
            "id": "GuangYaTransferAssistantAiringDue",
            "name": "光鸭转存助手更新日历到期检查",
            "trigger": "interval",
            "func": self._calendar_due_check_v1110,
            "kwargs": {"minutes": self._calendar_due_check_minutes_v1110},
        })
        return services

    @staticmethod
    def _next_episode_value_v1110(next_episode: Any, field: str, default: Any = None) -> Any:
        if isinstance(next_episode, dict):
            return next_episode.get(field, default)
        return getattr(next_episode, field, default)

    @staticmethod
    def _parse_iso_date_v1110(value: Any) -> Optional[datetime.date]:
        text = str(value or "").strip()[:10]
        if not text:
            return None
        try:
            return datetime.date.fromisoformat(text)
        except ValueError:
            return None

    def _subscription_tmdb_id_v1110(self, subscribe: Any) -> str:
        direct = getattr(subscribe, "tmdbid", None) or getattr(subscribe, "tmdb_id", None)
        if direct not in (None, ""):
            return str(direct)
        source = str(getattr(getattr(subscribe, "media_source", None), "value", getattr(subscribe, "media_source", "")) or "").lower()
        if "tmdb" not in source and "themoviedb" not in source:
            return ""
        media_id = getattr(subscribe, "mediaid", None) or getattr(subscribe, "media_id", None)
        return str(media_id or "").strip()

    def _airing_calendar_stale_v1110(self) -> bool:
        payload = self.get_data("airing_calendar_v1110") or {}
        try:
            updated = datetime.datetime.fromisoformat(str(payload.get("updated_at") or ""))
        except (TypeError, ValueError):
            return True
        return datetime.datetime.now() - updated >= datetime.timedelta(hours=self._calendar_refresh_hours_v1110)

    def _refresh_airing_calendar_v1110(self, force: bool = False) -> Dict[str, Any]:
        """从 MoviePilot 的统一媒体信息读取 TMDB 下一集播出摘要。"""
        current = self.get_data("airing_calendar_v1110") or {}
        if not force and current and not self._airing_calendar_stale_v1110():
            return current

        selected = set(int(value) for value in (self._selected_subscriptions or []) if str(value).isdigit())
        rows: List[Dict[str, Any]] = []
        errors: List[str] = []
        chain = MediaChain()
        for subscribe in self._list_subscriptions(None) or []:
            sid = int(getattr(subscribe, "id", 0) or 0)
            if sid not in selected or self._is_movie_subscription(subscribe):
                continue
            if str(getattr(subscribe, "state", "") or "") not in {"N", "R"}:
                continue
            tmdb_id = self._subscription_tmdb_id_v1110(subscribe)
            if not tmdb_id:
                continue
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
                errors.append(f"#{sid} {getattr(subscribe, 'name', '')}: {str(err)[:160]}")
                continue
            if not info:
                continue
            next_episode = getattr(info, "next_episode_to_air", None)
            if not next_episode:
                continue
            air_date = str(self._next_episode_value_v1110(next_episode, "air_date", "") or "")
            episode = int(self._next_episode_value_v1110(next_episode, "episode_number", 0) or 0)
            season = int(self._next_episode_value_v1110(next_episode, "season_number", 0) or 0)
            if not air_date or episode <= 0:
                continue
            missing = list(self._subscription_missing_episodes(subscribe) or [])
            rows.append({
                "subscribe_id": sid,
                "name": str(getattr(subscribe, "name", "") or getattr(info, "title", "") or ""),
                "year": str(getattr(subscribe, "year", "") or getattr(info, "year", "") or ""),
                "tmdb_id": tmdb_id,
                "season": season or int(getattr(subscribe, "season", 0) or 0),
                "episode": episode,
                "air_date": air_date[:10],
                "missing": missing,
                "target_missing": episode in set(int(value) for value in missing if int(value or 0) > 0),
            })

        rows.sort(key=lambda row: (str(row.get("air_date") or "9999-99-99"), str(row.get("name") or "")))
        payload = {
            "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "count": len(rows),
            "items": rows,
            "errors": errors[:30],
        }
        self.save_data("airing_calendar_v1110", payload)
        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【更新日历】已刷新 %s 个下一集计划，异常=%s",
            len(rows),
            len(errors),
        )
        return payload

    def _calendar_due_rows_v1110(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        today = datetime.date.today()
        earliest = today - datetime.timedelta(days=1)
        latest = today + datetime.timedelta(days=1)
        due: List[Dict[str, Any]] = []
        for row in payload.get("items") or []:
            if not isinstance(row, dict):
                continue
            air_date = self._parse_iso_date_v1110(row.get("air_date"))
            if not air_date or air_date < earliest or air_date > latest:
                continue
            due.append(dict(row))
        due.sort(key=lambda row: (str(row.get("air_date") or ""), int(row.get("subscribe_id") or 0)))
        return due[:self._calendar_due_limit_v1110]

    def _calendar_due_check_v1110(self) -> Dict[str, Any]:
        """对临近播出订阅做有限频率的强制补漏，覆盖“官方日期前提前放出”的情况。"""
        payload = self._refresh_airing_calendar_v1110(force=False)
        due = self._calendar_due_rows_v1110(payload)
        state = self.get_data("airing_check_state_v1110") or {}
        if not isinstance(state, dict):
            state = {}
        now = datetime.datetime.now()
        checked = 0
        skipped = 0
        results: List[Dict[str, Any]] = []
        for row in due:
            sid = int(row.get("subscribe_id") or 0)
            subscribe = self._find_subscription(sid)
            if not subscribe or not self._is_guangya_route(subscribe):
                continue
            missing = list(self._subscription_missing_episodes(subscribe) or [])
            episode = int(row.get("episode") or 0)
            if episode > 0 and missing and episode not in set(int(value) for value in missing if int(value or 0) > 0):
                skipped += 1
                continue
            last_text = str((state.get(str(sid)) or {}).get("checked_at") or "") if isinstance(state.get(str(sid)), dict) else ""
            try:
                last = datetime.datetime.fromisoformat(last_text)
            except (TypeError, ValueError):
                last = None
            if last and now - last < datetime.timedelta(hours=self._calendar_per_sub_cooldown_hours_v1110):
                skipped += 1
                continue
            try:
                result = self._try_transfer_subscription(subscribe, force=True, refresh_channel=False)
                results.append({"subscribe_id": sid, "episode": episode, "air_date": row.get("air_date"), "success": bool(result.get("success")), "message": result.get("message") or ""})
            except Exception as err:
                results.append({"subscribe_id": sid, "episode": episode, "air_date": row.get("air_date"), "success": False, "message": str(err)[:300]})
            state[str(sid)] = {"checked_at": now.isoformat(timespec="seconds"), "episode": episode, "air_date": row.get("air_date")}
            checked += 1
        self.save_data("airing_check_state_v1110", state)
        if checked:
            self._plugin_log("INFO", "【光鸭转存助手】【更新日历】到期检查完成：检查=%s 跳过=%s", checked, skipped)
        return {"success": True, "checked": checked, "skipped": skipped, "results": results}

    def _daily_full_catchup_v1110(self) -> Dict[str, Any]:
        """每天一次全员复核：不依赖是否有新频道消息，逐个核对真实缺集并重新匹配。"""
        started = datetime.datetime.now()
        try:
            self.refresh_channels(force=True)
        except Exception as err:
            self._plugin_log("WARNING", "【光鸭转存助手】【每日全员复核】频道强制刷新失败，继续使用缓存/其它来源：%s", err)
        try:
            self._refresh_airing_calendar_v1110(force=True)
        except Exception as err:
            self._plugin_log("WARNING", "【光鸭转存助手】【每日全员复核】更新日历刷新失败：%s", err)

        results: List[Dict[str, Any]] = []
        selected = list(dict.fromkeys(int(value) for value in (self._selected_subscriptions or []) if str(value).isdigit()))
        for sid in selected:
            subscribe = self._find_subscription(sid)
            if not subscribe or not self._is_guangya_route(subscribe):
                continue
            if str(getattr(subscribe, "state", "") or "") not in {"N", "R"}:
                continue
            try:
                sync = getattr(self, "_sync_media_library_progress", None)
                if callable(sync):
                    sync(subscribe)
            except Exception:
                pass
            fresh = self._find_subscription(sid) or subscribe
            before = [] if self._is_movie_subscription(fresh) else list(self._subscription_missing_episodes(fresh) or [])
            try:
                result = self._try_transfer_subscription(fresh, force=True, refresh_channel=False)
                success = bool(result.get("success"))
                message = str(result.get("message") or "")
            except Exception as err:
                success = False
                message = str(err)[:400]
            latest = self._find_subscription(sid) or fresh
            after = [] if self._is_movie_subscription(latest) else list(self._subscription_missing_episodes(latest) or [])
            results.append({
                "subscribe_id": sid,
                "name": str(getattr(latest, "name", "") or ""),
                "missing_before": before,
                "missing_after": after,
                "success": success,
                "message": message,
            })

        payload = {
            "started_at": started.isoformat(timespec="seconds"),
            "finished_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "checked": len(results),
            "changed": sum(1 for row in results if row.get("missing_before") != row.get("missing_after")),
            "failed": sum(1 for row in results if not row.get("success")),
            "results": results[-200:],
        }
        self.save_data("daily_catchup_v1110", payload)
        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【每日全员复核】完成：订阅=%s 缺集变化=%s 执行未成功=%s",
            payload["checked"], payload["changed"], payload["failed"],
        )
        return {"success": True, "data": payload, "message": f"已复核 {payload['checked']} 个固定路线订阅"}

    def get_page(self):
        pages = list(super().get_page() or [])
        calendar = self.get_data("airing_calendar_v1110") or {}
        catchup = self.get_data("daily_catchup_v1110") or {}
        rows = []
        for row in (calendar.get("items") or [])[:30]:
            if not isinstance(row, dict):
                continue
            rows.append({
                "component": "VListItem",
                "props": {
                    "title": f"{row.get('air_date') or '-'} · {row.get('name') or '-'} · S{int(row.get('season') or 0):02d}E{int(row.get('episode') or 0):02d}",
                    "subtitle": (
                        f"订阅 #{row.get('subscribe_id')} · TMDB {row.get('tmdb_id') or '-'} · "
                        f"当前缺集 {','.join('E%02d' % int(value) for value in (row.get('missing') or [])[:12]) or '无'}"
                    ),
                },
            })
        card = {
            "component": "VCard",
            "props": {"variant": "outlined", "class": "mb-3"},
            "content": [
                {"component": "VCardTitle", "text": "追更日历与每日补漏"},
                {"component": "VCardText", "text": (
                    f"更新日历：{calendar.get('updated_at') or '尚未生成'} · 下一集计划 {calendar.get('count') or 0} 个。"
                    f" 每天 04:10 自动全员复核一次；临近播出（昨天/今天/明天）每小时检查，单订阅至少间隔 2 小时。"
                    f" 最近全员复核：{catchup.get('finished_at') or '-'} · 检查 {catchup.get('checked') or 0} · 缺集变化 {catchup.get('changed') or 0}。"
                )},
                {"component": "VList", "props": {"density": "compact", "style": "max-height: 420px; overflow-y: auto;"}, "content": rows or [{"component": "VListItem", "props": {"title": "暂无 TMDB 下一集播出计划；每日全员复核仍会正常执行"}}]},
            ],
        }
        return [card, *pages]


__all__ = ["GuangYaReleaseV1110Mixin"]
