from __future__ import annotations

import ast
import hashlib
import html
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List
from urllib.parse import urlparse, urlunparse


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = PLUGIN / "__init__.py"
GYING = PLUGIN / "gying_runtime_v193.py"
FAILOVER = PLUGIN / "gying_failover_v193.py"
CONFIG = PLUGIN / "config_ui_v192.py"
SAFETY = PLUGIN / "planner_safety_v190.py"

entry_text = ENTRY.read_text(encoding="utf-8")
gying_text = GYING.read_text(encoding="utf-8")
failover_text = FAILOVER.read_text(encoding="utf-8")
config_text = CONFIG.read_text(encoding="utf-8")
safety_text = SAFETY.read_text(encoding="utf-8")


def _pure_namespace():
    tree = ast.parse(gying_text, filename=str(GYING))
    wanted_assigns = {
        "_GYING_SEARCH_RE",
        "_GYING_URL_RE",
        "_CHALLENGE_MARKERS",
        "_LOGIN_MARKERS",
        "_MAINTENANCE_MARKERS",
    }
    wanted_functions = {
        "_safe_int",
        "_normalize_node_url",
        "_registry_node_candidate",
        "_solve_pow_hex",
        "_solve_legacy_nonces",
        "_parse_search_payload_result_v11223",
        "_parse_search_payload",
    }
    body = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if names.intersection(wanted_assigns):
                body.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in wanted_functions:
            node.returns = None
            for arg in node.args.args:
                arg.annotation = None
            body.append(node)
    module = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(module)
    ns = {
        "Any": Any,
        "Dict": Dict,
        "Iterable": Iterable,
        "List": List,
        "html": html,
        "json": json,
        "re": re,
        "hashlib": hashlib,
        "urlparse": urlparse,
        "urlunparse": urlunparse,
    }
    exec(compile(module, str(GYING), "exec"), ns)
    return ns


def test_gying_runtime_and_failover_parse_and_precede_xunlei_provider():
    ast.parse(gying_text, filename=str(GYING))
    ast.parse(failover_text, filename=str(FAILOVER))
    assert "GuangYaGyingRuntimeMixin" in entry_text
    assert "GuangYaGyingFailoverMixin" in entry_text
    start = entry_text.index("class GuangYaTransferAssistant")
    order = [
        "GuangYaConfigUiMixin,",
        "GuangYaGyingFailoverMixin,",
        "GuangYaGyingRuntimeMixin,",
        "GuangYaXunleiFlashMixin,",
        "GuangYaProviderSourcesMixin,",
    ]
    positions = [entry_text.index(token, start) for token in order]
    assert positions == sorted(positions)


def test_node_pool_uses_release_pages_manual_nodes_and_auto_switch():
    for token in (
        "https://www.gying.page",
        "https://gying.si",
        '"viewing_registry_urls"',
        '"viewing_node_urls"',
        '"viewing_auto_switch"',
        '"viewing_auto_challenge"',
        '"viewing_node_cache_minutes"',
        "_discover_gying_nodes",
        "active_node",
        "viewing_session_state",
    ):
        assert token in gying_text or token in config_text or token in safety_text


def test_unicode_and_punycode_nodes_are_normalized_without_paths_or_credentials():
    ns = _pure_namespace()
    normalize = ns["_normalize_node_url"]
    assert normalize("https://www.星际穿越.com/a?x=1") == "https://www.星际穿越.com"
    assert normalize("https://www.xn--kivn76b41nnhi.com/") == "https://www.xn--kivn76b41nnhi.com"
    assert normalize("https://user:pass@example.com") == ""
    assert normalize("http://127.0.0.1:8080") == ""


def test_pow_solver_matches_reference_repeated_square_modulo():
    ns = _pure_namespace()
    solve = ns["_solve_pow_hex"]
    n = 0xE35
    x = 0x123
    rounds = 25
    expected = x
    for _ in range(rounds):
        expected = (expected * expected) % n
    assert solve(format(n, "x"), format(x, "x"), rounds) == format(expected, "x")


