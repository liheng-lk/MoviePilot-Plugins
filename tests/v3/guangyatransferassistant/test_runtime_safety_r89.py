"""2.0.7-r89：直接绑定 production 实现的 runtime/due/progress 回归。"""

from __future__ import annotations

import ast
import inspect
import textwrap
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


def test_r89_version_markers():
    assert 'plugin_version = "2.0.7"' in ENTRY


def test_r89_source_contracts():
    assert "def _normalize_search_call(" in ROUTING
    assert "def _dispatch_subscribe_search(self, *args, progress_callback=None, **kwargs)" in RUNTIME
    assert "【due失败】" in ROUTING
    assert "【due失败】" in RUNTIME
    assert "_list_subscriptions(state or \"N,R\")" not in ROUTING.split(
        "def _load_due_search_subscriptions(", 1
    )[1].split("def _is_active_transfer_state", 1)[0]
    assert "except TypeError:" not in ROUTING.split(
        "def _load_due_search_subscriptions(", 1
    )[1].split("def _is_active_transfer_state", 1)[0]
    assert "SubscribeChain().search(*args, **forward_kwargs)" not in RUNTIME
    assert "return SubscribeChain().search(**forward_kwargs)" in RUNTIME
    assert '"scheduled_interval" in parameters' in ROUTING


def _extract_class_methods(source: str, class_name: str, method_names: List[str]) -> Dict[str, Any]:
    tree = ast.parse(source)
    class_node = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    selected = []
    # 模块级 helper（供 AST 抽出的方法引用，如 _flatten_bound_search_kwargs）
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {
            "_flatten_bound_search_kwargs",
        }:
            selected.append(node)
    for node in class_node.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in method_names:
            selected.append(node)
        if isinstance(node, ast.Assign):
            # skip
            pass
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    ns: Dict[str, Any] = {
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "Optional": Optional,
        "inspect": inspect,
        "SubscribeChain": None,  # filled by caller if needed
    }
    exec(compile(module, str(ROUTING_PATH), "exec"), ns)
    return ns


def _make_sub(sid: int, *, state: str = "R"):
    return types.SimpleNamespace(id=sid, name=f"sub-{sid}", state=state)


class _HostChain:
    def __init__(self, due_ids=None, boom=None, old_abi=False):
        self.due_ids = set(due_ids or [])
        self.boom = boom
        self.old_abi = old_abi
        self.calls: List[Dict[str, Any]] = []
        self.list_calls = 0

    def _load_search_subscriptions(self, sid=None, sids=None, state="N", scheduled_interval=None):
        if self.boom:
            raise self.boom
        if self.old_abi and scheduled_interval is not None:
            # Should never be called with scheduled_interval for old ABI tests
            raise AssertionError("old ABI received scheduled_interval")
        # signature of this method is inspected by production code
        return [types.SimpleNamespace(id=i, state="R", name=f"d{i}") for i in sorted(self.due_ids)]

    # for old ABI variant we replace this method in tests


def _as_static(fn):
    def wrapper(self, *args, **kwargs):
        return fn(*args, **kwargs)
    return wrapper


