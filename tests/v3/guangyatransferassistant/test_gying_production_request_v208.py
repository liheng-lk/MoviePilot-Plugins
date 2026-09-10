"""2.0.8-r91：直接执行 production GuangYaGyingBrowserV1112Mixin._gying_request。

通过 AST 把生产方法挂进真实双层 MRO（Browser → PanSou stub），
不复制 fallback 分支；只 mock Browser submit / PanSou HTTP 结果。
"""

from __future__ import annotations

import ast
import types
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
BROWSER_PATH = PLUGIN / "gying_browser_v1112.py"
BROWSER = BROWSER_PATH.read_text(encoding="utf-8")
ROUTING = (PLUGIN / "routing_v170.py").read_text(encoding="utf-8")


class _FakeResponse:
    def __init__(self, text: str = "ok", status: int = 200):
        self.text = text
        self.status_code = status
        self.url = "https://node-a.example/search"


def _build_production_browser_class(submit_impl):
    """构造：PanSouStub ← GuangYaGyingBrowserV1112Mixin(_gying_request 生产实现)。"""
    tree = ast.parse(BROWSER)
    helpers = []
    request_method = None
    for node in tree.body:
        name = getattr(node, "name", None)
        if name in {
            "_GyingBrowserUnavailableV1112",
            "_GyingBrowserChallengeCompatFailureV1112",
            "_is_browser_challenge_compat_failure_v1112",
            "_same_origin_v1112",
        }:
            helpers.append(node)
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", None) in {
                "_BROWSER_CHALLENGE_COMPAT_MARKERS_V1112",
                "_BROWSER_AUTH_HARD_FAIL_MARKERS_V1112",
            }
            for t in node.targets
        ):
            helpers.append(node)
        if isinstance(node, ast.ClassDef) and node.name == "GuangYaGyingBrowserV1112Mixin":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "_gying_request":
                    request_method = item
    assert request_method is not None

    # 用 AST 组装完整类，保证 super() 的 __class__ cell 正确
    pan_sou = ast.parse(
        """
class _PanSouStub:
    def _gying_request(self, session, node, method, url, *, retry_challenge=True, **kwargs):
        self.pansou_calls += 1
        return _FakeResponse('{"ok":1}')

    def _gying_auth_log(self, *a, **k):
        self.logs.append(" ".join(str(x) for x in a))

class GuangYaGyingBrowserV1112Mixin(_PanSouStub):
    pass
"""
    )
    # 把生产 _gying_request 塞进 Browser mixin 类体
    browser_cls = next(
        n for n in pan_sou.body if isinstance(n, ast.ClassDef) and n.name == "GuangYaGyingBrowserV1112Mixin"
    )
    browser_cls.body = [request_method]

    module = ast.Module(body=[*helpers, *pan_sou.body], type_ignores=[])
    ast.fix_missing_locations(module)

    from urllib.parse import urlparse

    def canonical_gying_node(node: Any) -> str:
        return str(node or "").rstrip("/")

    ns: Dict[str, Any] = {
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "Optional": Optional,
        "canonical_gying_node": canonical_gying_node,
        "_FakeResponse": _FakeResponse,
        "urlparse": urlparse,
        "requests": types.SimpleNamespace(Session=object, Response=object),
    }
    exec(compile(module, str(BROWSER_PATH), "exec"), ns)
    cls = ns["GuangYaGyingBrowserV1112Mixin"]

    plugin = cls()
    plugin.browser_calls = 0
    plugin.pansou_calls = 0
    plugin.logs = []
    plugin._provider_timeout = 15
    plugin._gying_browser_fallback_logged_v1112 = False

    def _gying_browser_row_v1112(self, node):
        return {"node": node}

    def _gying_browser_request_in_thread_v1112(self, *a, **k):
        raise AssertionError("production submit should be mocked; thread path not used")

    def _gying_browser_submit_v1112(self, *a, **k):
        self.browser_calls += 1
        return submit_impl(self, *a, **k)

    plugin._gying_browser_row_v1112 = types.MethodType(_gying_browser_row_v1112, plugin)
    plugin._gying_browser_request_in_thread_v1112 = types.MethodType(
        _gying_browser_request_in_thread_v1112, plugin
    )
    plugin._gying_browser_submit_v1112 = types.MethodType(_gying_browser_submit_v1112, plugin)
    return plugin


def test_production_gying_request_owner_is_browser_mixin():
    assert "class GuangYaGyingBrowserV1112Mixin(GuangYaGyingPowV1111Mixin)" in BROWSER
    assert "fallback=pansou" in BROWSER
    plugin = _build_production_browser_class(lambda self, *a, **k: _FakeResponse())
    assert plugin._gying_request.__func__.__qualname__.endswith("_gying_request")


def test_case1_browser_success_pansou_zero():
    plugin = _build_production_browser_class(lambda self, *a, **k: _FakeResponse("browser-ok"))
    resp = plugin._gying_request(
        object(), "https://node-a.example", "GET", "https://node-a.example/search"
    )
    assert resp.status_code == 200
    assert plugin.browser_calls == 1
    assert plugin.pansou_calls == 0


