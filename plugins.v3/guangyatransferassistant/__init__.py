"""光鸭转存助手 v1.9.0 运行入口。

v1.9.0 在 v1.8.0 光鸭原生 Magnet/ED2K 云添加之上增加 ResourceGroup 决策层：
同一频道消息中的光鸭分享、Magnet、ED2K 作为同一资源的候选方式；先按 MoviePilot
真实缺集确定目标，再按“光鸭直接转存 > Magnet > ED2K”唯一执行，并使用统一高置信
Episode Resolver 做文件级拆包。无法可靠识别集号时不整包误存。

routing_v170 保留全入口 search 硬分流与消息直订，experience_v170 增加非阻塞后台检查、
消息管理、自检、原因诊断和路线崩溃恢复；reliability_v170 负责高频并发合并、热重载
唯一实例所有权以及频道源故障缓存降级/自动恢复；runtime_v170 负责宿主调度器最终非阻塞
分流、旧实例失效和诊断校正；本层保留 MoviePilot RSS/缓存匹配链最终下载断路器。
"""

from __future__ import annotations

import functools
import inspect
import time
import weakref
from typing import Any, Optional

from app.chain.subscribe import SubscribeChain
from app.schemas.types import EventType
from app.sdk.events import Event, eventmanager

from . import legacy as _legacy_module
from .channel_sources_v190 import install_channel_multisource_compat
from .episode_compat_v171 import collapse_unparsed_failure_notice, install_episode_filename_compat
from .experience_v170 import GuangYaExperienceMixin
from .multisource_v180 import GuangYaMultiSourceMixin
from .offline_safety_v180 import GuangYaOfflineSafetyMixin
from .page_auth_v172 import force_bear_auth, strip_page_api_secrets
from .reliability_v170 import GuangYaReliabilityMixin
from .resource_planner_v190 import GuangYaResourcePlannerMixin
from .runtime_v170 import GuangYaRuntimeFinalizerMixin
from .routing_v170 import GuangYaTransferAssistant as _RoutingV170Assistant


# legacy.py 保留成熟转存状态机；以热重载安全方式补充弱命名与多来源频道消息。
install_episode_filename_compat(_legacy_module)
install_channel_multisource_compat(_legacy_module)


