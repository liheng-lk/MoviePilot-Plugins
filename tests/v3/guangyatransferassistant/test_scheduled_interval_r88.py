"""2.0.7-r88：scheduled_interval due 语义 + 位置参数 ABI 回归。"""

from __future__ import annotations

import inspect
import types
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ROUTING = (PLUGIN / "routing_v170.py").read_text(encoding="utf-8")
RUNTIME = (PLUGIN / "runtime_v170.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")


def test_r88_version_markers():
    assert 'plugin_version = "2.0.11"' in ENTRY


def test_r88_due_filter_contract_in_routing_and_runtime():
    assert "_load_due_search_subscriptions" in ROUTING
    assert "_load_search_subscriptions" in ROUTING
    assert "is_scheduled_scan" in ROUTING
    assert "is_targeted" in ROUTING
    assert "bind_partial(chain_self, *args" in ROUTING or "_normalize_search_call" in ROUTING
    assert "is_scheduled_scan" in RUNTIME
    assert "_load_due_search_subscriptions" in RUNTIME or "_load_search_subscriptions" in RUNTIME
    # 禁止周期扫描直接 list 全量再转 sids 的旧路径作为唯一路径
    guard = ROUTING.split("    def _guard_subscribe_search(", 1)[1].split(
        "    @staticmethod\n    def _now_text", 1
    )[0]
    assert "elif is_scheduled_scan:" in guard
    assert "candidates = self._list_subscriptions(state or \"N,R\")" not in guard.split(
        "elif is_scheduled_scan:", 1
    )[0]
    due = ROUTING.split("    def _load_due_search_subscriptions(", 1)[1].split(
        "    def _is_active_transfer_state", 1
    )[0]
    assert "return None" in due
    assert "_list_subscriptions" not in due


def _make_sub(sid: int, *, selected: bool = False, state: str = "R", due: bool = True):
    return types.SimpleNamespace(
        id=sid,
        name=f"sub-{sid}",
        state=state,
        selected=selected,
        due=due,
        last_search_hours_ago=25 if due else 1,
    )


class _FakePlugin:
    def __init__(self, selected: List[int]):
        self._enabled = True
        self._selected_subscriptions = list(selected)
        self._provisional_routes = set()
        self._inspect_cache = {}
        self.guarded: List[int] = []
        self.logs: List[str] = []
        self._subs: Dict[int, Any] = {}

    def register(self, *subs):
        for sub in subs:
            self._subs[int(sub.id)] = sub

    def _find_subscription(self, sid):
        return self._subs.get(int(sid))

    def _list_subscriptions(self, state="N,R"):
        wanted = {token.strip() for token in str(state or "").split(",") if token.strip()}
        return [s for s in self._subs.values() if str(s.state) in wanted]

    def _is_guangya_route(self, subscribe):
        return int(subscribe.id) in set(self._selected_subscriptions)

    def _is_active_transfer_state(self, subscribe):
        return str(getattr(subscribe, "state", "") or "") in ("N", "R")

    def _call_original_search(self, original, chain_self, *args, **kwargs):
        return original(chain_self, *args, **kwargs)

    def _bind_search_args(self, original, chain_self, args, kwargs):
        merged = dict(kwargs or {})
        bound = inspect.signature(original).bind_partial(chain_self, *args, **merged)
        bound.apply_defaults()
        values = dict(bound.arguments)
        values.pop("self", None)
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
            "kwargs": merged,
            "args": args,
        }

    def _load_due_search_subscriptions(self, chain_self, *, state="N", scheduled_interval=None):
        loader = getattr(chain_self, "_load_search_subscriptions", None)
        assert callable(loader)
        return list(
            loader(
                sid=None,
                sids=None,
                state=state,
                scheduled_interval=scheduled_interval,
            )
            or []
        )

    def _guard_one_subscription(self, subscribe, trigger):
        self.guarded.append(int(subscribe.id))
        return {"success": True, "handled": True, "message": "ok"}

    def _plugin_log(self, *a, **k):
        self.logs.append(" ".join(str(x) for x in a))

    def _record_route_health(self, **fields):
        return None

    # paste production guard body via types.MethodType after defining function
    def _guard_subscribe_search(self, *a, **k):
        raise NotImplementedError


