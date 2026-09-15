"""r107 GYING current-node and detail-truth regressions."""
from __future__ import annotations

import ast
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[3]
ENTRY_PATH = ROOT / "plugins.v3" / "guangyatransferassistant" / "__init__.py"
ENTRY = ENTRY_PATH.read_text(encoding="utf-8")


def _bundled(name: str) -> str:
    tree = ast.parse(ENTRY, filename=str(ENTRY_PATH))
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(target, ast.Name) and target.id == "_BUNDLED_SOURCES" for target in targets):
            return str(ast.literal_eval(node.value)[name])
    raise AssertionError("_BUNDLED_SOURCES missing")


def _extract_method(module_name: str, class_name: str, method_name: str, globals_ns: dict):
    tree = ast.parse(_bundled(module_name), filename=f"<{module_name}>")
    cls = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    fn = next(
        node for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == method_name
    )
    ns = dict(globals_ns)
    exec(compile(ast.Module(body=[fn], type_ignores=[]), f"<{module_name}:{method_name}>", "exec"), ns)
    return ns[method_name]


def _runtime_helper():
    tree = ast.parse(_bundled("gying_runtime_v193"), filename="<gying_runtime_v193>")
    fn = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_gying_all_attempted_details_failed"
    )
    ns = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<detail-helper>", "exec"), ns)
    return ns["_gying_all_attempted_details_failed"]


class _Response:
    status_code = 200
    url = "https://www.xn--wcv59z.com/search?q=Demo&type=0&mode=2"
    text = "SEARCH_OK"


class _BaseProbe:
    _provider_result_limit = 20
    _gying_active_node = ""
    _viewing_base_url = ""
    _gying_search_cache = {}

    def __init__(self, detail_results):
        self.detail_results = list(detail_results)
        self._gying_search_cache = {}
        self.marked = []
        self.persisted = []

    def _gying_search_cache_key_v11223(self, keyword):
        return keyword

    def _viewing_session(self):
        return object(), {"success": True, "node": "https://www.xn--wcv59z.com", "mode": "cookie_reuse"}

    def _gying_request(self, session, node, method, url, headers=None):
        return _Response()

    def _gying_login_required(self, response):
        return False

    def _gying_login(self, session, node):
        return {"success": True, "mode": "cookie_reuse", "node": node}

    def _gying_detail(self, session, node, resource_type, resource_id, referer):
        value = self.detail_results.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    def _gying_persist_session(self, node, session, **kwargs):
        self.persisted.append((node, kwargs))

    def _gying_mark_node(self, node, status, message):
        self.marked.append((node, status, message))

    def _now_text(self):
        return "now"


def _base_raw_method():
    helper = _runtime_helper()
    cards = [
        {"title": "Demo A", "type": "tv", "id": "A", "year": 2026},
        {"title": "Demo B", "type": "tv", "id": "B", "year": 2026},
    ]
    return _extract_method(
        "gying_runtime_v193",
        "GuangYaGyingRuntimeMixin",
        "_gying_raw_results",
        {
            "Any": Any,
            "Dict": Dict,
            "List": List,
            "Tuple": Tuple,
            "quote": quote,
            "time": time,
            "_parse_search_payload_result_v11223": lambda text: (True, list(cards)),
            "_extract_panlist": lambda payload: dict(payload.get("panlist") or {}),
            "_gying_all_attempted_details_failed": helper,
        },
    )


def test_base_search_all_downurl_fail_is_transport_failure_not_zero_result():
    method = _base_raw_method()
    probe = _BaseProbe([RuntimeError("detail-1"), RuntimeError("detail-2")])
    rows, state = method(probe, "Demo", force=True)
    assert rows == []
    assert state["success"] is False
    assert state["node"] == "https://www.xn--wcv59z.com"
    assert "详情接口全部失败" in state["message"]
    assert probe.marked and probe.marked[-1][1] == "search_error"


def test_base_search_one_detail_success_with_no_links_is_valid_zero_result():
    method = _base_raw_method()
    probe = _BaseProbe([
        {"panlist": {"url": [], "name": [], "type": []}},
        RuntimeError("detail-2"),
    ])
    rows, state = method(probe, "Demo", force=True)
    assert rows == []
    assert state["success"] is True
    assert state["resources"] == 0
    assert state["detail_attempted"] == 2
    assert state["detail_succeeded"] == 1
    assert state["detail_failed"] == 1
    assert probe.persisted


