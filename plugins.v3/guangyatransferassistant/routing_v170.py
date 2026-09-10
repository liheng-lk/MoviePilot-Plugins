"""光鸭转存助手 v1.7：全入口硬分流、消息直订与无刷新路由切换。

v1.6.x 的成熟频道解析、分享检查、增量转存和进度闭环保留在 legacy.py。
本文件只叠加路由边界与交互体验，避免再次复制转存业务实现。
"""

from __future__ import annotations

import functools
import inspect
import re
import shlex
import threading
import time
import weakref
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.chain.media import MediaChain
from app.chain.subscribe import SubscribeChain
from app.db.oper.subscribe import SubscribeOper
from app.sdk.events import Event, eventmanager
from app.sdk.logging import logger
from app.schemas.types import EventType, MediaSource, MediaType

from .legacy import GuangYaTransferAssistant as _LegacyGuangYaTransferAssistant
from .legacy import _normalize_media_text


_TYPE_ALIASES = {
    "movie": MediaType.MOVIE,
    "film": MediaType.MOVIE,
    "电影": MediaType.MOVIE,
    "tv": MediaType.TV,
    "series": MediaType.TV,
    "电视剧": MediaType.TV,
    "剧集": MediaType.TV,
}


def _enum_value(value: Any) -> str:
    """Enum/字符串统一为稳定文本。"""
    return str(getattr(value, "value", value) or "").strip().lower()


def _flatten_bound_search_kwargs(signature, values: Dict[str, Any]) -> Dict[str, Any]:
    """去掉实例首参，并把 VAR_KEYWORD（常名 kwargs）展平为可二次 ** 转发的平面表。"""
    out = dict(values)
    first = next(iter(signature.parameters), None)
    if first:
        out.pop(first, None)
    out.pop("self", None)
    for name, param in signature.parameters.items():
        if param.kind == inspect.Parameter.VAR_KEYWORD and name in out:
            nested = out.pop(name) or {}
            if isinstance(nested, dict):
                out.update(nested)
        elif param.kind == inspect.Parameter.VAR_POSITIONAL and name in out:
            # 搜索 ABI 不应依赖 *args 残留；丢弃以免再次位置重复
            out.pop(name, None)
    return out


def _route_identity(media_source: Any, media_id: Any, season: Any = None) -> str:
    """生成订阅创建前后都可比较的媒体路由身份。"""
    source = _enum_value(media_source)
    media_id = str(media_id or "").strip()
    if not source or not media_id:
        return ""
    try:
        season_value = int(season) if season not in (None, "") else -1
    except (TypeError, ValueError):
        season_value = -1
    return f"{source}|{media_id}|{season_value}"


def _parse_direct_subscribe_args(arg_str: Any) -> Dict[str, Any]:
    """解析 /gysub 参数；标题中的空格可直接使用，也支持引号。"""
    raw = str(arg_str or "").strip()
    if not raw:
        return {"title": "", "year": None, "mtype": None, "season": None, "tmdb_id": ""}
    try:
        tokens = shlex.split(raw)
    except ValueError:
        tokens = raw.split()

    year = None
    mtype = None
    season = None
    tmdb_id = ""
    title_tokens: List[str] = []
    for token in tokens:
        lowered = token.lower().strip()
        tmdb_match = re.fullmatch(r"tmdb[:#=](\d{1,10})", lowered, re.I)
        if tmdb_match:
            tmdb_id = tmdb_match.group(1)
            continue
        season_match = re.fullmatch(r"s(?:eason)?0*(\d{1,2})", lowered, re.I)
        if season_match:
            season = int(season_match.group(1))
            continue
        if lowered in _TYPE_ALIASES:
            mtype = _TYPE_ALIASES[lowered]
            continue
        if re.fullmatch(r"(?:19|20)\d{2}", token):
            year = token
            continue
        title_tokens.append(token)
    return {
        "title": " ".join(title_tokens).strip(),
        "year": year,
        "mtype": mtype,
        "season": season,
        "tmdb_id": tmdb_id,
    }