def _attach_production_routing(plugin):
    methods = _extract_class_methods(
        ROUTING,
        "GuangYaTransferAssistant",
        [
            "_normalize_search_call",
            "_bind_search_args",
            "_load_due_search_subscriptions",
            "_call_original_search",
            "_is_active_transfer_state",
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
    plugin._guard_one_subscription = types.MethodType(methods["_guard_one_subscription"], plugin)
    plugin._guard_subscribe_search = types.MethodType(methods["_guard_subscribe_search"], plugin)
    return plugin


def _attach_production_runtime(plugin):
    methods = _extract_class_methods(
        RUNTIME,
        "GuangYaRuntimeFinalizerMixin",
        ["_dispatch_subscribe_search", "_runtime_call_native_search"],
    )
    plugin._dispatch_subscribe_search = types.MethodType(
        methods["_dispatch_subscribe_search"], plugin
    )
    plugin._runtime_call_native_search = types.MethodType(
        methods["_runtime_call_native_search"], plugin
    )
    return plugin


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
        return "2026-09-10 00:00:00"

    def _cached_matches_for_subscription(self, subscribe):
        return True

    def refresh_channels(self, force=False):
        return None

    def _try_transfer_subscription(self, subscribe, refresh_channel=False):
        self.guarded.append(int(subscribe.id))
        return {"success": True, "handled": True, "message": "ok"}


def test_normalize_search_call_positional_no_duplicate():
    plugin = _attach_production_routing(_ProdPlugin())

    def search(self, sid=None, state="N", manual=False, progress_callback=None, sids=None, scheduled_interval=None, **extra):
        return {
            "sid": sid, "state": state, "manual": manual, "sids": sids,
            "scheduled_interval": scheduled_interval, **extra,
        }

    values = plugin._normalize_search_call(search, object(), (123, "R", True), {})
    assert values["sid"] == 123
    assert values["state"] == "R"
    assert values["manual"] is True
    # kwargs-only: calling with **values must not TypeError
    assert search(object(), **values)["sid"] == 123


def test_due_loader_fail_closed_does_not_list_all():
    plugin = _attach_production_routing(_ProdPlugin(selected=[]))
    plugin.register(_make_sub(1), _make_sub(2))
    chain = _HostChain(due_ids=[1], boom=RuntimeError("database unavailable"))
    result = plugin._load_due_search_subscriptions(chain, state="R", scheduled_interval=24)
    assert result is None
    assert plugin.list_calls == 0


def test_due_internal_typeerror_not_treated_as_old_abi():
    plugin = _attach_production_routing(_ProdPlugin())

    class Chain:
        def _load_search_subscriptions(self, sid=None, sids=None, state=None, scheduled_interval=None):
            raise TypeError("internal database object is not iterable")

    result = plugin._load_due_search_subscriptions(Chain(), state="R", scheduled_interval=24)
    assert result is None
    assert plugin.list_calls == 0
    assert any("due失败" in row for row in plugin.logs)


def test_old_moviepilot_abi_without_scheduled_interval():
    plugin = _attach_production_routing(_ProdPlugin())

    class OldChain:
        def _load_search_subscriptions(self, sid=None, sids=None, state=None):
            return [types.SimpleNamespace(id=9, state="R", name="old")]

    rows = plugin._load_due_search_subscriptions(OldChain(), state="R", scheduled_interval=24)
    assert rows is not None
    assert [int(x.id) for x in rows] == [9]


def test_guard_due_failure_forwards_original_not_all_sids():
    plugin = _attach_production_routing(_ProdPlugin(selected=[]))
    plugin.register(_make_sub(1), _make_sub(2))
    captured = {}

    def original(chain_self, **kwargs):
        captured["kwargs"] = dict(kwargs)
        return "native"

    class Chain:
        def _load_search_subscriptions(self, sid=None, sids=None, state=None, scheduled_interval=None):
            raise RuntimeError("db down")

    plugin._guard_subscribe_search(
        original=original,
        chain_self=Chain(),
        kwargs={"state": "R", "scheduled_interval": 24},
    )
    assert "sids" not in (captured.get("kwargs") or {}) or captured["kwargs"].get("sids") is None
    assert captured["kwargs"].get("scheduled_interval") == 24
    assert plugin.list_calls == 0


def test_runtime_positional_dispatch_no_multiple_values(monkeypatch=None):
    # monkeypatch SubscribeChain in runtime method namespace via plugin attrs after attach
    plugin = _ProdPlugin(selected=[])
    plugin.register(_make_sub(123))
    _attach_production_routing(plugin)
    _attach_production_runtime(plugin)

    calls = []

    class FakeSC:
        def __init__(self):
            pass

        def search(self, sid=None, state="N", manual=False, progress_callback=None, sids=None, scheduled_interval=None, **extra):
            calls.append({
                "sid": sid, "state": state, "manual": manual, "sids": sids,
                "scheduled_interval": scheduled_interval, **extra,
            })
            return "ok"

        @staticmethod
        def _noop():
            return None

    # Patch SubscribeChain symbol used inside extracted runtime method
    # Re-extract with SubscribeChain injected
    tree = ast.parse(RUNTIME)
    class_node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "GuangYaRuntimeFinalizerMixin")
    selected = [n for n in class_node.body if isinstance(n, ast.FunctionDef) and n.name in {
        "_dispatch_subscribe_search", "_runtime_call_native_search"
    }]
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    ns = {"inspect": inspect, "List": List, "Dict": Dict, "Any": Any, "Optional": Optional, "SubscribeChain": FakeSC}
    exec(compile(module, str(RUNTIME_PATH), "exec"), ns)
    plugin._dispatch_subscribe_search = types.MethodType(ns["_dispatch_subscribe_search"], plugin)
    plugin._runtime_call_native_search = types.MethodType(ns["_runtime_call_native_search"], plugin)

    plugin._dispatch_subscribe_search(123)
    assert calls[-1]["sid"] == 123

    plugin._dispatch_subscribe_search(123, "R")
    assert calls[-1]["sid"] == 123 and calls[-1]["state"] == "R"

    plugin._dispatch_subscribe_search(123, "R", True)
    assert calls[-1]["manual"] is True


def test_progress_callback_visible_in_signature_and_forwarded():
    assert "progress_callback" in inspect.Signature.from_callable(
        # parse from source text for contract
        lambda *args, progress_callback=None, **kwargs: None
    ).parameters
    sig_src = RUNTIME.split("def _dispatch_subscribe_search(", 1)[1].split("):", 1)[0]
    assert "progress_callback=None" in sig_src

    plugin = _ProdPlugin(selected=[])
    plugin.register(_make_sub(5))
    tree = ast.parse(RUNTIME)
    class_node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "GuangYaRuntimeFinalizerMixin")
    selected = [n for n in class_node.body if isinstance(n, ast.FunctionDef) and n.name in {
        "_dispatch_subscribe_search", "_runtime_call_native_search"
    }]
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)

    calls = []
    seen = []

    class FakeSC:
        def search(self, sid=None, state="N", manual=False, progress_callback=None, sids=None, scheduled_interval=None, **extra):
            calls.append({"sid": sid, "progress_callback": progress_callback, "state": state})
            if progress_callback:
                seen.append(True)
            return "ok"

    ns = {"inspect": inspect, "List": List, "Dict": Dict, "Any": Any, "Optional": Optional, "SubscribeChain": FakeSC}
    exec(compile(module, str(RUNTIME_PATH), "exec"), ns)
    plugin._normalize_search_call = _extract_class_methods(
        ROUTING, "GuangYaTransferAssistant", ["_normalize_search_call"]
    )["_normalize_search_call"]
    plugin._dispatch_subscribe_search = types.MethodType(ns["_dispatch_subscribe_search"], plugin)
    plugin._runtime_call_native_search = types.MethodType(ns["_runtime_call_native_search"], plugin)

    def cb(value=0, text=""):
        seen.append((value, text))

    # signature visibility
    assert "progress_callback" in inspect.signature(plugin._dispatch_subscribe_search).parameters

    plugin._dispatch_subscribe_search(state="R", progress_callback=cb)
    assert calls and calls[-1]["progress_callback"] is cb


def test_scheduled_due_split_a_b_c_d():
    """A due native, B not due, C due GuangYa, D not due GuangYa."""
    plugin = _attach_production_routing(_ProdPlugin(selected=[3, 4]))
    a, b, c, d = _make_sub(1), _make_sub(2), _make_sub(3), _make_sub(4)
    plugin.register(a, b, c, d)
    captured = {}

    def original(chain_self, **kwargs):
        captured["kwargs"] = dict(kwargs)
        return "native"

    class Chain:
        def _load_search_subscriptions(self, sid=None, sids=None, state=None, scheduled_interval=None):
            return [a, c]  # only due

    # use production guard_one which tries transfer
    plugin._guard_subscribe_search(
        original=original,
        chain_self=Chain(),
        kwargs={"state": "R", "scheduled_interval": 24},
    )
    assert plugin.guarded == [3]
    assert set(captured["kwargs"]["sids"]) == {1}
    assert 2 not in captured["kwargs"]["sids"]
    assert 4 not in plugin.guarded
