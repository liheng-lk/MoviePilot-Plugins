"""每日助手：把全媒体榜单发现统一送入光鸭 GYSub 固定转存路线。"""
from __future__ import annotations

import datetime
import re
from typing import Any, Dict, List, Optional, Tuple

from apscheduler.triggers.cron import CronTrigger

from app.chain.download import DownloadChain
from app.chain.media import MediaChain
from app.plugins import _PluginBase
from app.sdk.config import settings
from app.sdk.events import eventmanager
from app.sdk.logging import logger
from app.sdk.media import MetaInfo
from app.schemas.types import EventType, MediaSource, MediaType

from .sources import DEFAULT_SOURCE_KEYS, SOURCE_MAP, fetch_source, source_options


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


class DailyAssistant(_PluginBase):
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
        if tmdb_id:
            return f"tmdb:{tmdb_id}:{item.get('media_type') or ''}"
        return f"title:{str(item.get('title') or '').casefold()}:{item.get('year') or ''}:{item.get('media_type') or ''}"

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

    def _dispatch_gysub(self, row: Dict[str, Any], *, source: str = "每日助手") -> Dict[str, Any]:
        """通过光鸭现有 /gysub PluginAction 精确创建固定转存订阅。"""
        tmdb_id = str(row.get("tmdb_id") or "").strip()
        media_type = str(row.get("media_type") or "tv").lower()
        if not tmdb_id or media_type not in {"movie", "tv"}:
            return {"success": False, "message": "缺少 TMDB 精确身份，未提交 GYSub"}
        arg = f"tmdb:{tmdb_id} {media_type}"
        if media_type == "tv":
            season = _safe_int(row.get("season"), 1, 1, 99)
            arg += f" S{season:02d}"
        event_data = {"action": "guangya_direct_subscribe", "arg_str": arg}
        try:
            eventmanager.send_event(EventType.PluginAction, event_data)
        except Exception as err:
            logger.error("【每日助手】GYSub 事件提交失败 %s: %s", arg, err)
            return {"success": False, "message": str(err)}
        identity = self._candidate_identity(row)
        submitted = self.get_data("gysub_submitted") or {}
        if not isinstance(submitted, dict):
            submitted = {}
        submitted[identity] = datetime.datetime.now().isoformat(timespec="seconds")
        self.save_data("gysub_submitted", submitted)
        logger.info("【每日助手】已提交 GYSub：%s %s source=%s", row.get("title"), arg, source)
        return {"success": True, "message": f"已提交 GYSub：{row.get('title')} ({arg})"}

    def refresh(self, manual: bool = False) -> Dict[str, Any]:
        """刷新所有启用榜单，统一识别、去重并可按榜单自动提交 GYSub。"""
        statuses: List[Dict[str, Any]] = []
        candidates: List[Dict[str, Any]] = []
        seen = set()
        filtered_library = 0
        unresolved = 0
        auto_success = 0
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

        payload = {
            "batch_id": datetime.datetime.now().strftime("%Y%m%d%H%M%S"),
            "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "manual": bool(manual),
            "source_count": len(self._source_keys),
            "statuses": statuses,
            "candidates": candidates,
            "filtered_library": filtered_library,
            "unresolved": unresolved,
        }
        self.save_data("dailyassistant_candidates", payload)

        if self._auto_gysub and self._auto_source_keys:
            submitted = self.get_data("gysub_submitted") or {}
            if not isinstance(submitted, dict):
                submitted = {}
            for row in candidates:
                if row.get("source_key") not in self._auto_source_keys or not row.get("tmdb_id"):
                    continue
                if self._candidate_identity(row) in submitted:
                    continue
                result = self._dispatch_gysub(row, source="每日助手自动订阅")
                if result.get("success"):
                    auto_success += 1
                else:
                    auto_failed += 1

        payload["auto_success"] = auto_success
        payload["auto_failed"] = auto_failed
        self.save_data("dailyassistant_candidates", payload)
        logger.info(
            "【每日助手】刷新完成：榜单=%s 候选=%s 媒体库过滤=%s 未识别=%s 自动GYSub=%s/%s",
            len(self._source_keys), len(candidates), filtered_library, unresolved, auto_success, auto_failed,
        )
        return {"success": True, "data": payload, "message": f"发现 {len(candidates)} 个候选，自动 GYSub {auto_success} 个"}

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
        status_lines = [
            f"{'✅' if item.get('ok') else '❌'} {item.get('label')}: {item.get('count', 0)}" + (f" · {item.get('error')}" if item.get("error") else "")
            for item in statuses
        ]
        cards: List[dict] = [{
            "component": "VAlert",
            "props": {"type": "info", "variant": "tonal", "text": (
                f"更新时间：{payload.get('updated_at') or '尚未刷新'} · 候选 {len(candidates)} · "
                f"已入库过滤 {payload.get('filtered_library', 0)} · 待识别 {payload.get('unresolved', 0)}"
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