class GuangYaTransferAssistant(_LegacyGuangYaTransferAssistant):
    """在 v1.6.5 之上增加 MoviePilot 全入口硬分流与消息直订。"""

    plugin_desc = "全入口固定分流：光鸭订阅阻断 MoviePilot 原生下载搜索，支持消息直接创建转存订阅并立即检查频道。"
    plugin_version = "1.7.0"
    plugin_label = "光鸭云盘,转存,订阅,Telegram,网盘,固定分流,消息命令,硬分流"

    _search_guard_lock = threading.RLock()
    _route_persist_delay = 1.2
    _pending_route_ttl = 120.0

    def init_plugin(self, config: dict = None) -> None:
        """优先恢复尚未落盘的路由变更，再启动旧版成熟运行时。"""
        config = dict(config or {})
        pending = self.get_data("route_membership_pending") or {}
        try:
            pending_age = time.time() - float(pending.get("created_at") or 0)
        except (TypeError, ValueError):
            pending_age = self._pending_route_ttl + 1
        if pending.get("token") and 0 <= pending_age <= self._pending_route_ttl:
            config["selected_subscriptions"] = list(pending.get("ids") or [])

        previous_snapshot = self.get_data("route_membership") or {}
        previous_ids = {
            int(value) for value in (previous_snapshot.get("ids") or [])
            if str(value).isdigit()
        }
        self._provisional_routes: set[str] = set()
        self._route_persist_timer = None
        super().init_plugin(config)

        current_ids = set(self._selected_subscriptions)
        self._remember_route_membership("init")
        if self._enabled:
            self._install_search_guard()
            newly_selected = sorted(current_ids - previous_ids)
            if newly_selected:
                self._spawn_route_prime(newly_selected, trigger="新加入转存路线")
        else:
            self._restore_search_guard()

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """消息端直接管理转存路线，不再要求进插件设置二次勾选。"""
        return [
            {
                "cmd": "/gysub",
                "event": EventType.PluginAction,
                "desc": "直接添加光鸭转存订阅：/gysub 片名 [年份] [movie|tv] [S01]",
                "category": "订阅",
                "data": {"action": "guangya_direct_subscribe"},
            },
            {
                "cmd": "/gystatus",
                "event": EventType.PluginAction,
                "desc": "查看光鸭转存路由与频道状态",
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
        ]

    def _install_takeover(self) -> None:
        """保留旧调度器接管，同时安装 SubscribeChain.search 全入口守卫。"""
        super()._install_takeover()
        self._install_search_guard()

    def _install_search_guard(self) -> None:
        """包装 SubscribeChain.search，使手动/API/消息/调度入口都服从固定分流。

        ABI 必须透明：宿主可能新增 scheduled_interval 等参数，禁止硬编码完整签名。
        """
        if not self._enabled:
            return
        with self._search_guard_lock:
            current = SubscribeChain.search
            if getattr(current, "_guangya_route_guard", False):
                current._guangya_plugin_ref = weakref.ref(self)
                self._record_route_health(search_guard=True, guard_message="全入口硬分流已接管")
                return

            original = current

            @functools.wraps(original)
            def guarded_search(chain_self, *args, **kwargs):
                plugin_ref = getattr(guarded_search, "_guangya_plugin_ref", None)
                plugin = plugin_ref() if callable(plugin_ref) else None
                if not plugin or not plugin._enabled:
                    return original(chain_self, *args, **kwargs)
                return plugin._guard_subscribe_search(
                    original=original,
                    chain_self=chain_self,
                    args=args,
                    kwargs=kwargs,
                )

            guarded_search._guangya_route_guard = True
            guarded_search._guangya_original_search = original
            guarded_search._guangya_plugin_ref = weakref.ref(self)
            SubscribeChain.search = guarded_search
            self._record_route_health(search_guard=True, guard_message="全入口硬分流已安装")
            self._plugin_log("INFO", "【光鸭转存助手】【硬分流】已接管 SubscribeChain.search 全入口；已选转存订阅不会进入原生下载搜索")

    def _restore_search_guard(self) -> None:
        """仅当当前 guard 仍属于本实例时恢复原方法，避免热重载实例互相覆盖。"""
        with self._search_guard_lock:
            current = SubscribeChain.search
            if not getattr(current, "_guangya_route_guard", False):
                return
            plugin_ref = getattr(current, "_guangya_plugin_ref", None)
            owner = plugin_ref() if callable(plugin_ref) else None
            if owner is not self:
                return
            original = getattr(current, "_guangya_original_search", None)
            if original:
                SubscribeChain.search = original
            self._record_route_health(search_guard=False, guard_message="全入口硬分流已释放")

    def _is_search_guard_active(self) -> bool:
        current = SubscribeChain.search
        if not getattr(current, "_guangya_route_guard", False):
            return False
        plugin_ref = getattr(current, "_guangya_plugin_ref", None)
        return bool(callable(plugin_ref) and plugin_ref() is self)

    def _subscription_route_identity(self, subscribe: Any) -> str:
        return _route_identity(
            getattr(subscribe, "media_source", None),
            getattr(subscribe, "media_id", None),
            getattr(subscribe, "season", None),
        )

    def _is_guangya_route(self, subscribe: Any) -> bool:
        sid = int(getattr(subscribe, "id", 0) or 0)
        if sid and sid in set(self._selected_subscriptions):
            return True
        return self._subscription_route_identity(subscribe) in set(self._provisional_routes or set())

    def _is_managed_sid(self, sid: Any) -> bool:
        """订阅 ID 是否已光鸭接管（配置名单；动态读取，禁止永久缓存）。"""
        try:
            value = int(sid)
        except (TypeError, ValueError):
            return False
        return bool(value > 0 and value in set(self._selected_subscriptions or []))

    def _is_managed_subscription(self, subscribe_or_id: Any) -> bool:
        """唯一接管所有权判断：selected ∪ provisional。"""
        if subscribe_or_id is None:
            return False
        if isinstance(subscribe_or_id, (int, str)) and str(subscribe_or_id).isdigit():
            sid = int(subscribe_or_id)
            if self._is_managed_sid(sid):
                return True
            subscribe = self._find_subscription(sid) if hasattr(self, "_find_subscription") else None
            return bool(subscribe and self._is_guangya_route(subscribe))
        return self._is_guangya_route(subscribe_or_id)

    def _route_trace(
        self,
        *,
        sid: Any = None,
        state: Any = None,
        manual: Any = False,
        scheduled_interval: Any = None,
        managed: bool = False,
        decision: str = "",
        source: str = "",
    ) -> None:
        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【路由】sid=%s state=%s manual=%s scheduled_interval=%s managed=%s decision=%s source=%s",
            sid if sid is not None else "-",
            state if state is not None else "-",
            bool(manual),
            scheduled_interval if scheduled_interval is not None else "-",
            bool(managed),
            decision or "-",
            source or "-",
        )

    def _call_original_search(self, original, chain_self, *args, **kwargs):
        """透明转发宿主 search，保留 scheduled_interval 等未知参数。"""
        return original(chain_self, *args, **kwargs)

    @staticmethod
    def _normalize_search_call(func, instance, args=(), kwargs=None) -> Dict[str, Any]:
        """把 *args/**kwargs 归一成仅 kwargs；已 bind 后不得再带原 args。

        保留全部已绑定参数（含未来 ABI），只去掉实例首参（self / chain_self 等）。
        """
        merged = dict(kwargs or {})
        try:
            signature = inspect.signature(func)
            bound = signature.bind_partial(instance, *(args or ()), **merged)
            bound.apply_defaults()
            return _flatten_bound_search_kwargs(signature, dict(bound.arguments))
        except TypeError:
            return dict(merged)

    @staticmethod
    def _bind_search_args(original, chain_self, args, kwargs) -> Dict[str, Any]:
        """从 *args/**kwargs 提取已知字段；forward 使用完整归一化 kwargs。"""
        merged = dict(kwargs or {})
        try:
            signature = inspect.signature(original)
            bound = signature.bind_partial(chain_self, *(args or ()), **merged)
            bound.apply_defaults()
            values = _flatten_bound_search_kwargs(signature, dict(bound.arguments))
        except TypeError:
            values = dict(merged)
        return {
            "sid": values.get("sid", merged.get("sid")),
            "sids": values.get("sids", merged.get("sids")),
            "state": values.get("state", merged.get("state", "N")),
            "manual": values.get("manual", merged.get("manual", False)),
            "progress_callback": values.get(
                "progress_callback", merged.get("progress_callback")
            ),
            "scheduled_interval": values.get(
                "scheduled_interval", merged.get("scheduled_interval")
            ),
            # 归一化后的完整参数表（kwargs-only），禁止再附带原 args
            "kwargs": values,
            "args": (),
        }

    def _load_due_search_subscriptions(
        self,
        chain_self: Any,
        *,
        state: Any = "N",
        scheduled_interval: Any = None,
    ) -> Optional[List[Any]]:
        """调用宿主 due 筛选。

        返回：
        - list：成功（可为 empty）
        - None：失败 / 无法确认 ABI → 调用方必须 fail-closed 或完整交还原生
        绝不以全量列举订阅兜底。
        """
        loader = getattr(chain_self, "_load_search_subscriptions", None)
        if not callable(loader):
            self._plugin_log(
                "WARNING",
                "【光鸭转存助手】【调度】【due失败】宿主无 _load_search_subscriptions；本轮取消周期搜索",
            )
            return None
        try:
            parameters = inspect.signature(loader).parameters
        except (TypeError, ValueError):
            parameters = {}
        if not parameters:
            self._plugin_log(
                "WARNING",
                "【光鸭转存助手】【调度】【due失败】无法确认宿主搜索 ABI；本轮取消周期搜索",
            )
            return None
        call_kwargs: Dict[str, Any] = {"sid": None, "sids": None, "state": state}
        if "scheduled_interval" in parameters:
            call_kwargs["scheduled_interval"] = scheduled_interval
        try:
            rows = loader(**call_kwargs)
            return [item for item in (rows or []) if item is not None]
        except Exception as err:
            self._plugin_log(
                "ERROR",
                "【光鸭转存助手】【调度】【due失败】宿主到期订阅筛选失败，本轮取消周期搜索：%s",
                str(err)[:360],
            )
            return None

    @staticmethod
    def _is_active_transfer_state(subscribe: Any) -> bool:
        return str(getattr(subscribe, "state", "") or "") in ("N", "R")

    def _guard_one_subscription(self, subscribe: Any, trigger: str) -> Dict[str, Any]:
        sid = int(getattr(subscribe, "id", 0) or 0)
        self._record_route_health(
            last_guarded_at=self._now_text(),
            last_guarded_id=sid,
            last_guarded_name=str(getattr(subscribe, "name", "") or ""),
        )
        # 已接管 = exclusive ownership：即使 P/S 非活跃也 handled=True，禁止 fallback native。
        if not self._is_active_transfer_state(subscribe):
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【原生阻断】%s #%s state=%s 已接管但非活跃；阻断原生且本轮不转存",
                trigger,
                sid,
                str(getattr(subscribe, "state", "") or "-"),
            )
            return {
                "success": True,
                "handled": True,
                "retryable": False,
                "message": f"订阅状态 {getattr(subscribe, 'state', None) or '-'} 非活跃，已阻断原生",
            }
        self._plugin_log(
            "INFO", "【光鸭转存助手】【硬分流】%s拦截原生搜索 #%s %s，改走光鸭转存",
            trigger, sid, getattr(subscribe, "name", ""),
        )
        try:
            if not self._cached_matches_for_subscription(subscribe):
                self._plugin_log(
                    "INFO", "【光鸭转存助手】【立即检查】#%s %s 本地频道索引未命中，强制增量刷新一次",
                    sid, getattr(subscribe, "name", ""),
                )
                self.refresh_channels(force=True)
            self._inspect_cache.clear()
            result = self._try_transfer_subscription(subscribe, refresh_channel=False)
            self._record_route_health(
                last_route_result=str(result.get("message") or "完成")[:500],
                last_route_result_at=self._now_text(),
            )
            # 失败也必须 handled=True，禁止因光鸭失败回退原生。
            if isinstance(result, dict):
                result = dict(result)
                result["handled"] = True
                if not result.get("success"):
                    result.setdefault("retryable", True)
            return result
        except Exception as err:
            self._plugin_log("EXCEPTION", "【光鸭转存助手】【硬分流】#%s %s 转存检查异常", sid, getattr(subscribe, "name", ""))
            self._record_route_health(last_route_result=f"异常：{err}"[:500], last_route_result_at=self._now_text())
            return {"success": False, "handled": True, "message": str(err), "retryable": True}

    def _guard_subscribe_search(
        self, original, chain_self, args=(), kwargs=None,
        # 兼容旧关键字调用（supports_sids / 显式 sid=...）
        supports_sids: bool = True,
        sid=None, sids=None, state="N", manual=False, progress_callback=None,
    ):
        """把一次 MP 原生搜索调用拆成“光鸭路线”和“普通路线”两组。

        关键约定：
        - sid / sids = 定向搜索，不做 due 过滤；
        - 仅 state + scheduled_interval 且非 manual = 周期扫描，必须先走宿主 due。
        禁止把全量 R 订阅直接转成 sids，否则会绕开 subscription_search_due。
        """
        del supports_sids  # ABI 由 inspect.signature(original) 决定，不再硬编码
        kwargs = dict(kwargs or {})
        legacy_kwargs_only = (
            not args
            and not kwargs
            and (
                sid is not None
                or sids is not None
                or state != "N"
                or bool(manual)
                or progress_callback is not None
            )
        )
        scheduled_interval = kwargs.get("scheduled_interval")
        if args or kwargs:
            parsed = self._bind_search_args(original, chain_self, args, kwargs)
            sid = parsed["sid"]
            sids = parsed["sids"]
            state = parsed["state"]
            manual = parsed["manual"]
            progress_callback = parsed["progress_callback"]
            scheduled_interval = parsed.get("scheduled_interval", scheduled_interval)
            forward_kwargs = dict(parsed["kwargs"])
        elif legacy_kwargs_only:
            forward_kwargs = {
                "sid": sid,
                "state": state,
                "manual": manual,
                "progress_callback": progress_callback,
            }
            if sids is not None:
                forward_kwargs["sids"] = sids
        else:
            # 无位置参数时仍归一化一次，避免后续再拼 *args
            forward_kwargs = self._normalize_search_call(original, chain_self, (), kwargs)

        is_targeted = sid is not None or sids is not None
        is_scheduled_scan = (
            (not is_targeted)
            and scheduled_interval is not None
            and not bool(manual)
        )

        if sid is not None:
            subscribe = self._find_subscription(int(sid))
            managed = self._is_managed_sid(sid) or bool(
                subscribe and self._is_managed_subscription(subscribe)
            )
            source = "manual" if manual else ("scheduled" if scheduled_interval is not None else "sid")
            if managed:
                self._route_trace(
                    sid=sid, state=state, manual=manual,
                    scheduled_interval=scheduled_interval, managed=True,
                    decision="guangya_only", source=source,
                )
                if subscribe:
                    result = self._guard_one_subscription(subscribe, "单订阅搜索")
                    # exclusive ownership：无论 handled 标记如何，已接管不得再调 native
                    return None if result.get("handled", True) else None
                self._plugin_log(
                    "WARNING",
                    "【光鸭转存助手】【原生阻断】#%s 已在接管名单但当前找不到订阅对象；仍跳过 MoviePilot 原生搜索",
                    sid,
                )
                return None
            self._route_trace(
                sid=sid, state=state, manual=manual,
                scheduled_interval=scheduled_interval, managed=False,
                decision="native", source=source,
            )
            return self._call_original_search(original, chain_self, **forward_kwargs)

        if sids is not None:
            # 定向批量：保持宿主语义，不做 due 过滤
            candidates = [self._find_subscription(int(value)) for value in sids]
            # 保留找不到对象但仍在接管名单的 sid，避免漏阻断
            found_ids = {
                int(getattr(item, "id", 0) or 0)
                for item in candidates if item is not None
            }
            candidates = [item for item in candidates if item is not None]
            for raw in sids:
                try:
                    missing = int(raw)
                except (TypeError, ValueError):
                    continue
                if missing > 0 and missing not in found_ids and self._is_managed_sid(missing):
                    self._plugin_log(
                        "WARNING",
                        "【光鸭转存助手】【原生阻断】批量 sids 中 #%s 已接管但找不到对象；跳过原生",
                        missing,
                    )
        elif is_scheduled_scan:
            candidates = self._load_due_search_subscriptions(
                chain_self,
                state=state or "N",
                scheduled_interval=scheduled_interval,
            )
            if candidates is None:
                # due 失败必须 fail-closed：禁止 _list_subscriptions 全量→sids（会绕过 due）。
                # 也不再带 scheduled_interval 交还原生（会把 managed 重新加载出来）。
                self._plugin_log(
                    "ERROR",
                    "【光鸭转存助手】【调度】【due失败】本轮取消周期搜索；禁止全量列举或 targeted sids 兜底",
                )
                if progress_callback:
                    progress_callback(value=100, text="宿主到期筛选失败，本轮周期搜索已取消")
                return None
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【调度】周期扫描先经宿主 due 筛选：interval=%s state=%s due=%s",
                scheduled_interval,
                state,
                len(candidates),
            )
        else:
            # 手动批量 / 无 interval：按 state 列举，与旧行为一致
            candidates = [item for item in (self._list_subscriptions(state or "N,R") or []) if item is not None]

        route_subs = []
        native_ids = []
        for item in candidates:
            item_id = int(getattr(item, "id", 0) or 0)
            if not item_id:
                continue
            if self._is_managed_subscription(item):
                # 已接管：一律光鸭所有权，含 P/S 非活跃（阻断原生、不转存）
                route_subs.append(item)
            else:
                native_ids.append(item_id)

        source = "manual" if manual else ("scheduled" if is_scheduled_scan else "sids")
        for subscribe in route_subs:
            self._route_trace(
                sid=getattr(subscribe, "id", None),
                state=getattr(subscribe, "state", None),
                manual=manual,
                scheduled_interval=scheduled_interval,
                managed=True,
                decision="guangya_only",
                source=source,
            )
            self._guard_one_subscription(subscribe, "批量搜索")

        if native_ids:
            for nid in native_ids:
                self._route_trace(
                    sid=nid, state=state, manual=manual,
                    scheduled_interval=None if is_scheduled_scan else scheduled_interval,
                    managed=False, decision="native", source=source,
                )
            native_kwargs = dict(forward_kwargs)
            native_kwargs.pop("sid", None)
            # 周期扫描：due/拆分已完成，必须用 sids 定向，禁止再带 scheduled_interval
            if is_scheduled_scan:
                native_kwargs.pop("scheduled_interval", None)
            try:
                sig = inspect.signature(original)
                supports_batch_sids = (
                    "sids" in sig.parameters
                    or any(
                        p.kind == inspect.Parameter.VAR_KEYWORD
                        for p in sig.parameters.values()
                    )
                )
            except (TypeError, ValueError):
                supports_batch_sids = True
            if supports_batch_sids:
                native_kwargs["sids"] = tuple(native_ids)
                native_kwargs["sid"] = None
                return self._call_original_search(original, chain_self, **native_kwargs)
            result = None
            for index, current_sid in enumerate(native_ids):
                one = dict(native_kwargs)
                one["sid"] = int(current_sid)
                one.pop("sids", None)
                if index > 0:
                    one["progress_callback"] = None
                result = self._call_original_search(original, chain_self, **one)
            return result
        if manual and progress_callback:
            progress_callback(value=100, text="光鸭固定分流订阅已处理，未进入原生下载搜索")
        return None

    @staticmethod
    def _now_text() -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S")

    def _record_route_health(self, **fields: Any) -> None:
        try:
            row = dict(self.get_data("route_health") or {})
            row.update(fields)
            row["updated_at"] = self._now_text()
            self.save_data("route_health", row)
        except Exception:
            pass

    def _remember_route_membership(self, source: str) -> None:
        try:
            self.save_data("route_membership", {
                "ids": list(sorted(set(self._selected_subscriptions))),
                "source": source,
                "updated_at": self._now_text(),
            })
        except Exception:
            pass

    def _queue_route_config_persist(self) -> None:
        """API 请求先返回，再持久化插件配置；避免热重载打断页面请求导致跳登录。"""
        token = str(time.time_ns())
        ids = list(sorted(set(int(value) for value in self._selected_subscriptions)))
        self.save_data("route_membership_pending", {
            "token": token,
            "ids": ids,
            "created_at": time.time(),
        })
        self._remember_route_membership("runtime")

        def persist() -> None:
            pending = self.get_data("route_membership_pending") or {}
            if pending.get("token") != token:
                return
            try:
                self._save_config()
                self._plugin_log("INFO", "【光鸭转存助手】【配置】固定分流名单已延迟持久化，避免操作请求被插件热重载中断")
            except Exception as err:
                self._plugin_log("WARNING", "【光鸭转存助手】【配置】固定分流名单持久化失败：%s", err)
                return
            latest = self.get_data("route_membership_pending") or {}
            if latest.get("token") == token:
                self.save_data("route_membership_pending", {})

        timer = threading.Timer(self._route_persist_delay, persist)
        timer.daemon = True
        self._route_persist_timer = timer
        timer.start()

    def _add_selected_subscription(self, sid: int, persist: bool = True) -> bool:
        sid = int(sid or 0)
        if not sid:
            return False
        selected = sorted(set(self._selected_subscriptions) | {sid})
        changed = selected != self._selected_subscriptions
        self._selected_subscriptions = selected
        if persist:
            self._queue_route_config_persist()
        else:
            self._remember_route_membership("runtime")
        return changed

    def _remove_selected_subscription(self, sid: int) -> None:
        """运行态立即切普通下载，配置延后写入，修复按钮请求期间被热重载导致登录页跳转。"""
        sid = int(sid or 0)
        selected = [value for value in self._selected_subscriptions if int(value) != sid]
        if selected == self._selected_subscriptions:
            return
        self._selected_subscriptions = selected
        self._clear_completion_guard(sid)
        self._queue_route_config_persist()
        self._record_route_health(last_release_id=sid, last_release_at=self._now_text())

    def _spawn_route_prime(self, sids: Iterable[int], trigger: str = "立即检查") -> None:
        ids = [int(value) for value in sids if int(value or 0)]
        if not ids or not self._enabled:
            return

        def worker() -> None:
            try:
                self._plugin_log("INFO", "【光鸭转存助手】【立即检查】%s：强制刷新频道并检查 %s 个转存订阅", trigger, len(ids))
                self.refresh_channels(force=True)
                self._inspect_cache.clear()
                for sid in ids:
                    subscribe = self._find_subscription(sid)
                    if not subscribe or not self._is_guangya_route(subscribe):
                        continue
                    result = self._try_transfer_subscription(subscribe, refresh_channel=False)
                    self._plugin_log("INFO", "【光鸭转存助手】【立即检查】%s #%s %s：%s", trigger, sid, getattr(subscribe, "name", ""), result.get("message") or "完成")
                self._record_route_health(last_prime_at=self._now_text(), last_prime_count=len(ids))
            except Exception as err:
                self._plugin_log("EXCEPTION", "【光鸭转存助手】【立即检查】%s 执行异常：%s", trigger, err)

        threading.Thread(target=worker, name="GuangYaRoutePrime", daemon=True).start()

    def _post_command(self, event_data: Dict[str, Any], title: str, text: str = "") -> None:
        channel = event_data.get("channel")
        userid = event_data.get("userid") or event_data.get("user")
        source = event_data.get("source")
        try:
            self.post_message(
                channel=channel, source=source, userid=userid,
                title=title, text=text, save_history=False,
            )
        except Exception as err:
            self._plugin_log("WARNING", "【光鸭转存助手】【消息命令】回复失败：%s", err)

    @eventmanager.register(EventType.PluginAction)
    def action_event_handler(self, event: Event) -> None:
        event_data = event.event_data or {}
        action = event_data.get("action")
        if action == "guangya_direct_subscribe":
            self._handle_direct_subscribe_command(event_data)
        elif action == "guangya_route_status":
            self._handle_status_command(event_data)
        elif action == "guangya_release_native":
            self._handle_release_native_command(event_data)

    def _direct_tmdb_candidates(
        self, tmdb_id: str, mtype: Optional[MediaType], season: Optional[int],
    ) -> List[Any]:
        types = [mtype] if mtype else [MediaType.MOVIE, MediaType.TV]
        results = []
        seen = set()
        for candidate_type in types:
            try:
                recognize = getattr(self, "_recognize_media_cached_v208", None)
                if callable(recognize):
                    info = recognize(
                        mtype=candidate_type,
                        media_source=MediaSource.TMDB,
                        media_id=str(tmdb_id),
                        cache=False,
                    )
                else:
                    info = MediaChain().recognize_media(
                        mtype=candidate_type,
                        media_source=MediaSource.TMDB,
                        media_id=str(tmdb_id),
                        cache=False,
                    )
            except Exception:
                info = None
            if not info:
                continue
            key = (str(getattr(info, "tmdb_id", "") or tmdb_id), _enum_value(getattr(info, "type", candidate_type)))
            if key in seen:
                continue
            seen.add(key)
            if candidate_type == MediaType.TV and season is not None:
                setattr(info, "season", season)
            results.append(info)
        return results

    def _search_direct_candidates(self, request: Dict[str, Any]) -> List[Any]:
        if request.get("tmdb_id"):
            return self._direct_tmdb_candidates(request["tmdb_id"], request.get("mtype"), request.get("season"))
        title = str(request.get("title") or "").strip()
        if not title:
            return []
        _, medias = MediaChain().search(title=title, media_source=MediaSource.TMDB)
        candidates = []
        for info in medias or []:
            if request.get("mtype") and getattr(info, "type", None) != request["mtype"]:
                continue
            if request.get("year") and str(getattr(info, "year", "") or "") != str(request["year"]):
                continue
            candidates.append(info)
        if len(candidates) <= 1:
            return candidates
        query_norm = _normalize_media_text(title)
        exact = [
            info for info in candidates
            if query_norm and query_norm in {
                _normalize_media_text(getattr(info, "title", "")),
                _normalize_media_text(getattr(info, "en_title", "")),
            }
        ]
        return exact if exact else candidates

    @staticmethod
    def _candidate_tmdb_id(info: Any) -> str:
        return str(getattr(info, "tmdb_id", None) or getattr(info, "media_id", None) or "").strip()

    @staticmethod
    def _candidate_type_token(info: Any) -> str:
        return "tv" if getattr(info, "type", None) == MediaType.TV else "movie"

    def _format_candidate_choices(self, candidates: List[Any], season: Optional[int]) -> str:
        rows = []
        for info in candidates[:6]:
            tmdb_id = self._candidate_tmdb_id(info)
            if not tmdb_id:
                continue
            command = f"/gysub tmdb:{tmdb_id} {self._candidate_type_token(info)}"
            if getattr(info, "type", None) == MediaType.TV and season is not None:
                command += f" S{int(season):02d}"
            rows.append(
                f"• {getattr(info, 'title', '')} ({getattr(info, 'year', '') or '-'}) [{self._candidate_type_token(info)}] TMDB {tmdb_id}\n  {command}"
            )
        return "\n".join(rows)

    def _handle_direct_subscribe_command(self, event_data: Dict[str, Any]) -> None:
        if not self._enabled:
            self._post_command(event_data, "光鸭转存助手未启用", "请先启用插件后再使用 /gysub。")
            return
        request = _parse_direct_subscribe_args(event_data.get("arg_str"))
        if not request.get("title") and not request.get("tmdb_id"):
            self._post_command(
                event_data,
                "光鸭直订用法",
                "/gysub 片名 [年份] [movie|tv] [S01]\n"
                "例如：/gysub 沙丘 2021 movie\n"
                "精确订阅：/gysub tmdb:438631 movie",
            )
            return
        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【消息命令v1.12.8】已收到 /gysub 请求，开始识别媒体",
        )
        self._post_command(
            event_data,
            "⏳ 已收到光鸭直订请求",
            "正在识别媒体并创建订阅；识别完成后会继续回传结果。",
        )
        try:
            candidates = self._search_direct_candidates(request)
        except Exception as err:
            self._plugin_log("EXCEPTION", "【光鸭转存助手】【命令订阅】媒体搜索失败：%s", err)
            self._post_command(event_data, "光鸭直订失败", f"MoviePilot 媒体搜索失败：{err}")
            return
        if not candidates:
            self._post_command(event_data, "未找到媒体", "请补充年份/类型，或使用 /gysub tmdb:ID movie|tv 精确订阅。")
            return
        if len(candidates) > 1:
            self._post_command(
                event_data,
                "找到多个候选，请精确选择",
                self._format_candidate_choices(candidates, request.get("season")) or "请补充年份或媒体类型。",
            )
            return

        info = candidates[0]
        mtype = getattr(info, "type", None) or request.get("mtype")
        if mtype not in (MediaType.MOVIE, MediaType.TV):
            self._post_command(event_data, "光鸭直订失败", "当前只支持电影和电视剧转存订阅。")
            return
        tmdb_id = self._candidate_tmdb_id(info)
        if not tmdb_id:
            self._post_command(event_data, "光鸭直订失败", "候选媒体缺少 TMDB 身份，无法建立精确转存订阅。")
            return
        season = request.get("season")
        if mtype == MediaType.TV and season is None:
            season = int(getattr(info, "season", None) or 1)
        if mtype == MediaType.MOVIE:
            season = None
        provisional = _route_identity(MediaSource.TMDB, tmdb_id, season)
        if provisional:
            self._provisional_routes.add(provisional)
        try:
            sid, message = SubscribeChain().add(
                title=str(getattr(info, "title", "") or request.get("title") or ""),
                year=str(getattr(info, "year", "") or request.get("year") or ""),
                mtype=mtype,
                media_source=MediaSource.TMDB,
                media_id=tmdb_id,
                season=season,
                exist_ok=True,
                username="光鸭消息订阅",
                message=False,
            )
        except Exception as err:
            sid, message = None, str(err)
        if not sid:
            self._provisional_routes.discard(provisional)
            self._plugin_log("WARNING", "【光鸭转存助手】【命令订阅】创建失败：%s", message)
            self._post_command(event_data, "光鸭直订失败", str(message or "MoviePilot 未创建订阅"))
            return

        self._add_selected_subscription(int(sid), persist=True)
        self._provisional_routes.discard(provisional)
        subscribe = self._find_subscription(int(sid))
        media_text = f"{getattr(subscribe or info, 'name', None) or getattr(info, 'title', '')} ({getattr(subscribe or info, 'year', '') or '-'})"
        if mtype == MediaType.TV:
            media_text += f" S{int(season or 1):02d}"
        self._plugin_log("INFO", "【光鸭转存助手】【命令订阅】#%s %s 已直接加入光鸭固定转存路线", sid, media_text)
        self._post_command(
            event_data,
            "✅ 已加入光鸭转存订阅",
            f"媒体：{media_text}\n订阅ID：{sid}\n路线：只走光鸭转存，MoviePilot 原生下载搜索已阻断\n后续：正在立即刷新频道并尝试转存",
        )
        self._spawn_command_transfer(int(sid), event_data)

    def _spawn_command_transfer(self, sid: int, event_data: Dict[str, Any]) -> None:
        snapshot = dict(event_data)

        def worker() -> None:
            try:
                self.refresh_channels(force=True)
                self._inspect_cache.clear()
                subscribe = self._find_subscription(sid)
                if not subscribe or not self._is_guangya_route(subscribe):
                    return
                result = self._try_transfer_subscription(subscribe, refresh_channel=False)
                message = str(result.get("message") or "检查完成")
                self._record_route_health(last_command_transfer_at=self._now_text(), last_route_result=message[:500])
                self._post_command(snapshot, "光鸭直订检查完成", f"{getattr(subscribe, 'name', '')} #{sid}\n{message}")
            except Exception as err:
                self._plugin_log("EXCEPTION", "【光鸭转存助手】【命令订阅】#%s 立即转存检查异常：%s", sid, err)
                self._post_command(snapshot, "光鸭直订检查失败", f"订阅 #{sid}\n{err}")

        threading.Thread(target=worker, name=f"GuangYaDirectSubscribe-{sid}", daemon=True).start()

    def _resolve_selected_subscription(self, value: Any) -> Tuple[Optional[Any], List[Any]]:
        query = str(value or "").strip()
        selected = set(self._selected_subscriptions)
        candidates = [item for item in self._list_subscriptions(None) if int(getattr(item, "id", 0) or 0) in selected]
        if query.isdigit():
            exact = [item for item in candidates if int(getattr(item, "id", 0) or 0) == int(query)]
            return (exact[0] if len(exact) == 1 else None), exact
        normalized = _normalize_media_text(query)
        matched = [item for item in candidates if normalized and normalized in _normalize_media_text(getattr(item, "name", ""))]
        exact = [item for item in matched if _normalize_media_text(getattr(item, "name", "")) == normalized]
        if len(exact) == 1:
            return exact[0], exact
        return (matched[0] if len(matched) == 1 else None), matched

    def _handle_release_native_command(self, event_data: Dict[str, Any]) -> None:
        query = str(event_data.get("arg_str") or "").strip()
        if not query:
            self._post_command(event_data, "切回普通下载用法", "/gynative 订阅ID或片名")
            return
        subscribe, matches = self._resolve_selected_subscription(query)
        if not subscribe:
            if matches:
                text = "\n".join(f"• #{getattr(item, 'id', 0)} {getattr(item, 'name', '')}" for item in matches[:10])
                self._post_command(event_data, "匹配到多个转存订阅", text + "\n请改用订阅ID。")
            else:
                self._post_command(event_data, "未找到转存订阅", "请先用 /gystatus 查看当前固定转存订阅。")
            return
        sid = int(getattr(subscribe, "id", 0) or 0)
        self._remove_selected_subscription(sid)
        self._plugin_log("WARNING", "【光鸭转存助手】【消息命令】#%s %s 已切回 MoviePilot 普通下载", sid, getattr(subscribe, "name", ""))
        self._post_command(
            event_data,
            "↪️ 已切回普通下载",
            f"{getattr(subscribe, 'name', '')} #{sid}\n已立即解除光鸭硬分流；后续由 MoviePilot 原生订阅搜索处理。",
        )

    def _handle_status_command(self, event_data: Dict[str, Any]) -> None:
        health = self.get_data("route_health") or {}
        index = self.get_data("channel_index") or {}
        jobs = list((self.get_data("transfer_jobs") or {}).values())
        pending = sum(1 for row in jobs if isinstance(row, dict) and str(row.get("status") or "") in {"submitted", "task_confirmed", "verifying"})
        failed = sum(1 for row in jobs if isinstance(row, dict) and str(row.get("status") or "") == "failed")
        selected = []
        selected_ids = set(self._selected_subscriptions)
        for sub in self._list_subscriptions(None):
            if int(getattr(sub, "id", 0) or 0) in selected_ids:
                selected.append(f"#{getattr(sub, 'id', 0)} {getattr(sub, 'name', '')}")
        text = (
            f"硬分流：{'正常' if self._is_search_guard_active() else '未接管'}\n"
            f"固定转存订阅：{len(selected_ids)}\n"
            f"频道索引：{len(index.get('items') or [])} 条，最近刷新 {index.get('time') or '-'}\n"
            f"待落盘：{pending}，失败任务：{failed}\n"
            f"最近硬分流：{health.get('last_guarded_at') or '-'} {health.get('last_guarded_name') or ''}\n"
            f"最近结果：{health.get('last_route_result') or '-'}"
        )
        if selected:
            text += "\n\n当前路线：\n" + "\n".join(selected[:12])
            if len(selected) > 12:
                text += f"\n…另有 {len(selected) - 12} 个"
        self._post_command(event_data, "光鸭转存状态", text)

    @staticmethod
    def _normalize_page_api_auth(node: Any) -> None:
        """V3 页面 API 按官方约定使用 apikey，修复 token 参数导致的鉴权/登录页跳转。"""
        if isinstance(node, dict):
            events = node.get("events")
            if isinstance(events, dict):
                click = events.get("click")
                if isinstance(click, dict) and str(click.get("api") or "").startswith("plugin/GuangYaTransferAssistant/"):
                    params = click.setdefault("params", {})
                    if isinstance(params, dict):
                        params.pop("token", None)
                        try:
                            from app.sdk.config import settings
                            params.setdefault("apikey", settings.API_TOKEN)
                        except Exception:
                            pass
            for value in node.values():
                GuangYaTransferAssistant._normalize_page_api_auth(value)
        elif isinstance(node, list):
            for value in node:
                GuangYaTransferAssistant._normalize_page_api_auth(value)

    def get_form(self):
        form, defaults = super().get_form()
        try:
            content = form[0].get("content") if form else None
            if isinstance(content, list):
                content.append({
                    "component": "VAlert",
                    "props": {
                        "type": "success",
                        "variant": "tonal",
                        "text": "v1.7 硬分流：已选订阅会在 SubscribeChain.search 全入口被拦截，不再进入本地下载检测。消息可直接使用 /gysub 片名 年份 movie|tv S01；/gystatus 查看状态；/gynative ID 切回普通下载。新加入转存路线会立即刷新频道检查资源，无需等待下一轮。",
                    },
                })
        except Exception:
            pass
        return form, defaults

    def get_page(self):
        pages = super().get_page() or []
        self._normalize_page_api_auth(pages)
        health = self.get_data("route_health") or {}
        guard_ok = self._is_search_guard_active()
        header = {
            "component": "VAlert",
            "props": {
                "type": "success" if guard_ok else "error",
                "variant": "tonal",
                "class": "mb-3",
                "title": "固定分流路由健康",
                "text": (
                    f"SubscribeChain.search 全入口硬分流：{'已接管' if guard_ok else '未接管'} · "
                    f"固定转存订阅 {len(self._selected_subscriptions)} 个 · "
                    f"最近拦截 {health.get('last_guarded_at') or '-'} · "
                    "页面操作已统一使用 V3 apikey 鉴权；切换普通下载先更新运行态、请求返回后再延迟持久化，不再因插件热重载跳转登录页。"
                ),
            },
        }
        return [header, *pages]

    def stop_service(self) -> None:
        try:
            super().stop_service()
        finally:
            self._restore_search_guard()
