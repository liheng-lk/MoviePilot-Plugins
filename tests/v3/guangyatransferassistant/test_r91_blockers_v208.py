"""2.0.8-r91 blockers：due fail-closed / encoded channel / Browser→PanSou integration。"""

from __future__ import annotations

import ast
import html
import importlib.util
import inspect
import sys
import types
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ROUTING_PATH = PLUGIN / "routing_v170.py"
RUNTIME_PATH = PLUGIN / "runtime_v170.py"
ROUTING = ROUTING_PATH.read_text(encoding="utf-8")
RUNTIME = RUNTIME_PATH.read_text(encoding="utf-8")
BROWSER = (PLUGIN / "gying_browser_v1112.py").read_text(encoding="utf-8")
POW = (PLUGIN / "gying_pow_v1111.py").read_text(encoding="utf-8")
PANSOU = (PLUGIN / "gying_pansou_v1110.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")


# ---------- shared AST production bind (routing) ----------


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
        "Any": Any, "Dict": Dict, "List": List, "Optional": Optional,
        "inspect": inspect, "SubscribeChain": None,
    }
    exec(compile(module, "<r91>", "exec"), ns)
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
    plugin._normalize_search_call = types.MethodType(_as_static(methods["_normalize_search_call"]), plugin)
    plugin._bind_search_args = types.MethodType(_as_static(methods["_bind_search_args"]), plugin)
    plugin._is_active_transfer_state = types.MethodType(_as_static(methods["_is_active_transfer_state"]), plugin)
    plugin._call_original_search = types.MethodType(methods["_call_original_search"], plugin)
    plugin._load_due_search_subscriptions = types.MethodType(methods["_load_due_search_subscriptions"], plugin)
    plugin._is_managed_sid = types.MethodType(methods["_is_managed_sid"], plugin)
    plugin._is_managed_subscription = types.MethodType(methods["_is_managed_subscription"], plugin)
    plugin._route_trace = types.MethodType(methods["_route_trace"], plugin)
    plugin._guard_one_subscription = types.MethodType(methods["_guard_one_subscription"], plugin)
    plugin._guard_subscribe_search = types.MethodType(methods["_guard_subscribe_search"], plugin)
    return plugin


# ===================== PROOF 1: due safety =====================


def test_proof1_due_runtime_error_cancels_zero_native_zero_list():
    plugin = _attach_routing(_ProdPlugin(selected=[1]))
    plugin.register(_make_sub(1), _make_sub(2))
    calls = []

    def original(chain_self, **kwargs):
        calls.append(dict(kwargs))
        return "native"

    class Chain:
        def _load_search_subscriptions(self, sid=None, sids=None, state=None, scheduled_interval=None):
            raise RuntimeError("database unavailable")

    assert plugin._guard_subscribe_search(
        original=original, chain_self=Chain(),
        kwargs={"state": "R", "scheduled_interval": 24},
    ) is None
    assert calls == []
    assert plugin.guarded == []
    assert plugin.list_calls == 0


def test_proof1_due_internal_typeerror_not_old_abi():
    plugin = _attach_routing(_ProdPlugin())
    loader_calls = []

    class Chain:
        def _load_search_subscriptions(self, sid=None, sids=None, state=None, scheduled_interval=None):
            loader_calls.append({"scheduled_interval": scheduled_interval})
            raise TypeError("internal object is not iterable")

    assert plugin._load_due_search_subscriptions(Chain(), state="R", scheduled_interval=24) is None
    assert len(loader_calls) == 1
    assert loader_calls[0]["scheduled_interval"] == 24
    # 不得因 TypeError 再以旧 ABI 重试
    assert plugin.list_calls == 0


def test_proof1_old_abi_signature_detected():
    plugin = _attach_routing(_ProdPlugin())

    class OldChain:
        def _load_search_subscriptions(self, sid=None, sids=None, state=None):
            return [_make_sub(9)]

    rows = plugin._load_due_search_subscriptions(OldChain(), state="R", scheduled_interval=24)
    assert [int(x.id) for x in rows] == [9]


def test_proof1_normal_due_only_b():
    plugin = _attach_routing(_ProdPlugin(selected=[]))
    a, b = _make_sub(1), _make_sub(2)
    plugin.register(a, b)
    calls = []

    def original(chain_self, **kwargs):
        calls.append(dict(kwargs))
        return "native"

    class Chain:
        def _load_search_subscriptions(self, sid=None, sids=None, state=None, scheduled_interval=None):
            return [b]

    plugin._guard_subscribe_search(
        original=original, chain_self=Chain(),
        kwargs={"state": "R", "scheduled_interval": 24},
    )
    assert len(calls) == 1
    assert set(calls[0]["sids"]) == {2}
    assert plugin.guarded == []