class _PreciseProbe:
    _provider_result_limit = 20
    _gying_search_cache = {}

    def __init__(self, detail_results):
        self.detail_results = list(detail_results)
        self._gying_search_cache = {}
        self.marked = []

    def _gying_search_cache_key_v11223(self, keyword):
        return keyword

    def _viewing_session(self):
        return object(), {"success": True, "node": "https://www.xn--wcv59z.com", "mode": "cookie_reuse"}

    def _gying_request(self, session, node, method, url, headers=None):
        return _Response()

    def _gying_login_required(self, response):
        return False

    def _gying_login_password(self, session, node):
        return {"success": True, "mode": "password", "node": node}

    def _gying_select_detail_cards_v11223(self, keyword, cards, limit):
        return list(cards)[:limit]

    def _gying_target_subscribe_v11223(self):
        return None

    def _gying_detail(self, session, node, resource_type, resource_id, referer):
        value = self.detail_results.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    def _gying_persist_session(self, node, session, **kwargs):
        pass

    def _gying_mark_node(self, node, status, message):
        self.marked.append((node, status, message))

    def _now_text(self):
        return "now"

    def _gying_obs_log(self, *args):
        pass


def _precise_method():
    helper = _runtime_helper()
    cards = [
        {"title": "Demo A", "type": "tv", "id": "A", "year": 2026},
        {"title": "Demo B", "type": "tv", "id": "B", "year": 2026},
    ]
    return _extract_method(
        "gying_hardening_v193",
        "GuangYaGyingHardeningMixin",
        "_gying_xunlei_precise_variant_v1125",
        {
            "Any": Any,
            "Dict": Dict,
            "List": List,
            "Tuple": Tuple,
            "quote": quote,
            "time": time,
            "_parse_search_payload_result_v11223": lambda text: (True, list(cards)),
            "rank_gying_cards_v1125": lambda keyword, values: list(values),
            "extract_resource_rows_v1106": lambda payload, item: list(payload.get("rows") or []),
            "_xunlei_candidates_from_rows_v1125": lambda rows, limit=80: [
                dict(row) for row in rows if str(row.get("url") or "").startswith("https://pan.xunlei.com/")
            ][:limit],
            "_gying_all_attempted_details_failed": helper,
        },
    )


def test_precise_xunlei_all_downurl_fail_returns_failure_for_existing_failover():
    method = _precise_method()
    probe = _PreciseProbe([RuntimeError("detail-a"), RuntimeError("detail-b")])
    rows, state = method(probe, "Demo", force=True)
    assert rows == []
    assert state["success"] is False
    assert "详情接口全部失败" in state["message"]
    assert probe.marked and probe.marked[-1][1] == "search_error"


def test_precise_xunlei_one_detail_success_but_no_xunlei_is_valid_zero():
    method = _precise_method()
    probe = _PreciseProbe([
        {"rows": [{"url": "magnet:?xt=urn:btih:ABC", "name": "Demo"}]},
        RuntimeError("detail-b"),
    ])
    rows, state = method(probe, "Demo", force=True)
    assert rows == []
    assert state["success"] is True
    assert state["xunlei_resources"] == 0
    assert state["detail_attempted"] == 2
    assert state["detail_succeeded"] == 1
    assert state["detail_failed"] == 1


def test_current_pansou_default_content_node_is_first_class_seed():
    provider = _bundled("provider_sources_v192")
    runtime = _bundled("gying_runtime_v193")
    hardening = _bundled("gying_hardening_v193")
    auth = _bundled("gying_auth_v1107")
    assert '_viewing_base_url = "https://www.xn--wcv59z.com"' in provider
    assert 'config.get("viewing_base_url") or "https://www.xn--wcv59z.com"' in provider
    assert '"https://www.xn--wcv59z.com"' in runtime
    assert '"https://www.xn--wcv59z.com"' in hardening
    assert '"https://www.教父.com"' in auth


def test_detail_failure_helper_only_fires_when_every_attempt_failed():
    helper = _runtime_helper()
    assert helper(2, 0, 2) is True
    assert helper(2, 1, 1) is False
    assert helper(0, 0, 0) is False


def test_release_marker_r107():
    final = ENTRY[ENTRY.rindex("\nclass GuangYaTransferAssistant("):]
    assert 'plugin_version = "2.1.9"' in final
    assert 'build_id = "20260915-r107"' in final
