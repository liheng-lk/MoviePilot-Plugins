"""每日助手：把全媒体榜单发现统一送入光鸭 GYSub 固定转存路线。"""
from __future__ import annotations

import datetime
import re
from typing import Any, Dict, List, Optional, Tuple

from apscheduler.triggers.cron import CronTrigger

from app.chain.download import DownloadChain
from app.chain.media import MediaChain
from app.chain.subscribe import SubscribeChain
from app.plugins import _PluginBase
from app.sdk.config import settings
from app.sdk.events import eventmanager
from app.sdk.logging import logger
from app.sdk.media import MetaInfo
from app.schemas.types import EventType, MediaSource, MediaType

from .sources import DEFAULT_SOURCE_KEYS, SOURCE_MAP, fetch_source, source_options
from .hardening_v110 import DailyAssistantV110Mixin


def _as_list(value: Any) -> List[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item or "").strip()]
    if value is None:
        return []
    return [item for item in re.split(r"[,，\s]+", str(value)) if item]


def _mtype(token: str) -> MediaType:
    return MediaType.MOVIE if str(token or "").lower() == "movie" else MediaType.TV


def _safe_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(number, maximum))


def _safe_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(number, maximum))


class DailyAssistantV100(_PluginBase):
    """聚合电影、剧集、动漫、综艺、纪录片和流媒体榜单，并通过 GYSub 接入光鸭转存。"""

    plugin_name = "每日助手"
    plugin_desc = "全媒体榜单发现 → TMDB 统一识别 → GYSub → 光鸭转存；支持候选模式与按榜单自动订阅。"
    plugin_icon = "movie.jpg"
    plugin_version = "1.0.0"
    plugin_author = "liheng-lk"
    plugin_label = "榜单,Netflix,HBO,AppleTV,Disney,Prime,Hulu,Crunchyroll,豆瓣,猫眼,IMDb,TMDB,AniList,Bangumi,GYSub"
    author_url = "https://github.com/liheng-lk/MoviePilot-Plugins"
    plugin_config_prefix = "dailyassistant_"
    plugin_order = 19
    auth_level = 1

    _enabled = False
    _cron = "15 8 * * *"
    _onlyonce = False
    _proxy = False
    _rank_limit = 20
    _vote_min = 0.0
    _auto_gysub = False
    _source_keys: List[str] = list(DEFAULT_SOURCE_KEYS)
    _auto_source_keys: List[str] = []
    _gysub_pending_ttl = datetime.timedelta(minutes=15)

    def init_plugin(self, config: Optional[dict] = None) -> None:
        """加载配置。"""
        config = config or {}
        self._enabled = bool(config.get("enabled", False))
        self._cron = str(config.get("cron") or "15 8 * * *").strip()
        self._onlyonce = bool(config.get("onlyonce", False))
        self._proxy = bool(config.get("proxy", False))
        self._rank_limit = _safe_int(config.get("rank_limit"), 20, 1, 50)
        self._vote_min = _safe_float(config.get("vote_min"), 0.0, 0.0, 10.0)
        self._auto_gysub = bool(config.get("auto_gysub", False))
        source_keys = _as_list(config.get("source_keys"))
        self._source_keys = [key for key in source_keys if key in SOURCE_MAP] or list(DEFAULT_SOURCE_KEYS)
        self._auto_source_keys = [key for key in _as_list(config.get("auto_source_keys")) if key in SOURCE_MAP]

    def get_state(self) -> bool:
        """返回插件启用状态。"""
        return self._enabled

    def get_service(self) -> List[Dict[str, Any]]:
        """注册每日刷新和一次性立即刷新。"""
        services: List[Dict[str, Any]] = []
        if self._onlyonce:
            services.append({
                "id": "DailyAssistantOnce",
                "name": "每日助手立即刷新",
                "trigger": "date",
                "run_date": datetime.datetime.now() + datetime.timedelta(seconds=3),
                "func": self.refresh,
                "kwargs": {"manual": True},
            })
            self._save_config(onlyonce=False)
        if self._enabled and self._cron:
            try:
                trigger = CronTrigger.from_crontab(self._cron)
                services.append({
                    "id": "DailyAssistant",
                    "name": "每日助手榜单刷新",
                    "trigger": trigger,
                    "func": self.refresh,
                    "kwargs": {"manual": False},
                })
            except Exception as err:
                logger.error("【每日助手】Cron 配置无效 %s: %s", self._cron, err)
        return services

    def _save_config(self, *, onlyonce: Optional[bool] = None) -> None:
        self.update_config({
            "enabled": self._enabled,
            "cron": self._cron,
            "onlyonce": self._onlyonce if onlyonce is None else onlyonce,
            "proxy": self._proxy,
            "rank_limit": self._rank_limit,
            "vote_min": self._vote_min,
            "auto_gysub": self._auto_gysub,
            "source_keys": self._source_keys,
            "auto_source_keys": self._auto_source_keys,
        })

    @staticmethod
    def _candidate_identity(item: Dict[str, Any]) -> str:
        tmdb_id = str(item.get("tmdb_id") or "")
        media_type = str(item.get("media_type") or "")
        if tmdb_id:
            season = _safe_int(item.get("season"), 1, 1, 99) if media_type == "tv" else 0
            return f"tmdb:{tmdb_id}:{media_type}:s{season:02d}"
        return f"title:{str(item.get('title') or '').casefold()}:{item.get('year') or ''}:{media_type}"

    @staticmethod
    def _candidate_tmdb_id(info: Any) -> str:
        return str(getattr(info, "tmdb_id", None) or (
            getattr(info, "media_id", None)
            if str(getattr(getattr(info, "media_source", None), "value", getattr(info, "media_source", ""))).lower() == "tmdb"
            else ""
        ) or "").strip()

    def _resolve_tmdb(self, item: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[Any]]:
        """把非 TMDB 榜单条目安全投影为 TMDB 身份；多候选时宁可不自动订阅。"""
        row = dict(item)
        media_type = str(row.get("media_type") or "tv")
        mtype = _mtype(media_type)
        tmdb_id = str(row.get("tmdb_id") or "").strip()
        chain = MediaChain()

        if tmdb_id:
            try:
                info = chain.recognize_media(mtype=mtype, media_source=MediaSource.TMDB, media_id=tmdb_id)
                if info:
                    row["title"] = str(getattr(info, "title", None) or row.get("title") or "")
                    row["year"] = getattr(info, "year", None) or row.get("year")
                    row["tmdb_id"] = self._candidate_tmdb_id(info) or tmdb_id
                    row["poster"] = getattr(info, "poster_path", None) or getattr(info, "poster", None) or row.get("poster") or ""
                    row["season"] = row.get("season") or getattr(info, "season", None)
                    return row, info
            except Exception as err:
                logger.debug("【每日助手】TMDB %s 详情识别失败: %s", tmdb_id, err)
            return row, None

        source_pairs = (
            ("imdb_id", MediaSource.IMDb),
            ("anilist_id", MediaSource.AniList),
            ("bangumi_id", MediaSource.Bangumi),
            ("douban_id", MediaSource.Douban),
        )
        for field, source in source_pairs:
            media_id = str(row.get(field) or "").strip()
            if not media_id:
                continue
            try:
                info = chain.recognize_media(mtype=mtype, media_source=source, media_id=media_id)
            except Exception:
                info = None
            if info:
                candidate_tmdb = self._candidate_tmdb_id(info)
                if candidate_tmdb:
                    row["tmdb_id"] = candidate_tmdb
                    row["title"] = str(getattr(info, "title", None) or row.get("title") or "")
                    row["year"] = getattr(info, "year", None) or row.get("year")
                    return row, info

        title = str(row.get("title") or "").strip()
        if not title:
            return row, None
        try:
            _, medias = chain.search(title=title, media_source=MediaSource.TMDB)
        except Exception as err:
            logger.debug("【每日助手】标题识别失败 %s: %s", title, err)
            return row, None

        wanted_year = str(row.get("year") or "").strip()
        title_norm = re.sub(r"\W+", "", title.casefold())
        candidates = []
        for info in medias or []:
            if getattr(info, "type", None) != mtype:
                continue
            if wanted_year and str(getattr(info, "year", "") or "") != wanted_year:
                continue
            aliases = {
                re.sub(r"\W+", "", str(getattr(info, "title", "") or "").casefold()),
                re.sub(r"\W+", "", str(getattr(info, "en_title", "") or "").casefold()),
            }
            if title_norm and title_norm in aliases:
                candidates.append(info)
        if len(candidates) != 1:
            return row, None
        info = candidates[0]
        candidate_tmdb = self._candidate_tmdb_id(info)
        if not candidate_tmdb:
            return row, None
        row["tmdb_id"] = candidate_tmdb
        row["title"] = str(getattr(info, "title", None) or row.get("title") or "")
        row["year"] = getattr(info, "year", None) or row.get("year")
        row["poster"] = getattr(info, "poster_path", None) or getattr(info, "poster", None) or row.get("poster") or ""
        row["season"] = row.get("season") or getattr(info, "season", None)
        return row, info

    @staticmethod
    def _library_complete(info: Any, row: Dict[str, Any]) -> bool:
        if not info:
            return False
        try:
            meta = MetaInfo(str(row.get("title") or getattr(info, "title", "") or ""))
            meta.type = _mtype(str(row.get("media_type") or "tv"))
            if row.get("season"):
                meta.begin_season = int(row["season"])
            complete, _ = DownloadChain().get_no_exists_info(meta=meta, mediainfo=info)
            return bool(complete)
        except Exception:
            return False

    @staticmethod
    def _pending_row(row: Dict[str, Any]) -> Dict[str, Any]:
        """持久化最小 GYSub 请求事实，避免保存整份榜单对象。"""
        return {
            key: row.get(key)
            for key in ("title", "year", "media_type", "season", "tmdb_id", "source_key", "source_label")
            if row.get(key) not in (None, "")
        }

    def _subscription_exists(self, row: Dict[str, Any]) -> bool:
        """用 MoviePilot 当前订阅仓储按 TMDB+季确认 GYSub 是否真正落库。"""
        tmdb_id = str(row.get("tmdb_id") or "").strip()
        media_type = str(row.get("media_type") or "tv").lower()
        if not tmdb_id or media_type not in {"movie", "tv"}:
            return False
        mtype = _mtype(media_type)
        try:
            info = MediaChain().recognize_media(
                mtype=mtype,
                media_source=MediaSource.TMDB,
                media_id=tmdb_id,
                cache=False,
            )
        except TypeError:
            info = MediaChain().recognize_media(mtype=mtype, media_source=MediaSource.TMDB, media_id=tmdb_id)
        except Exception as err:
            logger.debug("【每日助手】GYSub 落库确认识别失败 TMDB %s: %s", tmdb_id, err)
            return False
        if not info:
            return False
        meta = MetaInfo(str(row.get("title") or getattr(info, "title", "") or ""))
        meta.type = mtype
        if mtype == MediaType.TV:
            meta.begin_season = _safe_int(row.get("season"), 1, 1, 99)
        try:
            return bool(SubscribeChain().exists(mediainfo=info, meta=meta))
        except Exception as err:
            logger.debug("【每日助手】GYSub 落库确认失败 TMDB %s: %s", tmdb_id, err)
            return False

    def _confirm_gysub(self, row: Dict[str, Any], *, source: str) -> None:
        identity = self._candidate_identity(row)
        submitted = self.get_data("gysub_submitted") or {}
        if not isinstance(submitted, dict):
            submitted = {}
        submitted[identity] = {
            "confirmed_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "source": source,
            "row": self._pending_row(row),
        }
        self.save_data("gysub_submitted", submitted)
        pending = self.get_data("gysub_pending") or {}
        if isinstance(pending, dict) and identity in pending:
            pending.pop(identity, None)
            self.save_data("gysub_pending", pending)

    def _reconcile_pending_gysub(self) -> Dict[str, int]:
        """把广播请求与实际 MoviePilot 订阅事实对账；超时请求自动释放以允许重试。"""
        pending = self.get_data("gysub_pending") or {}
        if not isinstance(pending, dict) or not pending:
            return {"confirmed": 0, "expired": 0, "pending": 0}
        now = datetime.datetime.now()
        confirmed = 0
        expired = 0
        changed = False
        submitted = self.get_data("gysub_submitted") or {}
        if not isinstance(submitted, dict):
            submitted = {}
        for identity, entry in list(pending.items()):
            entry = entry if isinstance(entry, dict) else {}
            row = entry.get("row") if isinstance(entry.get("row"), dict) else {}
            if row and self._subscription_exists(row):
                submitted[identity] = {
                    "confirmed_at": now.isoformat(timespec="seconds"),
                    "source": entry.get("source") or "每日助手",
                    "row": row,
                }
                pending.pop(identity, None)
                confirmed += 1
                changed = True
                continue
            try:
                requested_at = datetime.datetime.fromisoformat(str(entry.get("requested_at") or ""))
            except (TypeError, ValueError):
                requested_at = now - self._gysub_pending_ttl - datetime.timedelta(seconds=1)
            if now - requested_at > self._gysub_pending_ttl:
                pending.pop(identity, None)
                expired += 1
                changed = True
        if changed:
            self.save_data("gysub_pending", pending)
            self.save_data("gysub_submitted", submitted)
        return {"confirmed": confirmed, "expired": expired, "pending": len(pending)}

    def _dispatch_gysub(self, row: Dict[str, Any], *, source: str = "每日助手") -> Dict[str, Any]:
        """发送光鸭 GYSub 请求；只有 MoviePilot 订阅实际存在后才写入已确认去重状态。"""
        tmdb_id = str(row.get("tmdb_id") or "").strip()
        media_type = str(row.get("media_type") or "tv").lower()
        if not tmdb_id or media_type not in {"movie", "tv"}:
            return {"success": False, "status": "rejected", "message": "缺少 TMDB 精确身份，未提交 GYSub"}
        identity = self._candidate_identity(row)
        if self._subscription_exists(row):
            self._confirm_gysub(row, source=source)
            return {"success": True, "status": "confirmed", "confirmed": True, "message": f"GYSub 已存在：{row.get('title')}"}

        now = datetime.datetime.now()
        pending = self.get_data("gysub_pending") or {}
        if not isinstance(pending, dict):
            pending = {}
        existing = pending.get(identity)
        if isinstance(existing, dict):
            try:
                requested_at = datetime.datetime.fromisoformat(str(existing.get("requested_at") or ""))
            except (TypeError, ValueError):
                requested_at = now - self._gysub_pending_ttl - datetime.timedelta(seconds=1)
            if now - requested_at <= self._gysub_pending_ttl:
                return {
                    "success": True,
                    "status": "pending",
                    "confirmed": False,
                    "message": f"GYSub 请求处理中：{row.get('title')}，等待 MoviePilot 订阅落库确认",
                }
            pending.pop(identity, None)

        arg = f"tmdb:{tmdb_id} {media_type}"
        if media_type == "tv":
            season = _safe_int(row.get("season"), 1, 1, 99)
            arg += f" S{season:02d}"
        event_data = {"action": "guangya_direct_subscribe", "arg_str": arg}
        try:
            eventmanager.send_event(EventType.PluginAction, event_data)
        except Exception as err:
            logger.error("【每日助手】GYSub 事件发送失败 %s: %s", arg, err)
            return {"success": False, "status": "failed", "message": str(err)}

        pending[identity] = {
            "requested_at": now.isoformat(timespec="seconds"),
            "source": source,
            "arg": arg,
            "row": self._pending_row(row),
        }
        self.save_data("gysub_pending", pending)
        logger.info("【每日助手】已发送 GYSub 请求：%s %s source=%s，等待订阅落库确认", row.get("title"), arg, source)
        return {
            "success": True,
            "status": "requested",
            "confirmed": False,
            "message": f"已发送 GYSub 请求：{row.get('title')} ({arg})，等待落库确认",
        }

    def refresh(self, manual: bool = False) -> Dict[str, Any]:
        """刷新所有启用榜单，统一识别、去重并可按榜单自动提交 GYSub。"""
        statuses: List[Dict[str, Any]] = []
        candidates: List[Dict[str, Any]] = []
        seen = set()
        filtered_library = 0
        unresolved = 0
        auto_requested = 0
        auto_confirmed = 0
        auto_failed = 0

        for source_key in self._source_keys:
            result = fetch_source(source_key, self._rank_limit, self._proxy)
            statuses.append({
                "key": source_key,
                "label": result.get("label") or source_key,
                "ok": bool(result.get("ok")),
                "count": len(result.get("items") or []),
                "error": result.get("error") or "",
            })
            for raw in result.get("items") or []:
                row, info = self._resolve_tmdb(raw)
                vote = row.get("vote_average")
                try:
                    if self._vote_min > 0 and vote is not None and float(vote) < self._vote_min:
                        continue
                except (TypeError, ValueError):
                    pass
                if self._library_complete(info, row):
                    filtered_library += 1
                    continue
                identity = self._candidate_identity(row)
                if identity in seen:
                    continue
                seen.add(identity)
                row["index"] = len(candidates) + 1
                row["resolved"] = bool(row.get("tmdb_id"))
                if not row["resolved"]:
                    unresolved += 1
                candidates.append(row)

        reconcile = self._reconcile_pending_gysub()
        payload = {
            "batch_id": datetime.datetime.now().strftime("%Y%m%d%H%M%S"),
            "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "manual": bool(manual),
            "source_count": len(self._source_keys),
            "statuses": statuses,
            "candidates": candidates,
            "filtered_library": filtered_library,
            "unresolved": unresolved,
            "gysub_reconcile": reconcile,
        }
        self.save_data("dailyassistant_candidates", payload)

        if self._auto_gysub and self._auto_source_keys:
            for row in candidates:
                if row.get("source_key") not in self._auto_source_keys or not row.get("tmdb_id"):
                    continue
                result = self._dispatch_gysub(row, source="每日助手自动订阅")
                if not result.get("success"):
                    auto_failed += 1
                elif result.get("status") == "requested":
                    auto_requested += 1
                elif result.get("status") == "confirmed":
                    auto_confirmed += 1

        payload["auto_requested"] = auto_requested
        payload["auto_confirmed"] = auto_confirmed
        payload["auto_success"] = auto_requested + auto_confirmed
        payload["auto_failed"] = auto_failed
        self.save_data("dailyassistant_candidates", payload)
        logger.info(
            "【每日助手】刷新完成：榜单=%s 候选=%s 媒体库过滤=%s 未识别=%s GYSub请求=%s 确认=%s 失败=%s 待确认=%s",
            len(self._source_keys), len(candidates), filtered_library, unresolved,
            auto_requested, auto_confirmed, auto_failed, reconcile.get("pending", 0),
        )
        return {
            "success": True,
            "data": payload,
            "message": f"发现 {len(candidates)} 个候选，自动 GYSub 请求 {auto_requested} 个，已确认 {auto_confirmed} 个",
        }

    def api_refresh(self) -> Dict[str, Any]:
        """手动刷新榜单 API。"""
        return self.refresh(manual=True)

    def api_gysub(self, index: int = 0, batch_id: str = "") -> Dict[str, Any]:
        """把候选条目提交给光鸭 GYSub。"""
        payload = self.get_data("dailyassistant_candidates") or {}
        if batch_id and str(payload.get("batch_id") or "") != str(batch_id):
            return {"success": False, "message": "候选批次已刷新，请重新打开页面"}
        candidates = payload.get("candidates") or []
        try:
            row = next(item for item in candidates if int(item.get("index") or 0) == int(index))
        except (StopIteration, TypeError, ValueError):
            return {"success": False, "message": "候选序号不存在"}
        return self._dispatch_gysub(dict(row))

    def api_state(self) -> Dict[str, Any]:
        """返回最近一次发现状态。"""
        return {"success": True, "data": self.get_data("dailyassistant_candidates") or {}}

    def get_api(self) -> List[Dict[str, Any]]:
        """注册插件 API。"""
        return [
            {"path": "/refresh", "endpoint": self.api_refresh, "methods": ["GET"], "summary": "刷新每日助手榜单"},
            {"path": "/gysub", "endpoint": self.api_gysub, "methods": ["GET"], "summary": "提交候选到 GYSub"},
            {"path": "/state", "endpoint": self.api_state, "methods": ["GET"], "summary": "读取每日助手状态"},
        ]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """返回每日助手配置表单。"""
        options = source_options()
        return [{
            "component": "VForm",
            "content": [
                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "enabled", "label": "启用每日助手"}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "onlyonce", "label": "保存后立即刷新"}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "proxy", "label": "外部榜单使用代理"}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "auto_gysub", "label": "启用自动 GYSub"}}]},
                ]},
                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VTextField", "props": {"model": "cron", "label": "刷新 Cron", "placeholder": "15 8 * * *"}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VTextField", "props": {"model": "rank_limit", "label": "每榜最多候选"}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VTextField", "props": {"model": "vote_min", "label": "最低评分（0=不限）"}}]},
                ]},
                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12}, "content": [{"component": "VSelect", "props": {"model": "source_keys", "label": "启用榜单", "items": options, "multiple": True, "chips": True, "clearable": True}}]},
                    {"component": "VCol", "props": {"cols": 12}, "content": [{"component": "VSelect", "props": {"model": "auto_source_keys", "label": "允许自动 GYSub 的榜单", "hint": "只有同时开启“自动 GYSub”的这些榜单会自动订阅，其余只作为候选。", "persistentHint": True, "items": options, "multiple": True, "chips": True, "clearable": True}}]},
                ]},
            ],
        }], {
            "enabled": False, "cron": "15 8 * * *", "onlyonce": False, "proxy": False,
            "rank_limit": 20, "vote_min": 0.0, "auto_gysub": False,
            "source_keys": list(DEFAULT_SOURCE_KEYS), "auto_source_keys": [],
        }

    def get_page(self) -> List[dict]:
        """展示最近发现、榜单状态和 GYSub 操作。"""
        payload = self.get_data("dailyassistant_candidates") or {}
        candidates = payload.get("candidates") or []
        statuses = payload.get("statuses") or []
        batch_id = str(payload.get("batch_id") or "")
        reconcile = payload.get("gysub_reconcile") or {}
        status_lines = [
            f"{'✅' if item.get('ok') else '❌'} {item.get('label')}: {item.get('count', 0)}" + (f" · {item.get('error')}" if item.get("error") else "")
            for item in statuses
        ]
        cards: List[dict] = [{
            "component": "VAlert",
            "props": {"type": "info", "variant": "tonal", "text": (
                f"更新时间：{payload.get('updated_at') or '尚未刷新'} · 候选 {len(candidates)} · "
                f"已入库过滤 {payload.get('filtered_library', 0)} · 待识别 {payload.get('unresolved', 0)} · "
                f"GYSub待确认 {reconcile.get('pending', 0)}"
            )},
        }]
        if status_lines:
            cards.append({"component": "VCard", "props": {"variant": "tonal", "class": "mb-3"}, "content": [{"component": "VCardText", "text": "\n".join(status_lines)}]})
        for row in candidates[:200]:
            title = f"#{row.get('index')} {row.get('title')} ({row.get('year') or '-'})"
            subtitle = f"{row.get('source_label')} · {row.get('media_type')} · TMDB {row.get('tmdb_id') or '待识别'}"
            content = [{"component": "VCardTitle", "text": title}, {"component": "VCardSubtitle", "text": subtitle}]
            if row.get("tmdb_id"):
                content.append({
                    "component": "VCardActions",
                    "content": [{
                        "component": "VBtn",
                        "props": {"text": "加入 GYSub", "variant": "tonal", "prependIcon": "mdi-cloud-download-outline"},
                        "events": {"click": {
                            "api": "plugin/DailyAssistant/gysub", "method": "get",
                            "params": {"index": str(row.get("index") or ""), "batch_id": batch_id, "apikey": settings.API_TOKEN},
                        }},
                    }],
                })
            cards.append({"component": "VCard", "props": {"variant": "outlined", "class": "mb-2"}, "content": content})
        return cards

    def stop_service(self) -> None:
        """插件停用时无常驻线程需要回收。"""
        return None


class DailyAssistant(DailyAssistantV110Mixin, DailyAssistantV100):
    """v1.1.0 最终运行类。"""

    plugin_version = "1.1.0"


__all__ = ["DailyAssistant"]