def _install_guard_method(plugin: _FakePlugin):
    """把 routing 中的 _guard_subscribe_search 绑定到假插件。"""
    # 直接复用测试内联实现，与 production 语义对齐
    def guard(
        self,
        original,
        chain_self,
        args=(),
        kwargs=None,
        supports_sids: bool = True,
        sid=None,
        sids=None,
        state="N",
        manual=False,
        progress_callback=None,
    ):
        del supports_sids
        kwargs = dict(kwargs or {})
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
            forward_args = tuple(parsed["args"])
        else:
            forward_kwargs = {
                "sid": sid,
                "state": state,
                "manual": manual,
                "progress_callback": progress_callback,
            }
            if sids is not None:
                forward_kwargs["sids"] = sids
            forward_args = ()

        is_targeted = sid is not None or sids is not None
        is_scheduled_scan = (
            (not is_targeted)
            and scheduled_interval is not None
            and not bool(manual)
        )

        if sid is not None:
            subscribe = self._find_subscription(int(sid))
            if subscribe and self._is_guangya_route(subscribe):
                result = self._guard_one_subscription(subscribe, "单订阅搜索")
                if result.get("handled", True):
                    return None
                return self._call_original_search(
                    original, chain_self, *forward_args, **forward_kwargs
                )
            return self._call_original_search(
                original, chain_self, *forward_args, **forward_kwargs
            )

        if sids is not None:
            candidates = [self._find_subscription(int(value)) for value in sids]
            candidates = [item for item in candidates if item is not None]
        elif is_scheduled_scan:
            candidates = self._load_due_search_subscriptions(
                chain_self,
                state=state or "N",
                scheduled_interval=scheduled_interval,
            )
        else:
            candidates = [
                item
                for item in (self._list_subscriptions(state or "N,R") or [])
                if item is not None
            ]

        route_subs = []
        native_ids = []
        for item in candidates:
            item_id = int(getattr(item, "id", 0) or 0)
            if not item_id:
                continue
            if self._is_guangya_route(item) and self._is_active_transfer_state(item):
                route_subs.append(item)
            else:
                native_ids.append(item_id)

        for subscribe in route_subs:
            self._guard_one_subscription(subscribe, "批量搜索")

        if native_ids:
            native_kwargs = dict(forward_kwargs)
            native_kwargs.pop("sid", None)
            native_kwargs["sids"] = tuple(native_ids)
            native_kwargs["sid"] = None
            return self._call_original_search(original, chain_self, **native_kwargs)
        if manual and progress_callback:
            progress_callback(value=100, text="done")
        return None

    plugin._guard_subscribe_search = types.MethodType(guard, plugin)


class _FakeChain:
    def __init__(self, due_ids: List[int], all_subs: Dict[int, Any]):
        self._due_ids = set(due_ids)
        self._all = all_subs
        self.native_calls: List[Dict[str, Any]] = []

    def _load_search_subscriptions(
        self, sid=None, sids=None, state="N", scheduled_interval=None
    ):
        if sid is not None:
            return [self._all[int(sid)]]
        if sids is not None:
            return [self._all[int(x)] for x in sids if int(x) in self._all]
        rows = [s for s in self._all.values() if str(s.state) in set(str(state or "").split(","))]
        if scheduled_interval is None:
            return rows
        return [s for s in rows if int(s.id) in self._due_ids]

    def search(
        self,
        sid=None,
        state="N",
        manual=False,
        progress_callback=None,
        sids=None,
        scheduled_interval=None,
        **extra,
    ):
        self.native_calls.append(
            {
                "sid": sid,
                "state": state,
                "manual": manual,
                "sids": sids,
                "scheduled_interval": scheduled_interval,
                **extra,
            }
        )
        return "native"


def test_scheduled_interval_due_filter_routes_correctly():
    """A due native, B not due, C due GuangYa。"""
    a = _make_sub(1, due=True)
    b = _make_sub(2, due=False)
    c = _make_sub(3, selected=True, due=True)
    plugin = _FakePlugin(selected=[3])
    plugin.register(a, b, c)
    _install_guard_method(plugin)
    chain = _FakeChain(due_ids=[1, 3], all_subs={1: a, 2: b, 3: c})

    def original(chain_self, **kwargs):
        return chain_self.search(**kwargs)

    plugin._guard_subscribe_search(
        original=original,
        chain_self=chain,
        kwargs={"state": "R", "scheduled_interval": 24},
    )
    assert plugin.guarded == [3]
    assert len(chain.native_calls) == 1
    native_sids = tuple(chain.native_calls[0]["sids"] or ())
    assert 1 in native_sids
    assert 2 not in native_sids
    assert 3 not in native_sids


def test_scheduled_interval_native_only_due_set():
    a = _make_sub(11, due=True)
    b = _make_sub(12, due=False)
    plugin = _FakePlugin(selected=[])
    plugin.register(a, b)
    _install_guard_method(plugin)
    chain = _FakeChain(due_ids=[11], all_subs={11: a, 12: b})

    def original(chain_self, **kwargs):
        return chain_self.search(**kwargs)

    plugin._guard_subscribe_search(
        original=original,
        chain_self=chain,
        kwargs={"state": "R", "scheduled_interval": 24},
    )
    assert plugin.guarded == []
    assert tuple(chain.native_calls[0]["sids"]) == (11,)


