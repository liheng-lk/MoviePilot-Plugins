import datetime
import re
import uuid
import xml.dom.minidom
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional, Tuple

from apscheduler.triggers.cron import CronTrigger

from app.chain.download import DownloadChain
from app.chain.media import MediaChain
from app.chain.subscribe import SubscribeChain
from app.core.config import settings
from app.core.context import MediaInfo
from app.core.event import Event, eventmanager
from app.core.metainfo import MetaInfo
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import MediaType
from app.schemas.types import EventType
from app.utils.http import RequestUtils


def _parse_date_value(value: Any) -> Optional[datetime.date]:
    """兼容 ISO 日期、日期时间和 RSS RFC822 日期格式。"""
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.date.fromisoformat(text[:10])
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(text).date()
    except (TypeError, ValueError, OverflowError):
        return None


def _parse_indexes_value(text: str) -> List[int]:
    """解析单个序号、逗号列表和连续区间。"""
    indexes = set()
    for token in re.split(r"[,，\s]+", str(text or "").strip()):
        if not token:
            continue
        match = re.fullmatch(r"(\d+)\s*[-~—]\s*(\d+)", token)
        if match:
            start, end = int(match.group(1)), int(match.group(2))
            if start > end:
                start, end = end, start
            if end - start <= 100:
                indexes.update(range(start, end + 1))
        elif token.isdigit():
            indexes.add(int(token))
    return sorted(i for i in indexes if i > 0)


def _xml_tag_value(node: Any, tag: str) -> str:
    """读取 XML 节点下指定标签的文本或 CDATA 内容。"""
    elements = node.getElementsByTagName(tag)
    if not elements:
        return ""
    values = []
    for child in elements[0].childNodes:
        if child.nodeType in (child.TEXT_NODE, child.CDATA_SECTION_NODE):
            values.append(child.data)
    return "".join(values).strip()


def _parse_douban_rss(xml_text: str, source: str) -> List[Dict[str, Any]]:
    """把 RSSHub 豆瓣 RSS 文本解析成统一候选字典。"""
    dom_tree = xml.dom.minidom.parseString(xml_text)
    nodes = dom_tree.documentElement.getElementsByTagName("item")
    result: List[Dict[str, Any]] = []
    for node in nodes:
        title = _xml_tag_value(node, "title")
        link = _xml_tag_value(node, "link")
        description = _xml_tag_value(node, "description")
        pubdate = _xml_tag_value(node, "pubDate")
        ids = re.findall(r"/(\d+)(?=/|$)", link or "")
        years = re.findall(r"\b(19\d{2}|20\d{2})\b", f"{pubdate} {description}")
        parsed_date = _parse_date_value(pubdate)
        result.append({
            "title": title,
            "doubanid": ids[0] if ids else "",
            "year": int(years[0]) if years else (parsed_date.year if parsed_date and source == "coming" else None),
            "link": link,
            "description": description,
            # 只有“即将播出”路由的 pubDate 表示剧集播出日期；热门榜 RSS 时间不能当首播日期。
            "air_date": parsed_date.isoformat() if parsed_date and source == "coming" else "",
            "rss_pub_date": parsed_date.isoformat() if parsed_date else "",
            "source": source,
        })
    return result


def _format_air_timing_value(air_date: Optional[datetime.date], today: datetime.date) -> str:
    """把首播日期格式化成通知中的相对时间文本。"""
    if not air_date:
        return "日期待定"
    days = (air_date - today).days
    if days == 0:
        return "今天开播"
    if days > 0:
        return f"{air_date.isoformat()} · {days}天后"
    return f"{air_date.isoformat()} · 已开播{-days}天"


