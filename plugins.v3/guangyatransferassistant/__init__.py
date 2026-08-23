"""光鸭转存助手：Telegram 频道分享索引 + MoviePilot 订阅精确分流。"""

from __future__ import annotations

import datetime
import hashlib
import html
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from app.chain.subscribe import SubscribeChain
from app.db.oper.subscribe import SubscribeOper
from app.plugins import _PluginBase
from app.schemas import NotificationType
from app.runtime.extensions.plugin_manager import PluginManager
from app.sdk.config import settings
from app.sdk.logging import logger
from app.sdk.network import RequestUtils


DEFAULT_CHANNEL_URLS = [
    "https://tgm.li668.asia/regengguangya",
    "https://tgm.li668.asia/yunpanguangya",
]
SHARE_PATTERN = re.compile(
    r"https?://(?:www\.)?guangyapan\.com/(?:s|share)/[A-Za-z0-9_-]+(?:\?[^\s\"'<>]*)?",
    re.I,
)
CODE_PATTERN = re.compile(r"(?:提取码|密码|code)\s*[：:]?\s*([A-Za-z0-9]{2,16})", re.I)


def _normalize_media_text(value: Any) -> str:
    """标题匹配使用的宽松归一化。"""
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[\[【（(].{0,28}?[\]】）)]", " ", text)
    text = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", text).lower()
    return text


def _canonical_share_url(raw_url: str, context: str = "") -> str:
    """规范化光鸭分享链接并从消息文本补齐提取码。"""
    raw_url = html.unescape(str(raw_url or "").strip()).rstrip(".,，。;；)")
    try:
        parsed = urlsplit(raw_url)
    except ValueError:
        return ""
    if not parsed.hostname or not parsed.hostname.lower().endswith("guangyapan.com"):
        return ""
    query = parse_qs(parsed.query)
    if not any(query.get(key) for key in ("code", "pwd")):
        code_match = CODE_PATTERN.search(html.unescape(context or ""))
        if code_match:
            query["code"] = [code_match.group(1)]
    normalized_query = urlencode(
        [(key, item) for key, values in query.items() for item in values]
    )
    return urlunsplit(("https", "www.guangyapan.com", parsed.path, normalized_query, ""))


def _extract_channel_entries(page_text: str, source_url: str, source_label: str) -> List[Dict[str, Any]]:
    """从 Telegram 镜像 HTML 中提取分享链接及附近消息文本。"""
    decoded = html.unescape(str(page_text or ""))
    entries: List[Dict[str, Any]] = []
    seen = set()
    for match in SHARE_PATTERN.finditer(decoded):
        start = max(0, match.start() - 900)
        end = min(len(decoded), match.end() + 900)
        context_html = decoded[start:end]
        context = re.sub(r"<script\b[^>]*>.*?</script>", " ", context_html, flags=re.I | re.S)
        context = re.sub(r"<style\b[^>]*>.*?</style>", " ", context, flags=re.I | re.S)
        context = re.sub(r"<[^>]+>", " ", context)
        context = re.sub(r"\s+", " ", html.unescape(context)).strip()
        share_url = _canonical_share_url(match.group(0), context)
        if not share_url:
            continue
        share_key = _share_identity(share_url)
        if not share_key or share_key in seen:
            continue
        seen.add(share_key)
        entries.append({
            "share_url": share_url,
            "share_id": share_key.split("|", 1)[0],
            "text": context[:1800],
            "source_url": source_url,
            "source_label": source_label,
            "priority": 0 if "regeng" in source_url.lower() else 1,
        })
    return entries


def _share_identity(share_url: str) -> str:
    """返回 shareId + code 的稳定键。"""
    try:
        parsed = urlsplit(str(share_url or ""))
    except ValueError:
        return ""
    combined_path = "/".join(
        value.strip("/") for value in (parsed.path, parsed.fragment) if value
    )
    matched = re.search(r"(?:^|/)(?:s|share)/([A-Za-z0-9_-]+)", combined_path, re.I)
    query = parse_qs(parsed.query)
    share_id = (query.get("shareId") or query.get("share_id") or query.get("id") or [""])[0]
    if not share_id and matched:
        share_id = matched.group(1)
    code = (query.get("code") or query.get("pwd") or [""])[0]
    return f"{share_id}|{code}" if share_id else ""


def _entry_matches_subscription(entry: Dict[str, Any], name: str, year: Any = None, season: Any = None) -> bool:
    """频道消息与 MoviePilot 订阅做保守标题/季匹配。"""
    haystack = _normalize_media_text(entry.get("text"))
    if not haystack:
        return False
    raw_name = str(name or "").strip()
    candidates = {
        _normalize_media_text(raw_name),
        _normalize_media_text(re.split(r"[(/（]", raw_name, maxsplit=1)[0]),
    }
    candidates = {value for value in candidates if len(value) >= 2}
    if not candidates or not any(value in haystack for value in candidates):
        return False
    if season not in (None, "", 0, "0"):
        explicit = re.findall(r"(?i)\bS(?:eason)?\s*0*(\d{1,2})\b", str(entry.get("text") or ""))
        if explicit and int(season) not in {int(value) for value in explicit}:
            return False
    if year:
        years = {int(value) for value in re.findall(r"\b(19\d{2}|20\d{2})\b", str(entry.get("text") or ""))}
        if years and int(year) not in years:
            # 标题已经明确命中时，年份冲突才拒绝，避免同名翻拍误转存。
            return False
    return True


