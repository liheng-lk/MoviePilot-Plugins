import base64
import datetime
import hashlib
import hmac
import re
import urllib.parse
import uuid
import xml.dom.minidom
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional, Tuple

from apscheduler.triggers.cron import CronTrigger

from app.chain.download import DownloadChain
from app.chain.media import MediaChain
from app.chain.subscribe import SubscribeChain
from app.sdk.config import settings
from app.sdk.media import MediaInfo, MetaInfo
from app.sdk.events import Event, eventmanager
from app.sdk.logging import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, MediaSource, MediaType
from app.sdk.network import RequestUtils

from .platform_sources import fetch_platform_sources


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
        year_text = f"{pubdate} {description}" if source == "coming" else description
        years = re.findall(r"\b(19\d{2}|20\d{2})\b", year_text)
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


def _parse_douban_direct_subjects(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """把豆瓣 Frodo 即将播出 JSON 转成统一候选字典。"""
    result: List[Dict[str, Any]] = []
    subjects = data.get("subjects") if isinstance(data, dict) else None
    if not isinstance(subjects, list):
        return result
    for subject in subjects:
        if not isinstance(subject, dict):
            continue
        title = str(subject.get("title") or "").strip()
        doubanid = str(subject.get("id") or "").strip()
        pubdates = subject.get("pubdate") or []
        pubdate_text = str(pubdates[0] if isinstance(pubdates, list) and pubdates else "").strip()
        date_match = re.search(r"(19\d{2}|20\d{2})-(\d{1,2})-(\d{1,2})", pubdate_text)
        air_date = ""
        year = None
        if date_match:
            year = int(date_match.group(1))
            try:
                air_date = datetime.date(year, int(date_match.group(2)), int(date_match.group(3))).isoformat()
            except ValueError:
                air_date = ""
        if not year:
            year_match = re.search(r"\b(19\d{2}|20\d{2})\b", pubdate_text)
            year = int(year_match.group(1)) if year_match else None
        result.append({
            "title": title,
            "doubanid": doubanid,
            "year": year,
            "link": str(subject.get("url") or subject.get("sharing_url") or (f"https://movie.douban.com/subject/{doubanid}/" if doubanid else "")),
            "description": str(subject.get("intro") or subject.get("card_subtitle") or ""),
            "air_date": air_date,
            "rss_pub_date": "",
            "source": "coming",
        })
    return result


def _extract_flaresolverr_response(data: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """从 FlareSolverr 返回 JSON 中提取页面正文和错误信息。"""
    if not isinstance(data, dict):
        return None, "FlareSolverr 返回非 JSON 对象"
    if str(data.get("status") or "").lower() != "ok":
        return None, str(data.get("message") or "FlareSolverr 请求失败")
    solution = data.get("solution") or {}
    if not isinstance(solution, dict):
        return None, "FlareSolverr solution 无效"
    response = solution.get("response")
    if not isinstance(response, str) or not response.strip():
        return None, "FlareSolverr 未返回页面内容"
    return response, None


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
    plugin_desc = "聚合豆瓣及腾讯视频、爱奇艺、优酷、芒果TV、哔哩哔哩的新剧与在播剧，仅过滤已入库/已订阅内容，页面不限候选数量并支持一键订阅。"
    plugin_icon = "movie.jpg"
    plugin_version = "3.0.0"
    plugin_author = "liheng-lk"
    plugin_label = "豆瓣,腾讯视频,爱奇艺,优酷,芒果TV,哔哩哔哩,电视剧,订阅,推荐,通知"
    author_url = "https://github.com/liheng-lk/MoviePilot-Plugins"
    plugin_config_prefix = "dailynewdrama_"
    plugin_order = 20
    auth_level = 1

    _enabled = False
    _cron = "0 9 * * *"
    _onlyonce = False
    _proxy = False
    _rsshub = "https://rsshub.app"
    _flaresolverr_enabled = False
    _flaresolverr_url = "http://flaresolverr:8191"
    _vote = 0.0
    _coming_days = 30
    _recent_days = 21
    _coming_count = 100
    _include_hot = True
    _repeat_days = 7
    _notify_empty = False
    _platform_tencent = True
    _platform_iqiyi = True
    _platform_youku = True
    _platform_mgtv = True
    _platform_bilibili = True

    def init_plugin(self, config: dict = None) -> None:
        """读取配置并初始化插件运行参数。"""
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._cron = str(config.get("cron") or "0 9 * * *").strip()
        self._onlyonce = bool(config.get("onlyonce"))
        self._proxy = bool(config.get("proxy"))
        self._rsshub = str(config.get("rsshub") or "https://rsshub.app").rstrip("/")
        self._flaresolverr_enabled = bool(config.get("flaresolverr_enabled", False))
        self._flaresolverr_url = str(config.get("flaresolverr_url") or "http://flaresolverr:8191").rstrip("/")
        self._include_hot = bool(config.get("include_hot", True))
        self._notify_empty = bool(config.get("notify_empty", False))
        self._platform_tencent = bool(config.get("platform_tencent", True))
        self._platform_iqiyi = bool(config.get("platform_iqiyi", True))
        self._platform_youku = bool(config.get("platform_youku", True))
        self._platform_mgtv = bool(config.get("platform_mgtv", True))
        self._platform_bilibili = bool(config.get("platform_bilibili", True))
        self._vote = self._to_float(config.get("vote"), 0.0, 0.0, 10.0)
        self._coming_days = self._to_int(config.get("coming_days"), 30, 1, 120)
        self._recent_days = self._to_int(config.get("recent_days"), 21, 0, 90)
        self._coming_count = self._to_int(config.get("coming_count"), 100, 10, 100)
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
                "methods": ["GET"],
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
                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                                {"component": "VCronField", "props": {"model": "cron", "label": "每日推送时间", "placeholder": "0 9 * * *"}}
                            ]},
                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
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
                                {"component": "VTextField", "props": {"model": "coming_count", "label": "豆瓣单次抓取数量（最多100）", "placeholder": "100", "type": "number"}}
                            ]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "md": 9}, "content": [
                                {"component": "VTextField", "props": {"model": "rsshub", "label": "RSSHub 地址（备用）", "placeholder": "https://rsshub.app"}}
                            ]},
                            {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [
                                {"component": "VSwitch", "props": {"model": "notify_empty", "label": "无新剧也通知"}}
                            ]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                                {"component": "VSwitch", "props": {"model": "flaresolverr_enabled", "label": "启用 FlareSolverr 过盾"}}
                            ]},
                            {"component": "VCol", "props": {"cols": 12, "md": 8}, "content": [
                                {"component": "VTextField", "props": {"model": "flaresolverr_url", "label": "FlareSolverr 地址", "placeholder": "http://flaresolverr:8191"}}
                            ]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 6, "md": 2}, "content": [{"component": "VSwitch", "props": {"model": "platform_tencent", "label": "腾讯视频"}}]},
                            {"component": "VCol", "props": {"cols": 6, "md": 2}, "content": [{"component": "VSwitch", "props": {"model": "platform_iqiyi", "label": "爱奇艺"}}]},
                            {"component": "VCol", "props": {"cols": 6, "md": 2}, "content": [{"component": "VSwitch", "props": {"model": "platform_youku", "label": "优酷"}}]},
                            {"component": "VCol", "props": {"cols": 6, "md": 2}, "content": [{"component": "VSwitch", "props": {"model": "platform_mgtv", "label": "芒果TV"}}]},
                            {"component": "VCol", "props": {"cols": 6, "md": 2}, "content": [{"component": "VSwitch", "props": {"model": "platform_bilibili", "label": "哔哩哔哩"}}]},
                        ],
                    },
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "info",
                            "variant": "tonal",
                            "text": "页面候选不限数量，仅过滤媒体库已有和 MoviePilot 已订阅内容；重复提醒间隔只影响消息推送，不会让候选从页面消失。每张剧集卡片可直接点击订阅。",
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
            "flaresolverr_enabled": False,
            "flaresolverr_url": "http://flaresolverr:8191",
            "vote": 0,
            "coming_days": 30,
            "recent_days": 21,
            "coming_count": 100,
            "include_hot": True,
            "repeat_days": 7,
            "notify_empty": False,
            "platform_tencent": True,
            "platform_iqiyi": True,
            "platform_youku": True,
            "platform_mgtv": True,
            "platform_bilibili": True,
        }

    def get_page(self) -> Optional[List[dict]]:
        """返回最近一次刷新状态和当前候选剧集。"""
        data = self.get_data("daily_candidates") or {}
        status = self.get_data("last_run") or {}
        items = data.get("items") or []
        batch_id = str(data.get("batch_id") or "")
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

        page_token = str(getattr(settings, "API_TOKEN", "") or "")
        page_token_hash = hashlib.sha256(page_token.encode("utf-8")).hexdigest()[:8] if page_token else "-"
        logger.info("【每日新剧助手】【页面鉴权诊断】构建GET订阅按钮: batch_id=%s, items=%s, apikey_present=%s, apikey_len=%s, apikey_sha256_8=%s", batch_id, len(items), bool(page_token), len(page_token), page_token_hash)

        cards = []
        for item in items:
            air = item.get("air_date") or "日期待定"
            source = item.get("source_label") or "豆瓣"
            vote = item.get("vote") or "-"
            remarks = [str(x).strip() for x in (item.get("platform_remarks") or []) if str(x).strip()]
            detail = f"{source} · {air} · 评分 {vote} · TMDB {item.get('tmdbid') or '-'}"
            if remarks:
                detail += " · " + " / ".join(remarks[:2])
            cards.append({
                "component": "VCard",
                "props": {"variant": "tonal", "class": "h-100"},
                "content": [
                    {"component": "VCardTitle", "text": f"{item.get('index')}. {item.get('title')} ({item.get('year') or '-'})"},
                    {"component": "VCardText", "text": detail},
                    {
                        "component": "VCardActions",
                        "content": [
                            {"component": "VSpacer"},
                            {
                                "component": "VBtn",
                                "props": {"color": "primary", "variant": "flat", "size": "small", "prepend-icon": "mdi-plus-circle"},
                                "text": "订阅",
                                "events": {
                                    "click": {
                                        "api": "plugin/DailyNewDrama/subscribe",
                                        "method": "get",
                                        "params": {"indexes": str(item.get("index") or ""), "batch_id": batch_id, "apikey": settings.API_TOKEN},
                                    }
                                },
                            },
                        ],
                    },
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

    def api_subscribe(self, indexes: str = "", batch_id: str = "", apikey: str = "") -> Dict[str, Any]:
        """订阅页面候选；参数与 MoviePilot get_page 事件 params 保持一致。"""
        received_token = str(apikey or "")
        expected_token = str(getattr(settings, "API_TOKEN", "") or "")
        received_hash = hashlib.sha256(received_token.encode("utf-8")).hexdigest()[:8] if received_token else "-"
        expected_hash = hashlib.sha256(expected_token.encode("utf-8")).hexdigest()[:8] if expected_token else "-"
        logger.info("【每日新剧助手】【订阅API诊断】收到请求: indexes=%s, batch_id=%s, apikey_present=%s, apikey_len=%s, apikey_sha256_8=%s, expected_present=%s, expected_len=%s, expected_sha256_8=%s, match=%s", indexes, batch_id, bool(received_token), len(received_token), received_hash, bool(expected_token), len(expected_token), expected_hash, received_token == expected_token)
        if received_token != expected_token:
            logger.warning("【每日新剧助手】【订阅API诊断】插件内部鉴权失败: received_len=%s expected_len=%s received_hash=%s expected_hash=%s", len(received_token), len(expected_token), received_hash, expected_hash)
            return {"success": False, "message": "API密钥错误", "handled_indexes": []}
        parsed_indexes = self._parse_indexes(str(indexes or ""))
        batch_id = str(batch_id or "")
        logger.info("【每日新剧助手】【订阅API诊断】鉴权通过，准备执行订阅: parsed_indexes=%s, batch_id=%s", parsed_indexes, batch_id)
        result = self._subscribe_indexes(indexes=parsed_indexes, batch_id=batch_id)
        logger.info("【每日新剧助手】【订阅API诊断】订阅链返回: success=%s, handled_indexes=%s, message=%s", result.get("success"), result.get("handled_indexes"), str(result.get("message") or "")[:300])
        handled = [int(i) for i in (result.get("handled_indexes") or []) if str(i).isdigit()]
        if handled:
            self._remove_current_candidates(handled, batch_id=batch_id)
        return result

    def _remove_current_candidates(self, indexes: List[int], batch_id: str = "") -> None:
        """从当前页面缓存移除已成功订阅或已确认入库/订阅的条目，历史批次保持不变。"""
        current = self.get_data("daily_candidates") or {}
        if batch_id and str(current.get("batch_id") or "") != str(batch_id):
            return
        remove_set = {int(i) for i in indexes}
        items = [item for item in (current.get("items") or []) if int(item.get("index") or 0) not in remove_set]
        if len(items) == len(current.get("items") or []):
            return
        current["items"] = items
        self.save_data("daily_candidates", current)
        status = self.get_data("last_run") or {}
        if status:
            status["candidate_count"] = len(items)
            self.save_data("last_run", status)

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
        logger.info("【每日新剧助手】开始刷新多平台新剧/在播剧")
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
            last_status["error"] = "全部新剧数据源获取失败，保留上次候选列表。"
            self.save_data("last_run", last_status)
            logger.error("【每日新剧助手】全部数据源获取失败，本次不覆盖候选缓存")
            if send_message:
                self.post_message(title="📺 每日新剧助手获取失败", text="豆瓣及视频平台数据源暂时不可用，本次未覆盖上次候选列表，请稍后重试。")
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
                    for existing in candidates:
                        if existing.get("tmdbid") == mediainfo.tmdb_id:
                            merged_platforms = list(dict.fromkeys((existing.get("platforms") or []) + (raw.get("platforms") or [])))
                            existing["platforms"] = merged_platforms
                            if merged_platforms:
                                state = "更新中" if raw.get("ongoing") or existing.get("ongoing") else "近期上线"
                                existing["source_label"] = " / ".join(merged_platforms) + f" · {state}"
                            existing["ongoing"] = bool(existing.get("ongoing") or raw.get("ongoing"))
                            remarks = list(existing.get("platform_remarks") or [])
                            new_remark = str(raw.get("platform_remark") or "").strip()
                            if new_remark and new_remark not in remarks:
                                remarks.append(new_remark)
                            existing["platform_remarks"] = remarks
                            break
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
                    "source_label": raw.get("source_label") or ("豆瓣即将播出" if raw.get("source") == "coming" else "豆瓣近期热播"),
                    "platforms": raw.get("platforms") or [],
                    "ongoing": bool(raw.get("ongoing")),
                    "platform_remark": raw.get("platform_remark") or "",
                    "platform_remarks": [raw.get("platform_remark")] if raw.get("platform_remark") else [],
                })
            except Exception as err:
                last_status["processing_errors"] += 1
                logger.warning("【每日新剧助手】处理候选条目失败 %s: %s", raw.get("title"), err)
                continue

        candidates.sort(key=self._candidate_sort_key)
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

        notify_candidates = candidates
        if suppress_recent:
            notify_candidates = [
                item for item in candidates
                if not self._recently_notified(item.get("tmdbid"), notified, today)
            ]
        last_status["notification_count"] = len(notify_candidates)
        self.save_data("last_run", last_status)

        if send_message and (notify_candidates or self._notify_empty):
            self._send_candidates(notify_candidates, batch_id=batch_id)
            if notify_candidates:
                for item in notify_candidates:
                    notified[str(item.get("tmdbid"))] = today.isoformat()
                self.save_data("notified_history", notified)
        return candidates

    def _fetch_sources(self) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
        """自动降级获取即将播出与近期热播数据，并记录每一层数据源状态。"""
        items: List[Dict[str, Any]] = []
        status: Dict[str, Dict[str, Any]] = {}

        coming, coming_detail = self._fetch_coming_auto()
        status["即将播出"] = {"ok": bool(coming), "count": len(coming), "error": coming_detail.get("error", ""), "via": coming_detail.get("via", ""), "attempts": coming_detail.get("attempts", [])}
        items.extend(coming)

        if self._include_hot:
            hot_url = f"{self._rsshub}/douban/movie/weekly/tv_hot"
            hot, error, via = self._fetch_rss_with_fallback(hot_url, source="hot")
            status["近期热播"] = {"ok": error is None, "count": len(hot), "error": error or "", "via": via}
            items.extend(hot)

        platform_items, platform_status = fetch_platform_sources(
            {
                "tencent": self._platform_tencent,
                "iqiyi": self._platform_iqiyi,
                "youku": self._platform_youku,
                "mgtv": self._platform_mgtv,
                "bilibili": self._platform_bilibili,
            },
            proxy=self._proxy,
            flaresolverr_enabled=self._flaresolverr_enabled,
            flaresolverr_url=self._flaresolverr_url,
        )
        items.extend(platform_items)
        status.update(platform_status)
        return items, status

    def _fetch_coming_auto(self) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """优先豆瓣 Frodo 直连，失败后依次使用 RSSHub 和 FlareSolverr。"""
        attempts: List[str] = []
        direct, error = self._fetch_douban_direct_coming()
        if direct:
            logger.info("【每日新剧助手】【豆瓣直连】获取即将播出成功，共 %s 条", len(direct))
            return direct, {"via": "豆瓣直连", "attempts": attempts}
        attempts.append(f"豆瓣直连: {error or '空数据'}")
        logger.warning("【每日新剧助手】【豆瓣直连】失败: %s", error or "空数据")
        url = f"{self._rsshub}/douban/tv/coming/time/{self._coming_count}"
        rss, rss_error, via = self._fetch_rss_with_fallback(url, source="coming")
        if rss:
            return rss, {"via": via, "attempts": attempts}
        attempts.append(f"{via or 'RSSHub'}: {rss_error or '空数据'}")
        return [], {"via": via or "全部失败", "attempts": attempts, "error": "；".join(attempts)}

    def _fetch_douban_direct_coming(self) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """使用与 RSSHub 当前实现一致的 Frodo 接口直接获取豆瓣即将播出剧集。"""
        api_url = "https://frodo.douban.com/api/v2/tv/coming_soon"
        api_key = "0dad551ec0f84ed02907ff5c42e8ec70"
        api_secret = "bf7dddc7c9cfe6f7"
        ua = "api-client/1 com.douban.frodo/7.22.0.beta9(231) Android/23 product/Mate 40 vendor/HUAWEI model/Mate 40 brand/HUAWEI rom/android network/wifi platform/AndroidPad"
        ts = datetime.datetime.now().strftime("%Y%m%d")
        path = urllib.parse.urlparse(api_url).path
        raw_sign = f"GET&{urllib.parse.quote(path, safe='')}&{ts}"
        signature = base64.b64encode(hmac.new(api_secret.encode(), raw_sign.encode(), hashlib.sha1).digest()).decode()
        params = {"start": 0, "count": self._coming_count, "sortby": "hot", "os_rom": "android", "apiKey": api_key, "_ts": ts, "_sig": signature}
        try:
            request = RequestUtils(proxies=settings.PROXY) if self._proxy else RequestUtils()
            response = request.get_res(api_url, params=params, headers={"Accept": "application/json", "User-Agent": ua})
            if not response:
                return [], "无响应"
            status_code = getattr(response, "status_code", 200)
            if status_code >= 400:
                return [], f"HTTP {status_code}"
            try:
                data = response.json()
            except Exception as err:
                return [], f"JSON解析失败: {err}"
            subjects = _parse_douban_direct_subjects(data)
            if not subjects:
                details = (data.get("msg") or data.get("message") or data.get("reason")) if isinstance(data, dict) else ""
                return [], f"空数据{': ' + str(details) if details else ''}"
            return subjects, None
        except Exception as err:
            return [], str(err)

    def _fetch_rss_with_fallback(self, url: str, source: str) -> Tuple[List[Dict[str, Any]], Optional[str], str]:
        """先普通请求 RSSHub，失败后按配置使用 FlareSolverr 过盾。"""
        items, error = self._fetch_rss(url, source=source)
        if items:
            logger.info("【每日新剧助手】【RSSHub】获取成功 %s，共 %s 条", url, len(items))
            return items, None, "RSSHub"
        logger.warning("【每日新剧助手】【RSSHub】失败 %s: %s", url, error or "空数据")
        if not self._flaresolverr_enabled:
            return [], error or "RSSHub 空数据", "RSSHub"
        flare_items, flare_error = self._fetch_rss_via_flaresolverr(url, source=source)
        if flare_items:
            logger.info("【每日新剧助手】【FlareSolverr】过盾成功 %s，共 %s 条", url, len(flare_items))
            return flare_items, None, "FlareSolverr"
        logger.error("【每日新剧助手】【FlareSolverr】失败 %s: %s", url, flare_error or "空数据")
        return [], f"RSSHub={error or '失败'}；FlareSolverr={flare_error or '失败'}", "FlareSolverr"

    def _fetch_rss(self, url: str, source: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """普通 HTTP 请求并解析一个 RSSHub 豆瓣 RSS 地址。"""
        try:
            request = RequestUtils(proxies=settings.PROXY) if self._proxy else RequestUtils()
            response = request.get_res(url)
            if not response:
                return [], "无响应"
            status_code = getattr(response, "status_code", 200)
            if status_code >= 400:
                return [], f"HTTP {status_code}"
            text = response.text or ""
            lowered = text.lower()
            if "cf-chl-" in lowered or ("cloudflare" in lowered and "challenge" in lowered):
                return [], "检测到 Cloudflare Challenge"
            items = _parse_douban_rss(text, source=source)
            if not items:
                return [], "RSS 解析后为空"
            return items, None
        except Exception as err:
            return [], str(err)

    def _fetch_rss_via_flaresolverr(self, url: str, source: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """通过 FlareSolverr /v1 代请求 RSSHub 并解析返回正文。"""
        endpoint = f"{self._flaresolverr_url}/v1"
        payload = {"cmd": "request.get", "url": url, "maxTimeout": 60000}
        try:
            response = RequestUtils().post_res(endpoint, json=payload)
            if not response:
                return [], "FlareSolverr 无响应"
            status_code = getattr(response, "status_code", 200)
            if status_code >= 400:
                return [], f"FlareSolverr HTTP {status_code}"
            try:
                data = response.json()
            except Exception as err:
                return [], f"FlareSolverr JSON解析失败: {err}"
            body, error = _extract_flaresolverr_response(data)
            if error:
                return [], error
            try:
                items = _parse_douban_rss(body or "", source=source)
            except Exception as err:
                return [], f"FlareSolverr 返回内容不是有效 RSS: {err}"
            if not items:
                return [], "FlareSolverr 返回 RSS 为空"
            return items, None
        except Exception as err:
            return [], str(err)

    def _recognize(self, meta: MetaInfo, doubanid: str) -> Optional[MediaInfo]:
        """通过豆瓣 ID 优先识别 MoviePilot 媒体信息。"""
        try:
            if doubanid:
                if settings.RECOGNIZE_SOURCE == "themoviedb":
                    tmdbinfo = MediaChain().get_tmdbinfo_by_doubanid(doubanid=doubanid, mtype=MediaType.TV)
                    if tmdbinfo and tmdbinfo.get("id"):
                        mediainfo = self.chain.recognize_media(meta=meta, mtype=MediaType.TV, media_source=MediaSource.TMDB, media_id=str(tmdbinfo.get("id")))
                        if mediainfo:
                            return mediainfo
                else:
                    mediainfo = self.chain.recognize_media(meta=meta, mtype=MediaType.TV, media_source=MediaSource.Douban, media_id=str(doubanid))
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
        if source == "platform_ongoing":
            return True
        if source == "platform_recent":
            if not air_date:
                return True
            days = (today - air_date).days
            return -self._coming_days <= days <= max(self._recent_days, 60)
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
        """分批发送全部候选，避免数量较多时超过消息渠道长度/按钮限制。"""
        if not items:
            self.post_message(channel=channel, userid=userid, title="📺 今日新剧/在播剧", text="今天没有发现新的、仍在更新且尚未入库或订阅的剧集。")
            return
        if not batch_id:
            batch_id = str((self.get_data("daily_candidates") or {}).get("batch_id") or "")

        today = datetime.date.today()
        chunk_size = 20
        total_chunks = (len(items) + chunk_size - 1) // chunk_size
        for chunk_no, offset in enumerate(range(0, len(items), chunk_size), start=1):
            chunk = items[offset: offset + chunk_size]
            lines = ["已过滤媒体库已有和现有订阅；重复提醒只影响消息，不影响插件页面候选：", ""]
            buttons: List[List[dict]] = []
            row: List[dict] = []
            for item in chunk:
                air_date = _parse_date_value(item.get("air_date"))
                timing = _format_air_timing_value(air_date, today)
                vote_text = f"⭐ {item.get('vote')}" if item.get("vote") else "暂无评分"
                if item.get("source") == "coming":
                    source_text = "待播"
                elif item.get("source") == "hot":
                    source_text = "新近开播"
                else:
                    source_text = item.get("source_label") or ("更新中" if item.get("ongoing") else "近期上线")
                remarks = [str(x).strip() for x in (item.get("platform_remarks") or []) if str(x).strip()]
                remark_text = f" · {' / '.join(remarks[:2])}" if remarks else ""
                lines.append(f"{item['index']}. {item['title']} ({item.get('year') or '-'}) · {source_text}{remark_text} · {timing} · {vote_text}")
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
            suffix = f" · {chunk_no}/{total_chunks}" if total_chunks > 1 else ""
            self.post_message(
                channel=channel,
                userid=userid,
                title=f"📺 今日新剧/在播剧 · {len(items)} 部可选{suffix}",
                text="\n".join(lines),
                image=chunk[0].get("poster") or None,
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
        handled_indexes: List[int] = []

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
                mediainfo = self.chain.recognize_media(meta=meta, mtype=MediaType.TV, media_source=MediaSource.TMDB, media_id=str(item.get("tmdbid")))
                if not mediainfo:
                    failed.append(f"{index}.{item.get('title')}(识别失败)")
                    continue
                exist_flag, _ = DownloadChain().get_no_exists_info(meta=meta, mediainfo=mediainfo)
                if exist_flag:
                    skipped.append(f"{index}.{item.get('title')}(已入库)")
                    handled_indexes.append(index)
                    continue
                subscribe_chain = SubscribeChain()
                if subscribe_chain.exists(mediainfo=mediainfo, meta=meta):
                    skipped.append(f"{index}.{item.get('title')}(已订阅)")
                    handled_indexes.append(index)
                    continue
                subscribe_media_source = getattr(mediainfo, "media_source", None) or MediaSource.TMDB
                subscribe_media_id = getattr(mediainfo, "media_id", None) or getattr(mediainfo, "tmdb_id", None)
                if not subscribe_media_id:
                    failed.append(f"{index}.{item.get('title')}(缺少媒体ID)")
                    continue
                logger.info(
                    "【每日新剧助手】【订阅链诊断】准备创建订阅: title=%s, media_source=%s, media_id=%s, season=%s",
                    mediainfo.title, subscribe_media_source, subscribe_media_id, meta.begin_season
                )
                sid, err_msg = subscribe_chain.add(
                    title=mediainfo.title,
                    year=mediainfo.year,
                    mtype=MediaType.TV,
                    media_source=subscribe_media_source,
                    media_id=str(subscribe_media_id),
                    season=meta.begin_season,
                    message=False,
                    exist_ok=True,
                    username="每日新剧助手",
                )
                if sid:
                    success.append(f"{index}.{mediainfo.title_year}")
                    handled_indexes.append(index)
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
        return {"success": bool(success), "message": "\n\n".join(parts) or "没有可处理的条目", "handled_indexes": handled_indexes}

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
            "flaresolverr_enabled": self._flaresolverr_enabled,
            "flaresolverr_url": self._flaresolverr_url,
            "vote": self._vote,
            "coming_days": self._coming_days,
            "recent_days": self._recent_days,
            "coming_count": self._coming_count,
            "include_hot": self._include_hot,
            "repeat_days": self._repeat_days,
            "notify_empty": self._notify_empty,
            "platform_tencent": self._platform_tencent,
            "platform_iqiyi": self._platform_iqiyi,
            "platform_youku": self._platform_youku,
            "platform_mgtv": self._platform_mgtv,
            "platform_bilibili": self._platform_bilibili,
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
