"""光鸭转存助手最终运行入口（2.0.13 / r97）。

本文件只负责 MoviePilot 插件组合、顶层宿主事件桥和少量最终兼容护栏；
领域业务应进入 ARCHITECTURE.md 指定的 Authority，不在这里继续堆版本补丁。

固定资源优先级：
    观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K

运行硬边界：
- managed subscription 不回落 MoviePilot 原生下载；
- Magnet/ED2K 继续使用光鸭原生 cloudcollection，不经过 MoviePilot 下载器；
- 搜索/频道标题只负责发现，真实 payload + 身份 + Episode Fence 才允许提交；
- API accepted != 文件落盘 != 媒体完成，完成必须回到真实媒体库缺口复核。

维护入口：
- README.md：使用与排障
- ARCHITECTURE.md：Authority / MRO / 状态机
- DEVELOPMENT.md：Fork、开发、测试、PR
- CHANGELOG.md：完整版本历史
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
from .channel_title_rename_v11226 import install_channel_title_rename_v11226
from .channel_ui_v1101 import GuangYaChannelUiV1101Mixin
from .config_ui_v1100 import GuangYaConfigUiV1100Mixin
from .console_ui_v1100 import GuangYaConsoleUiV1100Mixin
from .content_resilience_v1105 import GuangYaContentResilienceV1105Mixin
from .diagnostics_v1100 import GuangYaDiagnosticsV1100Mixin
from .dispatch_policy_v1125 import GuangYaDispatchPolicyV1125Mixin
from .dispatch_policy_final_v1125 import GuangYaDispatchPolicyFinalV1125Mixin
from .episode_target_v210 import GuangYaEpisodeTargetV210Mixin
from .episode_runtime_v211 import GuangYaEpisodeRuntimeV211Mixin
from .fast_recall_v1126 import GuangYaFastRecallV1126Mixin
from .movie_identity_v1129 import GuangYaMovieIdentityV1129Mixin
from .resource_gate_v1127 import GuangYaResourceGateV1127Mixin
from .provider_reliability_v1100 import GuangYaProviderReliabilityV1100Mixin
from .xunlei_reliability_v1100 import GuangYaXunleiReliabilityV1100Mixin
from .config_ui_v192 import GuangYaConfigUiMixin
from .episode_compat_v171 import collapse_unparsed_failure_notice, install_episode_filename_compat
from .experience_v170 import GuangYaExperienceMixin
from .gying_autologin_v1109 import GuangYaGyingAutoLoginV1109Mixin
from .gying_failover_v193 import GuangYaGyingFailoverMixin
from .gying_hardening_v193 import GuangYaGyingHardeningMixin
from .gying_observability_v1104 import GuangYaGyingObservabilityV1104Mixin
from .gying_protocol_v1106 import GuangYaGyingProtocolV1106Mixin
from .gying_recall_guard_v1125 import GuangYaGyingRecallGuardV1125Mixin
from .gying_runtime_v193 import GuangYaGyingRuntimeMixin
from .gying_search_truth_v11223 import GuangYaGyingSearchTruthV11223Mixin
from .gying_transport_v1108 import GuangYaGyingTransportV1108Mixin
from .multisource_v180 import GuangYaMultiSourceMixin
from .media_identity_guard_v1111 import GuangYaMediaIdentityGuardV1111Mixin
from .page_perf_v1123 import GuangYaPagePerfV1123Mixin
from .production_safety_v208 import GuangYaProductionSafetyV208Mixin
from .calendar_driven_v209 import GuangYaCalendarDrivenV209Mixin
from .foundation_ops_v209 import GuangYaFoundationOpsV209Mixin
from .pow_singleflight_v209 import GuangYaPowSingleflightV209Mixin
from .airing_weekly_v1121 import GuangYaAiringWeeklyV1121Mixin
from .airing_scheduler_v1120 import GuangYaAiringSchedulerV1120Mixin
from .airing_ui_v1120 import GuangYaAiringUiV1120Mixin
from .page_auth_v172 import force_bear_auth, strip_page_api_secrets
from .planner_safety_v190 import GuangYaPlannerSafetyMixin
from .provider_sources_v192 import GuangYaProviderSourcesMixin
from .receipt_completion_v1124 import GuangYaReceiptCompletionV1124Mixin
from .release_v1110 import GuangYaReleaseV1110Mixin
from .reliability_v170 import GuangYaReliabilityMixin
from .resource_planner_v190 import GuangYaResourcePlannerMixin
from .runtime_v170 import GuangYaRuntimeFinalizerMixin
from .routing_v170 import GuangYaTransferAssistant as _RoutingV170Assistant
from .stability_v1106 import GuangYaStabilityV1106Mixin
from .viewing_logging_v1113 import GuangYaViewingLoggingV1113Mixin
from .xunlei_flash_v193 import GuangYaXunleiFlashMixin
from .xunlei_hardening_v193 import GuangYaXunleiHardeningMixin


install_episode_filename_compat(_legacy_module)
install_channel_multisource_compat(_legacy_module)
install_channel_title_rename_v11226(_legacy_module)


class GuangYaTransferAssistant(
    GuangYaFoundationOpsV209Mixin,
    GuangYaEpisodeRuntimeV211Mixin,
    GuangYaEpisodeTargetV210Mixin,
    GuangYaCalendarDrivenV209Mixin,
    GuangYaPowSingleflightV209Mixin,
    GuangYaProductionSafetyV208Mixin,
    GuangYaPagePerfV1123Mixin,
    GuangYaMovieIdentityV1129Mixin,
    GuangYaResourceGateV1127Mixin,
    GuangYaFastRecallV1126Mixin,
    GuangYaDispatchPolicyFinalV1125Mixin,
    GuangYaDispatchPolicyV1125Mixin,
    GuangYaAiringWeeklyV1121Mixin,
    GuangYaAiringSchedulerV1120Mixin,
    GuangYaMediaIdentityGuardV1111Mixin,
    GuangYaReleaseV1110Mixin,
    GuangYaReceiptCompletionV1124Mixin,
    GuangYaAiringUiV1120Mixin,
    GuangYaGyingAutoLoginV1109Mixin,
    GuangYaGyingTransportV1108Mixin,
    GuangYaStabilityV1106Mixin,
    GuangYaContentResilienceV1105Mixin,
    GuangYaGyingObservabilityV1104Mixin,
    GuangYaGyingSearchTruthV11223Mixin,
    GuangYaChannelUiV1101Mixin,
    GuangYaConfigUiV1100Mixin,
    GuangYaConsoleUiV1100Mixin,
    GuangYaDiagnosticsV1100Mixin,
    GuangYaProviderReliabilityV1100Mixin,
    GuangYaXunleiReliabilityV1100Mixin,
    GuangYaConfigUiMixin,
    GuangYaGyingRecallGuardV1125Mixin,
    GuangYaGyingHardeningMixin,
    GuangYaGyingFailoverMixin,
    GuangYaViewingLoggingV1113Mixin,
    GuangYaGyingProtocolV1106Mixin,
    GuangYaGyingRuntimeMixin,
    GuangYaXunleiHardeningMixin,
    GuangYaXunleiFlashMixin,
    GuangYaProviderSourcesMixin,
    GuangYaPlannerSafetyMixin,
    GuangYaResourcePlannerMixin,
    GuangYaMultiSourceMixin,
    GuangYaRuntimeFinalizerMixin,
    GuangYaReliabilityMixin,
    GuangYaExperienceMixin,
    _RoutingV170Assistant,
):
    """固定分流 + CloakBrowser 观影验证 + 观影自动云添加 + 迅雷秒传 + 原生云添加。"""

    plugin_version = "2.0.13"
    build_id = "20260911-r97"

    def get_api(self):
        """统一 Bearer 鉴权，并为页面按钮安装标准响应适配。"""
        return force_bear_auth(super().get_api())

    @staticmethod
    def _normalize_page_api_auth(node: Any) -> None:
        strip_page_api_secrets(node)

    def post_message(self, *args, **kwargs):
        title = str(kwargs.get("title") or "")
        text = str(kwargs.get("text") or "")
        # Hard ban old misleading batch formats (may still appear from stale mixins/helpers).
        if (
            "失败/待补搜" in text
            or "光鸭转存检查完成" in title
            or title.strip() == "⚠️ 光鸭转存检查完成"
            or ("本轮处理：" in text and "失败" in text and "待补搜" in text)
        ):
            try:
                self._plugin_log(
                    "WARNING",
                    "【通知护栏】拦截旧格式通知 title=%s text=%s instance=%s",
                    title[:80],
                    text[:120],
                    getattr(self, "_instance_id_v209", "-"),
                )
            except Exception:
                pass
            return None
        if title == "⚠️ 光鸭转存失败" and kwargs.get("text"):
            kwargs["text"] = collapse_unparsed_failure_notice(kwargs.get("text"))
        return super().post_message(*args, **kwargs)

    @eventmanager.register(EventType.PluginAction)
    def action_event_handler(self, event: Event) -> None:
        """把 routing 层的 /gysub 等 PluginAction 显式绑定到最终插件类。"""
        event_data = event.event_data or {}
        action = str(event_data.get("action") or "")
        try:
            return super().action_event_handler(event)
        except Exception as err:
            self._plugin_log("EXCEPTION", "【光鸭转存助手】【消息命令v1.12.8】action=%s 处理异常：%s", action, err)
            if action in {"guangya_direct_subscribe", "guangya_route_status", "guangya_release_native"}:
                self._post_command(event_data, "光鸭命令处理失败", str(err)[:500])
            return None

    @eventmanager.register(EventType.PluginAction)
    def experience_action_event_handler(self, event: Event) -> None:
        """把 experience mixin 的 PluginAction 处理器绑定到真正插件类。"""
        return super().experience_action_event_handler(event)

    def _schedule_pending_route_recovery(self, token: str) -> None:
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
                owned = getattr(plugin, "_is_managed_subscription", None)
                if not callable(owned):
                    owned = plugin._is_guangya_route
                managed = [item for item in active if owned(item)]
                native = [item for item in active if not owned(item)]
                plugin._plugin_log(
                    "INFO",
                    "【原生审计】【RSS】active=%s managed=%s native=%s decision=%s",
                    len(active),
                    ",".join(str(int(getattr(item, "id", 0) or 0)) for item in managed) or "-",
                    ",".join(str(int(getattr(item, "id", 0) or 0)) for item in native) or "-",
                    "skip_native" if active and not native else ("mixed_native" if managed and native else "native"),
                )
                if active and not native:
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
                if managed and native:
                    plugin._plugin_log(
                        "INFO",
                        "【原生审计】【RSS】混合路线：managed=%s 仍由下载断路器阻断；native=%s 继续 Match",
                        ",".join(str(int(getattr(item, "id", 0) or 0)) for item in managed),
                        ",".join(str(int(getattr(item, "id", 0) or 0)) for item in native),
                    )
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
        """安装订阅最终下载断路器，混合路线也不能误进 MoviePilot 本地下载。"""
        method_name = "_SubscribeChain__download_best_version_with_full_pack_first"
        current = getattr(SubscribeChain, method_name, None)
        if not current:
            self._plugin_log("WARNING", "【光鸭转存助手】【最终下载断路器】当前 MoviePilot 未找到订阅下载提交方法；search 硬分流仍有效")
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

            owned = getattr(plugin, "_is_managed_subscription", None)
            if not callable(owned):
                owned = plugin._is_guangya_route
            if subscribe is not None and owned(subscribe):
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
        return pages


__all__ = ["GuangYaTransferAssistant"]


def _unwrap_orphan_subscribe_chain_attr(
    target: Any,
    attr: str,
    *,
    guard_flag: str,
    original_attr: str,
    max_depth: int = 8,
) -> bool:
    """循环剥离无主 GuangYa wrapper，恢复到未安装补丁时的方法。"""
    restored = False
    for _ in range(max(1, int(max_depth))):
        current = getattr(target, attr, None)
        if current is None or not getattr(current, guard_flag, False):
            break
        plugin_ref = getattr(current, "_guangya_plugin_ref", None)
        owner = plugin_ref() if callable(plugin_ref) else None
        if owner is not None:
            break
        original = getattr(current, original_attr, None)
        if original is None or original is current:
            break
        setattr(target, attr, original)
        restored = True
    return restored


def _emergency_restore_subscribe_chain_patches() -> None:
    """清理失败插件加载留下的孤儿 SubscribeChain 补丁（含嵌套 wrapper）。"""
    try:
        _unwrap_orphan_subscribe_chain_attr(
            SubscribeChain,
            "search",
            guard_flag="_guangya_route_guard",
            original_attr="_guangya_original_search",
        )
    except Exception:
        pass
    try:
        _unwrap_orphan_subscribe_chain_attr(
            SubscribeChain,
            "match",
            guard_flag="_guangya_match_guard",
            original_attr="_guangya_original_match",
        )
    except Exception:
        pass
    try:
        method_name = "_SubscribeChain__download_best_version_with_full_pack_first"
        _unwrap_orphan_subscribe_chain_attr(
            SubscribeChain,
            method_name,
            guard_flag="_guangya_download_guard",
            original_attr="_guangya_original_download",
        )
    except Exception:
        pass


def _scrub_public_mixin_exports() -> None:
    """Phase 0 Loader 护栏：模块 globals 只保留最终插件类给 PluginLoader。

    MoviePilot 按插入顺序取第一个同时具备 init_plugin + plugin_name 的公开类。
    公开 Mixin 名会增加误选风险；类已进入 MRO 后可安全从 globals 移除。
    不改变业务行为。
    """
    for name, obj in list(globals().items()):
        if name.startswith("_") or name == "GuangYaTransferAssistant":
            continue
        if isinstance(obj, type) and name.endswith("Mixin"):
            globals().pop(name, None)


_emergency_restore_subscribe_chain_patches()
_scrub_public_mixin_exports()