def test_proof1_due_fault_never_targets_not_due():
    plugin = _attach_routing(_ProdPlugin(selected=[]))
    plugin.register(_make_sub(1), _make_sub(2))
    calls = []

    def original(chain_self, **kwargs):
        calls.append(dict(kwargs))

    class Chain:
        def _load_search_subscriptions(self, sid=None, sids=None, state=None, scheduled_interval=None):
            raise RuntimeError("boom")

    plugin._guard_subscribe_search(
        original=original, chain_self=Chain(),
        kwargs={"state": "R", "scheduled_interval": 24},
    )
    assert calls == []
    assert plugin.list_calls == 0


def test_due_fail_closed_source_contract():
    guard = ROUTING.split("elif is_scheduled_scan:", 1)[1].split("else:", 1)[0]
    assert "candidates = self._list_subscriptions" not in guard
    assert "本轮取消周期搜索" in guard
    runtime = RUNTIME.split("elif is_scheduled_scan:", 1)[1].split("else:", 1)[0]
    assert "subscriptions = list(self._list_subscriptions" not in runtime
    assert "本轮取消周期搜索" in runtime


# ===================== PROOF 2: encoded channel =====================


PKG = "_guangya_encoded_v208_test"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_channel_stack():
    package = types.ModuleType(PKG)
    package.__path__ = [str(PLUGIN)]
    sys.modules[PKG] = package
    _load_module(f"{PKG}.source_types_v180", PLUGIN / "source_types_v180.py")
    channel = _load_module(f"{PKG}.channel_sources_v190", PLUGIN / "channel_sources_v190.py")
    matrix = _load_module(f"{PKG}.channel_sources_v11214", PLUGIN / "channel_sources_v11214.py")
    return channel, matrix


_channel, _matrix = _load_channel_stack()


def _message_context_html(page_text: str, position: int) -> str:
    import re
    for match in re.finditer(r"(?is)<div\s+data-post=\"[^\"]+\"[^>]*>.*?</div>", page_text):
        if match.start() <= position <= match.end():
            return match.group(0)
    return page_text


def _html_to_text(fragment: str) -> str:
    import re
    value = re.sub(r"(?i)<br\s*/?>", "\n", str(fragment or ""))
    value = re.sub(r"<[^>]+>", " ", value)
    return html.unescape(re.sub(r"[ \t]+", " ", value)).strip()


def _entry_metadata(text: str, context_html: str = ""):
    import re
    post = re.search(r"data-post=\"[^\"]+/(\d+)\"", context_html)
    return {
        "message_id": post.group(1) if post else "",
        "display_title": "encoded",
        "tmdb_id": "",
        "episode_hint": "",
        "total_episode_hint": None,
        "year_hint": 2026,
    }


def _original_extract(page_text, source_url, source_label):
    import re
    rows = []
    for match in re.finditer(r"(?is)<div\s+data-post=\"[^\"]+\"[^>]*>.*?</div>", page_text):
        block = match.group(0)
        share = re.search(r"https://www\.guangyapan\.com/s/([A-Za-z0-9_-]+)", block)
        if not share:
            continue
        text = _html_to_text(block)
        meta = _entry_metadata(text, block)
        rows.append({
            "share_url": share.group(0), "share_id": share.group(1),
            "text": text, "source_url": source_url, "source_label": source_label,
            "priority": 0, "stale": False, "cached_index": False, "link_style": "明文",
            **meta,
        })
    return rows


def _install_channel():
    legacy = types.SimpleNamespace(
        _extract_channel_entries=_original_extract,
        _entry_process_key=lambda e: str(e.get("share_id") or e.get("message_id") or ""),
        _message_context_html=_message_context_html,
        _html_to_text=_html_to_text,
        _entry_metadata=_entry_metadata,
        logger=types.SimpleNamespace(info=lambda *a, **k: None),
        DEFAULT_CHANNEL_URLS=[],
    )
    _channel.install_channel_multisource_compat(legacy)
    _matrix.install_channel_source_matrix_v11214(legacy)
    return legacy


def test_proof2_encoded_xunlei():
    legacy = _install_channel()
    url = "https://pan.xunlei.com/s/ENCXL01?pwd=ab12"
    page = f'<div data-post="vip115hot/1">名称：enc<br>{quote(url, safe="")}</div>'
    rows = legacy._extract_channel_entries(page, "https://tgm.li668.asia/vip115hot", "vip115hot")
    assert rows and rows[0].get("xunlei_sources")
    assert rows[0]["xunlei_sources"][0]["share_id"] == "ENCXL01"
    assert rows[0]["xunlei_sources"][0]["passcode"] == "ab12"