def _extract_result_list(response: Any) -> List[dict]:
    """兼容光鸭接口多种列表字段。"""
    if not isinstance(response, dict):
        return []
    data = response.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        data = response
    for key in ("list", "files", "items", "records", "fileList", "infoList"):
        value = data.get(key) if isinstance(data, dict) else None
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _cloud_item(raw: dict) -> Optional[Dict[str, Any]]:
    """规范化光鸭分享文件。"""
    if not isinstance(raw, dict):
        return None
    file_id = raw.get("fileId") or raw.get("id") or raw.get("fid") or raw.get("resId")
    name = str(raw.get("fileName") or raw.get("name") or raw.get("filename") or "").strip()
    if file_id in (None, "") or not name:
        return None
    raw_type = raw.get("type", raw.get("resType", raw.get("fileType", raw.get("dirType"))))
    is_dir = bool(raw.get("isDir") or raw.get("is_dir") or raw.get("dir") or raw_type in (2, "2", "dir", "folder"))
    if raw_type in (0, 1, "0", "1", "file"):
        is_dir = False
    return {
        "id": str(file_id),
        "name": name,
        "is_dir": is_dir,
        "size": int(raw.get("fileSize") or raw.get("size") or 0),
    }


def _asset_identity(relative_path: str, size: Any = 0) -> str:
    """按目标内相对路径+大小生成稳定资源键，跨分享链接也能去重。"""
    normalized = re.sub(r"/+", "/", str(relative_path or "").replace("\\", "/").strip("/")).lower()
    return hashlib.sha256(f"{normalized}|{int(size or 0)}".encode("utf-8")).hexdigest()


