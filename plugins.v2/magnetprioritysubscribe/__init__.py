from __future__ import annotations

import json
import threading
from typing import Any, Dict, List, Optional, Tuple

from app.core.event import Event, eventmanager
from app.core.plugin import PluginManager
from app.db.subscribe_oper import SubscribeOper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, MediaType

from .core import MagnetResult, select_best
from .guangya_offline import GuangYaOfflineClient, GuangYaOfflineConfig, GuangYaOfflineError
from .torznab import TorznabError, TorznabSource, search_torznab


class MagnetPrioritySubscribe(_PluginBase):
    """磁力优先订阅：在独立测试分支验证磁力搜索和光鸭离线链路。"""

    plugin_name = "磁力优先订阅"
    plugin_desc = "订阅时优先搜索配置的 Torznab 磁力源，强制中文字幕，成功提交光鸭离线后再决定是否接管原生下载。"
    plugin_icon = "magnet.png"
    plugin_version = "1.0-beta1"
    plugin_author = "liheng-lk"
    author_url = "https://github.com/liheng-lk/MoviePilot-Plugins"
    plugin_config_prefix = "magnetprioritysubscribe_"
    plugin_order = 18
    auth_level = 1

    _enabled = False
    _auto_enabled = False
    _dry_run = True
    _torznab_sources_json = "[]"
    _guangya_parent_id = ""
    _timeout = 12
    _records: List[Dict[str, Any]] = []
    _inflight: set[str] = set()
    _lock = threading.Lock()

    def init_plugin(self, config: dict = None) -> None:
        config = config or {}
        self._enabled = bool(config.get("enabled", False))
        self._auto_enabled = bool(config.get("auto_enabled", False))
        # Test branch defaults to dry-run; production merge will require explicit gate changes after real tests.
        self._dry_run = bool(config.get("dry_run", True))
        self._torznab_sources_json = str(config.get("torznab_sources_json") or "[]")
        self._guangya_parent_id = str(config.get("guangya_parent_id") or "").strip()
        try:
            self._timeout = max(3, min(int(config.get("timeout") or 12), 30))
        except Exception:
            self._timeout = 12
        self._records = list(self.get_data("records") or [])[-100:]

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_service(self) -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_page(self) -> List[dict]:
        return []

    def stop_service(self) -> None:
        return

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                                {"component": "VSwitch", "props": {"model": "enabled", "label": "启用插件"}}
                            ]},
                            {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                                {"component": "VSwitch", "props": {"model": "auto_enabled", "label": "监听新订阅"}}
                            ]},
                            {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                                {"component": "VSwitch", "props": {"model": "dry_run", "label": "安全测试模式", "hint": "开启时只搜索和筛选，不创建光鸭任务", "persistent-hint": True}}
                            ]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12}, "content": [
                                {"component": "VTextarea", "props": {
                                    "model": "torznab_sources_json",
                                    "label": "Torznab 搜索源 JSON",
                                    "rows": 5,
                                    "hint": '[{"name":"Prowlarr","url":"http://prowlarr:9696/1/api","api_key":"xxx"}]',
                                    "persistent-hint": True,
                                }}
                            ]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "md": 8}, "content": [
                                {"component": "VTextField", "props": {"model": "guangya_parent_id", "label": "光鸭目标目录 fileId", "hint": "测试阶段先使用目录 fileId；后续稳定版会支持目录选择器", "persistent-hint": True}}
                            ]},
                            {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                                {"component": "VTextField", "props": {"model": "timeout", "label": "单源超时(秒)", "type": "number"}}
                            ]},
                        ],
                    },
                    {"component": "VAlert", "props": {
                        "type": "warning", "variant": "tonal",
                        "text": "当前为测试分支 beta1：安全测试模式默认开启。只有经过 Torznab、中文字幕、光鸭离线与失败回退实机验证后才会允许生产接管并合并 main。"
                    }},
                ],
            }
        ], {
            "enabled": False,
            "auto_enabled": False,
            "dry_run": True,
            "torznab_sources_json": "[]",
            "guangya_parent_id": "",
            "timeout": 12,
        }

    @eventmanager.register(EventType.SubscribeAdded)
    def on_subscribe_added(self, event: Event = None) -> None:
        """监听新增订阅；所有异常均吞掉并放行 MoviePilot 原生链路。"""
        if not self._enabled or not self._auto_enabled or not event or not event.event_data:
            return
        data = event.event_data or {}
        sid = str(data.get("subscribe_id") or "")
        if not sid:
            return
        with self._lock:
            if sid in self._inflight:
                logger.info("【磁力优先订阅】订阅 %s 已在处理中，跳过重复触发", sid)
                return
            self._inflight.add(sid)
        threading.Thread(target=self._safe_process_subscription, args=(sid, data), daemon=True,
                         name=f"magnet-priority-{sid}").start()

    def _safe_process_subscription(self, sid: str, event_data: dict) -> None:
        try:
            self._process_subscription(sid, event_data)
        except Exception as err:
            logger.exception("【磁力优先订阅】订阅 %s 处理异常，已放行 MoviePilot 原生链路: %s", sid, err)
            self._record(sid=sid, status="fallback", message=str(err))
        finally:
            with self._lock:
                self._inflight.discard(sid)

    def _process_subscription(self, sid: str, event_data: dict) -> None:
        subscribe = None
        try:
            subscribe = SubscribeOper().get(int(sid))
        except Exception as err:
            logger.warning("【磁力优先订阅】读取订阅 %s 失败: %s", sid, err)
        mediainfo = event_data.get("mediainfo") or {}
        title = str(getattr(subscribe, "name", None) or mediainfo.get("title") or "").strip()
        if not title:
            raise RuntimeError("订阅缺少可搜索标题")
        season = getattr(subscribe, "season", None)
        tmdb_id = mediainfo.get("tmdb_id") or mediainfo.get("tmdbid")
        missing: List[int] = []
        if subscribe and getattr(subscribe, "type", None) == MediaType.TV.value:
            start = int(getattr(subscribe, "start_episode", None) or 1)
            total = int(getattr(subscribe, "total_episode", None) or 0)
            downloaded = {int(x) for x in (getattr(subscribe, "note", None) or []) if str(x).isdigit()}
            if total >= start:
                missing = [x for x in range(start, total + 1) if x not in downloaded]
        results = self._search_all(title=title, season=season, tmdb_id=tmdb_id,
                                   episode=(missing[0] if missing else None))
        selected = select_best(results, target_season=season, missing_episodes=missing)
        if not selected:
            logger.info("【磁力优先订阅】%s 未找到符合中文字幕/季集规则的磁力，放行 MoviePilot", title)
            self._record(sid=sid, status="fallback", message="无合格磁力")
            return
        logger.info("【磁力优先订阅】选中候选: %s | %s | score=%s", selected.title, selected.source, selected.score)
        if self._dry_run:
            self._record(sid=sid, status="dry-run", message=selected.title)
            logger.info("【磁力优先订阅】安全测试模式，不创建光鸭离线任务")
            return
        if not self._guangya_parent_id:
            raise RuntimeError("未配置光鸭目标目录 fileId")
        client = self._build_guangya_client()
        resolved = client.resolve_magnet(selected.magnet)
        res_type = int(resolved.get("resType") or 0)
        if res_type <= 0:
            raise GuangYaOfflineError(f"光鸭无法解析磁力: resType={res_type}")
        task_id = client.create_task(selected.magnet, self._guangya_parent_id, title)
        if not task_id:
            raise GuangYaOfflineError("光鸭未返回 taskId")
        self._record(sid=sid, status="submitted", message=f"{selected.title} task={task_id}")
        logger.info("【磁力优先订阅】光鸭离线任务创建成功: %s task_id=%s", title, task_id)
        # beta1 intentionally does NOT suppress MoviePilot native search/download yet.
        # Production takeover will only be enabled after real-world task and fallback verification.

    def _parse_sources(self) -> List[TorznabSource]:
        try:
            raw = json.loads(self._torznab_sources_json or "[]")
        except Exception as err:
            raise RuntimeError(f"Torznab JSON 配置无效: {err}") from err
        if not isinstance(raw, list):
            raise RuntimeError("Torznab JSON 必须是数组")
        sources: List[TorznabSource] = []
        for idx, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            sources.append(TorznabSource(
                name=str(item.get("name") or f"source-{idx + 1}"),
                url=url,
                api_key=str(item.get("api_key") or item.get("apikey") or ""),
                timeout=int(item.get("timeout") or self._timeout),
            ))
        return sources

    def _search_all(self, title: str, season: Optional[int] = None, episode: Optional[int] = None,
                    tmdb_id: Optional[int] = None) -> List[MagnetResult]:
        results: List[MagnetResult] = []
        sources = self._parse_sources()
        if not sources:
            logger.warning("【磁力优先订阅】没有配置 Torznab 搜索源")
            return results
        for source in sources:
            try:
                current = search_torznab(source, title, season=season, episode=episode, tmdb_id=tmdb_id)
                results.extend(current)
                logger.info("【磁力优先订阅】【%s】返回 %s 个有效磁力", source.name, len(current))
            except TorznabError as err:
                logger.warning("【磁力优先订阅】【%s】搜索失败，继续其他源: %s", source.name, err)
            except Exception as err:
                logger.warning("【磁力优先订阅】【%s】异常，继续其他源: %s", source.name, err)
        return results

    def _build_guangya_client(self) -> GuangYaOfflineClient:
        config = PluginManager().get_plugin_config("ShukGuangYaDisk") or {}
        access_token = str(config.get("access_token") or "").strip()
        refresh_token = str(config.get("refresh_token") or "").strip()
        device_id = str(config.get("device_id") or "").strip()
        if not access_token or not refresh_token or not device_id:
            raise GuangYaOfflineError("光鸭云盘助手未登录或缺少 access_token/refresh_token/device_id")
        return GuangYaOfflineClient(GuangYaOfflineConfig(
            access_token=access_token,
            refresh_token=refresh_token,
            device_id=device_id,
            timeout=max(self._timeout, 10),
        ))

    def _record(self, sid: str, status: str, message: str) -> None:
        self._records.append({"subscribe_id": sid, "status": status, "message": str(message)[:500]})
        self._records = self._records[-100:]
        self.save_data("records", self._records)
