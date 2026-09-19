"""每日助手：只负责发现最新电影/电视剧并创建 MoviePilot 订阅。"""
from __future__ import annotations

import datetime
import re
from typing import Any, Dict, List, Optional, Tuple

from app.chain.download import DownloadChain
from app.chain.media import MediaChain
from app.chain.subscribe import SubscribeChain
from app.plugins import _PluginBase
from app.sdk.logging import logger
from app.sdk.media import MetaInfo
from app.schemas.types import MediaSource, MediaType

from .sources import SOURCE_MAP, fetch_source, source_options

try:
    from app.runtime.cache import fresh
except Exception:
    fresh = None


LATEST_SOURCE_KEYS = [
    "tmdb_latest_movie",
    "tmdb_latest_tv",
    "douban_showing",
    "douban_coming",
    "douban_new_movies",
    "douban_tv_recent",
    "maoyan_movie",
    "maoyan_tv",
    "tencent_hot",
    "tencent_tv",
]


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
    """高频发现最新影视，只创建 MoviePilot 原生订阅。"""

    plugin_name = "每日助手"
    plugin_desc = "TMDB 最新电影/电视剧为主源，豆瓣/猫眼/腾讯补漏，精确识别后只创建 MoviePilot 订阅。"
    plugin_icon = "movie.jpg"
    plugin_version = "1.3.4"
    plugin_author = "liheng-lk"
    plugin_label = "MoviePilot订阅,最新电影,最新电视剧,TMDB,豆瓣,猫眼"
    author_url = "https://github.com/liheng-lk/MoviePilot-Plugins"
    plugin_config_prefix = "dailyassistant_"
    plugin_order = 19
    auth_level = 1

    _enabled = False
    _onlyonce = False
    _proxy = False
    _interval_minutes = 10
    _rank_limit = 30
    _vote_min = 0.0
    _recent_days = 30
    _future_days = 60
    _source_keys: List[str] = list(LATEST_SOURCE_KEYS)

    def init_plugin(self, config: Optional[dict] = None) -> None:
        config = config or {}
        self._enabled = bool(config.get("enabled", False))
        self._onlyonce = bool(config.get("onlyonce", False))
        self._proxy = bool(config.get("proxy", False))
        self._interval_minutes = _safe_int(config.get("interval_minutes"), 10, 5, 60)
        self._rank_limit = _safe_int(config.get("rank_limit"), 30, 5, 100)
        self._vote_min = _safe_float(config.get("vote_min"), 0.0, 0.0, 10.0)
        self._recent_days = _safe_int(config.get("recent_days"), 30, 1, 180)
        self._future_days = _safe_int(config.get("future_days"), 60, 0, 365)
        source_keys = [key for key in _as_list(config.get("source_keys")) if key in SOURCE_MAP]
        self._source_keys = source_keys or list(LATEST_SOURCE_KEYS)

    def get_state(self) -> bool:
        return self._enabled

    def _save_config(self, *, onlyonce: Optional[bool] = None) -> None:
        self.update_config({
            "enabled": self._enabled,
            "onlyonce": self._onlyonce if onlyonce is None else onlyonce,
            "proxy": self._proxy,
            "interval_minutes": self._interval_minutes,
            "rank_limit": self._rank_limit,
            "vote_min": self._vote_min,
            "recent_days": self._recent_days,
            "future_days": self._future_days,
            "source_keys": self._source_keys,
        })

    def get_service(self) -> List[Dict[str, Any]]:
        services: List[Dict[str, Any]] = []
        if self._onlyonce:
            services.append({
                "id": "DailyAssistantOnce",
                "name": "每日助手立即订阅检查",
                "trigger": "date",
                "func": self.refresh,
                "kwargs": {"run_date": datetime.datetime.now() + datetime.timedelta(seconds=3)},
                "func_kwargs": {"manual": True},
            })
            self._save_config(onlyonce=False)
        if self._enabled:
            services.append({
                "id": "DailyAssistantSubscribe",
                "name": "每日助手最新影视订阅",
                "trigger": "interval",
                "func": self.refresh,
                "kwargs": {"minutes": self._interval_minutes},
                "func_kwargs": {"manual": False},
            })
        return services

    @staticmethod
    def _candidate_tmdb_id(info: Any) -> str:
        return str(
            getattr(info, "tmdb_id", None)
            or (
                getattr(info, "media_id", None)
                if str(
                    getattr(
                        getattr(info, "media_source", None),
                        "value",
                        getattr(info, "media_source", ""),
                    )
                ).lower() == "tmdb"
                else ""
            )
            or ""
        ).strip()

    def _resolve_tmdb(self, item: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[Any]]:
        row = dict(item)
        mtype = _mtype(str(row.get("media_type") or "tv"))
        tmdb_id = str(row.get("tmdb_id") or "").strip()
        chain = MediaChain()

        if tmdb_id:
            try:
                info = chain.recognize_media(
                    mtype=mtype,
                    media_source=MediaSource.TMDB,
                    media_id=tmdb_id,
                    cache=False,
                )
            except TypeError:
                info = chain.recognize_media(
                    mtype=mtype, media_source=MediaSource.TMDB, media_id=tmdb_id
                )
            except Exception as err:
                logger.debug("【每日助手】TMDB识别失败 %s: %s", tmdb_id, err)
                info = None
            if info:
                row["title"] = str(getattr(info, "title", None) or row.get("title") or "")
                row["year"] = getattr(info, "year", None) or row.get("year")
                row["tmdb_id"] = self._candidate_tmdb_id(info) or tmdb_id
                row = self._resolve_tv_season(info, row)
                return row, info

        for field, source in (
            ("imdb_id", MediaSource.IMDb),
            ("anilist_id", MediaSource.AniList),
            ("bangumi_id", MediaSource.Bangumi),
            ("douban_id", MediaSource.Douban),
        ):
            media_id = str(row.get(field) or "").strip()
            if not media_id:
                continue
            try:
                info = chain.recognize_media(mtype=mtype, media_source=source, media_id=media_id)
            except Exception:
                info = None
            if info and self._candidate_tmdb_id(info):
                row["tmdb_id"] = self._candidate_tmdb_id(info)
                row["title"] = str(getattr(info, "title", None) or row.get("title") or "")
                row["year"] = getattr(info, "year", None) or row.get("year")
                row["season"] = row.get("season") or getattr(info, "season", None)
                row = self._resolve_tv_season(info, row)
                return row, info

        title = str(row.get("title") or "").strip()
        if not title:
            return row, None
        try:
            _, medias = chain.search(title=title, media_source=MediaSource.TMDB)
        except Exception:
            return row, None

        wanted_year = str(row.get("year") or "").strip()
        title_norm = re.sub(r"\W+", "", title.casefold())
        matches = []
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
                matches.append(info)
        if len(matches) != 1:
            return row, None
        info = matches[0]
        row["tmdb_id"] = self._candidate_tmdb_id(info)
        row["title"] = str(getattr(info, "title", None) or title)
        row["year"] = getattr(info, "year", None) or row.get("year")
        row = self._resolve_tv_season(info, row)
        return row, info

    def _resolve_tv_season(self, info: Any, row: Dict[str, Any]) -> Dict[str, Any]:
        """为多季电视剧解析本次应订阅的真实季号，优先使用 TMDB 季首播日期。"""
        if str(row.get("media_type") or "").lower() != "tv":
            return row

        explicit = row.get("season")
        try:
            explicit_season = int(explicit) if explicit not in (None, "") else None
        except (TypeError, ValueError):
            explicit_season = None
        if explicit_season and explicit_season > 0:
            row["season"] = explicit_season
            return row

        today = datetime.date.today()
        candidates: List[Tuple[datetime.date, int]] = []
        season_info = getattr(info, "season_info", None) or []
        for item in season_info:
            if isinstance(item, dict):
                number = item.get("season_number")
                air_value = item.get("air_date")
            else:
                number = getattr(item, "season_number", None)
                air_value = getattr(item, "air_date", None)
            try:
                season_number = int(number)
            except (TypeError, ValueError):
                continue
            if season_number <= 0:
                continue
            air_date = self._parse_date(air_value)
            if not air_date:
                continue
            delta = (air_date - today).days
            if -self._recent_days <= delta <= self._future_days:
                candidates.append((air_date, season_number))

        if candidates:
            # 同一作品如果多季都处于窗口，订阅首播日期最新的那一季。
            _, season = max(candidates, key=lambda value: (value[0], value[1]))
            row["season"] = season
            return row

        # 兜底：只有当 MoviePilot 明确给出当前季时才采用，不再无条件回退 S01。
        current = getattr(info, "season", None)
        try:
            current_season = int(current) if current not in (None, "") else None
        except (TypeError, ValueError):
            current_season = None
        if current_season and current_season > 0:
            row["season"] = current_season
        return row

    def _season_air_date(self, info: Any, season: Any) -> Optional[datetime.date]:
        try:
            wanted = int(season)
        except (TypeError, ValueError):
            return None
        for item in getattr(info, "season_info", None) or []:
            if isinstance(item, dict):
                number = item.get("season_number")
                air_value = item.get("air_date")
            else:
                number = getattr(item, "season_number", None)
                air_value = getattr(item, "air_date", None)
            try:
                number = int(number)
            except (TypeError, ValueError):
                continue
            if number == wanted:
                return self._parse_date(air_value)
        return None

    @staticmethod
    def _parse_date(value: Any) -> Optional[datetime.date]:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return datetime.date.fromisoformat(text[:10])
        except ValueError:
            return None

    def _release_date(self, info: Any, row: Dict[str, Any]) -> Optional[datetime.date]:
        if str(row.get("media_type") or "") == "movie":
            values = (
                getattr(info, "release_date", None),
                row.get("release_date"),
                row.get("air_date"),
            )
        else:
            season_date = self._season_air_date(info, row.get("season")) if row.get("season") else None
            values = (
                season_date,
                row.get("air_date"),
                row.get("release_date"),
                getattr(info, "first_air_date", None),
                getattr(info, "release_date", None),
                row.get("first_air_date"),
            )
        for value in values:
            parsed = self._parse_date(value)
            if parsed:
                return parsed
        return None

    def _is_latest(self, info: Any, row: Dict[str, Any]) -> bool:
        release_date = self._release_date(info, row)
        if not release_date:
            return False
        today = datetime.date.today()
        delta = (release_date - today).days
        return -self._recent_days <= delta <= self._future_days

    @staticmethod
    def _library_has_content(info: Any, row: Dict[str, Any]) -> bool:
        """电影存在即跳过；电视剧只检查目标季，目标季已有任意内容即跳过。"""
        if not info:
            return False
        try:
            meta = MetaInfo(str(row.get("title") or getattr(info, "title", "") or ""))
            meta.type = _mtype(str(row.get("media_type") or "tv"))
            if row.get("season"):
                meta.begin_season = int(row["season"])
            complete, no_exists = DownloadChain().get_no_exists_info(meta=meta, mediainfo=info)
            if complete:
                return True
            if meta.type != MediaType.TV:
                return False

            seasons = getattr(info, "seasons", None) or {}
            if row.get("season"):
                expected_seasons = {int(row["season"])}
            else:
                expected_seasons = {int(season) for season, episodes in seasons.items() if episodes}
            if not expected_seasons:
                return False

            missing_by_season: Dict[int, Any] = {}
            for season_map in (no_exists or {}).values():
                if not isinstance(season_map, dict):
                    continue
                for season, detail in season_map.items():
                    try:
                        missing_by_season[int(season)] = detail
                    except (TypeError, ValueError):
                        continue

            for season in expected_seasons:
                detail = missing_by_season.get(season)
                if detail is None:
                    # 该季没有出现在缺失列表，说明整季已存在。
                    return True
                missing_episodes = getattr(detail, "episodes", None)
                if missing_episodes is None and isinstance(detail, dict):
                    missing_episodes = detail.get("episodes")
                # MoviePilot 用 [] 表示整季不存在；非空列表表示只缺部分集，即库里已有内容。
                if missing_episodes:
                    return True
            return False
        except Exception as err:
            logger.debug("【每日助手】媒体库存在性检查失败 %s: %s", row.get("title"), err)
            return False

    @staticmethod
    def _identity(row: Dict[str, Any]) -> str:
        tmdb_id = str(row.get("tmdb_id") or "").strip()
        media_type = str(row.get("media_type") or "").lower()
        season = ""
        if media_type == "tv":
            try:
                value = int(row.get("season")) if row.get("season") not in (None, "") else None
                season = f":s{value:02d}" if value and value > 0 else ":s00"
            except (TypeError, ValueError):
                season = ":s00"
        return f"tmdb:{tmdb_id}:{media_type}{season}" if tmdb_id and media_type else ""

    def _load_processed(self) -> Dict[str, Any]:
        data = self.get_data("dailyassistant_processed") or {}
        return data if isinstance(data, dict) else {}

    def _remember_processed(self, row: Dict[str, Any], status: str, *, source: str = "") -> None:
        identity = self._identity(row)
        if not identity:
            return
        data = self._load_processed()
        data[identity] = {
            "status": status,
            "title": row.get("title"),
            "year": row.get("year"),
            "media_type": row.get("media_type"),
            "season": row.get("season"),
            "tmdb_id": row.get("tmdb_id"),
            "source": source or row.get("source_label") or row.get("source_key") or "",
            "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        # 防止无限增长；保留最近 5000 条处理记录。
        if len(data) > 5000:
            ordered = sorted(
                data.items(),
                key=lambda item: str((item[1] or {}).get("updated_at") or ""),
                reverse=True,
            )[:5000]
            data = dict(ordered)
        self.save_data("dailyassistant_processed", data)

    def _subscribe(self, info: Any, row: Dict[str, Any]) -> Dict[str, Any]:
        mtype = _mtype(str(row.get("media_type") or "tv"))
        meta = MetaInfo(str(row.get("title") or getattr(info, "title", "") or ""))
        meta.type = mtype

        season = None
        if mtype == MediaType.TV:
            raw_season = row.get("season")
            try:
                season = int(raw_season) if raw_season not in (None, "") else None
            except (TypeError, ValueError):
                season = None
            if not season or season <= 0:
                return {"status": "failed", "success": False, "message": "未能确定当前新季季号"}
            meta.begin_season = season

        chain = SubscribeChain()
        try:
            if chain.exists(mediainfo=info, meta=meta):
                return {"status": "exists", "success": True}
        except Exception as err:
            logger.debug("【每日助手】订阅存在性检查失败 %s: %s", row.get("title"), err)

        media_source = getattr(info, "media_source", None) or MediaSource.TMDB
        media_id = getattr(info, "media_id", None) or getattr(info, "tmdb_id", None) or row.get("tmdb_id")
        if not media_id:
            return {"status": "failed", "success": False, "message": "缺少媒体ID"}

        try:
            sid, err_msg = chain.add(
                title=getattr(info, "title", None) or str(row.get("title") or ""),
                year=getattr(info, "year", None) or row.get("year"),
                mtype=mtype,
                media_source=media_source,
                media_id=str(media_id),
                season=season,
                message=False,
                exist_ok=True,
                username="每日助手",
            )
        except Exception as err:
            return {"status": "failed", "success": False, "message": str(err)}

        if sid:
            return {"status": "created", "success": True, "id": sid}
        return {"status": "failed", "success": False, "message": err_msg or "添加失败"}

    def refresh(self, manual: bool = False) -> Dict[str, Any]:
        now = datetime.datetime.now()
        seen = set()
        created: List[Dict[str, Any]] = []
        existed = 0
        library = 0
        outdated = 0
        unresolved = 0
        failed = 0
        statuses: List[Dict[str, Any]] = []
        processed = self._load_processed()
        processed_skip = 0

        for source_key in self._source_keys:
            try:
                if fresh:
                    with fresh(True):
                        result = fetch_source(source_key, self._rank_limit, self._proxy)
                else:
                    result = fetch_source(source_key, self._rank_limit, self._proxy)
            except Exception as err:
                result = {"ok": False, "label": source_key, "items": [], "error": str(err)}

            statuses.append({
                "key": source_key,
                "label": result.get("label") or source_key,
                "ok": bool(result.get("ok")),
                "count": len(result.get("items") or []),
                "error": result.get("error") or "",
            })

            for raw in result.get("items") or []:
                row, info = self._resolve_tmdb(raw)
                tmdb_id = str(row.get("tmdb_id") or "")
                media_type = str(row.get("media_type") or "")
                identity = f"{tmdb_id}:{media_type}" if tmdb_id else ""
                if not identity or identity in seen or not info:
                    unresolved += 1 if not tmdb_id or not info else 0
                    continue
                seen.add(identity)

                processed_identity = self._identity(row)
                if processed_identity and processed_identity in processed:
                    processed_skip += 1
                    continue

                try:
                    vote = float(row.get("vote_average") or getattr(info, "vote_average", 0) or 0)
                except (TypeError, ValueError):
                    vote = 0
                if self._vote_min > 0 and vote < self._vote_min:
                    continue
                if not self._is_latest(info, row):
                    outdated += 1
                    continue
                if self._library_has_content(info, row):
                    library += 1
                    self._remember_processed(row, "library", source=row.get("source_label") or source_key)
                    processed[self._identity(row)] = {"status": "library"}
                    continue

                sub = self._subscribe(info, row)
                if sub.get("status") == "created":
                    release_date = self._release_date(info, row)
                    created.append({
                        "title": getattr(info, "title", None) or row.get("title"),
                        "year": getattr(info, "year", None) or row.get("year"),
                        "media_type": media_type,
                        "season": row.get("season"),
                        "tmdb_id": tmdb_id,
                        "release_date": release_date.isoformat() if release_date else "",
                        "source": row.get("source_label") or source_key,
                    })
                    self._remember_processed(row, "created", source=created[-1]["source"])
                    processed[self._identity(row)] = {"status": "created"}
                    logger.info(
                        "【每日助手】【订阅成功】%s (%s) type=%s season=%s TMDB=%s source=%s",
                        created[-1]["title"], created[-1]["year"] or "-", media_type,
                        (f"S{int(row.get('season')):02d}" if row.get("season") else "-"),
                        tmdb_id, created[-1]["source"],
                    )
                elif sub.get("status") == "exists":
                    existed += 1
                    self._remember_processed(row, "exists", source=row.get("source_label") or source_key)
                    processed[self._identity(row)] = {"status": "exists"}
                else:
                    failed += 1
                    logger.warning(
                        "【每日助手】【订阅失败】%s TMDB=%s: %s",
                        row.get("title"), tmdb_id, sub.get("message") or "未知错误",
                    )

        payload = {
            "updated_at": now.isoformat(timespec="seconds"),
            "manual": bool(manual),
            "created": created,
            "created_count": len(created),
            "exists_count": existed,
            "library_count": library,
            "outdated_count": outdated,
            "unresolved_count": unresolved,
            "failed_count": failed,
            "processed_skip_count": processed_skip,
            "processed_total": len(self._load_processed()),
            "statuses": statuses,
            "interval_minutes": self._interval_minutes,
            "recent_days": self._recent_days,
            "future_days": self._future_days,
        }
        self.save_data("dailyassistant_last_run", payload)
        logger.info(
            "【每日助手】订阅检查完成：新增=%s 已订阅=%s 已入库=%s 历史跳过=%s 非最新=%s 未识别=%s 失败=%s",
            len(created), existed, library, processed_skip, outdated, unresolved, failed,
        )
        return {
            "success": True,
            "data": payload,
            "message": f"新增订阅 {len(created)}，已订阅 {existed}，已入库 {library}，历史跳过 {processed_skip}",
        }

    def api_refresh(self) -> Dict[str, Any]:
        return self.refresh(manual=True)

    def api_state(self) -> Dict[str, Any]:
        return {"success": True, "data": self.get_data("dailyassistant_last_run") or {}}

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {"path": "/refresh", "endpoint": self.api_refresh, "methods": ["GET"], "summary": "立即检查最新影视并订阅"},
            {"path": "/state", "endpoint": self.api_state, "methods": ["GET"], "summary": "读取最近订阅检查状态"},
        ]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        options = source_options()
        return [{
            "component": "VForm",
            "content": [
                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                        {"component": "VSwitch", "props": {"model": "enabled", "label": "启用最新影视订阅"}}
                    ]},
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                        {"component": "VSwitch", "props": {"model": "onlyonce", "label": "保存后立即检查"}}
                    ]},
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                        {"component": "VSwitch", "props": {"model": "proxy", "label": "外部来源使用代理"}}
                    ]},
                ]},
                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [
                        {"component": "VTextField", "props": {"model": "interval_minutes", "label": "检查间隔（分钟）", "hint": "5-60，默认10", "persistentHint": True}}
                    ]},
                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [
                        {"component": "VTextField", "props": {"model": "recent_days", "label": "已上映回看天数"}}
                    ]},
                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [
                        {"component": "VTextField", "props": {"model": "future_days", "label": "提前订阅天数"}}
                    ]},
                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [
                        {"component": "VTextField", "props": {"model": "vote_min", "label": "最低评分（0=不限）"}}
                    ]},
                ]},
                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12}, "content": [
                        {"component": "VSelect", "props": {
                            "model": "source_keys",
                            "label": "最新影视来源",
                            "items": options,
                            "multiple": True,
                            "chips": True,
                            "clearable": True,
                        }}
                    ]}
                ]},
            ],
        }], {
            "enabled": False,
            "onlyonce": False,
            "proxy": False,
            "interval_minutes": 10,
            "rank_limit": 30,
            "vote_min": 0.0,
            "recent_days": 30,
            "future_days": 60,
            "source_keys": list(LATEST_SOURCE_KEYS),
        }

    def get_page(self) -> List[dict]:
        data = self.get_data("dailyassistant_last_run") or {}
        created = data.get("created") or []
        cards: List[dict] = [{
            "component": "VAlert",
            "props": {
                "type": "info",
                "variant": "tonal",
                "text": (
                    f"最近检查：{data.get('updated_at') or '尚未运行'} · "
                    f"新增订阅 {data.get('created_count', 0)} · "
                    f"已订阅 {data.get('exists_count', 0)} · "
                    f"已入库 {data.get('library_count', 0)} · "
                    f"历史跳过 {data.get('processed_skip_count', 0)} · "
                    f"非最新过滤 {data.get('outdated_count', 0)}"
                ),
            },
        }]
        for item in created[:100]:
            cards.append({
                "component": "VCard",
                "props": {"variant": "outlined", "class": "mb-2"},
                "content": [
                    {"component": "VCardTitle", "text": f"{item.get('title')} ({item.get('year') or '-'})"},
                    {"component": "VCardSubtitle", "text": f"{item.get('media_type')} · TMDB {item.get('tmdb_id')} · {item.get('release_date') or '日期未知'}"},
                ],
            })
        return cards

    def stop_service(self) -> None:
        return None


__all__ = ["DailyAssistant"]
