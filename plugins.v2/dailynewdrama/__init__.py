import datetime
import re
import xml.dom.minidom
from typing import Any, Dict, List, Tuple

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
from app.utils.dom import DomUtils
from app.utils.http import RequestUtils


class DailyNewDrama(_PluginBase):
    plugin_name = "每日新剧助手"
    plugin_desc = "每天推送豆瓣近期新剧，自动过滤已订阅和媒体库已有内容，并支持按序号订阅。"
    plugin_icon = "movie.jpg"
    plugin_version = "1.0"
    plugin_author = "liheng-lk"
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
    _year_span = 1
    _notify_empty = True

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return [
            {
                "cmd": "/newdrama",
                "event": EventType.PluginAction,
                "desc": "查看今日豆瓣新剧",
                "category": "每日新剧",
                "data": {"action": "daily_new_drama"},
            },
            {
                "cmd": "/newdrama_sub",
                "event": EventType.PluginAction,
                "desc": "按序号订阅今日新剧",
                "category": "每日新剧",
                "data": {"action": "daily_new_drama_sub"},
            },
        ]

    def init_plugin(self, config: dict = None):
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._cron = str(config.get("cron") or "0 9 * * *").strip()
        self._onlyonce = bool(config.get("onlyonce"))
        self._proxy = bool(config.get("proxy"))
        self._rsshub = str(config.get("rsshub") or "https://rsshub.app").rstrip("/")
        try:
            self._vote = float(config.get("vote") or 0)
        except (TypeError, ValueError):
            self._vote = 0.0
        try:
            self._max_items = max(1, min(int(config.get("max_items") or 12), 30))
        except (TypeError, ValueError):
            self._max_items = 12
        try:
            self._year_span = max(0, min(int(config.get("year_span") or 1), 5))
        except (TypeError, ValueError):
            self._year_span = 1
        self._notify_empty = bool(config.get("notify_empty", True))

        # onlyonce 由 get_service() 注册一次性任务，避免保存配置时同步阻塞。

    def get_state(self) -> bool:
        return self._enabled

    def get_service(self) -> List[Dict[str, Any]]:
        services = []
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
        return [
            {
                "path": "/refresh",
                "endpoint": self.api_refresh,
                "methods": ["POST"],
                "summary": "立即刷新今日新剧",
            },
            {
                "path": "/subscribe",
                "endpoint": self.api_subscribe,
                "methods": ["POST"],
                "summary": "按序号订阅今日新剧",
            },
        ]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                                {"component": "VSwitch", "props": {"model": "enabled", "label": "启用每日推送"}}
                            ]},
                            {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                                {"component": "VSwitch", "props": {"model": "onlyonce", "label": "立即运行一次"}}
                            ]},
                            {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
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
                                {"component": "VTextField", "props": {"model": "vote", "label": "最低评分", "placeholder": "0 表示不限"}}
                            ]},
                            {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                                {"component": "VTextField", "props": {"model": "max_items", "label": "最多推送数量", "placeholder": "12"}}
                            ]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                                {"component": "VTextField", "props": {"model": "rsshub", "label": "RSSHub 地址", "placeholder": "https://rsshub.app"}}
                            ]},
                            {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [
                                {"component": "VTextField", "props": {"model": "year_span", "label": "允许年份跨度", "placeholder": "1"}}
                            ]},
                            {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [
                                {"component": "VSwitch", "props": {"model": "notify_empty", "label": "无新剧也通知"}}
                            ]},
                        ],
                    },
                    {
                        "component": "VAlert",
                        "props": {"type": "info", "variant": "tonal", "text": "每天读取豆瓣热门电视剧榜，只保留近年剧集；媒体库已存在或 MoviePilot 已订阅的内容会自动过滤。可用 /newdrama_sub 1,3 或 /newdrama_sub 1-3 订阅。"},
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
            "year_span": 1,
            "notify_empty": True,
        }

    def get_page(self) -> List[dict]:
        data = self.get_data("daily_candidates") or {}
        items = data.get("items") or []
        if not items:
            return [{"component": "VAlert", "props": {"type": "info", "text": "暂无今日候选新剧，运行一次刷新后会在这里显示。"}}]
        cards = []
        for item in items:
            cards.append({
                "component": "VCard",
                "props": {"variant": "tonal"},
                "content": [
                    {"component": "VCardTitle", "text": f"{item.get('index')}. {item.get('title')} ({item.get('year') or '-'})"},
                    {"component": "VCardText", "text": f"豆瓣/媒体评分：{item.get('vote') or '-'}  ·  TMDB: {item.get('tmdbid') or '-'}"},
                ],
            })
        return [
            {"component": "VAlert", "props": {"type": "success", "variant": "tonal", "text": f"候选日期：{data.get('date', '-')}，共 {len(items)} 部。"}},
            {"component": "div", "props": {"class": "grid gap-3 grid-info-card mt-3"}, "content": cards},
        ]

    def stop_service(self):
        pass

    def _save_config_state(self):
        self.update_config({
            "enabled": self._enabled,
            "cron": self._cron,
            "onlyonce": False,
            "proxy": self._proxy,
            "rsshub": self._rsshub,
            "vote": self._vote,
            "max_items": self._max_items,
            "year_span": self._year_span,
            "notify_empty": self._notify_empty,
        })

    def api_refresh(self) -> Dict[str, Any]:
        items = self.refresh_and_notify(send_message=False)
        return {"success": True, "count": len(items), "items": items}

    def api_subscribe(self, payload: dict) -> Dict[str, Any]:
        indexes = self._parse_indexes(str((payload or {}).get("indexes") or ""))
        return self._subscribe_indexes(indexes)

    @eventmanager.register(EventType.PluginAction)
    def command_action(self, event: Event):
        event_data = event.event_data or {}
        action = event_data.get("action")
        channel = event_data.get("channel")
        user = event_data.get("user")
        arg_str = str(event_data.get("arg_str") or "").strip()

        if action == "daily_new_drama":
            items = self.refresh_and_notify(send_message=False)
            self._send_candidates(items, channel=channel, userid=user)
            return

        if action == "daily_new_drama_sub":
            indexes = self._parse_indexes(arg_str)
            result = self._subscribe_indexes(indexes)
            self.post_message(
                channel=channel,
                userid=user,
                title="🎬 每日新剧订阅结果",
                text=result.get("message") or "未执行订阅",
            )

    @eventmanager.register(EventType.MessageAction)
    def message_action(self, event: Event):
        event_data = event.event_data or {}
        if event_data.get("plugin_id") != self.__class__.__name__:
            return
        text = str(event_data.get("text") or "")
        if not text.startswith("sub|"):
            return
        try:
            index = int(text.split("|", 1)[1])
        except (TypeError, ValueError):
            return
        result = self._subscribe_indexes([index])
        self.post_message(
            channel=event_data.get("channel"),
            userid=event_data.get("userid"),
            title="🎬 每日新剧订阅结果",
            text=result.get("message") or "未执行订阅",
            original_message_id=event_data.get("original_message_id"),
            original_chat_id=event_data.get("original_chat_id"),
        )

    def refresh_and_notify(self, send_message: bool = True) -> List[Dict[str, Any]]:
        logger.info("【每日新剧助手】开始刷新豆瓣新剧")
        raw_items = self._fetch_douban_tv()
        candidates: List[Dict[str, Any]] = []
        seen_tmdb = set()
        current_year = datetime.datetime.now().year

        for raw in raw_items:
            if len(candidates) >= self._max_items:
                break
            title = str(raw.get("title") or "").strip()
            doubanid = str(raw.get("doubanid") or "").strip()
            year = raw.get("year")
            if not title:
                continue
            if year:
                try:
                    if int(year) < current_year - self._year_span:
                        continue
                except (TypeError, ValueError):
                    pass

            meta = MetaInfo(title)
            meta.type = MediaType.TV
            if year:
                try:
                    meta.year = int(year)
                except (TypeError, ValueError):
                    pass

            mediainfo = self._recognize(meta, doubanid)
            if not mediainfo or mediainfo.type != MediaType.TV:
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

            candidates.append({
                "index": len(candidates) + 1,
                "title": mediainfo.title,
                "year": mediainfo.year,
                "vote": round(vote, 1) if vote else 0,
                "tmdbid": mediainfo.tmdb_id,
                "doubanid": doubanid,
                "poster": mediainfo.get_poster_image(),
                "overview": mediainfo.overview or "",
            })

        payload = {
            "date": datetime.datetime.now().strftime("%Y-%m-%d"),
            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "items": candidates,
        }
        self.save_data("daily_candidates", payload)
        logger.info("【每日新剧助手】刷新完成，未拥有且未订阅的新剧 %s 部", len(candidates))

        if send_message:
            if candidates or self._notify_empty:
                self._send_candidates(candidates)
        return candidates

    def _recognize(self, meta: MetaInfo, doubanid: str) -> MediaInfo | None:
        try:
            if doubanid:
                if settings.RECOGNIZE_SOURCE == "themoviedb":
                    tmdbinfo = MediaChain().get_tmdbinfo_by_doubanid(doubanid=doubanid, mtype=MediaType.TV)
                    if not tmdbinfo:
                        return None
                    return self.chain.recognize_media(meta=meta, tmdbid=tmdbinfo.get("id"))
                return self.chain.recognize_media(meta=meta, doubanid=doubanid)
            return self.chain.recognize_media(meta=meta)
        except Exception as err:
            logger.warning("【每日新剧助手】识别失败 %s: %s", meta.name, err)
            return None

    def _fetch_douban_tv(self) -> List[Dict[str, Any]]:
        url = f"{self._rsshub}/douban/movie/weekly/tv_hot"
        try:
            response = RequestUtils(proxies=settings.PROXY).get_res(url) if self._proxy else RequestUtils().get_res(url)
            if not response:
                logger.error("【每日新剧助手】RSSHub 无响应: %s", url)
                return []
            dom_tree = xml.dom.minidom.parseString(response.text)
            items = dom_tree.documentElement.getElementsByTagName("item")
            result = []
            for node in items:
                title = DomUtils.tag_value(node, "title", default="")
                link = DomUtils.tag_value(node, "link", default="")
                description = DomUtils.tag_value(node, "description", default="")
                ids = re.findall(r"/(\d+)(?=/|$)", link or "")
                years = re.findall(r"\b(19\d{2}|20\d{2})\b", description or "")
                result.append({
                    "title": title,
                    "doubanid": ids[0] if ids else "",
                    "year": int(years[0]) if years else None,
                    "link": link,
                })
            return result
        except Exception as err:
            logger.error("【每日新剧助手】获取豆瓣新剧失败: %s", err)
            return []

    def _send_candidates(self, items: List[Dict[str, Any]], channel=None, userid=None):
        if not items:
            self.post_message(channel=channel, userid=userid, title="📺 今日豆瓣新剧", text="今天没有发现你尚未拥有、尚未订阅的新剧。")
            return

        lines = ["已自动过滤媒体库已有内容和现有订阅：", ""]
        buttons = []
        row = []
        for item in items:
            vote_text = f"⭐ {item.get('vote')}" if item.get("vote") else "暂无评分"
            lines.append(f"{item['index']}. {item['title']} ({item.get('year') or '-'}) · {vote_text}")
            row.append({
                "text": f"{item['index']}. {item['title'][:10]}",
                "callback_data": f"[PLUGIN]{self.__class__.__name__}|sub|{item['index']}",
            })
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        lines.extend(["", "回复命令订阅：", "`/newdrama_sub 1,3` 或 `/newdrama_sub 1-3`"]) 
        self.post_message(
            channel=channel,
            userid=userid,
            title=f"📺 今日豆瓣新剧 · {len(items)} 部可选",
            text="\n".join(lines),
            buttons=buttons,
        )

    @staticmethod
    def _parse_indexes(text: str) -> List[int]:
        indexes = set()
        for token in re.split(r"[,，\s]+", str(text or "").strip()):
            if not token:
                continue
            match = re.fullmatch(r"(\d+)\s*[-~—]\s*(\d+)", token)
            if match:
                start, end = int(match.group(1)), int(match.group(2))
                if start > end:
                    start, end = end, start
                indexes.update(range(start, end + 1))
            elif token.isdigit():
                indexes.add(int(token))
        return sorted(i for i in indexes if i > 0)

    def _subscribe_indexes(self, indexes: List[int]) -> Dict[str, Any]:
        if not indexes:
            return {"success": False, "message": "未识别到有效序号，例如：/newdrama_sub 1,3 或 /newdrama_sub 1-3"}

        data = self.get_data("daily_candidates") or {}
        items = data.get("items") or []
        mapping = {int(item.get("index")): item for item in items if item.get("index")}
        success = []
        skipped = []
        failed = []

        for index in indexes:
            item = mapping.get(index)
            if not item:
                failed.append(f"{index}(不存在)")
                continue
            meta = MetaInfo(item.get("title") or "")
            meta.type = MediaType.TV
            meta.year = item.get("year")
            try:
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
                subscribe_chain.add(
                    title=mediainfo.title,
                    year=mediainfo.year,
                    mtype=MediaType.TV,
                    tmdbid=mediainfo.tmdb_id,
                    season=meta.begin_season,
                    exist_ok=True,
                    username="每日新剧助手",
                )
                success.append(f"{index}.{mediainfo.title_year}")
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