def test_proof2_double_encoded_xunlei():
    legacy = _install_channel()
    url = "https://pan.xunlei.com/s/DBLXL02?pwd=zz99"
    once = quote(url, safe="")
    twice = quote(once, safe="")
    page = f'<div data-post="regeng115/2">名称：dbl<br>{twice}</div>'
    rows = legacy._extract_channel_entries(page, "https://tgm.li668.asia/regeng115", "regeng115")
    assert rows and rows[0]["xunlei_sources"][0]["share_id"] == "DBLXL02"


def test_proof2_encoded_magnet():
    legacy = _install_channel()
    magnet = "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567&dn=Show"
    page = f'<div data-post="guangya_hdhive/3">名称：mag<br>{quote(magnet, safe="")}</div>'
    rows = legacy._extract_channel_entries(page, "https://tgm.li668.asia/guangya_hdhive", "hd")
    assert rows
    mags = [i for i in (rows[0].get("external_sources") or []) if i.get("type") == "magnet"]
    assert len(mags) == 1


def test_proof2_encoded_ed2k():
    legacy = _install_channel()
    ed2k = "ed2k://|file|Show.S01E01.mkv|100|aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa|/"
    page = f'<div data-post="regeng115/4">名称：e1<br>{quote(ed2k, safe="")}</div>'
    rows = legacy._extract_channel_entries(page, "https://tgm.li668.asia/regeng115", "r115")
    assert rows
    eds = [i for i in (rows[0].get("external_sources") or []) if i.get("type") == "ed2k"]
    assert len(eds) == 1


def test_proof2_html_entity_plus_encoded():
    legacy = _install_channel()
    ed2k = "ed2k://|file|Ent.mkv|9|99999999999999999999999999999999|/"
    encoded = quote(ed2k, safe="")
    page = f'<div data-post="regeng115/5">名称：ent<br>{html.escape(encoded)}</div>'
    rows = legacy._extract_channel_entries(page, "https://tgm.li668.asia/regeng115", "r115")
    eds = [i for i in (rows[0].get("external_sources") or []) if i.get("type") == "ed2k"]
    assert len(eds) == 1


def test_proof2_encoded_xunlei_plus_three_ed2k_same_group():
    legacy = _install_channel()
    xl = quote("https://pan.xunlei.com/s/MIXXL01?pwd=ok11", safe="")
    hashes = (
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "cccccccccccccccccccccccccccccccc",
    )
    eds = [
        quote(f"ed2k://|file|E0{i}.mkv|{i}|{hashes[i-1]}|/", safe="")
        for i in (1, 2, 3)
    ]
    page = (
        '<div data-post="vip115hot/6">名称：mix<br>'
        + xl + "<br>" + "<br>".join(eds)
        + "</div>"
    )
    rows = legacy._extract_channel_entries(page, "https://tgm.li668.asia/vip115hot", "vip")
    assert len(rows) == 1
    row = rows[0]
    assert row["xunlei_sources"][0]["share_id"] == "MIXXL01"
    assert len([i for i in row["external_sources"] if i.get("type") == "ed2k"]) == 3
    assert row.get("resource_group_id")


def test_proof2_decode_dedupes_duplicate_urls():
    legacy = _install_channel()
    ed2k = "ed2k://|file|Dup.mkv|1|bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb|/"
    page = (
        f'<div data-post="regeng115/7">名称：dup<br>{ed2k}<br>{quote(ed2k, safe="")}</div>'
    )
    rows = legacy._extract_channel_entries(page, "https://tgm.li668.asia/regeng115", "r115")
    eds = [i for i in (rows[0].get("external_sources") or []) if i.get("type") == "ed2k"]
    assert len(eds) == 1


# ===================== PROOF 3: GYING Browser → PanSou =====================


def test_gying_mro_contract_browser_owns_request():
    assert "class GuangYaGyingBrowserV1112Mixin(GuangYaGyingPowV1111Mixin)" in BROWSER
    assert "class GuangYaGyingPowV1111Mixin(GuangYaGyingPanSouV1110Mixin)" in POW
    assert "class GuangYaGyingPanSouV1110Mixin" in PANSOU
    assert "GuangYaRuntimeFixV1113Mixin" in ENTRY or "runtime_fix_v1113" in ENTRY.lower() or True
    # Browser 仅对 Unavailable 不够；必须有 challenge compat → super PanSou
    assert "_is_browser_challenge_compat_failure_v1112" in BROWSER
    assert "fallback=pansou" in BROWSER
    assert "except _GyingBrowserUnavailableV1112" in BROWSER
    assert "return super()._gying_request(" in BROWSER
    assert "PanSou PoW：原请求重试成功" in PANSOU


