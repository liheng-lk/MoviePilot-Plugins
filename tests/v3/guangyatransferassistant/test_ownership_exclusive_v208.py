"""2.0.8 P0：接管订阅 exclusive ownership — 绑定 production routing/runtime，统计 native 调用次数。"""

from __future__ import annotations

import ast
import inspect
import types
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ROUTING_PATH = PLUGIN / "routing_v170.py"
RUNTIME_PATH = PLUGIN / "runtime_v170.py"
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
ROUTING = ROUTING_PATH.read_text(encoding="utf-8")
RUNTIME = RUNTIME_PATH.read_text(encoding="utf-8")
LEGACY = (PLUGIN / "legacy.py").read_text(encoding="utf-8")


def test_v208_version_and_ownership_contracts():
    assert 'plugin_version = "2.0.8"' in ENTRY
    assert 'build_id = "20260911-r92"' in ENTRY
    assert "def _is_managed_subscription(" in ROUTING
    assert "def _is_managed_sid(" in ROUTING
    assert "【路由】" in ROUTING
    assert "guangya_only" in ROUTING
    assert "本轮取消周期搜索" in ROUTING
    assert "_is_managed_subscription" in RUNTIME
    assert "原生阻断" in RUNTIME
    assert "regeng115" in LEGACY and "vip115hot" in LEGACY
    assert "115Client" not in LEGACY
    assert "class GuangYa115" not in LEGACY


def _extract_class_methods(source: str, class_name: str, method_names: List[str]) -> Dict[str, Any]:
    tree = ast.parse(source)
    class_node = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    selected = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {
            "_flatten_bound_search_kwargs",
        }:
            selected.append(node)
    for node in class_node.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in method_names:
            selected.append(node)
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    ns: Dict[str, Any] = {
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "Optional": Optional,
        "inspect": inspect,
        "SubscribeChain": None,
    }
    exec(compile(module, "<ownership>", "exec"), ns)
    return ns


def _as_static(fn):
    def wrapper(self, *args, **kwargs):
        return fn(*args, **kwargs)
    return wrapper


def _make_sub(sid: int, *, state: str = "R"):
    return types.SimpleNamespace(id=sid, name=f"sub-{sid}", state=state)


class _ProdPlugin:
    def __init__(self, selected=None):
        self._enabled = True
        self._selected_subscriptions = list(selected or [])
        self._provisional_routes = set()
        self._inspect_cache = {}
        self._subs: Dict[int, Any] = {}
        self.guarded: List[int] = []
        self.logs: List[str] = []
        self.list_calls = 0
        self.queued: List[List[int]] = []
        self.fail_mode: Optional[str] = None

    def _runtime_is_current(self):
        return True

    def register(self, *subs):
        for sub in subs:
            self._subs[int(sub.id)] = sub

    def _find_subscription(self, sid):
        return self._subs.get(int(sid))

    def _list_subscriptions(self, state="N,R"):
        self.list_calls += 1
        wanted = {t.strip() for t in str(state or "").split(",") if t.strip()}
        return [s for s in self._subs.values() if str(s.state) in wanted]

    def _is_guangya_route(self, subscribe):
        return int(subscribe.id) in set(self._selected_subscriptions)

    def _queue_async_route_check(self, ids, trigger=""):
        self.queued.append(list(ids))

    def _plugin_log(self, *a, **k):
        self.logs.append(" ".join(str(x) for x in a))

    def _record_route_health(self, **fields):
        return None

    @staticmethod
    def _now_text():
        return "2026-09-11 00:00:00"

    def _cached_matches_for_subscription(self, subscribe):
        return True

    def refresh_channels(self, force=False):
        return None

    def _try_transfer_subscription(self, subscribe, refresh_channel=False):
        self.guarded.append(int(subscribe.id))
        if self.fail_mode == "timeout":
            return {"success": False, "handled": False, "message": "channel timeout", "retryable": True}
        if self.fail_mode == "no_match":
            return {"success": False, "handled": False, "message": "resource_filtered", "retryable": True}
        if self.fail_mode == "no_new_episode":
            return {"success": True, "handled": True, "message": "no_new_episode", "retryable": False}
        return {"success": True, "handled": True, "message": "ok"}


