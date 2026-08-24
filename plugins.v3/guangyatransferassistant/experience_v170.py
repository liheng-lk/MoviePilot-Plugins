"""光鸭转存助手 v1.7.0 体验增强层。

本层不改动 legacy.py 的成熟转存实现，只补足用户真正会感知到的交互能力：
- MoviePilot 原生订阅搜索触发时只做硬分流，不在搜索线程里访问频道网络；
- 后台合并/去重光鸭检查，避免一次搜索卡住整个订阅任务；
- /gyroute /gycheck /gywhy /gyselfcheck 消息管理；
- 页面一键自检与“为什么没转存”诊断；
- route_membership_pending 跨异常重启恢复，降低路线切换丢失概率；
- 页面显示实际运行版本和构建标识。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.chain.subscribe import SubscribeChain
from app.sdk.config import settings
from app.sdk.events import Event, eventmanager
from app.schemas.types import EventType

from .legacy import _normalize_media_text


class GuangYaExperienceMixin:
    """叠加在 routing_v170 之前的用户体验增强 mixin。"""

    build_id = "20260824-r4"
    _async_route_debounce = 0.25
    _recovery_retry_seconds = 60.0

    def init_plugin(self, config: dict = None) -> None:
        """恢复路由意图并初始化后台检查合并器，再进入既有初始化流程。"""
        config = dict(config or {})
        pending = self.get_data("route_membership_pending") or {}
        pending_token = str(pending.get("token") or "")
        pending_ids = [
            int(value) for value in (pending.get("ids") or [])
            if str(value).isdigit()
        ]
        # routing_v170 原本只恢复 120 秒内的 pending。这里把 pending 视为一次未确认写盘的
        # durable intent：即使进程宕机很久，下一次启动也先恢复用户最后一次路线选择。
        if pending_token:
            config["selected_subscriptions"] = pending_ids

        self._async_route_lock = threading.RLock()
        self._async_route_pending: set[int] = set()
        self._async_route_worker_running = False
        super().init_plugin(config)

        if pending_token:
            self._record_route_health(
                recovered_route_intent=True,
                recovered_route_ids=len(pending_ids),
                recovered_route_at=self._now_text(),
            )
            self._schedule_pending_route_recovery(pending_token)

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """消息端提供完整的“新建、接管、检查、诊断、释放”闭环。"""
        return [
            {
                "cmd": "/gysub",
                "event": EventType.PluginAction,
                "desc": "直接创建光鸭转存订阅：/gysub 片名 [年份] [movie|tv] [S01]",
                "category": "订阅",
                "data": {"action": "guangya_direct_subscribe"},
            },
            {
                "cmd": "/gyroute",
                "event": EventType.PluginAction,
                "desc": "把已有 MoviePilot 订阅切到光鸭：/gyroute 订阅ID或片名",
                "category": "订阅",
                "data": {"action": "guangya_takeover_existing"},
            },
            {
                "cmd": "/gycheck",
                "event": EventType.PluginAction,
                "desc": "后台立即检查一个光鸭订阅：/gycheck 订阅ID或片名",
                "category": "订阅",
                "data": {"action": "guangya_check_existing"},
            },
            {
                "cmd": "/gywhy",
                "event": EventType.PluginAction,
                "desc": "查看为什么还没转存：/gywhy 订阅ID或片名",
                "category": "订阅",
                "data": {"action": "guangya_explain_existing"},
            },
            {
                "cmd": "/gystatus",
                "event": EventType.PluginAction,
                "desc": "查看光鸭转存总体状态",
                "category": "订阅",
                "data": {"action": "guangya_route_status"},
            },
            {
                "cmd": "/gynative",
                "event": EventType.PluginAction,
                "desc": "切回普通下载：/gynative 订阅ID或片名",
                "category": "订阅",
                "data": {"action": "guangya_release_native"},
            },
            {
                "cmd": "/gyselfcheck",
                "event": EventType.PluginAction,
                "desc": "检查光鸭登录、频道、分流门禁和待落盘任务",
                "category": "订阅",
                "data": {"action": "guangya_selfcheck"},
            },
        ]

    def _schedule_pending_route_recovery(self, token: str) -> None:
        """把异常退出留下的路线意图重新写入插件配置，且避免热重载循环。"""
        marker = self.get_data("route_recovery_marker") or {}
        now = time.time()
        same_token = str(marker.get("token") or "") == str(token or "")
        try:
            age = now - float(marker.get("scheduled_at") or 0)
        except (TypeError, ValueError):
            age = self._recovery_retry_seconds + 1
        if same_token and str(marker.get("state") or "") == "scheduled" and age < self._recovery_retry_seconds:
            return

        self.save_data("route_recovery_marker", {
            "token": token,
            "state": "scheduled",
            "scheduled_at": now,
            "ids": list(sorted(set(self._selected_subscriptions))),
        })

        def persist_recovered_route() -> None:
            pending = self.get_data("route_membership_pending") or {}
            if str(pending.get("token") or "") != token:
                return
            try:
                self._save_config()
            except Exception as err:
                self._plugin_log("WARNING", "【光鸭转存助手】【崩溃恢复】路线配置重新落盘失败：%s", err)
                self.save_data("route_recovery_marker", {
                    "token": token,
                    "state": "failed",
                    "scheduled_at": now,
                    "error": str(err)[:500],
                })
                return
            latest = self.get_data("route_membership_pending") or {}
            if str(latest.get("token") or "") == token:
                self.save_data("route_membership_pending", {})
            self.save_data("route_recovery_marker", {
                "token": token,
                "state": "done",
                "finished_at": time.time(),
                "ids": list(sorted(set(self._selected_subscriptions))),
            })
            self._record_route_health(recovered_route_persisted_at=self._now_text())
            self._plugin_log("INFO", "【光鸭转存助手】【崩溃恢复】未确认的固定分流路线已重新持久化")

        timer = threading.Timer(max(2.0, float(getattr(self, "_route_persist_delay", 1.2)) + 0.8), persist_recovered_route)
        timer.daemon = True
        timer.start()

    def _guard_one_subscription(self, subscribe: Any, trigger: str) -> Dict[str, Any]:
        """硬阻断原生下载后立即返回，网络刷新和转存全部转入后台。"""
        sid = int(getattr(subscribe, "id", 0) or 0)
        name = str(getattr(subscribe, "name", "") or "")
        self._record_route_health(
            last_guarded_at=self._now_text(),
            last_guarded_id=sid,
            last_guarded_name=name,
            last_guard_mode="async",
        )
        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【硬分流】%s拦截原生搜索 #%s %s；搜索线程立即返回，光鸭检查转入后台",
            trigger, sid, name,
        )
        if str(getattr(subscribe, "state", "") or "") not in ("N", "R"):
            return {
                "success": True,
                "handled": True,
                "queued": False,
                "message": "固定转存订阅当前非活跃，已阻断原生下载但不执行转存检查",
            }
        self._queue_async_route_check([sid], trigger=trigger)
        return {
            "success": True,
            "handled": True,
            "queued": True,
            "message": "已阻断 MoviePilot 原生下载，光鸭检查已进入后台队列",
        }

    def _queue_async_route_check(self, sids: Iterable[int], trigger: str = "后台检查") -> None:
        """合并短时间内的多个订阅检查，只刷新一次频道，避免搜索线程和频道源互相拖慢。"""
        ids = {
            int(value) for value in sids
            if str(value).isdigit() and int(value) > 0
        }
        if not ids or not self._enabled:
            return
        with self._async_route_lock:
            self._async_route_pending.update(ids)
            if self._async_route_worker_running:
                return
            self._async_route_worker_running = True

        def worker() -> None:
            try:
                # 给一次批量 search 留一个很短的合并窗口，几十个订阅不会各自刷新频道。
                time.sleep(self._async_route_debounce)
                while self._enabled:
                    with self._async_route_lock:
                        batch = sorted(self._async_route_pending)
                        self._async_route_pending.clear()
                    if not batch:
                        break

                    subscriptions = []
                    need_refresh = False
                    for sid in batch:
                        subscribe = self._find_subscription(sid)
                        if not subscribe or not self._is_guangya_route(subscribe):
                            continue
                        subscriptions.append(subscribe)
                        try:
                            if not self._cached_matches_for_subscription(subscribe):
                                need_refresh = True
                        except Exception:
                            need_refresh = True

                    if need_refresh and subscriptions:
                        self._plugin_log(
                            "INFO",
                            "【光鸭转存助手】【后台检查】%s：%s 个订阅中存在缓存未命中，后台统一刷新一次频道",
                            trigger, len(subscriptions),
                        )
                        try:
                            self.refresh_channels(force=True)
                        except Exception as err:
                            self._plugin_log("WARNING", "【光鸭转存助手】【后台检查】频道刷新失败：%s", err)
                    try:
                        self._inspect_cache.clear()
                    except Exception:
                        pass

                    for subscribe in subscriptions:
                        sid = int(getattr(subscribe, "id", 0) or 0)
                        try:
                            result = self._try_transfer_subscription(subscribe, refresh_channel=False)
                            message = str(result.get("message") or "检查完成")
                            self._record_route_health(
                                last_route_result=message[:500],
                                last_route_result_at=self._now_text(),
                                last_async_check_id=sid,
                            )
                            self._plugin_log(
                                "INFO", "【光鸭转存助手】【后台检查】#%s %s：%s",
                                sid, getattr(subscribe, "name", ""), message,
                            )
                        except Exception as err:
                            self._plugin_log(
                                "EXCEPTION", "【光鸭转存助手】【后台检查】#%s %s 异常：%s",
                                sid, getattr(subscribe, "name", ""), err,
                            )
                    # 工作期间如果又进来新的订阅，继续下一批；否则退出。
                    time.sleep(0.05)
            finally:
                with self._async_route_lock:
                    self._async_route_worker_running = False
                    restart = bool(self._async_route_pending) and self._enabled
                if restart:
                    self._queue_async_route_check([], trigger="合并补偿")

        threading.Thread(target=worker, name="GuangYaAsyncRouteCheck", daemon=True).start()

    def _resolve_any_subscription(self, value: Any) -> Tuple[Optional[Any], List[Any]]:
        """按 ID 或标题解析 MoviePilot 当前订阅，不要求已在光鸭路线。"""
        query = str(value or "").strip()
        candidates = list(self._list_subscriptions(None) or [])
        if not query:
            return None, []
        if query.isdigit():
            exact = [
                item for item in candidates
                if int(getattr(item, "id", 0) or 0) == int(query)
            ]
            return (exact[0] if len(exact) == 1 else None), exact
        normalized = _normalize_media_text(query)
        matched = [
            item for item in candidates
            if normalized and normalized in _normalize_media_text(getattr(item, "name", ""))
        ]
        exact = [
            item for item in matched
            if _normalize_media_text(getattr(item, "name", "")) == normalized
        ]
        if len(exact) == 1:
            return exact[0], exact
        return (matched[0] if len(matched) == 1 else None), matched

    @eventmanager.register(EventType.PluginAction)
    def experience_action_event_handler(self, event: Event) -> None:
        """只处理体验层新增 action；旧 action 继续由 routing_v170 原处理器负责。"""
        event_data = event.event_data or {}
        action = event_data.get("action")
        if action == "guangya_takeover_existing":
            self._handle_takeover_existing_command(event_data)
        elif action == "guangya_check_existing":
            self._handle_check_existing_command(event_data)
        elif action == "guangya_explain_existing":
            self._handle_explain_existing_command(event_data)
        elif action == "guangya_selfcheck":
            self._handle_selfcheck_command(event_data)

    def _command_subscription_or_reply(
        self, event_data: Dict[str, Any], *, selected_only: bool = False,
    ) -> Optional[Any]:
        query = str(event_data.get("arg_str") or "").strip()
        if not query:
            self._post_command(event_data, "缺少订阅", "请提供订阅ID或片名。")
            return None
        if selected_only:
            subscribe, matches = self._resolve_selected_subscription(query)
        else:
            subscribe, matches = self._resolve_any_subscription(query)
        if subscribe:
            return subscribe
        if matches:
            text = "\n".join(
                f"• #{getattr(item, 'id', 0)} {getattr(item, 'name', '')}"
                for item in matches[:10]
            )
            self._post_command(event_data, "匹配到多个订阅", text + "\n请改用订阅ID。")
        else:
            self._post_command(event_data, "未找到订阅", "请确认订阅仍存在于 MoviePilot。")
        return None

    def _handle_takeover_existing_command(self, event_data: Dict[str, Any]) -> None:
        subscribe = self._command_subscription_or_reply(event_data, selected_only=False)
        if not subscribe:
            return
        sid = int(getattr(subscribe, "id", 0) or 0)
        if self._is_guangya_route(subscribe):
            self._post_command(
                event_data, "已经是光鸭路线",
                f"#{sid} {getattr(subscribe, 'name', '')}\n无需重复加入；可发送 /gycheck {sid} 立即检查。",
            )
            return
        self._add_selected_subscription(sid, persist=True)
        self._record_route_health(last_takeover_id=sid, last_takeover_at=self._now_text())
        self._plugin_log("INFO", "【光鸭转存助手】【消息命令】#%s %s 已从普通订阅切到光鸭固定转存", sid, getattr(subscribe, "name", ""))
        self._post_command(
            event_data,
            "✅ 已切到光鸭转存",
            f"#{sid} {getattr(subscribe, 'name', '')}\n原生下载已立即阻断；后台正在检查频道资源。",
        )
        self._queue_async_route_check([sid], trigger="消息切换路线")

    def _handle_check_existing_command(self, event_data: Dict[str, Any]) -> None:
        subscribe = self._command_subscription_or_reply(event_data, selected_only=True)
        if not subscribe:
            return
        sid = int(getattr(subscribe, "id", 0) or 0)
        self._queue_async_route_check([sid], trigger="消息立即检查")
        diagnosis = self._diagnose_subscription(subscribe)
        self._post_command(
            event_data,
            "🔎 已进入后台检查队列",
            self._format_subscription_diagnosis(diagnosis, include_hint=True),
        )

    def _handle_explain_existing_command(self, event_data: Dict[str, Any]) -> None:
        subscribe = self._command_subscription_or_reply(event_data, selected_only=True)
        if not subscribe:
            return
        diagnosis = self._diagnose_subscription(subscribe)
        self._post_command(
            event_data,
            "为什么还没转存",
            self._format_subscription_diagnosis(diagnosis, include_hint=True),
        )

    def _handle_selfcheck_command(self, event_data: Dict[str, Any]) -> None:
        report = self._build_selfcheck()
        self._post_command(event_data, "光鸭转存自检", self._format_selfcheck(report))

    def _diagnose_subscription(self, subscribe: Any) -> Dict[str, Any]:
        """把已有状态机数据翻译成用户能直接理解的“为什么还没转存”。"""
        sid = int(getattr(subscribe, "id", 0) or 0)
        state = str(getattr(subscribe, "state", "") or "")
        done, total, lack = self._subscription_episode_progress(subscribe)
        missing = self._subscription_missing_episodes(subscribe)
        try:
            matches = list(self._cached_matches_for_subscription(subscribe) or [])
        except Exception:
            matches = []
        try:
            channel_state = self._channel_state_for_subscription(subscribe)
        except Exception:
            channel_state = {}

        jobs = []
        for key, row in (self.get_data("transfer_jobs") or {}).items():
            if not isinstance(row, dict):
                continue
            row_sid = row.get("subscribe_id") or row.get("sid")
            if str(row_sid or "") == str(sid):
                copied = dict(row)
                copied["_key"] = key
                jobs.append(copied)
        pending_status = {"submitting", "submitted", "task_confirmed", "verifying"}
        pending_jobs = [row for row in jobs if str(row.get("status") or "") in pending_status]
        failed_jobs = [row for row in jobs if str(row.get("status") or "") == "failed"]

        index = self.get_data("channel_index") or {}
        index_count = len(index.get("items") or [])
        reason = "等待下一次频道检查"
        severity = "info"
        if state not in ("N", "R"):
            reason = f"订阅状态为 {state or '-'}，光鸭路线会保留但不会自动执行"
            severity = "warning"
        elif pending_jobs:
            reason = f"已有 {len(pending_jobs)} 个转存任务已提交，正在等待光鸭落盘确认"
            severity = "info"
        elif failed_jobs:
            last = failed_jobs[-1]
            error = str(last.get("error") or last.get("message") or "未知错误")[:160]
            reason = f"最近转存任务失败：{error}"
            severity = "error"
        elif total and lack <= 0:
            if bool(channel_state.get("ongoing")) and not bool(channel_state.get("complete")):
                reason = "目标集已齐，但频道仍标记连载中，正在执行连载保护"
            else:
                reason = "目标内容已齐，等待 MoviePilot 完成订阅流程"
            severity = "success"
        elif matches:
            reason = f"频道已命中 {len(matches)} 条候选，下一步是分享内容检查和增量转存"
            severity = "info"
        elif index_count <= 0:
            reason = "频道索引为空，后台需要重新抓取频道后才能匹配"
            severity = "warning"
        elif channel_state.get("matched"):
            reason = "频道能识别到该媒体，但当前缓存候选未通过精确匹配/可转存检查"
            severity = "warning"
        else:
            reason = "当前频道索引没有命中该媒体；不会回退到 MoviePilot 本地下载"
            severity = "warning"

        return {
            "id": sid,
            "name": str(getattr(subscribe, "name", "") or ""),
            "year": str(getattr(subscribe, "year", "") or ""),
            "state": state,
            "route": self._is_guangya_route(subscribe),
            "done": done,
            "total": total,
            "lack": lack,
            "missing": missing[:20],
            "matches": len(matches),
            "channel_matched": int(channel_state.get("matched") or 0),
            "channel_ongoing": bool(channel_state.get("ongoing")),
            "channel_complete": bool(channel_state.get("complete")),
            "pending_jobs": len(pending_jobs),
            "failed_jobs": len(failed_jobs),
            "reason": reason,
            "severity": severity,
            "next_check": f"约每 {max(1, int(getattr(self, '_refresh_minutes', 10) or 10))} 分钟轮询；也可 /gycheck {sid}",
        }

    @staticmethod
    def _format_subscription_diagnosis(row: Dict[str, Any], include_hint: bool = False) -> str:
        progress = f"{row.get('done', 0)}/{row.get('total', 0)}，剩余 {row.get('lack', 0)}" if row.get("total") else "电影/总集数未知"
        text = (
            f"#{row.get('id')} {row.get('name')} ({row.get('year') or '-'})\n"
            f"当前原因：{row.get('reason')}\n"
            f"进度：{progress}\n"
            f"频道命中：{row.get('matches', 0)} 条 · 待落盘：{row.get('pending_jobs', 0)} · 失败任务：{row.get('failed_jobs', 0)}\n"
            f"下一步：{row.get('next_check')}"
        )
        if row.get("missing"):
            text += "\n缺集：" + ", ".join(str(value) for value in row["missing"])
        if include_hint:
            text += f"\n操作：/gycheck {row.get('id')} 立即后台检查；/gynative {row.get('id')} 切回普通下载"
        return text

    def _build_selfcheck(self) -> Dict[str, Any]:
        """只读取本地运行状态，不主动访问 Telegram；点击自检不会阻塞外部网络。"""
        checks = []

        def add(key: str, label: str, ok: bool, detail: str, critical: bool = True) -> None:
            checks.append({
                "key": key,
                "label": label,
                "ok": bool(ok),
                "detail": str(detail or "")[:500],
                "critical": bool(critical),
            })

        add("enabled", "插件运行", bool(self._enabled), "已启用" if self._enabled else "插件未启用")
        add(
            "search_guard",
            "原生搜索硬分流",
            bool(self._is_search_guard_active()),
            "SubscribeChain.search 已接管" if self._is_search_guard_active() else "未接管，固定转存可能进入原生搜索",
        )
        match_guard = bool(getattr(SubscribeChain.match, "_guangya_match_guard", False))
        download_method = getattr(SubscribeChain, "_SubscribeChain__download_best_version_with_full_pack_first", None)
        download_guard = bool(download_method and getattr(download_method, "_guangya_download_guard", False))
        add("match_guard", "RSS/缓存匹配门禁", match_guard, "已接管" if match_guard else "未接管")
        add("download_guard", "最终下载断路器", download_guard, "已接管" if download_guard else "未接管")

        try:
            client, runtime = self._get_guangya_runtime()
            runtime_ok = bool(client)
            runtime_detail = "光鸭云盘助手运行中且可取得客户端" if runtime_ok else str(runtime or "光鸭云盘助手未运行或未登录")
        except Exception as err:
            runtime_ok = False
            runtime_detail = f"读取光鸭客户端失败：{err}"
        add("guangya_runtime", "光鸭登录/运行时", runtime_ok, runtime_detail)

        urls = list(self._source_urls() or [])
        add("channel_sources", "频道源配置", bool(urls), f"已配置 {len(urls)} 个频道源" if urls else "未配置频道源")
        index = self.get_data("channel_index") or {}
        index_items = list(index.get("items") or [])
        source_errors = index.get("errors") or []
        add(
            "channel_index",
            "频道本地索引",
            bool(index_items),
            f"{len(index_items)} 条，最近刷新 {index.get('time') or '-'}，最近错误 {len(source_errors)} 个",
            critical=False,
        )

        save_path = str(getattr(self, "_save_path", "") or "").strip()
        add("save_path", "转存目标目录", bool(save_path), save_path or "目标目录为空")

        jobs = list((self.get_data("transfer_jobs") or {}).values())
        pending = sum(
            1 for row in jobs
            if isinstance(row, dict) and str(row.get("status") or "") in {"submitting", "submitted", "task_confirmed", "verifying"}
        )
        failed = sum(
            1 for row in jobs
            if isinstance(row, dict) and str(row.get("status") or "") == "failed"
        )
        add("jobs", "转存任务状态", True, f"待落盘 {pending}，失败 {failed}", critical=False)

        pending_route = self.get_data("route_membership_pending") or {}
        add(
            "route_persist",
            "路线持久化",
            not bool(pending_route.get("token")),
            "已持久化" if not pending_route.get("token") else "存在未确认路线写盘意图，已启用崩溃恢复",
            critical=False,
        )

        critical_failed = [item for item in checks if item["critical"] and not item["ok"]]
        return {
            "healthy": not critical_failed,
            "checks": checks,
            "selected": len(self._selected_subscriptions),
            "pending_jobs": pending,
            "failed_jobs": failed,
            "index_count": len(index_items),
            "build": self.build_id,
            "version": str(getattr(self, "plugin_version", "1.7.0")),
            "time": self._now_text(),
        }

    @staticmethod
    def _format_selfcheck(report: Dict[str, Any]) -> str:
        rows = [
            f"光鸭转存助手 v{report.get('version')} · build {report.get('build')}",
            f"总体：{'正常' if report.get('healthy') else '存在关键异常'} · 固定转存 {report.get('selected', 0)} 个",
        ]
        for item in report.get("checks") or []:
            icon = "✅" if item.get("ok") else ("❌" if item.get("critical") else "⚠️")
            rows.append(f"{icon} {item.get('label')}：{item.get('detail')}")
        return "\n".join(rows)

    def get_api(self) -> List[Dict[str, Any]]:
        apis = list(super().get_api() or [])
        existing = {str(item.get("path") or "") for item in apis if isinstance(item, dict)}
        extras = [
            {"path": "/selfcheck", "endpoint": self.api_selfcheck, "methods": ["POST"], "summary": "光鸭转存助手本地运行状态自检"},
            {"path": "/route_guangya", "endpoint": self.api_route_guangya, "methods": ["POST"], "summary": "把已有 MoviePilot 订阅加入光鸭固定转存"},
            {"path": "/check_route", "endpoint": self.api_check_route, "methods": ["POST"], "summary": "后台检查一个光鸭固定转存订阅"},
        ]
        apis.extend(item for item in extras if item["path"] not in existing)
        return apis

    def api_selfcheck(self) -> Dict[str, Any]:
        report = self._build_selfcheck()
        return {
            "success": True,
            "healthy": report["healthy"],
            "message": self._format_selfcheck(report),
            "data": report,
        }

    def api_route_guangya(self, subscribe_id: int = 0) -> Dict[str, Any]:
        sid = int(subscribe_id or 0)
        subscribe = self._find_subscription(sid)
        if not sid or not subscribe:
            return {"success": False, "message": "订阅不存在"}
        changed = self._add_selected_subscription(sid, persist=True)
        self._queue_async_route_check([sid], trigger="页面切换光鸭路线")
        return {
            "success": True,
            "message": (
                f"{getattr(subscribe, 'name', '')} 已切到光鸭固定转存，后台检查已排队"
                if changed else f"{getattr(subscribe, 'name', '')} 已经是光鸭固定转存路线"
            ),
        }

    def api_check_route(self, subscribe_id: int = 0) -> Dict[str, Any]:
        sid = int(subscribe_id or 0)
        subscribe = self._find_subscription(sid)
        if not sid or not subscribe:
            return {"success": False, "message": "订阅不存在"}
        if not self._is_guangya_route(subscribe):
            return {"success": False, "message": "该订阅当前不是光鸭固定转存路线"}
        self._queue_async_route_check([sid], trigger="页面后台检查")
        diagnosis = self._diagnose_subscription(subscribe)
        return {
            "success": True,
            "message": "后台检查已排队；当前状态：" + str(diagnosis.get("reason") or "等待检查"),
            "data": diagnosis,
        }

    def get_form(self):
        form, defaults = super().get_form()
        try:
            content = form[0].get("content") if form else None
            if isinstance(content, list):
                content.append({
                    "component": "VAlert",
                    "props": {
                        "type": "info",
                        "variant": "tonal",
                        "text": (
                            "消息快捷操作：/gyroute ID 把已有普通订阅切入光鸭；/gycheck ID 后台立即检查；"
                            "/gywhy ID 查看未转存原因；/gyselfcheck 检查运行状态。原生订阅搜索只负责触发后台检查，不再等待频道网络。"
                        ),
                    },
                })
        except Exception:
            pass
        return form, defaults

    def get_page(self):
        pages = list(super().get_page() or [])
        report = self._build_selfcheck()
        selfcheck = {
            "component": "VCard",
            "props": {"variant": "tonal", "class": "mb-3"},
            "content": [
                {
                    "component": "VCardTitle",
                    "text": f"光鸭转存助手 v{report['version']} · build {report['build']}",
                },
                {
                    "component": "VCardText",
                    "text": (
                        f"运行自检：{'正常' if report['healthy'] else '存在关键异常'} · "
                        f"固定转存 {report['selected']} 个 · 频道索引 {report['index_count']} 条 · "
                        f"待落盘 {report['pending_jobs']} · 失败 {report['failed_jobs']}"
                    ),
                },
                {
                    "component": "VCardActions",
                    "content": [
                        {
                            "component": "VBtn",
                            "props": {"size": "small", "variant": "outlined", "prepend-icon": "mdi-stethoscope"},
                            "text": "运行转存自检",
                            "events": {
                                "click": {
                                    "api": "plugin/GuangYaTransferAssistant/selfcheck",
                                    "method": "post",
                                    "params": {"apikey": settings.API_TOKEN},
                                }
                            },
                        }
                    ],
                },
            ],
        }

        selected_ids = set(self._selected_subscriptions)
        diagnosis_rows = []
        for subscribe in self._list_subscriptions(None):
            sid = int(getattr(subscribe, "id", 0) or 0)
            if sid and sid in selected_ids:
                diagnosis_rows.append(self._diagnose_subscription(subscribe))
        diagnosis_rows = diagnosis_rows[:20]
        diagnostic_cards = []
        for row in diagnosis_rows:
            progress = f"{row['done']}/{row['total']} · 剩余 {row['lack']}" if row["total"] else "电影/总集数未知"
            diagnostic_cards.append({
                "component": "VAlert",
                "props": {
                    "type": row["severity"],
                    "variant": "tonal",
                    "class": "mb-2",
                    "title": f"#{row['id']} {row['name']} ({row['year'] or '-'})",
                    "text": (
                        f"{row['reason']} · 进度 {progress} · 频道候选 {row['matches']} · "
                        f"待落盘 {row['pending_jobs']} · 失败 {row['failed_jobs']} · {row['next_check']}"
                    ),
                },
            })
        diagnostics = {
            "component": "VCard",
            "props": {"variant": "flat", "class": "mb-3"},
            "content": [
                {"component": "VCardTitle", "text": "为什么还没转存"},
                {
                    "component": "VCardText",
                    "text": "这里直接解释每个固定转存订阅当前停在哪一步；不会因为频道暂时无资源而回退到本地下载。",
                },
                *diagnostic_cards,
            ],
        }

        if pages:
            # 保留 routing_v170 的硬分流健康卡作为第一项，方便运行入口继续补充 RSS/下载断路器状态。
            return [pages[0], selfcheck, diagnostics, *pages[1:]]
        return [selfcheck, diagnostics]


__all__ = ["GuangYaExperienceMixin"]