class GuangYaTransferAssistant(_PluginBase):
    """对用户勾选的订阅优先尝试光鸭频道转存，未勾选保持 MoviePilot 原生路线。"""

    plugin_name = "光鸭转存助手"
    plugin_desc = "读取指定 Telegram 光鸭资源频道，对手动勾选的 MoviePilot 订阅优先匹配并转存光鸭分享；未勾选或转存失败时继续原生订阅下载。"
    plugin_icon = "Guangyadisk_A.png"
    plugin_version = "1.1.0"
    plugin_author = "liheng-lk"
    plugin_label = "光鸭云盘,转存,订阅,Telegram,网盘,下载回退"
    author_url = "https://github.com/liheng-lk/MoviePilot-Plugins"
    plugin_config_prefix = "guangyatransferassistant_"
    plugin_order = 24
    auth_level = 1

    _enabled = False
    _channel_urls = "\n".join(DEFAULT_CHANNEL_URLS)
    _selected_subscriptions: List[int] = []
    _save_path = "/光鸭转存"
    _create_media_folder = False
    _fallback_native = True
    _notify = True
    _auto_transfer_on_refresh = True
    _refresh_minutes = 5
    _proxy = False
    _max_share_files = 5000
    _takeover_originals: Dict[str, Any] = {}
    _route_lock = threading.RLock()
    _inspect_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}

    def init_plugin(self, config: dict = None) -> None:
        """读取配置并安装订阅搜索分流。"""
        self._restore_takeover()
        config = config or {}
        self._enabled = bool(config.get("enabled", False))
        self._channel_urls = str(config.get("channel_urls") or "\n".join(DEFAULT_CHANNEL_URLS)).strip()
        self._selected_subscriptions = sorted({int(value) for value in (config.get("selected_subscriptions") or []) if str(value).isdigit()})
        self._save_path = str(config.get("save_path") or "/光鸭转存").strip() or "/"
        self._create_media_folder = bool(config.get("create_media_folder", False))
        self._fallback_native = bool(config.get("fallback_native", True))
        self._notify = bool(config.get("notify", True))
        self._auto_transfer_on_refresh = bool(config.get("auto_transfer_on_refresh", True))
        self._proxy = bool(config.get("proxy", False))
        self._refresh_minutes = self._to_int(config.get("refresh_minutes"), 5, 1, 120)
        self._max_share_files = self._to_int(config.get("max_share_files"), 5000, 100, 20000)
        self._cleanup_selected_ids()
        if self._enabled:
            self._install_takeover()

    def get_state(self) -> bool:
        return self._enabled

    def get_service(self) -> List[Dict[str, Any]]:
        if not self._enabled:
            return []
        return [{
            "id": "GuangYaTransferAssistantTick",
            "name": "光鸭转存助手频道刷新与路由守护",
            "trigger": "interval",
            "func": self._tick,
            "kwargs": {"minutes": self._refresh_minutes},
        }]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        subscriptions = self._subscription_options()
        folders = self._root_folder_options()
        return [{
            "component": "VForm",
            "content": [
                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "enabled", "label": "启用转存优先路由"}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "fallback_native", "label": "未命中/失败回退原生下载"}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "notify", "label": "转存结果通知"}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "proxy", "label": "频道读取使用代理"}}]},
                ]},
                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 7}, "content": [{"component": "VSelect", "props": {"model": "selected_subscriptions", "label": "选择走光鸭优先的订阅", "items": subscriptions, "multiple": True, "chips": True, "clearable": True}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 2}, "content": [{"component": "VTextField", "props": {"model": "refresh_minutes", "label": "频道刷新间隔(分钟)", "type": "number"}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "auto_transfer_on_refresh", "label": "刷新后自动检查转存"}}]},
                ]},
                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 9}, "content": [{"component": "VCombobox", "props": {"model": "save_path", "label": "光鸭目标文件夹", "items": folders, "clearable": False, "hint": "可选择根目录下已有文件夹，也可直接输入完整路径", "persistent-hint": True}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "create_media_folder", "label": "按媒体名建立子文件夹"}}]},
                ]},
                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12}, "content": [{"component": "VTextarea", "props": {"model": "channel_urls", "label": "资源频道地址（每行一个）", "rows": 3}}]},
                ]},
                {"component": "VAlert", "props": {"type": "info", "variant": "tonal", "text": "未勾选订阅保持原路线；勾选订阅会在频道刷新后主动检查。转存按文件级增量去重：同一资源不会重复转存，热更只转存新增文件。登录态直接复用“光鸭云盘助手”。"}},
            ],
        }], {
            "enabled": self._enabled,
            "channel_urls": self._channel_urls or "\n".join(DEFAULT_CHANNEL_URLS),
            "selected_subscriptions": self._selected_subscriptions,
            "save_path": self._save_path or "/光鸭转存",
            "create_media_folder": self._create_media_folder,
            "fallback_native": self._fallback_native,
            "notify": self._notify,
            "auto_transfer_on_refresh": self._auto_transfer_on_refresh,
            "refresh_minutes": self._refresh_minutes or 5,
            "proxy": self._proxy,
            "max_share_files": self._max_share_files or 5000,
        }

    def get_page(self) -> Optional[List[dict]]:
        index = self.get_data("channel_index") or {}
        history = self.get_data("transfer_history") or {}
        inventory = self.get_data("transfer_inventory") or {}
        last = self.get_data("last_run") or {}
        selected = set(self._selected_subscriptions)
        selected_subs = [sub for sub in self._list_subscriptions("N,R,P") if int(getattr(sub, "id", 0) or 0) in selected]
        rows = []
        for sub in selected_subs:
            sid = int(sub.id)
            recent = [value for key, value in history.items() if str(key).startswith(f"{sid}:")]
            recent.sort(key=lambda value: str(value.get("time") or ""), reverse=True)
            asset_count = len(((inventory.get(str(sid)) or {}).get("assets") or {}))
            state_text = (f"{recent[0].get('time') or '-'} · {recent[0].get('message') or '-'}" if recent else "等待频道匹配")
            rows.append({
                "component": "VCard",
                "props": {"variant": "tonal", "class": "h-100"},
                "content": [
                    {"component": "VCardTitle", "text": f"{sub.name} ({getattr(sub, 'year', '') or '-'})"},
                    {"component": "VCardText", "text": f"订阅ID {sid} · 已记录去重资源 {asset_count} 个 · {state_text}"},
                ],
            })
        contents: List[dict] = [{
            "component": "VAlert",
            "props": {
                "type": "success" if last.get("success") else "info",
                "variant": "tonal",
                "text": f"频道索引 {len(index.get('items') or [])} 个分享 · 已选择 {len(selected)} 个订阅 · 最近刷新 {index.get('time') or '-'}",
            },
        }]
        if rows:
            contents.append({"component": "div", "props": {"class": "grid gap-3 grid-info-card mt-3"}, "content": rows})

        resources = []
        for entry in list(index.get("items") or [])[:100]:
            matched = [
                f"{getattr(sub, 'name', '')}#{int(getattr(sub, 'id', 0) or 0)}"
                for sub in selected_subs
                if _entry_matches_subscription(entry, getattr(sub, "name", ""), getattr(sub, "year", None), getattr(sub, "season", None))
            ]
            snippet = re.sub(r"https?://\S+", "", str(entry.get("text") or ""))
            snippet = re.sub(r"\s+", " ", snippet).strip()[:180]
            share_id = str(entry.get("share_id") or "-")
            status = "匹配：" + "、".join(matched) if matched else "未匹配已勾选订阅"
            resources.append({
                "component": "VListItem",
                "props": {
                    "title": f"{entry.get('source_label') or '频道资源'} · {share_id}",
                    "subtitle": f"{status} · {snippet}",
                },
            })
        contents.append({
            "component": "VCard",
            "props": {"variant": "outlined", "class": "mt-4"},
            "content": [
                {"component": "VCardTitle", "text": f"频道资源（{len(index.get('items') or [])}）"},
                {"component": "VCardText", "text": "显示频道已识别资源及其与已勾选订阅的匹配结果；最多显示 100 条。"},
                {"component": "VList", "props": {"density": "compact"}, "content": resources or [{"component": "VListItem", "props": {"title": "暂无频道资源"}}]},
            ],
        })
        return contents

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {"path": "/refresh", "endpoint": self.api_refresh, "methods": ["POST"], "summary": "立即刷新频道索引"},
            {"path": "/transfer", "endpoint": self.api_transfer, "methods": ["POST"], "summary": "立即尝试一个订阅的光鸭转存"},
            {"path": "/folders", "endpoint": self.api_folders, "methods": ["GET"], "summary": "读取光鸭根目录文件夹"},
        ]

    def api_refresh(self) -> Dict[str, Any]:
        items = self.refresh_channels(force=True)
        routed = self._process_selected_subscriptions(trigger="手动刷新") if self._auto_transfer_on_refresh else []
        return {"success": True, "count": len(items), "items": items, "routes": routed}

    def api_transfer(self, payload: dict) -> Dict[str, Any]:
        payload = payload or {}
        sid = int(payload.get("subscribe_id") or 0)
        if not sid:
            return {"success": False, "message": "subscribe_id 不能为空"}
        subscribe = self._find_subscription(sid)
        if not subscribe:
            return {"success": False, "message": "订阅不存在"}
        return self._try_transfer_subscription(subscribe, force=True)

    def api_folders(self) -> Dict[str, Any]:
        return {"success": True, "items": self._root_folder_options(raw=True)}

    def _tick(self) -> None:
        self._install_takeover()
        items = self.refresh_channels(force=True)
        if self._auto_transfer_on_refresh and items:
            self._process_selected_subscriptions(trigger="频道定时刷新")

    def _process_selected_subscriptions(self, trigger: str = "后台检查") -> List[Dict[str, Any]]:
        """频道刷新后主动检查已勾选订阅；这里只转存，不主动触发原生下载。"""
        results: List[Dict[str, Any]] = []
        with self._route_lock:
            for sid in list(self._selected_subscriptions):
                subscribe = self._find_subscription(int(sid))
                if not subscribe:
                    continue
                try:
                    result = self._try_transfer_subscription(subscribe)
                    results.append({"subscribe_id": int(sid), **result})
                    logger.info("【光鸭转存助手】【自动】%s #%s %s：%s", trigger, sid, getattr(subscribe, "name", ""), result.get("message") or "完成")
                except Exception as err:
                    logger.exception("【光鸭转存助手】【自动】%s #%s 执行异常", trigger, sid)
                    results.append({"subscribe_id": int(sid), "success": False, "handled": False, "message": str(err)})
        return results

    def refresh_channels(self, force: bool = False) -> List[Dict[str, Any]]:
        """抓取频道镜像并建立光鸭分享索引。"""
        current = self.get_data("channel_index") or {}
        current_time = self._parse_datetime(current.get("time"))
        if not force and current_time and (datetime.datetime.now() - current_time).total_seconds() < self._refresh_minutes * 60:
            return list(current.get("items") or [])
        entries: List[Dict[str, Any]] = []
        errors = []
        seen = set()
        source_successes = 0
        for source_url in self._source_urls():
            label = "光鸭云盘影视热更频道" if "regeng" in source_url.lower() else "光鸭云盘资源分享频道"
            try:
                request = RequestUtils(proxies=settings.PROXY) if self._proxy else RequestUtils()
                response = request.get_res(source_url)
                if not response or getattr(response, "status_code", 200) >= 400:
                    errors.append(f"{label}: HTTP {getattr(response, 'status_code', '无响应')}")
                    continue
                source_successes += 1
                found = _extract_channel_entries(response.text or "", source_url, label)
                for item in found:
                    key = _share_identity(item.get("share_url") or "")
                    if key and key not in seen:
                        seen.add(key)
                        entries.append(item)
            except Exception as err:
                errors.append(f"{label}: {err}")
        entries.sort(key=lambda item: int(item.get("priority") or 0))
        if not entries and current.get("items") and (errors or source_successes == 0):
            logger.warning("【光鸭转存助手】本轮频道抓取未得到有效分享，保留上次索引，避免临时网络异常误触发原生下载")
            self.save_data("last_run", {
                "success": False,
                "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "count": len(current.get("items") or []),
                "errors": errors or ["频道返回空数据，已保留上次索引"],
                "stale_index": True,
            })
            return list(current.get("items") or [])
        payload = {
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "items": entries[:1000],
            "errors": errors,
        }
        self.save_data("channel_index", payload)
        self.save_data("last_run", {"success": bool(entries), "time": payload["time"], "count": len(entries), "errors": errors})
        logger.info("【光鸭转存助手】频道刷新完成，识别分享 %s 个，错误 %s 个", len(entries), len(errors))
        return entries

    def _source_urls(self) -> List[str]:
        values = [line.strip() for line in re.split(r"[\r\n]+", self._channel_urls or "") if line.strip()]
        return values or list(DEFAULT_CHANNEL_URLS)

    def _subscription_options(self) -> List[Dict[str, Any]]:
        options = []
        for sub in self._list_subscriptions("N,R"):
            sid = int(getattr(sub, "id", 0) or 0)
            if not sid:
                continue
            season = getattr(sub, "season", None)
            suffix = f" S{int(season):02d}" if season not in (None, 0) else ""
            options.append({"title": f"{sub.name} ({getattr(sub, 'year', '') or '-'}){suffix} · #{sid}", "value": sid})
        return options

    @staticmethod
    def _list_subscriptions(state: str = "N,R") -> List[Any]:
        try:
            return list(SubscribeOper().list(state) or [])
        except Exception as err:
            logger.warning("【光鸭转存助手】读取 MoviePilot 订阅失败: %s", err)
            return []

    def _find_subscription(self, sid: int) -> Optional[Any]:
        for sub in self._list_subscriptions("N,R,P"):
            if int(getattr(sub, "id", 0) or 0) == int(sid):
                return sub
        return None

    def _cleanup_selected_ids(self) -> None:
        valid = {int(getattr(item, "id", 0) or 0) for item in self._list_subscriptions("N,R,P")}
        # 启动阶段订阅查询暂时不可用时，保留用户已经勾选的路由。
        if not valid:
            return
        selected = [sid for sid in self._selected_subscriptions if sid in valid]
        if selected == self._selected_subscriptions:
            return
        self._selected_subscriptions = selected
        self._save_config()

    def _save_config(self) -> None:
        self.update_config({
            "enabled": self._enabled,
            "channel_urls": self._channel_urls,
            "selected_subscriptions": self._selected_subscriptions,
            "save_path": self._save_path,
            "create_media_folder": self._create_media_folder,
            "fallback_native": self._fallback_native,
            "notify": self._notify,
            "auto_transfer_on_refresh": self._auto_transfer_on_refresh,
            "refresh_minutes": self._refresh_minutes,
            "proxy": self._proxy,
            "max_share_files": self._max_share_files,
        })

    def _install_takeover(self) -> None:
        """只接管订阅搜索任务；未选择的订阅仍调用原生 SubscribeChain.search。"""
        if not self._enabled:
            return
        try:
            from app.scheduler import Scheduler
            scheduler = Scheduler.get_existing_instance()
            jobs = getattr(scheduler, "_jobs", None) if scheduler else None
            jobs = jobs or {}
            for job_id in ("subscribe_search", "new_subscribe_search"):
                job = jobs.get(job_id)
                if not job:
                    continue
                current = job.get("func")
                if getattr(current, "__self__", None) is self:
                    continue
                self._takeover_originals.setdefault(job_id, current)
                job["func"] = self._dispatch_subscribe_search
        except Exception as err:
            logger.warning("【光鸭转存助手】安装订阅分流失败: %s", err)

    def _restore_takeover(self) -> None:
        originals = dict(self._takeover_originals or {})
        if not originals:
            return
        try:
            from app.scheduler import Scheduler
            scheduler = Scheduler.get_existing_instance()
            jobs = getattr(scheduler, "_jobs", None) if scheduler else None
            jobs = jobs or {}
            for job_id, original in originals.items():
                job = jobs.get(job_id)
                current = job.get("func") if job else None
                if job and getattr(current, "__self__", None) is self:
                    job["func"] = original
        except Exception as err:
            logger.warning("【光鸭转存助手】恢复原生订阅搜索失败: %s", err)
        finally:
            self._takeover_originals = {}

    def _dispatch_subscribe_search(self, sid: Optional[int] = None, state: Optional[str] = "R", manual: Optional[bool] = False, progress_callback=None):
        """将勾选订阅转入光鸭优先，其余订阅逐条交给原生搜索。"""
        with self._route_lock:
            selected = set(self._selected_subscriptions)
            if sid:
                if int(sid) not in selected:
                    return SubscribeChain().search(sid=sid, state=state, manual=manual, progress_callback=progress_callback)
                subscribe = self._find_subscription(int(sid))
                if not subscribe:
                    return SubscribeChain().search(sid=sid, state=state, manual=manual, progress_callback=progress_callback)
                result = self._try_transfer_subscription(subscribe)
                if result.get("handled"):
                    return True
                if self._fallback_native:
                    return SubscribeChain().search(sid=sid, state=state, manual=manual, progress_callback=progress_callback)
                return True

            subscriptions = self._list_subscriptions(state or "N,R")
            for index, subscribe in enumerate(subscriptions):
                subscribe_id = int(getattr(subscribe, "id", 0) or 0)
                if not subscribe_id:
                    continue
                callback = progress_callback if index == 0 else None
                if subscribe_id in selected:
                    result = self._try_transfer_subscription(subscribe)
                    if result.get("handled"):
                        continue
                    if not self._fallback_native:
                        continue
                SubscribeChain().search(sid=subscribe_id, state=None, manual=manual, progress_callback=callback)
            return True

    def _try_transfer_subscription(self, subscribe: Any, force: bool = False) -> Dict[str, Any]:
        """匹配全部相关分享，只转存尚未记录的新文件；同一分享热更不会重转旧文件。"""
        sid = int(getattr(subscribe, "id", 0) or 0)
        self.refresh_channels(force=False)
        entries = list((self.get_data("channel_index") or {}).get("items") or [])
        matches = [item for item in entries if _entry_matches_subscription(item, getattr(subscribe, "name", ""), getattr(subscribe, "year", None), getattr(subscribe, "season", None))]
        if not matches:
            logger.info("【光鸭转存助手】【匹配】#%s %s 未命中频道分享；%s", sid, getattr(subscribe, "name", ""), "将由 MoviePilot 原订阅任务继续下载" if self._fallback_native else "原生下载回退已关闭")
            return {"success": False, "handled": False, "message": "频道未匹配到光鸭分享"}
        logger.info("【光鸭转存助手】【匹配】#%s %s 命中 %s 个频道分享", sid, getattr(subscribe, "name", ""), len(matches))

        history = self.get_data("transfer_history") or {}
        inventory = self.get_data("transfer_inventory") or {}
        sid_key = str(sid)
        inv_row = inventory.get(sid_key) or {"assets": {}}
        assets = inv_row.get("assets") or {}
        errors: List[str] = []
        transferred_assets: List[Dict[str, Any]] = []
        task_ids: List[str] = []
        sources = set()
        valid_match = False
        attempted_new = False
        target_path = self._target_path(subscribe)

        for entry in matches[:20]:
            share_url = entry.get("share_url") or ""
            share_key = _share_identity(share_url)
            if not share_key:
                continue
            probe = self._inspect_share(share_url)
            if not probe.get("success"):
                error = str(probe.get("message") or "分享读取失败")
                logger.warning("【光鸭转存助手】【匹配】分享读取失败 share_id=%s：%s", share_key.split("|", 1)[0], error)
                errors.append(error)
                continue
            valid_match = True
            source = str(entry.get("source_label") or "频道资源")
            sources.add(source)
            fingerprint = str(probe.get("fingerprint") or "")
            history_key = f"{sid}:{share_key}"
            old = history.get(history_key) or {}

            planned = self._plan_incremental_files(probe, assets)
            # 从 1.0.x 升级时，如果同一分享已经完整成功且内容未变，用当前文件清单补建增量索引，绝不重新转一遍。
            if not assets and old.get("success") and fingerprint and old.get("fingerprint") == fingerprint:
                migrated = self._plan_incremental_files(probe, {})
                self._remember_assets(assets, migrated, share_key, target_path)
                inventory[sid_key] = {"assets": assets, "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                self.save_data("transfer_inventory", inventory)
                logger.info("【光鸭转存助手】【去重】#%s %s 从旧版成功记录建立文件级索引 %s 个，不重复转存", sid, getattr(subscribe, "name", ""), len(migrated))
                continue

            if not planned:
                logger.info("【光鸭转存助手】【去重】#%s %s share_id=%s 无新增文件，已转存内容跳过", sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0])
                continue

            attempted_new = True
            logger.info("【光鸭转存助手】【增量】#%s %s share_id=%s 扫描文件=%s，新增待转=%s，已记录=%s", sid, getattr(subscribe, "name", ""), share_key.split("|", 1)[0], probe.get("leaf_count") or len(probe.get("files") or []), len(planned), len(assets))
            restored = self._restore_items(probe, target_path, planned)
            completed = list(restored.get("completed_items") or [])
            if completed:
                self._remember_assets(assets, completed, share_key, target_path)
                inventory[sid_key] = {"assets": assets, "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                self.save_data("transfer_inventory", inventory)
                transferred_assets.extend(completed)
                task_ids.extend([value for value in (restored.get("task_ids") or []) if value])
            record = {
                "success": bool(restored.get("success")),
                "fingerprint": fingerprint,
                "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "share_url": share_url,
                "source": source,
                "target_path": target_path,
                "message": restored.get("message") or "",
                "task_id": ",".join(restored.get("task_ids") or []),
                "confirmed": bool(restored.get("success")),
                "confirmation": restored.get("confirmation") or "",
                "file_count": probe.get("leaf_count") or len(probe.get("files") or []),
                "new_count": len(completed),
            }
            history[history_key] = record
            self._trim_history(history)
            self.save_data("transfer_history", history)
            if not restored.get("success"):
                errors.append(str(restored.get("message") or "增量转存失败"))

        if transferred_assets:
            unique_paths = []
            seen_paths = set()
            for item in transferred_assets:
                rel = str(item.get("effective_path") or item.get("relative_path") or item.get("name") or "")
                if rel and rel not in seen_paths:
                    seen_paths.add(rel)
                    unique_paths.append(rel)
            logger.info("【光鸭转存助手】【转存】#%s %s 增量转存完成：新增 %s 个文件，累计去重记录 %s 个，目标=%s", sid, getattr(subscribe, "name", ""), len(unique_paths), len(assets), target_path)
            if self._notify:
                season = getattr(subscribe, "season", None)
                media_text = f"{getattr(subscribe, 'name', '')} ({getattr(subscribe, 'year', '') or '-'})"
                if season not in (None, "", 0, "0"):
                    media_text += f" S{int(season):02d}"
                preview = "、".join(unique_paths[:8])
                if len(unique_paths) > 8:
                    preview += f" 等 {len(unique_paths)} 个"
                lines = [
                    f"媒体：{media_text}",
                    "状态：增量转存已确认完成",
                    f"本次新增：{len(unique_paths)} 个文件",
                    f"累计去重：{len(assets)} 个文件",
                    f"来源：{'、'.join(sorted(sources))}",
                    f"目标：{target_path}",
                    f"新增内容：{preview or '-'}",
                ]
                if task_ids:
                    lines.append(f"任务ID：{','.join(task_ids[:6])}")
                self.post_message(mtype=NotificationType.Plugin, title="✅ 光鸭转存成功", text="\n".join(lines))
                logger.info("【光鸭转存助手】【通知】已发送增量转存成功通知：#%s %s", sid, getattr(subscribe, "name", ""))
            return {"success": True, "handled": True, "message": f"增量转存成功，本次新增 {len(unique_paths)} 个文件", "new_count": len(unique_paths), "target_path": target_path}

        if valid_match and not attempted_new:
            # 有可读匹配分享且没有新增，说明该订阅已经被光鸭路线满足，不能再触发原生下载造成重复。
            logger.info("【光鸭转存助手】【去重】#%s %s 所有匹配分享均无新增，保持光鸭优先，不触发重复下载", sid, getattr(subscribe, "name", ""))
            return {"success": True, "handled": True, "already": True, "message": "已同步，无新增资源"}

        final_message = "；".join(errors[:4]) or "匹配分享均不可用"
        logger.warning("【光鸭转存助手】【回退】#%s %s 增量转存未完成：%s；%s", sid, getattr(subscribe, "name", ""), final_message, "将回退 MoviePilot 原生下载" if self._fallback_native else "原生下载回退已关闭")
        if self._notify and matches:
            notices = self.get_data("failure_notices") or {}
            notice_key = f"{sid}:{hashlib.sha256(final_message.encode('utf-8')).hexdigest()[:12]}"
            last_notice = self._parse_datetime(notices.get(notice_key))
            now = datetime.datetime.now()
            if not last_notice or (now - last_notice).total_seconds() >= 6 * 3600:
                try:
                    self.post_message(
                        mtype=NotificationType.Plugin,
                        title="⚠️ 光鸭转存失败",
                        text=(
                            f"媒体：{getattr(subscribe, 'name', '')} ({getattr(subscribe, 'year', '') or '-'})\n"
                            f"状态：增量转存未完成\n原因：{final_message}\n"
                            + ("后续：将回退 MoviePilot 原生下载" if self._fallback_native else "后续：原生下载回退已关闭")
                        ),
                    )
                    notices[notice_key] = now.strftime("%Y-%m-%d %H:%M:%S")
                    self.save_data("failure_notices", notices)
                    logger.info("【光鸭转存助手】【通知】已发送转存失败通知：#%s %s（相同错误 6 小时内不重复推送）", sid, getattr(subscribe, "name", ""))
                except Exception as err:
                    logger.warning("【光鸭转存助手】【通知】发送失败通知异常：%s", err)
        return {"success": False, "handled": False, "message": final_message}

    def _target_path(self, subscribe: Any) -> str:
        base = "/" + self._save_path.strip("/") if self._save_path.strip("/") else "/"
        if not self._create_media_folder:
            return base
        name = re.sub(r"[\\/:*?\"<>|]+", " ", str(getattr(subscribe, "name", "") or "")).strip()
        year = str(getattr(subscribe, "year", "") or "").strip()
        folder = f"{name} ({year})" if year else name
        return (base.rstrip("/") + "/" + folder).replace("//", "/")

    def _plan_incremental_files(self, probe: Dict[str, Any], assets: Dict[str, Any]) -> List[Dict[str, Any]]:
        files = [dict(item) for item in (probe.get("files") or []) if item.get("id")]
        if not files:
            return []
        top_parts = {str(item.get("relative_path") or "").split("/", 1)[0] for item in files if "/" in str(item.get("relative_path") or "")}
        strip_root = next(iter(top_parts)) if self._create_media_folder and len(top_parts) == 1 else ""
        planned = []
        for item in files:
            rel = str(item.get("relative_path") or item.get("name") or "").strip("/")
            effective = rel
            if strip_root and rel.startswith(strip_root + "/"):
                effective = rel[len(strip_root) + 1:]
            parent = effective.rsplit("/", 1)[0] if "/" in effective else ""
            asset_key = _asset_identity(effective, item.get("size") or 0)
            if asset_key in assets:
                continue
            item["effective_path"] = effective
            item["target_parent"] = parent
            item["asset_key"] = asset_key
            planned.append(item)
        return planned

    @staticmethod
    def _remember_assets(assets: Dict[str, Any], items: List[Dict[str, Any]], share_key: str, target_path: str) -> None:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for item in items:
            key = str(item.get("asset_key") or _asset_identity(item.get("effective_path") or item.get("relative_path") or item.get("name") or "", item.get("size") or 0))
            assets[key] = {
                "path": item.get("effective_path") or item.get("relative_path") or item.get("name") or "",
                "size": int(item.get("size") or 0),
                "share_id": str(share_key or "").split("|", 1)[0],
                "target": target_path,
                "time": now,
            }
        if len(assets) > 20000:
            ordered = sorted(assets.items(), key=lambda pair: str((pair[1] or {}).get("time") or ""), reverse=True)[:20000]
            assets.clear()
            assets.update(dict(ordered))

    def _get_guangya_runtime(self) -> Tuple[Any, Any]:
        manager = PluginManager()
        client = manager.get_plugin_attr("ShukGuangYaDisk", "_client")
        api = manager.get_plugin_attr("ShukGuangYaDisk", "_guangya_api")
        return client, api

    @staticmethod
    def _is_success(response: Any) -> bool:
        if not isinstance(response, dict):
            return False
        code = response.get("code")
        return code in (None, 0, "0") and str(response.get("msg") or response.get("message") or "success").lower() not in ("error", "failed", "fail")

    def _share_access(self, client: Any, share_url: str) -> Tuple[Optional[str], str]:
        identity = _share_identity(share_url)
        if not identity:
            return None, "无效光鸭分享链接"
        share_id, code = identity.split("|", 1)
        response = client._request(
            method="POST",
            url=f"{client.API_BASE_URL}/nd.bizuserres.s/v1/get_share_access_token",
            data={"shareId": share_id, "code": code},
            need_auth=False,
        )
        data = response.get("data") or {} if isinstance(response, dict) else {}
        token = str(data.get("accessToken") or data.get("access_token") or data.get("token") or "") if isinstance(data, dict) else ""
        if not self._is_success(response) or not token:
            return None, str(response.get("msg") or response.get("error") or "获取分享令牌失败")
        return token, ""

    def _inspect_share(self, share_url: str) -> Dict[str, Any]:
        cached = self._inspect_cache.get(_share_identity(share_url))
        if cached and time.time() - cached[0] < min(self._refresh_minutes * 60, 900):
            return dict(cached[1])
        client, _ = self._get_guangya_runtime()
        if not client:
            return {"success": False, "message": "光鸭云盘助手未运行或未登录"}
        token, error = self._share_access(client, share_url)
        if not token:
            return {"success": False, "message": error}
        stack: List[Tuple[str, str]] = [("", "")]
        root_ids: List[str] = []
        fingerprint_rows: List[str] = []
        files: List[Dict[str, Any]] = []
        count = 0
        while stack and count < self._max_share_files:
            parent_id, parent_path = stack.pop()
            page = 1
            while count < self._max_share_files:
                response = client._request(
                    method="POST",
                    url=f"{client.API_BASE_URL}/nd.bizuserres.s/v1/get_share_page_files_list",
                    data={"accessToken": token, "parentId": parent_id, "page": page, "pageSize": 100, "orderBy": 0, "sortType": 0},
                    need_auth=False,
                )
                if not self._is_success(response):
                    return {"success": False, "message": str(response.get("msg") or response.get("error") or "读取分享文件失败")}
                raw_items = _extract_result_list(response)
                if parent_id == "":
                    root_ids.extend(str(item.get("fileId") or item.get("id") or item.get("fid") or item.get("resId") or "") for item in raw_items)
                for raw in raw_items:
                    item = _cloud_item(raw)
                    if not item:
                        continue
                    count += 1
                    rel = "/".join(value for value in (parent_path.strip("/"), item["name"].strip("/")) if value)
                    fingerprint_rows.append(f"{item['id']}|{rel}|{item['size']}|{int(item['is_dir'])}")
                    if item["is_dir"]:
                        stack.append((item["id"], rel))
                    else:
                        files.append({**item, "relative_path": rel, "parent_path": parent_path})
                    if count >= self._max_share_files:
                        break
                if len(raw_items) < 100:
                    break
                page += 1
        fingerprint = hashlib.sha256("\n".join(sorted(fingerprint_rows)).encode("utf-8")).hexdigest()
        result = {
            "success": True, "access_token": token,
            "root_ids": [value for value in root_ids if value],
            "fingerprint": fingerprint, "file_count": count,
            "leaf_count": len(files), "files": files,
        }
        self._inspect_cache[_share_identity(share_url)] = (time.time(), result)
        return dict(result)

    def _restore_items(self, probe: Dict[str, Any], save_path: str, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        client, api = self._get_guangya_runtime()
        if not client or not api:
            return {"success": False, "message": "请先安装、启用并登录光鸭云盘助手", "completed_items": []}
        if not items:
            return {"success": True, "message": "无新增文件", "completed_items": [], "task_ids": []}
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for item in items:
            groups.setdefault(str(item.get("target_parent") or ""), []).append(item)
        completed: List[Dict[str, Any]] = []
        task_ids: List[str] = []
        try:
            for relative_parent, group in groups.items():
                base = "/" + str(save_path or "/").strip("/") if str(save_path or "/").strip("/") else "/"
                normalized = (base.rstrip("/") + ("/" + relative_parent.strip("/") if relative_parent else "")) or "/"
                folder = api.get_folder(Path(normalized))
                if not folder and normalized != "/":
                    return {"success": False, "message": f"无法创建/定位目标目录 {normalized}", "completed_items": completed, "task_ids": task_ids}
                parent_id = str(getattr(folder, "fileid", "") or "") if folder else ""
                file_ids = [str(item.get("id") or "") for item in group if item.get("id")]
                logger.info("【光鸭转存助手】【增量】提交目录 %s：新增文件 %s 个", normalized, len(file_ids))
                response = client._request(
                    method="POST",
                    url=f"{client.API_BASE_URL}/nd.bizuserres.s/v1/restore_share",
                    data={"accessToken": probe.get("access_token"), "fileIds": file_ids, "parentId": parent_id},
                    need_auth=True,
                )
                if not self._is_success(response):
                    return {"success": False, "message": str(response.get("msg") or response.get("error") or "光鸭增量转存失败"), "completed_items": completed, "task_ids": task_ids}
                data = response.get("data") or {}
                task_id = str(data.get("taskId") or data.get("task_id") or "") if isinstance(data, dict) else ""
                if task_id:
                    task_ids.append(task_id)
                if task_id and hasattr(api, "_wait_task_done"):
                    logger.info("【光鸭转存助手】【转存】等待增量任务完成：task_id=%s", task_id)
                    done = api._wait_task_done(task_id, max_try=120, interval=1, allow_missing=True)
                    if not done:
                        return {"success": False, "message": f"增量转存任务 {task_id} 未确认完成", "completed_items": completed, "task_ids": task_ids}
                completed.extend(group)
            return {
                "success": True, "message": f"增量转存完成，共新增 {len(completed)} 个文件",
                "completed_items": completed, "task_ids": task_ids,
                "confirmation": "所有增量转存任务已确认完成",
            }
        except Exception as err:
            logger.exception("【光鸭转存助手】【转存】执行增量转存异常：target=%s", save_path)
            return {"success": False, "message": f"光鸭增量转存异常: {err}", "completed_items": completed, "task_ids": task_ids}

    def _restore_share(self, share_url: str, save_path: str, probe: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """兼容入口：仍使用文件级恢复，避免整份分享重复转存。"""
        probe = probe or self._inspect_share(share_url)
        if not probe.get("success"):
            return probe
        items = self._plan_incremental_files(probe, {})
        return self._restore_items(probe, save_path, items)

    def _root_folder_options(self, raw: bool = False) -> List[Any]:
        client, _ = self._get_guangya_runtime()
        if not client:
            return []
        try:
            response = client._request(
                method="POST",
                url=f"{client.API_BASE_URL}/nd.bizuserres.s/v1/file/get_file_list",
                data={"parentId": "", "page": 0, "pageSize": 100, "orderBy": 0, "sortType": 0, "fileTypes": []},
                need_auth=True,
            )
            result = []
            for value in _extract_result_list(response):
                item = _cloud_item(value)
                if item and item["is_dir"]:
                    row = {"title": "/" + item["name"], "value": "/" + item["name"], "file_id": item["id"]}
                    result.append(row if raw else {"title": row["title"], "value": row["value"]})
            return result
        except Exception:
            return []

    @staticmethod
    def _trim_history(history: Dict[str, Any]) -> None:
        if len(history) <= 500:
            return
        ordered = sorted(history.items(), key=lambda pair: str((pair[1] or {}).get("time") or ""), reverse=True)
        history.clear()
        history.update(dict(ordered[:500]))

    @staticmethod
    def _parse_datetime(value: Any) -> Optional[datetime.datetime]:
        try:
            return datetime.datetime.strptime(str(value or ""), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None

    @staticmethod
    def _to_int(value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(parsed, maximum))

    def stop_service(self) -> None:
        self._restore_takeover()
        self._inspect_cache.clear()