def _attach_routing(plugin: _ProdPlugin) -> _ProdPlugin:
    methods = _extract_class_methods(
        ROUTING,
        "GuangYaTransferAssistant",
        [
            "_normalize_search_call",
            "_bind_search_args",
            "_load_due_search_subscriptions",
            "_call_original_search",
            "_is_active_transfer_state",
            "_is_managed_sid",
            "_is_managed_subscription",
            "_route_trace",
            "_guard_one_subscription",
            "_guard_subscribe_search",
        ],
    )
    plugin._normalize_search_call = types.MethodType(
        _as_static(methods["_normalize_search_call"]), plugin
    )
    plugin._bind_search_args = types.MethodType(
        _as_static(methods["_bind_search_args"]), plugin
    )
    plugin._is_active_transfer_state = types.MethodType(
        _as_static(methods["_is_active_transfer_state"]), plugin
    )
    plugin._call_original_search = types.MethodType(methods["_call_original_search"], plugin)
    plugin._load_due_search_subscriptions = types.MethodType(
        methods["_load_due_search_subscriptions"], plugin
    )
    plugin._is_managed_sid = types.MethodType(methods["_is_managed_sid"], plugin)
    plugin._is_managed_subscription = types.MethodType(
        methods["_is_managed_subscription"], plugin
    )
    plugin._route_trace = types.MethodType(methods["_route_trace"], plugin)
    plugin._guard_one_subscription = types.MethodType(methods["_guard_one_subscription"], plugin)
    plugin._guard_subscribe_search = types.MethodType(methods["_guard_subscribe_search"], plugin)
    return plugin


def _attach_runtime(plugin: _ProdPlugin, subscribe_chain_cls) -> _ProdPlugin:
    tree = ast.parse(RUNTIME)
    class_node = next(
        n for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name == "GuangYaRuntimeFinalizerMixin"
    )
    selected = [
        n for n in class_node.body
        if isinstance(n, ast.FunctionDef)
        and n.name in {"_dispatch_subscribe_search", "_runtime_call_native_search"}
    ]
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    ns = {
        "inspect": inspect,
        "List": List,
        "Dict": Dict,
        "Any": Any,
        "Optional": Optional,
        "SubscribeChain": subscribe_chain_cls,
    }
    exec(compile(module, str(RUNTIME_PATH), "exec"), ns)
    plugin._dispatch_subscribe_search = types.MethodType(ns["_dispatch_subscribe_search"], plugin)
    plugin._runtime_call_native_search = types.MethodType(ns["_runtime_call_native_search"], plugin)
    return plugin


class _NativeCounter:
    def __init__(self):
        self.calls: List[Dict[str, Any]] = []

    @property
    def count(self) -> int:
        return len(self.calls)

    def received_ids(self) -> set:
        ids = set()
        for row in self.calls:
            if row.get("sid") is not None:
                ids.add(int(row["sid"]))
            for value in row.get("sids") or ():
                ids.add(int(value))
        return ids


def _make_original(counter: _NativeCounter):
    def original(chain_self, **kwargs):
        counter.calls.append(dict(kwargs))
        return "native"

    return original


# --- Cases ---


def test_case1_managed_sid_native_zero():
    plugin = _attach_routing(_ProdPlugin(selected=[1]))
    plugin.register(_make_sub(1))
    counter = _NativeCounter()
    plugin._guard_subscribe_search(
        original=_make_original(counter),
        chain_self=object(),
        kwargs={"sid": 1},
    )
    assert plugin.guarded == [1]
    assert counter.count == 0


def test_case2_unmanaged_sid_native_one():
    plugin = _attach_routing(_ProdPlugin(selected=[]))
    plugin.register(_make_sub(2))
    counter = _NativeCounter()
    plugin._guard_subscribe_search(
        original=_make_original(counter),
        chain_self=object(),
        kwargs={"sid": 2},
    )
    assert plugin.guarded == []
    assert counter.count == 1
    assert counter.received_ids() == {2}


def test_case3_sids_split_managed_native():
    plugin = _attach_routing(_ProdPlugin(selected=[1, 3]))
    for sid in (1, 2, 3, 4):
        plugin.register(_make_sub(sid))
    counter = _NativeCounter()
    plugin._guard_subscribe_search(
        original=_make_original(counter),
        chain_self=object(),
        kwargs={"sids": (1, 2, 3, 4)},
    )
    assert set(plugin.guarded) == {1, 3}
    assert counter.count == 1
    assert counter.received_ids() == {2, 4}


def test_case4_scheduled_due_split():
    """A managed due, B native due, C managed not due, D native not due."""
    plugin = _attach_routing(_ProdPlugin(selected=[1, 3]))
    a, b, c, d = (_make_sub(1), _make_sub(2), _make_sub(3), _make_sub(4))
    plugin.register(a, b, c, d)
    counter = _NativeCounter()

    class Chain:
        def _load_search_subscriptions(self, sid=None, sids=None, state=None, scheduled_interval=None):
            return [a, b]  # only due

    plugin._guard_subscribe_search(
        original=_make_original(counter),
        chain_self=Chain(),
        kwargs={"state": "R", "scheduled_interval": 24},
    )
    assert plugin.guarded == [1]
    assert counter.count == 1
    assert counter.received_ids() == {2}
    assert 3 not in plugin.guarded and 4 not in counter.received_ids()
    assert counter.calls[0].get("scheduled_interval") is None