def test_legacy_challenge_solver_preserves_challenge_order():
    ns = _pure_namespace()
    solve = ns["_solve_legacy_nonces"]
    salt = "demo"
    nonce_a, nonce_b = 7, 23
    hashes = [
        hashlib.sha256(f"{nonce_b}{salt}".encode()).hexdigest(),
        hashlib.sha256(f"{nonce_a}{salt}".encode()).hexdigest(),
    ]
    assert solve(hashes, salt, 100) == [nonce_b, nonce_a]


def test_real_gying_endpoints_replace_old_s_path_contract():
    for token in (
        "/user/login",
        "/res/pow",
        "/search?q=",
        "/res/downurl/",
        "_GYING_SEARCH_RE",
        'code not in (200, "200")',
        '"siteid": "1"',
        '"cookietime": "10506240"',
    ):
        assert token in gying_text
    runtime_search = gying_text.split("    def _gying_raw_results(", 1)[1].split("    def _search_viewing(", 1)[0]
    assert "/s/1---1/" not in runtime_search


def test_search_payload_parser_reads_nested_obj_search_arrays():
    ns = _pure_namespace()
    parse = ns["_parse_search_payload"]
    html_text = '<script>_obj.search={"q":"星际穿越","n":"1","l":{"title":["星际穿越"],"year":[2014],"d":["mv"],"i":["abc1"],"info":["demo"]}};</script>'
    rows = parse(html_text)
    assert rows == [{"title": "星际穿越", "year": 2014, "type": "mv", "id": "abc1", "info": "demo"}]


def test_search_payload_parser_distinguishes_valid_zero_results_from_invalid_html():
    ns = _pure_namespace()
    parse_result = ns["_parse_search_payload_result_v11223"]
    valid_empty = '<script>_obj.search={"q":"象行记","n":"0","l":{"title":[],"year":[],"d":[],"i":[],"info":[]}};</script>'

    assert parse_result(valid_empty) == (True, [])
    assert parse_result("<html>站点公告，没有搜索对象</html>") == (False, [])
    malformed = '<script>_obj.search={"l":{"title":["象行记"],"d":[],"i":["broken"]}};</script>'
    scalar_schema = '<script>_obj.search={"l":{"title":"象行记","d":"mv","i":"broken"}};</script>'
    contradictory_zero = '<script>_obj.search={"n":"1","l":{"title":[],"d":[],"i":[]}};</script>'
    assert parse_result(malformed) == (False, [])
    assert parse_result(scalar_schema) == (False, [])
    assert parse_result(contradictory_zero) == (False, [])


def test_challenge_session_is_persisted_but_public_api_never_returns_cookie():
    for token in (
        "browser_verified",
        "browser_pow",
        "_gying_persist_session",
        '"cookie": _cookie_header(session)',
        '"/viewing/nodes"',
        '"/viewing/nodes/refresh"',
        '"/viewing/session/test"',
    ):
        assert token in gying_text
    public = gying_text.split("    def api_viewing_nodes(", 1)[1].split("    def api_provider_test", 1)[0]
    assert '"cookie"' not in public
    assert "_viewing_password" not in public
    assert "_viewing_cookie" not in public


def test_gying_search_is_shared_by_magnet_provider_and_xunlei_priority_path():
    assert "def _gying_raw_results" in gying_text
    search_provider = gying_text.split("    def _search_viewing(", 1)[1].split("    def _search_viewing_xunlei", 1)[0]
    search_xunlei = gying_text.split("    def _search_viewing_xunlei(", 1)[1].split("    # ------------------------------------------------------------------\n    # 对外诊断 API", 1)[0]
    assert "_gying_raw_results(keyword)" in search_provider
    assert "_gying_raw_results(keyword)" in search_xunlei
    assert "_XUNLEI_URL_RE" in search_xunlei
    assert '"type": "xunlei"' in search_xunlei


def test_failover_rejects_landing_pages_cools_bad_nodes_and_retries_search():
    for token in (
        "_BAD_NODE_STATES",
        "_gying_node_cooldown_seconds = 600",
        "当前网址将在不久后失效",
        "获取新网址",
        '"landing"',
        "for attempt in range(3)",
        'store["active_node"] = ""',
        "_gying_search_cache.pop",
    ):
        assert token in failover_text
    start = entry_text.index("class GuangYaTransferAssistant")
    assert entry_text.index("GuangYaGyingFailoverMixin,", start) < entry_text.index("GuangYaGyingRuntimeMixin,", start)