def test_case2_browser_compat_fail_calls_production_super_pansou():
    def submit(self, *a, **k):
        raise RuntimeError("观影 CloakBrowser 验证后原请求仍返回挑战页")

    plugin = _build_production_browser_class(submit)
    resp = plugin._gying_request(
        object(), "https://node-a.example", "GET", "https://node-a.example/search"
    )
    assert resp.status_code == 200
    assert plugin.browser_calls == 1
    assert plugin.pansou_calls == 1
    assert any("fallback=pansou" in row for row in plugin.logs)


def test_case3_auth_error_does_not_fallback_pansou():
    def submit(self, *a, **k):
        raise RuntimeError("登录失败：账号密码错误")

    plugin = _build_production_browser_class(submit)
    raised = None
    try:
        plugin._gying_request(
            object(), "https://node-a.example", "GET", "https://node-a.example/search"
        )
    except RuntimeError as err:
        raised = err
    assert raised is not None
    assert "账号密码" in str(raised)
    assert plugin.browser_calls == 1
    assert plugin.pansou_calls == 0


def test_case4_managed_total_fail_native_zero():
    import inspect
    from typing import Any as _Any, Dict as _Dict, List as _List, Optional as _Optional

    tree = ast.parse(ROUTING)
    class_node = next(
        n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "GuangYaTransferAssistant"
    )
    selected = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_flatten_bound_search_kwargs":
            selected.append(node)
    names = {
        "_normalize_search_call",
        "_bind_search_args",
        "_call_original_search",
        "_is_active_transfer_state",
        "_is_managed_sid",
        "_is_managed_subscription",
        "_route_trace",
        "_guard_one_subscription",
        "_guard_subscribe_search",
    }
    for node in class_node.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            selected.append(node)
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    ns: Dict[str, Any] = {
        "Any": _Any,
        "Dict": _Dict,
        "List": _List,
        "Optional": _Optional,
        "inspect": inspect,
        "SubscribeChain": None,
    }
    exec(compile(module, "<routing>", "exec"), ns)

    plugin = types.SimpleNamespace(
        _enabled=True,
        _selected_subscriptions=[77],
        _provisional_routes=set(),
        _inspect_cache={},
        _subs={77: types.SimpleNamespace(id=77, name="m", state="R")},
        guarded=[],
        logs=[],
    )

    def _as_static(fn):
        def wrapper(self, *a, **k):
            return fn(*a, **k)

        return wrapper

    plugin._normalize_search_call = types.MethodType(_as_static(ns["_normalize_search_call"]), plugin)
    plugin._bind_search_args = types.MethodType(_as_static(ns["_bind_search_args"]), plugin)
    plugin._is_active_transfer_state = types.MethodType(
        _as_static(ns["_is_active_transfer_state"]), plugin
    )
    plugin._call_original_search = types.MethodType(ns["_call_original_search"], plugin)
    plugin._is_managed_sid = types.MethodType(ns["_is_managed_sid"], plugin)
    plugin._is_managed_subscription = types.MethodType(ns["_is_managed_subscription"], plugin)
    plugin._route_trace = types.MethodType(ns["_route_trace"], plugin)
    plugin._guard_one_subscription = types.MethodType(ns["_guard_one_subscription"], plugin)
    plugin._guard_subscribe_search = types.MethodType(ns["_guard_subscribe_search"], plugin)
    plugin._find_subscription = lambda sid: plugin._subs.get(int(sid))
    plugin._is_guangya_route = lambda sub: int(sub.id) in set(plugin._selected_subscriptions)
    plugin._plugin_log = lambda *a, **k: plugin.logs.append(" ".join(str(x) for x in a))
    plugin._record_route_health = lambda **f: None
    plugin._now_text = lambda: "t"
    plugin._cached_matches_for_subscription = lambda s: True
    plugin.refresh_channels = lambda force=False: None
    plugin._try_transfer_subscription = lambda subscribe, refresh_channel=False: {
        "success": False,
        "handled": False,
        "message": "browser+pansou+nodes fail",
        "retryable": True,
    }

    native = []

    def original(chain_self, **kwargs):
        native.append(dict(kwargs))

    plugin._guard_subscribe_search(original=original, chain_self=object(), kwargs={"sid": 77})
    assert native == []


def test_case5_compat_fail_then_pansou_returns_ok_for_xunlei_pipeline():
    def submit(self, *a, **k):
        raise RuntimeError("观影 PoW 参数无效")

    plugin = _build_production_browser_class(submit)
    resp = plugin._gying_request(
        object(), "https://node-a.example", "GET", "https://node-a.example/downurl"
    )
    assert plugin.browser_calls == 1
    assert plugin.pansou_calls == 1
    assert resp.text == '{"ok":1}'
    assert "return super()._gying_request(" in BROWSER
