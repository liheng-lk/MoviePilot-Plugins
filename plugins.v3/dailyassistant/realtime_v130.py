"""每日助手 v1.3.0：实时发现后直接创建 MoviePilot 订阅，不经过任何转存链路。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.chain.media import MediaChain
from app.chain.subscribe import SubscribeChain
from app.sdk.logging import logger
from app.sdk.media import MetaInfo
from app.schemas.types import MediaSource, MediaType


class DailyAssistantRealtimeV130Mixin:
    """v1.3.0 实时订阅层：高频增量刷新 + MoviePilot 原生订阅。"""

    plugin_version = "1.3.0"
    _realtime_enabled = True
    _realtime_minutes = 10
    _auto_subscribe = True

    # 默认只自动处理“新片/正在上映/即将上映/近期剧集/平台实时热播”一类来源。
    _realtime_default_sources = {
        "douban_showing",
        "douban_coming",
        "douban_new_movies",
        "douban_tv_recent",
        "maoyan_movie",
        "maoyan_tv",
        "tencent_hot",
        "tencent_tv",
        "tmdb_trending",
    }

    def init_plugin(self, config: Optional[dict] = None) -> None:
        config = config or {}
        super().init_plugin(config)
        self._realtime_enabled = bool(config.get("realtime_enabled", True))
        try:
            minutes = int(config.get("realtime_minutes", 10))
        except (TypeError, ValueError):
            minutes = 10
        self._realtime_minutes = max(5, min(minutes, 60))
        self._auto_subscribe = bool(config.get("auto_subscribe", True))
        # v1.3.0 不再调用 GYSub/光鸭；保留旧字段仅为兼容历史配置。
        self._auto_gysub = False

    def get_service(self) -> List[Dict[str, Any]]:
        services = list(super().get_service() or [])
        # 移除仅为 GYSub pending 服务的旧对账任务。
        services = [item for item in services if item.get("id") != "DailyAssistantGYSubReconcile"]
        if self._enabled and self._realtime_enabled:
            services.append({
                "id": "DailyAssistantRealtime",
                "name": "每日助手实时发现",
                "trigger": "interval",
                "func": self.refresh,
                "kwargs": {"minutes": self._realtime_minutes},
                "func_kwargs": {"manual": False},
            })
        return services

    def _save_config(self, *, onlyonce: Optional[bool] = None) -> None:
        self.update_config({
            "enabled": self._enabled,
            "cron": self._cron,
            "onlyonce": self._onlyonce if onlyonce is None else onlyonce,
            "proxy": self._proxy,
            "rank_limit": self._rank_limit,
            "vote_min": self._vote_min,
            "auto_gysub": False,
            "auto_subscribe": self._auto_subscribe,
            "realtime_enabled": self._realtime_enabled,
            "realtime_minutes": self._realtime_minutes,
            "source_keys": self._source_keys,
            "auto_source_keys": self._auto_source_keys,
        })

    def _direct_subscribe(self, row: Dict[str, Any], *, source: str = "每日助手实时订阅") -> Dict[str, Any]:
        """直接走 MoviePilot SubscribeChain.add，不广播插件事件，也不触发任何转存。"""
        tmdb_id = str(row.get("tmdb_id") or "").strip()
        media_type = str(row.get("media_type") or "tv").lower()
        if not tmdb_id or media_type not in {"movie", "tv"}:
            return {"success": False, "status": "rejected", "message": "缺少 TMDB 精确身份"}

        mtype = MediaType.MOVIE if media_type == "movie" else MediaType.TV
        try:
            info = MediaChain().recognize_media(
                mtype=mtype,
                media_source=MediaSource.TMDB,
                media_id=tmdb_id,
                cache=False,
            )
        except TypeError:
            info = MediaChain().recognize_media(
                mtype=mtype,
                media_source=MediaSource.TMDB,
                media_id=tmdb_id,
            )
        except Exception as err:
            logger.warning("【每日助手】【实时订阅】识别失败 TMDB=%s: %s", tmdb_id, err)
            return {"success": False, "status": "failed", "message": str(err)}
        if not info:
            return {"success": False, "status": "failed", "message": "MoviePilot 未识别到媒体"}

        meta = MetaInfo(str(row.get("title") or getattr(info, "title", "") or ""))
        meta.type = mtype
        season = None
        if mtype == MediaType.TV:
            try:
                season = int(row.get("season") or getattr(info, "season", None) or 1)
            except (TypeError, ValueError):
                season = 1
            season = max(1, min(season, 99))
            meta.begin_season = season

        chain = SubscribeChain()
        try:
            if chain.exists(mediainfo=info, meta=meta):
                return {"success": True, "status": "exists", "message": f"已订阅：{getattr(info, 'title', row.get('title'))}"}
        except Exception as err:
            logger.debug("【每日助手】【实时订阅】订阅存在性检查失败 %s: %s", tmdb_id, err)

        media_source = getattr(info, "media_source", None) or MediaSource.TMDB
        media_id = getattr(info, "media_id", None) or getattr(info, "tmdb_id", None) or tmdb_id
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
            logger.error("【每日助手】【实时订阅】创建订阅失败 %s(%s): %s", row.get("title"), tmdb_id, err)
            return {"success": False, "status": "failed", "message": str(err)}

        if sid:
            logger.info(
                "【每日助手】【实时订阅】创建成功：%s (%s) %s TMDB=%s source=%s",
                getattr(info, "title", None) or row.get("title"),
                getattr(info, "year", None) or row.get("year") or "-",
                f"S{season:02d}" if season else "MOVIE",
                tmdb_id,
                source,
            )
            return {"success": True, "status": "created", "id": sid, "message": "订阅创建成功"}
        return {"success": False, "status": "failed", "message": err_msg or "订阅创建失败"}

    def refresh(self, manual: bool = False) -> Dict[str, Any]:
        # 强制关闭旧 GYSub 自动分发，先复用既有多来源发现、TMDB 识别、媒体库过滤和缓存能力。
        old_auto = getattr(self, "_auto_gysub", False)
        self._auto_gysub = False
        try:
            result = super().refresh(manual=manual)
        finally:
            self._auto_gysub = False

        payload = (result or {}).get("data") or {}
        candidates = payload.get("candidates") or []
        created = 0
        existed = 0
        failed = 0
        skipped = 0

        if self._auto_subscribe:
            configured = set(self._auto_source_keys or [])
            allowed = configured or set(self._realtime_default_sources)
            for row in candidates:
                if not row.get("tmdb_id"):
                    skipped += 1
                    continue
                fresh_sources = set(row.get("fresh_source_keys") or [row.get("source_key")])
                fresh_sources.discard(None)
                if not allowed.intersection(fresh_sources):
                    continue
                sub = self._direct_subscribe(row)
                status = str(sub.get("status") or "")
                if sub.get("success") and status == "created":
                    created += 1
                elif sub.get("success") and status == "exists":
                    existed += 1
                elif not sub.get("success"):
                    failed += 1

        payload["direct_subscribe"] = {
            "created": created,
            "exists": existed,
            "failed": failed,
            "skipped": skipped,
            "interval_minutes": self._realtime_minutes,
        }
        payload["auto_requested"] = created
        payload["auto_confirmed"] = created + existed
        payload["auto_success"] = created + existed
        payload["auto_failed"] = failed
        self.save_data("dailyassistant_candidates", payload)

        logger.info(
            "【每日助手】【实时发现】刷新完成：候选=%s 新增订阅=%s 已订阅=%s 失败=%s 周期=%s分钟",
            len(candidates), created, existed, failed, self._realtime_minutes,
        )
        return {
            "success": True,
            "data": payload,
            "message": f"发现 {len(candidates)} 个候选，新增订阅 {created} 个，已存在 {existed} 个",
        }

    def api_gysub(self, index: int = 0, batch_id: str = "") -> Dict[str, Any]:
        """兼容旧 API 路径，但动作已经变为直接创建 MoviePilot 订阅。"""
        payload = self.get_data("dailyassistant_candidates") or {}
        if batch_id and str(payload.get("batch_id") or "") != str(batch_id):
            return {"success": False, "message": "候选批次已刷新，请重新打开页面"}
        candidates = payload.get("candidates") or []
        try:
            row = next(item for item in candidates if int(item.get("index") or 0) == int(index))
        except (StopIteration, TypeError, ValueError):
            return {"success": False, "message": "候选序号不存在"}
        return self._direct_subscribe(dict(row), source="每日助手手动订阅")

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        form, defaults = super().get_form()
        defaults["auto_gysub"] = False
        defaults["auto_subscribe"] = True
        defaults["realtime_enabled"] = True
        defaults["realtime_minutes"] = 10

        def rewrite(node: Any) -> None:
            if isinstance(node, dict):
                props = node.get("props")
                if isinstance(props, dict):
                    if props.get("model") == "auto_gysub":
                        props["model"] = "auto_subscribe"
                        props["label"] = "自动订阅最新影视"
                    if props.get("model") == "auto_source_keys":
                        props["label"] = "允许自动订阅的来源"
                        props["hint"] = "为空时使用内置“最新影视”安全来源；只会创建 MoviePilot 订阅，不触发转存。"
                    for key, value in list(props.items()):
                        if isinstance(value, str):
                            props[key] = value.replace("GYSub", "MoviePilot订阅")
                for value in node.values():
                    rewrite(value)
            elif isinstance(node, list):
                for value in node:
                    rewrite(value)

        rewrite(form)
        try:
            content = form[0]["content"]
            content.insert(1, {
                "component": "VRow",
                "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                        {"component": "VSwitch", "props": {"model": "realtime_enabled", "label": "启用实时发现"}}
                    ]},
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                        {"component": "VTextField", "props": {
                            "model": "realtime_minutes",
                            "label": "实时检查间隔（分钟）",
                            "hint": "建议 5-15 分钟；最小 5 分钟",
                            "persistentHint": True,
                        }}
                    ]},
                ],
            })
        except Exception:
            pass
        return form, defaults

    def get_page(self) -> List[dict]:
        page = super().get_page()

        def rewrite(node: Any) -> None:
            if isinstance(node, dict):
                for key, value in list(node.items()):
                    if isinstance(value, str):
                        node[key] = (
                            value.replace("加入 GYSub", "立即订阅")
                            .replace("GYSub待确认", "实时订阅")
                            .replace("GYSub", "MoviePilot订阅")
                        )
                    else:
                        rewrite(value)
            elif isinstance(node, list):
                for value in node:
                    rewrite(value)

        rewrite(page)
        return page


__all__ = ["DailyAssistantRealtimeV130Mixin"]