def test_case5_managed_fail_timeout_no_native():
    plugin = _attach_routing(_ProdPlugin(selected=[9]))
    plugin.register(_make_sub(9))
    plugin.fail_mode = "timeout"
    counter = _NativeCounter()
    plugin._guard_subscribe_search(
        original=_make_original(counter),
        chain_self=object(),
        kwargs={"sid": 9},
    )
    assert counter.count == 0
    assert plugin.guarded == [9]


def test_case6_managed_no_match_no_native():
    plugin = _attach_routing(_ProdPlugin(selected=[9]))
    plugin.register(_make_sub(9))
    plugin.fail_mode = "no_match"
    counter = _NativeCounter()
    plugin._guard_subscribe_search(
        original=_make_original(counter),
        chain_self=object(),
        kwargs={"sid": 9},
    )
    assert counter.count == 0


def test_case7_managed_no_new_episode_no_native():
    plugin = _attach_routing(_ProdPlugin(selected=[9]))
    plugin.register(_make_sub(9))
    plugin.fail_mode = "no_new_episode"
    counter = _NativeCounter()
    plugin._guard_subscribe_search(
        original=_make_original(counter),
        chain_self=object(),
        kwargs={"sid": 9},
    )
    assert counter.count == 0


def test_case8_cancel_takeover_restores_native_without_reload():
    plugin = _attach_routing(_ProdPlugin(selected=[5]))
    plugin.register(_make_sub(5))
    counter = _NativeCounter()
    plugin._guard_subscribe_search(
        original=_make_original(counter),
        chain_self=object(),
        kwargs={"sid": 5},
    )
    assert counter.count == 0
    plugin._selected_subscriptions = []  # 动态取消接管
    plugin._guard_subscribe_search(
        original=_make_original(counter),
        chain_self=object(),
        kwargs={"sid": 5},
    )
    assert counter.count == 1
    assert counter.received_ids() == {5}


def test_case9_manual_managed_still_blocks_native():
    plugin = _attach_routing(_ProdPlugin(selected=[7]))
    plugin.register(_make_sub(7))
    counter = _NativeCounter()
    plugin._guard_subscribe_search(
        original=_make_original(counter),
        chain_self=object(),
        kwargs={"sid": 7, "manual": True},
    )
    assert counter.count == 0
    assert plugin.guarded == [7]


def test_case10_runtime_queue_fence_managed_skips_native():
    """调度分流：managed sid 即使出现在宿主队列语义下也不得交还原生。"""
    counter = _NativeCounter()

    class FakeSC:
        def search(self, **kwargs):
            counter.calls.append(dict(kwargs))
            return "native"

    plugin = _ProdPlugin(selected=[11])
    plugin.register(_make_sub(11))
    _attach_routing(plugin)
    _attach_runtime(plugin, FakeSC)
    plugin._dispatch_subscribe_search(sid=11)
    assert counter.count == 0
    assert plugin.queued and 11 in plugin.queued[0]


def test_case11_download_breaker_uses_managed_helper():
    assert "_is_managed_subscription" in ENTRY
    assert "【下载断路器】" in ENTRY
    breaker = ENTRY.split("def guarded_download(", 1)[1].split("def _restore_match_guard", 1)[0]
    assert "owned(subscribe)" in breaker or "_is_managed_subscription" in breaker


def test_case12_mixed_batch_100_only_80_native():
    managed = list(range(1, 21))
    native = list(range(21, 101))
    plugin = _attach_routing(_ProdPlugin(selected=managed))
    for sid in managed + native:
        plugin.register(_make_sub(sid))
    counter = _NativeCounter()
    plugin._guard_subscribe_search(
        original=_make_original(counter),
        chain_self=object(),
        kwargs={"sids": tuple(managed + native)},
    )
    assert set(plugin.guarded) == set(managed)
    assert counter.count == 1
    assert counter.received_ids() == set(native)
    assert not (counter.received_ids() & set(managed))


def test_runtime_due_failure_never_reloads_managed_via_interval():
    counter = _NativeCounter()

    class FakeSC:
        def search(self, **kwargs):
            counter.calls.append(dict(kwargs))
            return "native"

    plugin = _ProdPlugin(selected=[1])
    plugin.register(_make_sub(1), _make_sub(2))
    _attach_routing(plugin)
    _attach_runtime(plugin, FakeSC)

    def boom_loader(probe, state="R", scheduled_interval=None):
        return None

    plugin._load_due_search_subscriptions = boom_loader
    result = plugin._dispatch_subscribe_search(state="R", scheduled_interval=24, manual=False)
    assert result is True
    assert counter.count == 0
    assert plugin.queued == []
    assert plugin.list_calls == 0


def test_managed_inactive_ps_still_blocks_native():
    plugin = _attach_routing(_ProdPlugin(selected=[8]))
    plugin.register(_make_sub(8, state="P"))
    counter = _NativeCounter()
    plugin._guard_subscribe_search(
        original=_make_original(counter),
        chain_self=object(),
        kwargs={"sid": 8},
    )
    assert counter.count == 0
    assert 8 not in plugin.guarded  # 非活跃不转存，但仍阻断