class GuangYaTransferAssistant(
    GuangYaResourcePlannerMixin,
    GuangYaOfflineSafetyMixin,
    GuangYaMultiSourceMixin,
    GuangYaRuntimeFinalizerMixin,
    GuangYaReliabilityMixin,
    GuangYaExperienceMixin,
    _RoutingV170Assistant,
):
    """完整硬分流 + ResourceGroup 决策 + 光鸭原生多来源云添加运行时。"""

    plugin_version = "1.9.0"
    build_id = "20260901-r2"

    def get_api(self):
        """统一 Bearer 鉴权，并为状态页按钮安装非阻塞/标准响应适配。"""
        return force_bear_auth(super().get_api())

    @staticmethod
    def _normalize_page_api_auth(node: Any) -> None:
        """状态页按钮只传业务参数，不再向前端暴露或依赖 API_TOKEN。"""
        strip_page_api_secrets(node)

    def post_message(self, *args, **kwargs):
        """发送前合并同一通知里的重复“无法解析集号”诊断，避免同批文件重复告警。"""
        if str(kwargs.get("title") or "") == "⚠️ 光鸭转存失败" and kwargs.get("text"):
            kwargs["text"] = collapse_unparsed_failure_notice(kwargs.get("text"))
        return super().post_message(*args, **kwargs)

    @eventmanager.register(EventType.PluginAction)
    def experience_action_event_handler(self, event: Event) -> None:
        """把体验层消息 action 绑定到真实插件类，避免 mixin 事件处理器无法被 V3 resolver 解析。"""
        return super().experience_action_event_handler(event)

    def _schedule_pending_route_recovery(self, token: str) -> None:
        """进程重启后重新挂起未确认的路线写盘，不把旧进程的 scheduled 标记当成活定时器。"""
        token = str(token or "")
        if not token:
            return
        if str(getattr(self, "_route_recovery_runtime_token", "") or "") == token:
            return
        marker = dict(self.get_data("route_recovery_marker") or {})
        if (
            str(marker.get("token") or "") == token
            and str(marker.get("state") or "") == "scheduled"
        ):
            marker["state"] = "interrupted"
            marker["interrupted_at"] = time.time()
            self.save_data("route_recovery_marker", marker)
        self._route_recovery_runtime_token = token
        return super()._schedule_pending_route_recovery(token)

    def _install_search_guard(self) -> None:
        super()._install_search_guard()
        self._install_match_guard()
        self._install_download_circuit_breaker()

    def _install_match_guard(self) -> None:
        """当所有可匹配订阅均为光鸭路线时，RSS 缓存匹配整轮直接跳过。"""
        current = SubscribeChain.match
        if getattr(current, "_guangya_match_guard", False):
            current._guangya_plugin_ref = weakref.ref(self)
            self._record_route_health(match_guard=True)
            return
        original = current

        @functools.wraps(original)
        def guarded_match(chain_self, torrents, progress_callback=None):
            plugin_ref = getattr(guarded_match, "_guangya_plugin_ref", None)
            plugin = plugin_ref() if callable(plugin_ref) else None
            if not plugin or not plugin._enabled:
                return original(chain_self, torrents, progress_callback=progress_callback)

            try:
                active = list(plugin._list_subscriptions("R") or [])
                if active and all(plugin._is_guangya_route(item) for item in active):
                    plugin._plugin_log(
                        "INFO",
                        "【光鸭转存助手】【RSS硬分流】当前可匹配订阅全部为光鸭路线，跳过 MoviePilot 本地资源匹配/下载链",
                    )
                    plugin._record_route_health(
                        last_rss_blocked_at=plugin._now_text(),
                        last_rss_blocked_count=len(active),
                        match_guard=True,
                    )
                    if progress_callback:
                        progress_callback(value=100, text="固定转存订阅已由光鸭接管，跳过原生 RSS 匹配")
                    return None
            except Exception as err:
                plugin._plugin_log("WARNING", "【光鸭转存助手】【RSS硬分流】前置判断失败，继续执行并由下载断路器兜底：%s", err)
            return original(chain_self, torrents, progress_callback=progress_callback)

        guarded_match._guangya_match_guard = True
        guarded_match._guangya_original_match = original
        guarded_match._guangya_plugin_ref = weakref.ref(self)
        SubscribeChain.match = guarded_match
        self._record_route_health(match_guard=True)
        self._plugin_log("INFO", "【光鸭转存助手】【RSS硬分流】已接管 SubscribeChain.match；全光鸭路线时跳过原生 RSS 匹配")

    def _install_download_circuit_breaker(self) -> None:
        """在订阅最终提交 DownloadChain 前做第二道硬门禁，混合路线也不会误下载。"""
        method_name = "_SubscribeChain__download_best_version_with_full_pack_first"
        current = getattr(SubscribeChain, method_name, None)
        if not current:
            self._plugin_log("WARNING", "【光鸭转存助手】【下载断路器】当前 MoviePilot 未找到订阅下载提交方法；search 硬分流仍有效")
            self._record_route_health(download_guard=False)
            return
        if getattr(current, "_guangya_download_guard", False):
            current._guangya_plugin_ref = weakref.ref(self)
            self._record_route_health(download_guard=True)
            return

        original = current
        signature = inspect.signature(original)

        @functools.wraps(original)
        def guarded_download(chain_self, *args, **kwargs):
            plugin_ref = getattr(guarded_download, "_guangya_plugin_ref", None)
            plugin = plugin_ref() if callable(plugin_ref) else None
            if not plugin or not plugin._enabled:
                return original(chain_self, *args, **kwargs)

            subscribe = None
            no_exists = None
            try:
                bound = signature.bind_partial(chain_self, *args, **kwargs)
                subscribe = bound.arguments.get("subscribe")
                no_exists = bound.arguments.get("no_exists")
            except Exception:
                if len(args) >= 3:
                    no_exists = args[1]
                    subscribe = args[2]

            if subscribe is not None and plugin._is_guangya_route(subscribe):
                sid = int(getattr(subscribe, "id", 0) or 0)
                plugin._plugin_log(
                    "WARNING",
                    "【光鸭转存助手】【下载断路器】阻断 MoviePilot 原生下载提交 #%s %s；固定转存路线只允许光鸭转存/原生云添加",
                    sid,
                    getattr(subscribe, "name", ""),
                )
                plugin._record_route_health(
                    last_download_blocked_at=plugin._now_text(),
                    last_download_blocked_id=sid,
                    last_download_blocked_name=str(getattr(subscribe, "name", "") or ""),
                    download_guard=True,
                )
                return [], no_exists or {}

            return original(chain_self, *args, **kwargs)

        guarded_download._guangya_download_guard = True
        guarded_download._guangya_original_download = original
        guarded_download._guangya_plugin_ref = weakref.ref(self)
        setattr(SubscribeChain, method_name, guarded_download)
        self._record_route_health(download_guard=True)
        self._plugin_log("INFO", "【光鸭转存助手】【下载断路器】已安装原生订阅最终下载门禁；混合普通/光鸭路线也不会误下")

    def _restore_match_guard(self) -> None:
        current = SubscribeChain.match
        if not getattr(current, "_guangya_match_guard", False):
            return
        plugin_ref = getattr(current, "_guangya_plugin_ref", None)
        owner = plugin_ref() if callable(plugin_ref) else None
        if owner is not self:
            return
        original = getattr(current, "_guangya_original_match", None)
        if original:
            SubscribeChain.match = original
        self._record_route_health(match_guard=False)

    def _restore_download_circuit_breaker(self) -> None:
        method_name = "_SubscribeChain__download_best_version_with_full_pack_first"
        current = getattr(SubscribeChain, method_name, None)
        if not current or not getattr(current, "_guangya_download_guard", False):
            return
        plugin_ref = getattr(current, "_guangya_plugin_ref", None)
        owner = plugin_ref() if callable(plugin_ref) else None
        if owner is not self:
            return
        original = getattr(current, "_guangya_original_download", None)
        if original:
            setattr(SubscribeChain, method_name, original)
        self._record_route_health(download_guard=False)

    def _restore_search_guard(self) -> None:
        self._restore_match_guard()
        self._restore_download_circuit_breaker()
        super()._restore_search_guard()

    def _native_guard_status(self) -> tuple[bool, bool]:
        match_guard = bool(getattr(SubscribeChain.match, "_guangya_match_guard", False))
        download_method = getattr(SubscribeChain, "_SubscribeChain__download_best_version_with_full_pack_first", None)
        download_guard = bool(download_method and getattr(download_method, "_guangya_download_guard", False))
        return match_guard, download_guard

    def get_page(self):
        pages = super().get_page() or []
        strip_page_api_secrets(pages)
        match_guard, download_guard = self._native_guard_status()

        health_card = None
        for page in pages:
            if not isinstance(page, dict):
                continue
            props = page.get("props") or {}
            if str(props.get("title") or "") == "固定分流路由健康":
                health_card = page
                break
        if health_card is None and pages and isinstance(pages[0], dict):
            health_card = pages[0]

        if health_card is not None:
            props = health_card.get("props") or {}
            old_text = str(props.get("text") or "")
            props["text"] = (
                f"{old_text} · RSS匹配门禁：{'已接管' if match_guard else '未接管'}"
                f" · 最终下载断路器：{'已接管' if download_guard else '未接管'}"
                " · 资源决策：光鸭分享 > Magnet > ED2K · Magnet/ED2K：光鸭原生云添加"
            )
            if not (match_guard and download_guard):
                props["type"] = "warning"
            health_card["props"] = props
        return pages


__all__ = ["GuangYaTransferAssistant"]
