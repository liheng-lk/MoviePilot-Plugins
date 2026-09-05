"""光鸭转存助手 v1.12.15 运行入口。

v1.9.0 增加 ResourceGroup、缺集决策和高置信 Episode Resolver；
v1.9.1 重构紧凑状态页；v1.9.2 重新整理插件配置页，并补齐观影 GYING
地址/登录配置及通用 Magnet/ED2K 搜索 API；v1.9.3 把观影中的迅雷分享接入
光鸭 userres 秒传链路，并补齐观影多节点、浏览器 PoW 验证、真实登录/搜索/downurl 会话；
v1.10.23 完整生成迅雷 JSON，但只导入媒体库同步后仍缺失且高置信匹配的集数；拒绝无法识别的顺带文件；
v1.10.24 成功资源立即记账：剧集按成功集号立刻写入进度并阻止同集重复版本，电影首个正片成功即完成订阅；
同时增加跨来源集级终止栅栏：秒传/分享转存/Magnet/ED2K 共用已成功集与在途集，成功一集立即终止该集其它任务。
v1.11.2 补齐频道 ED2K 云添加：频道命中的 ED2K 单文件允许先 resolve，再用真实文件名/频道集号确认缺集并提交光鸭原生 cloudcollection。
v1.12.0 改为逐集上映日历驱动：普通后台只处理当前应播缺集，未来集等待更新窗口；每日全员补漏仍保留。
v1.12.1 新增周视图追剧日历和严格星期门禁：普通后台仅在对应更新日搜索，跨日欠集交给每日全员补漏兜底；电影不参与星期筛选。
v1.12.2 收口追剧三态与来源轮询：日历仅显示已入库/转存中/待补；频道缓存按最后可见时间续期；频道事件后继续观影常规轮询；新订阅缓存未命中时补一次频道现查；当天缺集按外部搜索冷却继续重试，跨日后由每日04:10全员补漏兜底。
v1.12.3 优化大订阅页面体验：数据页优先读取周快照并后台校准媒体库，7 天日期可点击/滑动查看对应剧集；配置页改为轻量搜索选择器，不再逐订阅计算进度或铺满 chips。
v1.12.4 修复实机交互：日期详情改为浏览器本地即时展开；固定接管订阅改为固定高度的单项搜索添加/取消管理器，不再随已选数量无限增长。
v1.12.5 完成 Push/Pull 调度收口：5 分钟频道 Push 只消费已到达资源；每小时 AiringDue 只处理今日到期且仍未覆盖的媒体，并按观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K 跑完整来源链；同媒体小时复查窗口固定 60 分钟；04:10 每日全员复核继续先频道、再对真实剩余缺口强制补漏；稳定星期、日历故障退避、并发 trigger 与跨来源终止栅栏同步收口。
v1.12.6 快速追更：当天应播 TV/动漫的 AiringDue 改为每 10 分钟唤醒并使用独立 10 分钟主动检索窗口；电影继续 60 分钟；命中、已入库或在途后立即退出快追。
v1.12.7 修复“已找到资源/缺集但未提交光鸭”：S02+ 季发行年份不再被系列首播年份误杀；GYING 已命中且真实分享顶层名/文件结构一致时允许合法别名桥接；拆包 needs_review 在证据变化或 6 小时后自动重评，并补齐拆包决策日志。
v1.12.8 修复 /gysub 消息入口：最终插件类显式注册 routing PluginAction 桥，不再依赖继承层隐式事件绑定；合法直订请求先即时回执，再执行 TMDB 识别和订阅创建，避免上游变慢时消息端表现为无响应。
v1.12.9 修复电影观影已命中但真实英文原名被媒体身份门禁误杀：仅按订阅精确 TMDB ID 从 MoviePilot MediaChain 补全官方 title/en_title/original_title 等可信别名；错误 TMDB/年份仍拒绝，不引入模糊电影匹配。
v1.12.10 修复同一迅雷分享被同媒体不同季重复消费：无季号整包先校验完整集号结构，成功后持久占用真实 share，同系列迅雷流程串行化；显式多季包仍由既有 planner 拆分。
v1.12.11 修复 /gycheck 只检查频道却未保证主动资源链的问题：人工立即检查先强刷并消费频道，频道仍未覆盖时以 force=True 立即执行观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K；人工操作绕过自动检索冷却，但继续保留媒体身份、年份、质量、Episode Fence、reservation/source claim 与 v1.12.10 迅雷跨季物理资源栅栏。
v1.12.12 修复 GYING 前置搜索未使用精确 TMDB 官方别名的问题：电影中文标题未命中当前媒体时，继续用同一 TMDB 身份与年份下的官方英文/原始标题搜索；无关卡片不再阻止降级，网络/认证失败仍硬停止；观影迅雷召回与 GYING Magnet/ED2K 共用该语义，不引入模糊匹配。
v1.12.13 修复媒体库已有剧集仍被迅雷秒传重复导入：TV 迅雷硬目标改为媒体库 missing 与成功事实/订阅 missing 的交集，并在 JSON batch import 前逐视频二次过滤；跨边界多集文件整文件拒绝，媒体库缺集事实读取失败时跳过迅雷但继续后续来源。
v1.12.14 统一核心资源链：频道/观影均支持光鸭分享、迅雷分享、Magnet、ED2K；TV/动漫按精确 TMDB 官方标题补召回；所有 TV 最终写盘收紧到 library missing ∩ logical/fact missing - reservation - other source claim，并对光鸭分享、迅雷、Magnet、ED2K 统一执行不可分割物理文件 episodes ⊆ allowed missing 与实际 payload 身份门禁。
v1.12.15 修复频道已有资源但未触发转存：既有订阅在严格 Telegram 游标 bootstrap、插件重启或一次性事件未形成时由 7 天缓存补偿；新增订阅固定先强刷全部配置频道、写入缓存后再匹配，若仍未命中且频道健康则按 history_pages 有界回溯当前游标之前的历史页，只补 cache、不修改 channel_cursors、不伪造新事件；所有频道路径均不主动访问 GYING、不消耗外部检索冷却，v1.12.14 的媒体身份、权威缺集与物理文件硬栅栏全部保持。

最终优先级：观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K。
后续 ResourceGroup 内部仍保持：光鸭直接转存 > Magnet > ED2K。
Magnet/ED2K 继续使用光鸭原生 cloudcollection，不经过 MoviePilot 下载器。
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
from .channel_ui_v1101 import GuangYaChannelUiV1101Mixin
from .config_ui_v1100 import GuangYaConfigUiV1100Mixin
from .console_ui_v1100 import GuangYaConsoleUiV1100Mixin
from .content_resilience_v1105 import GuangYaContentResilienceV1105Mixin
from .diagnostics_v1100 import GuangYaDiagnosticsV1100Mixin
from .dispatch_policy_v1125 import GuangYaDispatchPolicyV1125Mixin
from .dispatch_policy_final_v1125 import GuangYaDispatchPolicyFinalV1125Mixin
from .episode_fence_final_v1124 import GuangYaEpisodeFenceFinalV1124Mixin
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
from .gying_transport_v1108 import GuangYaGyingTransportV1108Mixin
from .multisource_v180 import GuangYaMultiSourceMixin
from .media_identity_guard_v1111 import GuangYaMediaIdentityGuardV1111Mixin
from .page_perf_v1123 import GuangYaPagePerfV1123Mixin
from .airing_weekly_v1121 import GuangYaAiringWeeklyV1121Mixin
from .airing_scheduler_v1120 import GuangYaAiringSchedulerV1120Mixin
from .airing_ui_v1120 import GuangYaAiringUiV1120Mixin
from .offline_safety_v180 import GuangYaOfflineSafetyMixin
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
from .status_hardening_v193 import GuangYaStatusHardeningMixin
from .viewing_logging_v1113 import GuangYaViewingLoggingV1113Mixin
from .xunlei_flash_v193 import GuangYaXunleiFlashMixin
from .xunlei_hardening_v193 import GuangYaXunleiHardeningMixin


install_episode_filename_compat(_legacy_module)
install_channel_multisource_compat(_legacy_module)


class GuangYaTransferAssistant(
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
    GuangYaEpisodeFenceFinalV1124Mixin,
    GuangYaReceiptCompletionV1124Mixin,
    GuangYaAiringUiV1120Mixin,
    GuangYaGyingAutoLoginV1109Mixin,
    GuangYaGyingTransportV1108Mixin,
    GuangYaStabilityV1106Mixin,
    GuangYaContentResilienceV1105Mixin,
    GuangYaGyingObservabilityV1104Mixin,
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
    GuangYaStatusHardeningMixin,
    GuangYaPlannerSafetyMixin,
    GuangYaResourcePlannerMixin,
    GuangYaOfflineSafetyMixin,
    GuangYaMultiSourceMixin,
    GuangYaRuntimeFinalizerMixin,
    GuangYaReliabilityMixin,
    GuangYaExperienceMixin,
    _RoutingV170Assistant,
):
    """固定分流 + CloakBrowser 观影验证 + 观影自动云添加 + 迅雷秒传 + 原生云添加。"""

    plugin_version = "1.12.15"
    build_id = "20260906-r62"

    def get_api(self):
        """统一 Bearer 鉴权，并为页面按钮安装标准响应适配。"""
        return force_bear_auth(super().get_api())

    @staticmethod
    def _normalize_page_api_auth(node: Any) -> None:
        strip_page_api_secrets(node)

    def post_message(self, *args, **kwargs):
        if str(kwargs.get("title") or "") == "⚠️ 光鸭转存失败" and kwargs.get("text"):
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
        return pages


__all__ = ["GuangYaTransferAssistant"]