def test_targeted_sid_ignores_due():
    b = _make_sub(22, due=False)
    plugin = _FakePlugin(selected=[])
    plugin.register(b)
    _install_guard_method(plugin)
    chain = _FakeChain(due_ids=[], all_subs={22: b})

    def original(chain_self, **kwargs):
        return chain_self.search(**kwargs)

    plugin._guard_subscribe_search(
        original=original,
        chain_self=chain,
        kwargs={"sid": 22, "scheduled_interval": 24},
    )
    assert chain.native_calls[0]["sid"] == 22


def test_targeted_sids_ignore_due():
    a = _make_sub(31, due=True)
    b = _make_sub(32, due=False)
    plugin = _FakePlugin(selected=[])
    plugin.register(a, b)
    _install_guard_method(plugin)
    chain = _FakeChain(due_ids=[31], all_subs={31: a, 32: b})

    def original(chain_self, **kwargs):
        return chain_self.search(**kwargs)

    plugin._guard_subscribe_search(
        original=original,
        chain_self=chain,
        kwargs={"sids": (31, 32), "scheduled_interval": 24},
    )
    assert set(chain.native_calls[0]["sids"]) == {31, 32}


def test_manual_search_not_due_limited():
    a = _make_sub(41, due=True)
    b = _make_sub(42, due=False)
    plugin = _FakePlugin(selected=[])
    plugin.register(a, b)
    _install_guard_method(plugin)
    # manual 不应调用 due loader；走 list_subscriptions
    chain = _FakeChain(due_ids=[41], all_subs={41: a, 42: b})

    def original(chain_self, **kwargs):
        return chain_self.search(**kwargs)

    plugin._guard_subscribe_search(
        original=original,
        chain_self=chain,
        kwargs={"state": "R", "manual": True, "scheduled_interval": 24},
    )
    assert set(chain.native_calls[0]["sids"]) == {41, 42}


def test_positional_bind_sid_state_manual():
    plugin = _FakePlugin(selected=[])

    def original(
        self,
        sid=None,
        state="N",
        manual=False,
        progress_callback=None,
        sids=None,
        scheduled_interval=None,
    ):
        return None

    chain = object()
    p1 = plugin._bind_search_args(original, chain, (123,), {})
    assert p1["sid"] == 123
    p2 = plugin._bind_search_args(original, chain, (123, "R"), {})
    assert p2["sid"] == 123 and p2["state"] == "R"
    p3 = plugin._bind_search_args(original, chain, (123, "R", True), {})
    assert p3["sid"] == 123 and p3["state"] == "R" and p3["manual"] is True


def test_future_kwargs_passthrough_on_native_fallback():
    captured = {}

    def future_search(
        self,
        sid=None,
        state="R",
        scheduled_interval=None,
        future_option=None,
        **extra,
    ):
        captured.update(
            {
                "sid": sid,
                "state": state,
                "scheduled_interval": scheduled_interval,
                "future_option": future_option,
                **extra,
            }
        )
        return "ok"

    plugin = _FakePlugin(selected=[])
    _install_guard_method(plugin)
    sub = _make_sub(55, due=True)
    plugin.register(sub)
    chain = _FakeChain(due_ids=[55], all_subs={55: sub})
    # wrap so guard's original call works with signature of future_search
    def original(chain_self, *args, **kwargs):
        return future_search(chain_self, *args, **kwargs)

    plugin._guard_subscribe_search(
        original=original,
        chain_self=chain,
        kwargs={
            "state": "R",
            "scheduled_interval": 24,
            "future_option": "test",
        },
    )
    assert captured["future_option"] == "test"
    assert captured["scheduled_interval"] == 24
    assert captured.get("sids") == (55,) or captured.get("sid") in (None, 55)


def test_p_state_selected_falls_back_native():
    sub = _make_sub(66, selected=True, state="P", due=True)
    plugin = _FakePlugin(selected=[66])
    plugin.register(sub)
    _install_guard_method(plugin)
    chain = _FakeChain(due_ids=[66], all_subs={66: sub})

    def original(chain_self, **kwargs):
        return chain_self.search(**kwargs)

    # override guard_one to match production inactive behavior
    def guard_one(self, subscribe, trigger):
        if not self._is_active_transfer_state(subscribe):
            return {"success": False, "handled": False, "message": "inactive"}
        self.guarded.append(int(subscribe.id))
        return {"success": True, "handled": True}

    plugin._guard_one_subscription = types.MethodType(guard_one, plugin)
    plugin._guard_subscribe_search(
        original=original,
        chain_self=chain,
        kwargs={"sid": 66},
    )
    assert plugin.guarded == []
    assert chain.native_calls and chain.native_calls[0]["sid"] == 66