def test_complete_gying_config_survives_async_route_persistence():
    save = safety_text.split("    def _save_config(self)", 1)[1].split("    def _external_resource_allowed", 1)[0]
    for key in (
        "viewing_registry_urls",
        "viewing_node_urls",
        "viewing_auto_switch",
        "viewing_auto_challenge",
        "viewing_node_cache_minutes",
    ):
        assert f'"{key}"' in save



def _failover_probe_class():
    tree = ast.parse(failover_text, filename=str(FAILOVER))
    source_class = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "GuangYaGyingFailoverMixin"
    )
    method = next(
        node for node in source_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "_gying_raw_results"
    )
    method.returns = None
    for arg in method.args.args:
        arg.annotation = None

    class_node = ast.ClassDef(
        name="FailoverProbe",
        bases=[ast.Name(id="Base", ctx=ast.Load())],
        keywords=[],
        body=[method],
        decorator_list=[],
    )
    module = ast.Module(body=[class_node], type_ignores=[])
    ast.fix_missing_locations(module)

    class Base:
        def _gying_raw_results(self, keyword, force=False):
            self.base_calls.append((keyword, bool(force)))
            return self.base_results.pop(0)

    ns = {
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "Base": Base,
        "_normalize_node_url": _pure_namespace()["_normalize_node_url"],
    }
    exec(compile(module, str(FAILOVER), "exec"), ns)
    return ns["FailoverProbe"]


def test_same_business_search_fails_over_from_node_a_to_b_and_aggregates_network_evidence():
    Probe = _failover_probe_class()
    probe = Probe()
    probe._viewing_auto_switch = True
    probe.base_calls = []
    probe.base_results = [
        (
            [],
            {
                "success": False,
                "node": "https://a.example",
                "message": "search failed",
                "network_requested": True,
                "search_request_count_this_call": 1,
                "detail_request_count_this_call": 0,
            },
        ),
        (
            [{"url": "magnet:?xt=urn:btih:ABC"}],
            {
                "success": True,
                "node": "https://b.example",
                "message": "ok",
                "network_requested": True,
                "search_request_count_this_call": 1,
                "detail_request_count_this_call": 2,
            },
        ),
    ]
    probe.store = {"active_node": "https://a.example", "nodes": {}}
    probe._gying_search_cache = {"demo": {"ts": 1}}

    def mark_node(node, status, message):
        probe.store.setdefault("nodes", {})[node] = {
            "status": status,
            "message": message,
        }

    probe._gying_mark_node = mark_node
    probe._gying_state = lambda: probe.store
    probe._save_gying_state = lambda value: setattr(probe, "store", dict(value))
    probe._gying_search_cache_key_v11223 = lambda keyword: keyword

    rows, state = probe._gying_raw_results("demo")

    assert rows == [{"url": "magnet:?xt=urn:btih:ABC"}]
    assert probe.base_calls == [("demo", False), ("demo", True)]
    assert state["attempted_nodes"] == ["https://a.example", "https://b.example"]
    assert state["failover_attempts"] == 2
    assert state["search_request_count_total"] == 2
    assert state["detail_request_count_total"] == 2
    assert probe.store["nodes"]["https://a.example"]["status"] == "search_error"
    assert probe.store["active_node"] == ""
    assert "demo" not in probe._gying_search_cache


def test_auto_switch_disabled_records_single_node_without_hidden_retry():
    Probe = _failover_probe_class()
    probe = Probe()
    probe._viewing_auto_switch = False
    probe.base_calls = []
    probe.base_results = [
        (
            [],
            {
                "success": False,
                "node": "https://only.example",
                "network_requested": True,
                "search_request_count_this_call": 1,
                "detail_request_count_this_call": 0,
            },
        ),
    ]
    rows, state = probe._gying_raw_results("demo")
    assert rows == []
    assert probe.base_calls == [("demo", False)]
    assert state["attempted_nodes"] == ["https://only.example"]
    assert state["failover_attempts"] == 1
    assert state["search_request_count_total"] == 1