class DailyNewDrama(_PluginBase):
    """每日发现豆瓣新剧并在过滤媒体库、订阅后提供交互订阅。"""

    plugin_name = "每日新剧助手"
    plugin_desc = "每天发现豆瓣即将播出和近期热播新剧，过滤已订阅/已入库内容，并支持按序号订阅。"
    plugin_icon = "movie.jpg"
    plugin_version = "1.0"
    plugin_author = "liheng-lk"
    plugin_label = "豆瓣,电视剧,订阅,推荐,通知"
    author_url = "https://github.com/liheng-lk/MoviePilot-Plugins"
    plugin_config_prefix = "dailynewdrama_"
    plugin_order = 20
    auth_level = 1

    _enabled = False
    _cron = "0 9 * * *"
    _onlyonce = False
    _proxy = False
    _rsshub = "https://rsshub.app"
    _vote = 0.0
    _max_items = 12
    _coming_days = 30
    _recent_days = 21
    _coming_count = 40
    _include_hot = True
    _repeat_days = 7
    _notify_empty = False

    def init_plugin(self, config: dict = None) -> None:
        """读取配置并初始化插件运行参数。"""
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._cron = str(config.get("cron") or "0 9 * * *").strip()
        self._onlyonce = bool(config.get("onlyonce"))
        self._proxy = bool(config.get("proxy"))
        self._rsshub = str(config.get("rsshub") or "https://rsshub.app").rstrip("/")
        self._include_hot = bool(config.get("include_hot", True))
        self._notify_empty = bool(config.get("notify_empty", False))
        self._vote = self._to_float(config.get("vote"), 0.0, 0.0, 10.0)
        self._max_items = self._to_int(config.get("max_items"), 12, 1, 30)
        self._coming_days = self._to_int(config.get("coming_days"), 30, 1, 120)
        self._recent_days = self._to_int(config.get("recent_days"), 21, 0, 90)
        self._coming_count = self._to_int(config.get("coming_count"), 40, 10, 100)
        self._repeat_days = self._to_int(config.get("repeat_days"), 7, 0, 60)

    def get_state(self) -> bool:
        """返回插件是否处于启用状态。"""
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """注册查看新剧和按序号订阅的远程命令。"""
        return [
            {
                "cmd": "/newdrama",
                "event": EventType.PluginAction,
                "desc": "查看当前豆瓣新剧",
                "category": "每日新剧",
                "data": {"action": "daily_new_drama"},
            },
            {
                "cmd": "/newdrama_sub",
                "event": EventType.PluginAction,
                "desc": "按序号订阅新剧",
                "category": "每日新剧",
                "data": {"action": "daily_new_drama_sub"},
            },
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        """注册每日定时任务以及配置中的一次性立即刷新任务。"""
        services: List[Dict[str, Any]] = []
        if self._onlyonce:
            self._onlyonce = False
            self._save_config_state()
            services.append({
                "id": "DailyNewDramaOnce",
                "name": "立即刷新每日新剧",
                "trigger": "date",
                "func": self.refresh_and_notify,
                "kwargs": {},
            })
        if self._enabled:
            try:
                trigger = CronTrigger.from_crontab(self._cron)
            except Exception:
                logger.warning("【每日新剧助手】Cron 配置无效，回退到每天 09:00")
                trigger = CronTrigger.from_crontab("0 9 * * *")
            services.append({
                "id": "DailyNewDrama",
                "name": "每日新剧推荐",
                "trigger": trigger,
                "func": self.refresh_and_notify,
                "kwargs": {},
            })
        return services

    def get_api(self) -> List[Dict[str, Any]]:
        """返回手动刷新和序号订阅接口。"""
        return [
            {
                "path": "/refresh",
                "endpoint": self.api_refresh,
                "methods": ["POST"],
                "summary": "立即刷新当前新剧",
            },
            {
                "path": "/subscribe",
                "endpoint": self.api_subscribe,
                "methods": ["POST"],
                "summary": "按序号订阅当前新剧",
            },
        ]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """返回 Vuetify 配置表单和默认配置。"""
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [
                                {"component": "VSwitch", "props": {"model": "enabled", "label": "启用每日推送"}}
                            ]},
                            {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [
                                {"component": "VSwitch", "props": {"model": "onlyonce", "label": "立即运行一次"}}
                            ]},
                            {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [
                                {"component": "VSwitch", "props": {"model": "include_hot", "label": "补充近期热播"}}
                            ]},
                            {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [
                                {"component": "VSwitch", "props": {"model": "proxy", "label": "RSSHub 使用代理"}}
                            ]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                                {"component": "VCronField", "props": {"model": "cron", "label": "每日推送时间", "placeholder": "0 9 * * *"}}
                            ]},
                            {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                                {"component": "VTextField", "props": {"model": "max_items", "label": "最多推送数量", "placeholder": "12", "type": "number"}}
                            ]},
                            {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                                {"component": "VTextField", "props": {"model": "vote", "label": "最低评分", "placeholder": "0 表示不限", "type": "number"}}
                            ]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [
                                {"component": "VTextField", "props": {"model": "coming_days", "label": "未来新剧天数", "placeholder": "30", "type": "number"}}
                            ]},
                            {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [
                                {"component": "VTextField", "props": {"model": "recent_days", "label": "已开播补充天数", "placeholder": "21", "type": "number"}}
                            ]},
                            {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [
                                {"component": "VTextField", "props": {"model": "repeat_days", "label": "重复提醒间隔(天)", "placeholder": "7", "type": "number"}}
                            ]},
                            {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [
                                {"component": "VTextField", "props": {"model": "coming_count", "label": "豆瓣新剧抓取数量", "placeholder": "40", "type": "number"}}
                            ]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "md": 9}, "content": [
                                {"component": "VTextField", "props": {"model": "rsshub", "label": "RSSHub 地址", "placeholder": "https://rsshub.app"}}
                            ]},
                            {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [
                                {"component": "VSwitch", "props": {"model": "notify_empty", "label": "无新剧也通知"}}
                            ]},
                        ],
                    },
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "info",
                            "variant": "tonal",
                            "text": "主源使用豆瓣“即将播出剧集”，按播出日期筛选；可选补充近期已开播的豆瓣热门剧。媒体库已有和 MoviePilot 已订阅内容会自动过滤。通知支持按钮订阅；普通消息渠道可发送 /newdrama_sub 1,3 或 /newdrama_sub 1-3。",
                        },
                    },
                ],
            }
        ], {
            "enabled": False,
            "cron": "0 9 * * *",
            "onlyonce": False,
            "proxy": False,
            "rsshub": "https://rsshub.app",
            "vote": 0,
            "max_items": 12,
            "coming_days": 30,
            "recent_days": 21,
            "coming_count": 40,
            "include_hot": True,
            "repeat_days": 7,
            "notify_empty": False,
        }

    def get_page(self) -> Optional[List[dict]]:
        """返回最近一次刷新状态和当前候选剧集。"""
        data = self.get_data("daily_candidates") or {}
        status = self.get_data("last_run") or {}
        items = data.get("items") or []
        contents: List[dict] = []

        if status:
            source_text = " / ".join(
                f"{name}:{'OK' if info.get('ok') else '失败'}({info.get('count', 0)})"
                for name, info in (status.get("sources") or {}).items()
                if isinstance(info, dict)
            )
            contents.append({
                "component": "VAlert",
                "props": {
                    "type": "success" if status.get("success") else "warning",
                    "variant": "tonal",
                    "text": f"最近刷新：{status.get('time', '-')} · 候选 {status.get('candidate_count', 0)} 部 · {source_text or '无数据源状态'}",
                },
            })

        if not items:
            contents.append({
                "component": "VAlert",
                "props": {"type": "info", "variant": "tonal", "text": "暂无候选新剧。可开启“立即运行一次”保存配置后刷新。"},
            })
            return contents

        cards = []
        for item in items:
            air = item.get("air_date") or "日期待定"
            source = item.get("source_label") or "豆瓣"
            vote = item.get("vote") or "-"
            cards.append({
                "component": "VCard",
                "props": {"variant": "tonal"},
                "content": [
                    {"component": "VCardTitle", "text": f"{item.get('index')}. {item.get('title')} ({item.get('year') or '-'})"},
                    {"component": "VCardText", "text": f"{source} · {air} · 评分 {vote} · TMDB {item.get('tmdbid') or '-'}"},
                ],
            })
        contents.append({"component": "div", "props": {"class": "grid gap-3 grid-info-card mt-3"}, "content": cards})
        return contents

    def stop_service(self) -> None:
        """插件没有自建线程或调度器，无需额外释放资源。"""
        return None

    def api_refresh(self) -> Dict[str, Any]:
        """手动刷新候选列表，不主动发送通知。"""
        items = self.refresh_and_notify(send_message=False, suppress_recent=False)
        status = self.get_data("last_run") or {}
        return {"success": bool(status.get("success")), "count": len(items), "items": items, "status": status}

    def api_subscribe(self, payload: dict) -> Dict[str, Any]:
        """按请求中的 indexes 字段订阅当前候选序号。"""
        payload = payload or {}
        indexes = self._parse_indexes(str(payload.get("indexes") or ""))
        batch_id = str(payload.get("batch_id") or "")
        return self._subscribe_indexes(indexes=indexes, batch_id=batch_id)

    @eventmanager.register(EventType.PluginAction)
    def command_action(self, event: Event) -> None:
        """处理 /newdrama 与 /newdrama_sub 远程命令。"""
        event_data = event.event_data or {}
        action = event_data.get("action")
        channel = event_data.get("channel")
        user = event_data.get("user")
        arg_str = str(event_data.get("arg_str") or "").strip()

        if action == "daily_new_drama":
            items = self.refresh_and_notify(send_message=False, suppress_recent=False)
            batch_id = str((self.get_data("daily_candidates") or {}).get("batch_id") or "")
            self._send_candidates(items, channel=channel, userid=user, batch_id=batch_id)
            return

        if action == "daily_new_drama_sub":
            result = self._subscribe_indexes(self._parse_indexes(arg_str))
            self.post_message(
                channel=channel,
                userid=user,
                title="🎬 每日新剧订阅结果",
                text=result.get("message") or "未执行订阅",
            )

    @eventmanager.register(EventType.MessageAction)
    def message_action(self, event: Event) -> None:
        """处理支持消息按钮渠道发回的剧集订阅回调。"""
        event_data = event.event_data or {}
        if event_data.get("plugin_id") != self.__class__.__name__:
            return
        text = str(event_data.get("text") or "")
        if not text.startswith("sub|"):
            return
        parts = text.split("|")
        try:
            batch_id = parts[1]
            index = int(parts[2])
        except (TypeError, ValueError, IndexError):
            self.post_message(
                channel=event_data.get("channel"),
                userid=event_data.get("userid"),
                title="🎬 每日新剧订阅结果",
                text="回调参数无效，请发送 /newdrama 获取最新列表。",
            )
            return
        result = self._subscribe_indexes([index], batch_id=batch_id)
        self.post_message(
            channel=event_data.get("channel"),
            userid=event_data.get("userid"),
            title="🎬 每日新剧订阅结果",
            text=result.get("message") or "未执行订阅",
            original_message_id=event_data.get("original_message_id"),
            original_chat_id=event_data.get("original_chat_id"),
        )

    def refresh_and_notify(self, send_message: bool = True, suppress_recent: bool = True) -> List[Dict[str, Any]]:
        """抓取、识别、过滤新剧，保存批次并按需发送通知。"""
        logger.info("【每日新剧助手】开始刷新豆瓣新剧")
        now = datetime.datetime.now()
        today = now.date()
        raw_items, source_status = self._fetch_sources()
        last_status: Dict[str, Any] = {
            "time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "success": any(v.get("ok") for v in source_status.values()),
            "sources": source_status,
            "raw_count": len(raw_items),
            "candidate_count": 0,
            "processing_errors": 0,
        }

        if not last_status["success"]:
            last_status["error"] = "全部豆瓣数据源获取失败，保留上次候选列表。"
            self.save_data("last_run", last_status)
            logger.error("【每日新剧助手】全部数据源获取失败，本次不覆盖候选缓存")
            if send_message:
                self.post_message(title="📺 每日新剧助手获取失败", text="豆瓣/RSSHub 数据源暂时不可用，本次未覆盖上次候选列表，请稍后重试。")
            return list((self.get_data("daily_candidates") or {}).get("items") or [])

        batch_id = now.strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:8]
        candidates: List[Dict[str, Any]] = []
        seen_tmdb = set()
        notified = self._load_notified_history()

        for raw in raw_items:
            try:
                title = str(raw.get("title") or "").strip()
                doubanid = str(raw.get("doubanid") or "").strip()
                if not title:
                    continue
                meta = MetaInfo(title)
                meta.type = MediaType.TV
                raw_year = raw.get("year")
                if raw_year:
                    meta.year = str(raw_year)

                mediainfo = self._recognize(meta, doubanid)
                if not mediainfo or mediainfo.type != MediaType.TV or not mediainfo.tmdb_id:
                    continue

                air_date = self._resolve_air_date(raw, mediainfo)
                if not self._eligible_by_date(raw.get("source"), air_date, today):
                    continue
                if mediainfo.tmdb_id in seen_tmdb:
                    continue
                seen_tmdb.add(mediainfo.tmdb_id)

                vote = float(mediainfo.vote_average or 0)
                if self._vote and vote < self._vote:
                    continue

                exist_flag, _ = DownloadChain().get_no_exists_info(meta=meta, mediainfo=mediainfo)
                if exist_flag:
                    logger.info("【每日新剧助手】过滤媒体库已存在: %s", mediainfo.title_year)
                    continue

                subscribe_chain = SubscribeChain()
                if subscribe_chain.exists(mediainfo=mediainfo, meta=meta):
                    logger.info("【每日新剧助手】过滤已订阅: %s", mediainfo.title_year)
                    continue

                if suppress_recent and self._recently_notified(mediainfo.tmdb_id, notified, today):
                    logger.debug("【每日新剧助手】过滤近期已提醒: %s", mediainfo.title_year)
                    continue

                candidates.append({
                    "index": 0,
                    "title": mediainfo.title,
                    "year": mediainfo.year,
                    "vote": round(vote, 1) if vote else 0,
                    "tmdbid": mediainfo.tmdb_id,
                    "doubanid": doubanid or mediainfo.douban_id,
                    "poster": mediainfo.get_poster_image(),
                    "overview": mediainfo.overview or "",
                    "air_date": air_date.isoformat() if air_date else "",
                    "source": raw.get("source"),
                    "source_label": "豆瓣即将播出" if raw.get("source") == "coming" else "豆瓣近期热播",
                })
            except Exception as err:
                last_status["processing_errors"] += 1
                logger.warning("【每日新剧助手】处理候选条目失败 %s: %s", raw.get("title"), err)
                continue

        candidates.sort(key=self._candidate_sort_key)
        candidates = candidates[: self._max_items]
        for index, item in enumerate(candidates, start=1):
            item["index"] = index

        payload = {
            "batch_id": batch_id,
            "date": today.isoformat(),
            "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "items": candidates,
        }
        self.save_data("daily_candidates", payload)
        self._save_candidate_batch(payload)
        last_status["candidate_count"] = len(candidates)
        self.save_data("last_run", last_status)
        logger.info("【每日新剧助手】刷新完成，当前可推荐 %s 部", len(candidates))

        if send_message and (candidates or self._notify_empty):
            self._send_candidates(candidates, batch_id=batch_id)
            if candidates:
                for item in candidates:
                    notified[str(item.get("tmdbid"))] = today.isoformat()
                self.save_data("notified_history", notified)
        return candidates

    def _fetch_sources(self) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
        """分别获取即将播出主源和近期热门补充源，并隔离单源故障。"""
        items: List[Dict[str, Any]] = []
        status: Dict[str, Dict[str, Any]] = {}

        coming_url = f"{self._rsshub}/douban/tv/coming/time/{self._coming_count}"
        coming, error = self._fetch_rss(coming_url, source="coming")
        status["即将播出"] = {"ok": error is None, "count": len(coming), "error": error or ""}
        items.extend(coming)

        if self._include_hot:
            hot_url = f"{self._rsshub}/douban/movie/weekly/tv_hot"
            hot, error = self._fetch_rss(hot_url, source="hot")
            status["近期热播"] = {"ok": error is None, "count": len(hot), "error": error or ""}
            items.extend(hot)
        return items, status

    def _fetch_rss(self, url: str, source: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """请求并解析一个 RSSHub 豆瓣 RSS 地址。"""
        try:
            response = RequestUtils(proxies=settings.PROXY).get_res(url) if self._proxy else RequestUtils().get_res(url)
            if not response:
                return [], "无响应"
            if getattr(response, "status_code", 200) >= 400:
                return [], f"HTTP {response.status_code}"
            return _parse_douban_rss(response.text, source=source), None
        except Exception as err:
            logger.error("【每日新剧助手】获取 RSS 失败 %s: %s", url, err)
            return [], str(err)

    def _recognize(self, meta: MetaInfo, doubanid: str) -> Optional[MediaInfo]:
        """通过豆瓣 ID 优先识别 MoviePilot 媒体信息。"""
        try:
            if doubanid:
                if settings.RECOGNIZE_SOURCE == "themoviedb":
                    tmdbinfo = MediaChain().get_tmdbinfo_by_doubanid(doubanid=doubanid, mtype=MediaType.TV)
                    if tmdbinfo and tmdbinfo.get("id"):
                        mediainfo = self.chain.recognize_media(meta=meta, tmdbid=tmdbinfo.get("id"))
                        if mediainfo:
                            return mediainfo
                else:
                    mediainfo = self.chain.recognize_media(meta=meta, doubanid=doubanid)
                    if mediainfo:
                        return mediainfo
            return self.chain.recognize_media(meta=meta)
        except Exception as err:
            logger.warning("【每日新剧助手】识别失败 %s: %s", getattr(meta, "name", ""), err)
            return None

    def _resolve_air_date(self, raw: Dict[str, Any], mediainfo: MediaInfo) -> Optional[datetime.date]:
        """按可信 RSS 日期、TMDB 首播日期和发行日期顺序解析首播日期。"""
        values = []
        if raw.get("source") == "coming":
            values.append(raw.get("air_date"))
        values.extend([mediainfo.first_air_date, mediainfo.release_date])
        for value in values:
            parsed = _parse_date_value(value)
            if parsed:
                return parsed
        return None

    def _eligible_by_date(self, source: str, air_date: Optional[datetime.date], today: datetime.date) -> bool:
        """判断主源未来剧和热播补充剧是否处于配置的时间窗口。"""
        if source == "coming":
            if not air_date:
                return True
            days = (air_date - today).days
            return -1 <= days <= self._coming_days
        if source == "hot":
            if not air_date:
                return False
            days = (today - air_date).days
            return 0 <= days <= self._recent_days
        return False

    def _candidate_sort_key(self, item: Dict[str, Any]) -> Tuple[int, int, float]:
        """即将播出按日期升序；近期热播按首播日期倒序，再按评分排序。"""
        air_date = _parse_date_value(item.get("air_date"))
        vote = float(item.get("vote") or 0)
        ordinal = air_date.toordinal() if air_date else datetime.date.max.toordinal()
        if item.get("source") == "coming":
            return 0, ordinal, -vote
        return 1, -ordinal, -vote

    def _send_candidates(self, items: List[Dict[str, Any]], channel=None, userid=None, batch_id: str = "") -> None:
        """发送候选列表，支持按钮回调并保留普通命令方式。"""
        if not items:
            self.post_message(channel=channel, userid=userid, title="📺 今日豆瓣新剧", text="今天没有发现新的、且尚未入库或订阅的剧集。")
            return
        if not batch_id:
            batch_id = str((self.get_data("daily_candidates") or {}).get("batch_id") or "")

        today = datetime.date.today()
        lines = ["已过滤媒体库已有、现有订阅和近期重复提醒：", ""]
        buttons: List[List[dict]] = []
        row: List[dict] = []
        for item in items:
            air_date = _parse_date_value(item.get("air_date"))
            timing = _format_air_timing_value(air_date, today)
            vote_text = f"⭐ {item.get('vote')}" if item.get("vote") else "暂无评分"
            source_text = "待播" if item.get("source") == "coming" else "新近开播"
            lines.append(f"{item['index']}. {item['title']} ({item.get('year') or '-'}) · {source_text} · {timing} · {vote_text}")
            row.append({
                "text": f"{item['index']}. {str(item['title'])[:10]}",
                "callback_data": f"[PLUGIN]{self.__class__.__name__}|sub|{batch_id}|{item['index']}",
            })
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        lines.extend(["", "普通消息渠道可发送：", "`/newdrama_sub 1,3` 或 `/newdrama_sub 1-3`"]) 
        self.post_message(
            channel=channel,
            userid=userid,
            title=f"📺 今日豆瓣新剧 · {len(items)} 部可选",
            text="\n".join(lines),
            image=items[0].get("poster") or None,
            buttons=buttons,
        )

    def _subscribe_indexes(self, indexes: List[int], batch_id: str = "") -> Dict[str, Any]:
        """对指定候选批次中的序号执行订阅，并在订阅前再次去重。"""
        if not indexes:
            return {"success": False, "message": "未识别到有效序号，例如：/newdrama_sub 1,3 或 /newdrama_sub 1-3"}
        data = self._get_candidate_batch(batch_id)
        if not data:
            return {"success": False, "message": "推荐批次不存在或已过期，请发送 /newdrama 获取最新列表。"}
        items = data.get("items") or []
        mapping = {int(item.get("index")): item for item in items if item.get("index")}
        success: List[str] = []
        skipped: List[str] = []
        failed: List[str] = []

        for index in indexes:
            item = mapping.get(index)
            if not item:
                failed.append(f"{index}(不存在)")
                continue
            try:
                meta = MetaInfo(item.get("title") or "")
                meta.type = MediaType.TV
                if item.get("year"):
                    meta.year = str(item.get("year"))
                mediainfo = self.chain.recognize_media(meta=meta, tmdbid=item.get("tmdbid"))
                if not mediainfo:
                    failed.append(f"{index}.{item.get('title')}(识别失败)")
                    continue
                exist_flag, _ = DownloadChain().get_no_exists_info(meta=meta, mediainfo=mediainfo)
                if exist_flag:
                    skipped.append(f"{index}.{item.get('title')}(已入库)")
                    continue
                subscribe_chain = SubscribeChain()
                if subscribe_chain.exists(mediainfo=mediainfo, meta=meta):
                    skipped.append(f"{index}.{item.get('title')}(已订阅)")
                    continue
                sid, err_msg = subscribe_chain.add(
                    title=mediainfo.title,
                    year=mediainfo.year,
                    mtype=MediaType.TV,
                    tmdbid=mediainfo.tmdb_id,
                    doubanid=item.get("doubanid") or mediainfo.douban_id,
                    season=meta.begin_season,
                    message=False,
                    exist_ok=True,
                    username="每日新剧助手",
                )
                if sid:
                    success.append(f"{index}.{mediainfo.title_year}")
                else:
                    failed.append(f"{index}.{item.get('title')}({err_msg or '添加失败'})")
            except Exception as err:
                logger.error("【每日新剧助手】订阅 %s 失败: %s", item.get("title"), err)
                failed.append(f"{index}.{item.get('title')}(失败)")

        parts = []
        if success:
            parts.append("✅ 已订阅：\n" + "\n".join(success))
        if skipped:
            parts.append("⏭ 已跳过：\n" + "\n".join(skipped))
        if failed:
            parts.append("❌ 未完成：\n" + "\n".join(failed))
        return {"success": bool(success), "message": "\n\n".join(parts) or "没有可处理的条目"}

    def _get_candidate_batch(self, batch_id: str = "") -> Dict[str, Any]:
        """取得指定候选批次；未传批次时使用当前最新批次。"""
        current = self.get_data("daily_candidates") or {}
        if not batch_id or str(current.get("batch_id") or "") == str(batch_id):
            return current
        batches = self.get_data("candidate_batches") or []
        for batch in reversed(batches):
            if isinstance(batch, dict) and str(batch.get("batch_id") or "") == str(batch_id):
                return batch
        return {}

    def _save_candidate_batch(self, payload: Dict[str, Any]) -> None:
        """保存最近候选批次，限制数量和最长保存时间。"""
        cutoff = datetime.date.today() - datetime.timedelta(days=14)
        batches = self.get_data("candidate_batches") or []
        kept = []
        for batch in batches:
            if not isinstance(batch, dict):
                continue
            batch_date = _parse_date_value(batch.get("date"))
            if batch_date and batch_date >= cutoff and batch.get("batch_id") != payload.get("batch_id"):
                kept.append(batch)
        kept.append(payload)
        self.save_data("candidate_batches", kept[-30:])

    def _load_notified_history(self) -> Dict[str, str]:
        """读取并清理已通知条目的日期记录。"""
        history = self.get_data("notified_history") or {}
        if not isinstance(history, dict):
            history = {}
        cutoff = datetime.date.today() - datetime.timedelta(days=max(self._repeat_days, 1) + 30)
        cleaned = {}
        for tmdbid, date_text in history.items():
            notify_date = _parse_date_value(date_text)
            if notify_date and notify_date >= cutoff:
                cleaned[str(tmdbid)] = notify_date.isoformat()
        if cleaned != history:
            self.save_data("notified_history", cleaned)
        return cleaned

    def _recently_notified(self, tmdbid: int, history: Dict[str, str], today: datetime.date) -> bool:
        """判断指定 TMDB 条目是否仍处于重复提醒抑制周期。"""
        if self._repeat_days <= 0:
            return False
        notify_date = _parse_date_value(history.get(str(tmdbid)))
        return bool(notify_date and (today - notify_date).days < self._repeat_days)

    def _save_config_state(self) -> None:
        """持久化当前配置并自动复位一次性执行开关。"""
        self.update_config({
            "enabled": self._enabled,
            "cron": self._cron,
            "onlyonce": False,
            "proxy": self._proxy,
            "rsshub": self._rsshub,
            "vote": self._vote,
            "max_items": self._max_items,
            "coming_days": self._coming_days,
            "recent_days": self._recent_days,
            "coming_count": self._coming_count,
            "include_hot": self._include_hot,
            "repeat_days": self._repeat_days,
            "notify_empty": self._notify_empty,
        })

    @staticmethod
    def _parse_indexes(text: str) -> List[int]:
        """代理纯函数序号解析，便于插件内部统一调用。"""
        return _parse_indexes_value(text)

    @staticmethod
    def _to_int(value: Any, default: int, minimum: int, maximum: int) -> int:
        """安全读取有上下限的整数配置。"""
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(parsed, maximum))

    @staticmethod
    def _to_float(value: Any, default: float, minimum: float, maximum: float) -> float:
        """安全读取有上下限的浮点配置。"""
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(parsed, maximum))