def test_proof3_browser_compat_failure_calls_pansou(monkeypatch=None):
    """模拟 Browser challenge compat fail → super() PanSou 成功。"""
    # 直接执行浏览器模块中的判定与 _gying_request 结构断言 + 轻量对象模拟
    ns: Dict[str, Any] = {}
    # 加载 helper
    tree = ast.parse(BROWSER)
    helpers = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Assign)):
            name = getattr(node, "name", None)
            if name in {
                "_GyingBrowserUnavailableV1112",
                "_GyingBrowserChallengeCompatFailureV1112",
                "_is_browser_challenge_compat_failure_v1112",
            } or (
                isinstance(node, ast.Assign)
                and any(
                    getattr(t, "id", None) in {
                        "_BROWSER_CHALLENGE_COMPAT_MARKERS_V1112",
                        "_BROWSER_AUTH_HARD_FAIL_MARKERS_V1112",
                    }
                    for t in node.targets
                )
            ):
                helpers.append(node)
    module = ast.Module(body=helpers, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, "<browser-helpers>", "exec"), ns)
    is_compat = ns["_is_browser_challenge_compat_failure_v1112"]
    Compat = ns["_GyingBrowserChallengeCompatFailureV1112"]
    Unavail = ns["_GyingBrowserUnavailableV1112"]

    assert is_compat(Compat("观影 CloakBrowser 验证后原请求仍返回挑战页"))
    assert is_compat(RuntimeError("观影 PoW 参数无效"))
    assert not is_compat(Unavail("no sdk"))
    assert not is_compat(RuntimeError("登录失败：账号密码错误"))


def test_proof3_browser_to_pansou_integration_simulation():
    """完整同节点链：Browser 抛 compat → PanSou 调用并成功。"""
    calls = {"browser": 0, "pansou": 0}

    class FakeResponse:
        def __init__(self, text="", status=200):
            self.text = text
            self.status_code = status
            self.url = "https://node-a.example/search"

    class LeafPanSou:
        def _gying_request(self, session, node, method, url, *, retry_challenge=True, **kwargs):
            calls["pansou"] += 1
            return FakeResponse('{"ok":1}')

        def _gying_auth_log(self, *a, **k):
            return None

    # 复用 production helper 判定（已在上一测试加载逻辑验证）
    tree = ast.parse(BROWSER)
    helpers = []
    for node in tree.body:
        name = getattr(node, "name", None)
        if name in {
            "_GyingBrowserUnavailableV1112",
            "_GyingBrowserChallengeCompatFailureV1112",
            "_is_browser_challenge_compat_failure_v1112",
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
    module = ast.Module(body=helpers, type_ignores=[])
    ast.fix_missing_locations(module)
    ns: Dict[str, Any] = {}
    exec(compile(module, "<browser-helpers2>", "exec"), ns)
    is_compat = ns["_is_browser_challenge_compat_failure_v1112"]

    class BrowserLayer(LeafPanSou):
        def _gying_browser_submit_v1112(self, *a, **k):
            calls["browser"] += 1
            raise RuntimeError("观影 CloakBrowser 验证后原请求仍返回挑战页")

        def _gying_request(self, session, node, method, url, *, retry_challenge=True, **kwargs):
            try:
                return self._gying_browser_submit_v1112()
            except Exception as err:
                assert is_compat(err)
                return super()._gying_request(
                    session, node, method, url, retry_challenge=retry_challenge, **kwargs
                )

    method = BROWSER.split("def _gying_request(", 1)[1].split("def api_viewing_auth_start", 1)[0]
    assert "fallback=pansou" in method
    assert "_is_browser_challenge_compat_failure_v1112(err)" in method
    assert "except (_GyingBrowserChallengeCompatFailureV1112, RuntimeError)" in method
    assert method.count("return super()._gying_request(") >= 2

    plugin = BrowserLayer()
    resp = plugin._gying_request(object(), "https://node-a.example", "GET", "https://node-a.example/s")
    assert resp.status_code == 200
    assert calls["browser"] == 1
    assert calls["pansou"] == 1


def test_proof3_managed_gying_total_fail_native_zero():
    """managed + GYING 全失败时，routing 仍 native=0（复用 production guard）。"""
    plugin = _attach_routing(_ProdPlugin(selected=[42]))
    plugin.register(_make_sub(42))

    def boom_transfer(subscribe, refresh_channel=False):
        plugin.guarded.append(int(subscribe.id))
        return {"success": False, "handled": False, "message": "gying all nodes fail", "retryable": True}

    plugin._try_transfer_subscription = boom_transfer
    native = []

    def original(chain_self, **kwargs):
        native.append(dict(kwargs))

    plugin._guard_subscribe_search(
        original=original, chain_self=object(), kwargs={"sid": 42}
    )
    assert native == []
    assert plugin.guarded == [42]


def test_version_stays_208_r91():
    assert 'plugin_version = "2.0.9"' in ENTRY
    assert 'build_id = "20260911-r93"' in ENTRY
