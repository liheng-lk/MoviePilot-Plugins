from __future__ import annotations

import ast
import importlib.util
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterable, List, Optional
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
PATCH = PLUGIN / "gying_search_truth_v11223.py"
PROTOCOL = PLUGIN / "gying_protocol_v1106.py"
HARDENING = PLUGIN / "gying_hardening_v193.py"
RUNTIME = PLUGIN / "gying_runtime_v193.py"
ENTRY = PLUGIN / "__init__.py"
PLUGIN_JSON = PLUGIN / "plugin.json"
PACKAGE_JSON = ROOT / "package.v3.json"
RELEASE_DOC = ROOT / "docs" / "guangyatransferassistant-v11223-release.md"
RECALL = PLUGIN / "gying_recall_guard_v1125.py"


def _namespace():
    source = PATCH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(PATCH))
    wanted = {"_gying_exact_title_key_v11223", "select_gying_detail_cards_v11223"}
    body = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if names.intersection({"_MOVIE_CARD_TYPES_V11223", "_SERIES_CARD_TYPES_V11223"}):
                body.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in wanted:
            body.append(node)
    module = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(module)
    ns = {
        "Any": Any,
        "Callable": Callable,
        "Dict": Dict,
        "Iterable": Iterable,
        "List": List,
        "Optional": Optional,
        "re": re,
    }
    exec(compile(module, str(PATCH), "exec"), ns)
    return ns


def _truth_mixin():
    module_name = "_gying_search_truth_v11223_test"
    spec = importlib.util.spec_from_file_location(module_name, PATCH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module.GuangYaGyingSearchTruthV11223Mixin


def _title_match(expected: str):
    def matcher(row):
        return str(row.get("search_title") or "") == expected and str(row.get("year") or "") == "2026"
    return matcher


def _protocol_class():
    runtime_tree = ast.parse(RUNTIME.read_text(encoding="utf-8"), filename=str(RUNTIME))
    parser_body = []
    for node in runtime_tree.body:
        if isinstance(node, ast.Assign):
            names = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if "_GYING_SEARCH_RE" in names:
                parser_body.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name == "_parse_search_payload_result_v11223":
            parser_body.append(node)
    parser_module = ast.Module(body=parser_body, type_ignores=[])
    ast.fix_missing_locations(parser_module)
    parser_ns = {"Any": Any, "Dict": Dict, "List": List, "Tuple": tuple, "json": json, "re": re}
    exec(compile(parser_module, str(RUNTIME), "exec"), parser_ns)

    protocol_tree = ast.parse(PROTOCOL.read_text(encoding="utf-8"), filename=str(PROTOCOL))
    original = next(
        child
        for node in protocol_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "GuangYaGyingProtocolV1106Mixin"
        for child in node.body
        if isinstance(child, ast.FunctionDef) and child.name == "_gying_raw_results"
    )
    original.returns = None
    for arg in original.args.args:
        arg.annotation = None
    cls = ast.ClassDef(name="ProtocolProbe", bases=[], keywords=[], body=[original], decorator_list=[])
    module = ast.Module(body=[cls], type_ignores=[])
    ast.fix_missing_locations(module)
    ns = {
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "Tuple": tuple,
        "quote": quote,
        "time": time,
        "_safe_float": lambda value, default=0.0: float(value or default),
        "_safe_int": lambda value, default=0: int(value if value is not None else default),
        "_parse_search_payload_result_v11223": parser_ns["_parse_search_payload_result_v11223"],
        "extract_resource_rows_v1106": lambda payload, item: [
            {"url": f"magnet:?xt=urn:btih:{item['id']}", "search_title": item["title"]}
        ],
    }
    exec(compile(module, str(PROTOCOL), "exec"), ns)
    return ns["ProtocolProbe"]


def _hardening_precise_class():
    tree = ast.parse(HARDENING.read_text(encoding="utf-8"), filename=str(HARDENING))
    original = next(
        child
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "GuangYaGyingHardeningMixin"
        for child in node.body
        if isinstance(child, ast.FunctionDef) and child.name == "_gying_xunlei_precise_variant_v1125"
    )
    original.returns = None
    for arg in original.args.args:
        arg.annotation = None
    cls = ast.ClassDef(name="HardeningProbe", bases=[], keywords=[], body=[original], decorator_list=[])
    module = ast.Module(body=[cls], type_ignores=[])
    ast.fix_missing_locations(module)
    ns = {
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "Tuple": tuple,
        "time": time,
        "_xunlei_candidates_from_rows_v1125": lambda rows, limit=80: list(rows)[:limit],
    }
    exec(compile(module, str(HARDENING), "exec"), ns)
    return ns["HardeningProbe"]


def _recall_dispatch_class(base):
    tree = ast.parse(RECALL.read_text(encoding="utf-8"), filename=str(RECALL))
    original = next(
        child
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "GuangYaGyingRecallGuardV1125Mixin"
        for child in node.body
        if isinstance(child, ast.FunctionDef) and child.name == "_dispatch_viewing_external_v1113"
    )
    original.returns = None
    for arg in original.args.args:
        arg.annotation = None
    cls = ast.ClassDef(
        name="RecallDispatchProbe",
        bases=[ast.Name(id="Base", ctx=ast.Load())],
        keywords=[],
        body=[original],
        decorator_list=[],
    )
    module = ast.Module(body=[cls], type_ignores=[])
    ast.fix_missing_locations(module)
    ns = {
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "Base": base,
        "gying_keyword_variants": lambda keyword: [keyword, "象行记"],
    }
    exec(compile(module, str(RECALL), "exec"), ns)
    return ns["RecallDispatchProbe"]


class _Response:
    def __init__(self, text):
        self.text = text
        self.status_code = 200


class _ProtocolHarness(_protocol_class()):
    _provider_result_limit = 20

    def __init__(self, responses):
        self.responses = list(responses)
        self.request_urls = []
        self.detail_ids = []
        self._gying_search_cache = {}

    @staticmethod
    def _viewing_session():
        return object(), {"success": True, "node": "https://example.invalid", "mode": "cookie"}

    def _gying_request(self, _session, _node, _method, url, **_kwargs):
        self.request_urls.append(url)
        return self.responses.pop(0)

    @staticmethod
    def _gying_login_required(_response):
        return False

    def _gying_detail(self, _session, _node, _kind, resource_id, _referer):
        self.detail_ids.append(resource_id)
        return {}

    @staticmethod
    def _gying_persist_session(*_args, **_kwargs):
        return None

    @staticmethod
    def _now_text():
        return "2026-09-09 17:00:00"

    @staticmethod
    def _gying_mark_node(*_args, **_kwargs):
        return None

    @staticmethod
    def _gying_target_subscribe_v11223():
        return SimpleNamespace(id=126, name="象行记", year=2026, type="电影")

    def _gying_select_detail_cards_v11223(self, _keyword, cards, limit):
        select = _namespace()["select_gying_detail_cards_v11223"]
        return select(cards, limit, _title_match("象行记"), expected_kind="movie")


def _search_html(cards):
    listing = {
        "title": [row["title"] for row in cards],
        "year": [row.get("year", "") for row in cards],
        "d": [row["type"] for row in cards],
        "i": [row["id"] for row in cards],
        "info": [row.get("info", "") for row in cards],
    }
    return f"<script>_obj.search={json.dumps({'q': '象行记', 'n': str(len(cards)), 'l': listing}, ensure_ascii=False)};</script>"


def test_unrelated_recommendation_cards_are_never_expanded():
    select = _namespace()["select_gying_detail_cards_v11223"]
    cards = [
        {"title": f"无关影片{index}", "year": 2026, "type": "mv", "id": str(index)}
        for index in range(25)
    ]
    assert select(cards, 20, _title_match("象行记"), expected_kind="movie") == []


def test_v11223_release_metadata_and_runtime_order_are_consistent():
    entry = ENTRY.read_text(encoding="utf-8")
    plugin = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))
    package = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    doc = RELEASE_DOC.read_text(encoding="utf-8")

    assert plugin["version"] == package["version"] == "2.0.8"
    assert "v2.0.8" in package["history"]
    assert 'plugin_version = "2.0.8"' in entry
    assert "from .gying_search_truth_v11223 import GuangYaGyingSearchTruthV11223Mixin" in entry
    start = entry.index("class GuangYaTransferAssistant(")
    assert entry.index("GuangYaGyingObservabilityV1104Mixin,", start) < entry.index(
        "GuangYaGyingSearchTruthV11223Mixin,", start
    ) < entry.index("GuangYaGyingHardeningMixin,", start)
    for token in ("象行记", "合法零结果", "第 26 位", "single-flight"):
        assert token in doc


def test_target_after_old_twenty_card_limit_is_selected_before_limiting():
    select = _namespace()["select_gying_detail_cards_v11223"]
    cards = [
        {"title": f"无关影片{index}", "year": 2026, "type": "mv", "id": str(index)}
        for index in range(25)
    ]
    cards.append({"title": "象行记", "year": 2026, "type": "mv", "id": "target"})
    selected = select(cards, 20, _title_match("象行记"), expected_kind="movie")
    assert [row["id"] for row in selected] == ["target"]


def test_movie_search_rejects_same_title_tv_or_anime_cards_before_detail():
    select = _namespace()["select_gying_detail_cards_v11223"]
    cards = [
        {"title": "象行记", "year": 2026, "type": "tv", "id": "tv"},
        {"title": "象行记", "year": 2026, "type": "ac", "id": "anime"},
        {"title": "象行记", "year": 2026, "type": "mv", "id": "movie"},
    ]
    selected = select(cards, 20, _title_match("象行记"), expected_kind="movie")
    assert [row["id"] for row in selected] == ["movie"]


def test_exact_title_gate_rejects_contains_style_near_matches():
    select = _namespace()["select_gying_detail_cards_v11223"]
    cards = [
        {"title": "大象行记", "year": 2026, "type": "mv", "id": "prefix"},
        {"title": "象行记事", "year": 2026, "type": "mv", "id": "suffix"},
        {"title": "象行记", "year": 2026, "type": "mv", "id": "exact"},
    ]
    selected = select(
        cards,
        20,
        lambda _row: True,
        expected_kind="movie",
        accepted_titles=["象行记 2026"],
        expected_year=2026,
    )
    assert [row["id"] for row in selected] == ["exact"]


def test_exact_title_gate_accepts_a_card_made_only_from_two_official_titles():
    select = _namespace()["select_gying_detail_cards_v11223"]
    cards = [
        {"title": "象行记 Elephant Journey", "year": 2026, "type": "mv", "id": "bilingual"},
        {"title": "象行记 Unrelated Words", "year": 2026, "type": "mv", "id": "noise"},
    ]
    selected = select(
        cards,
        20,
        lambda _row: True,
        expected_kind="movie",
        accepted_titles=["象行记", "Elephant Journey"],
        expected_year=2026,
    )
    assert [row["id"] for row in selected] == ["bilingual"]


def test_exact_title_key_keeps_numbers_that_are_part_of_the_real_title():
    key = _namespace()["_gying_exact_title_key_v11223"]
    assert key("1984") == "1984"
    assert key("Blade Runner 2049") == "bladerunner2049"
    assert key("象行记 (2026)", 2026) == key("象行记 2026", 2026) == "象行记"


def test_unknown_card_type_fails_closed_before_detail():
    select = _namespace()["select_gying_detail_cards_v11223"]
    cards = [
        {"title": "象行记", "year": 2026, "type": "unknown", "id": "unknown"},
        {"title": "象行记", "year": 2026, "type": "mv", "id": "movie"},
    ]
    selected = select(cards, 20, _title_match("象行记"), expected_kind="movie")
    assert [row["id"] for row in selected] == ["movie"]


def test_series_query_and_chinese_season_card_share_the_same_exact_title_key():
    select = _namespace()["select_gying_detail_cards_v11223"]
    cards = [
        {"title": "示例剧 第2季", "year": 2026, "type": "tv", "id": "season-2-digit"},
        {"title": "示例剧 第二季", "year": 2026, "type": "tv", "id": "season-2-cn"},
    ]
    selected = select(
        cards,
        20,
        lambda _row: True,
        expected_kind="series",
        accepted_titles=["示例剧 2026 S02"],
        expected_year=2026,
    )
    assert [row["id"] for row in selected] == ["season-2-digit", "season-2-cn"]


def test_protocol_and_xunlei_use_valid_empty_parser_and_target_card_selector():
    protocol = PROTOCOL.read_text(encoding="utf-8")
    hardening = HARDENING.read_text(encoding="utf-8")
    for source in (protocol, hardening):
        assert "_parse_search_payload_result_v11223" in source
        assert "parsed_ok" in source
        assert "_gying_select_detail_cards_v11223" in source
        assert '"matched_cards"' in source
    assert "for item in cards[:limit]" not in protocol
    assert "detail_cards = ranked_cards[:detail_limit]" not in hardening


def test_valid_empty_browser_result_does_not_fall_through_to_legacy_recommendations():
    probe = _ProtocolHarness([_Response(_search_html([]))])
    rows, state = probe._gying_raw_results("象行记 2026")
    assert rows == []
    assert state["success"] is True
    assert state["cards"] == 0
    assert len(probe.request_urls) == 1
    assert "mode=1" in probe.request_urls[0]
    assert probe.detail_ids == []


def test_unparseable_browser_response_alone_falls_back_to_valid_legacy_response():
    probe = _ProtocolHarness([_Response("<html>invalid</html>"), _Response(_search_html([]))])
    rows, state = probe._gying_raw_results("象行记 2026")
    assert rows == []
    assert state["success"] is True
    assert len(probe.request_urls) == 2
    assert "mode=1" in probe.request_urls[0]
    assert "mode=2" in probe.request_urls[1]


def test_malformed_nonempty_browser_payload_falls_back_instead_of_becoming_false_zero():
    malformed = (
        '<script>_obj.search={"q":"象行记","n":"1","l":'
        '{"title":["象行记"],"year":[2026],"d":[],"i":["broken"]}};</script>'
    )
    probe = _ProtocolHarness([_Response(malformed), _Response(_search_html([]))])
    rows, state = probe._gying_raw_results("象行记 2026")
    assert rows == []
    assert state["success"] is True
    assert len(probe.request_urls) == 2
    assert "mode=1" in probe.request_urls[0]
    assert "mode=2" in probe.request_urls[1]


def test_protocol_calls_downurl_only_for_target_beyond_twenty_unrelated_cards():
    cards = [
        {"title": f"无关影片{index}", "year": 2026, "type": "mv", "id": str(index)}
        for index in range(25)
    ]
    cards.append({"title": "象行记", "year": 2026, "type": "mv", "id": "target"})
    probe = _ProtocolHarness([_Response(_search_html(cards))])
    rows, state = probe._gying_raw_results("象行记 2026")
    assert probe.detail_ids == ["target"]
    assert len(rows) == 1
    assert state["raw_cards"] == 26
    assert state["matched_cards"] == 1
    assert state["detail_cards"] == 1


def test_zero_target_cards_do_not_stop_keyword_fallback():
    hardening = HARDENING.read_text(encoding="utf-8")
    method = hardening.split("    def _gying_raw_results(", 1)[1].split(
        "    def _gying_xunlei_precise_variant_v1125", 1
    )[0]
    assert 'state.get("target_scoped")' in method
    assert 'state.get("matched_cards")' in method


def test_cache_identity_isolated_by_subscription_and_global_search_scope():
    Mixin = _truth_mixin()

    class Base:
        def _gying_alias_subscribe_v11212(self):
            return self.subscribe

    class Probe(Mixin, Base):
        pass

    probe = Probe()
    probe.subscribe = SimpleNamespace(id=1, name="同名影片", year=2020, season=0, type="电影")
    first = probe._gying_search_cache_key_v11223("同名影片")
    probe.subscribe = SimpleNamespace(id=2, name="同名影片", year=2026, season=0, type="电影")
    second = probe._gying_search_cache_key_v11223("同名影片")
    probe.subscribe = None
    global_key = probe._gying_search_cache_key_v11223("同名影片")

    assert first != second
    assert second != global_key
    assert global_key == "同名影片"


def test_same_subscription_concurrent_search_reuses_one_completed_request():
    Mixin = _truth_mixin()

    class Probe(Mixin, _ProtocolHarness):
        @staticmethod
        def _gying_alias_subscribe_v11212():
            return SimpleNamespace(id=126, name="象行记", year=2026, season=0, type="电影")

    class SlowProbe(Probe):
        def _gying_request(self, *args, **kwargs):
            time.sleep(0.05)
            return super()._gying_request(*args, **kwargs)

    probe = SlowProbe([_Response(_search_html([])), _Response(_search_html([]))])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: probe._gying_raw_results("象行记 2026"), range(2)))

    assert all(state["success"] for _rows, state in results)
    assert len(probe.request_urls) == 1


def test_overlapping_forced_refreshes_are_coalesced_but_later_force_still_refreshes():
    Mixin = _truth_mixin()

    class Probe(Mixin, _ProtocolHarness):
        @staticmethod
        def _gying_alias_subscribe_v11212():
            return SimpleNamespace(id=126, name="象行记", year=2026, season=0, type="电影")

    class SlowProbe(Probe):
        def _gying_request(self, *args, **kwargs):
            time.sleep(0.05)
            return super()._gying_request(*args, **kwargs)

    probe = SlowProbe([
        _Response(_search_html([])),
        _Response(_search_html([])),
        _Response(_search_html([])),
    ])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: probe._gying_raw_results("象行记 2026", force=True), range(2)))

    assert all(state["success"] for _rows, state in results)
    assert len(probe.request_urls) == 1
    probe._gying_raw_results("象行记 2026", force=True)
    assert len(probe.request_urls) == 2


def test_same_title_different_year_subscriptions_never_share_filtered_cache():
    Mixin = _truth_mixin()

    class Probe(Mixin, _ProtocolHarness):
        def __init__(self, responses):
            super().__init__(responses)
            self.subscribe = None

        def _gying_alias_subscribe_v11212(self):
            return self.subscribe

        @staticmethod
        def _is_movie_subscription(_subscribe):
            return True

        @staticmethod
        def _provider_candidate_matches(subscribe, row):
            return (
                str(row.get("search_title") or "") == "同名影片"
                and str(row.get("year") or "") == str(subscribe.year)
            )

    card_2020 = {"title": "同名影片", "year": 2020, "type": "mv", "id": "movie-2020"}
    card_2026 = {"title": "同名影片", "year": 2026, "type": "mv", "id": "movie-2026"}
    probe = Probe([_Response(_search_html([card_2020])), _Response(_search_html([card_2026]))])
    probe.subscribe = SimpleNamespace(id=1, name="同名影片", year=2020, season=0, type="电影")
    rows_2020, _ = probe._gying_raw_results("同名影片")
    probe.subscribe = SimpleNamespace(id=2, name="同名影片", year=2026, season=0, type="电影")
    rows_2026, _ = probe._gying_raw_results("同名影片")

    assert rows_2020[0]["url"].endswith("movie-2020")
    assert rows_2026[0]["url"].endswith("movie-2026")
    assert probe.detail_ids == ["movie-2020", "movie-2026"]
    assert len(probe.request_urls) == 2


def test_xunlei_reuses_subscription_scoped_protocol_detail_snapshot():
    Probe = _hardening_precise_class()
    probe = Probe()
    probe._provider_result_limit = 20
    probe._gying_search_cache_key_v11223 = lambda keyword: f"scope:{keyword}"
    probe._gying_search_cache = {
        "scope:象行记 2026": {
            "ts": time.time(),
            "rows": [{"share_id": "target-share", "search_title": "象行记"}],
            "state": {
                "success": True,
                "target_scoped": True,
                "matched_cards": 1,
                "detail_cards": 1,
            },
        }
    }
    probe._viewing_session = lambda: (_ for _ in ()).throw(AssertionError("must reuse cache"))

    rows, state = probe._gying_xunlei_precise_variant_v1125("象行记 2026")
    assert rows[0]["share_id"] == "target-share"
    assert state["detail_snapshot_reused_v11223"] is True
    assert state["xunlei_resources"] == 1


def test_magnet_fallback_keeps_subscription_scope_for_cache_and_precise_search():
    class Base:
        def _dispatch_viewing_external_v1113(self, _subscribe):
            return self.base_results.pop(0)

    ProbeBase = _recall_dispatch_class(Base)

    class Probe(ProbeBase):
        def __init__(self):
            self.base_results = [
                {"success": False, "actions": [], "message": "strict miss"},
                {"success": True, "actions": [{"source_id": "queued"}]},
            ]
            self.scope_active = False
            self.precise_scoped = False
            self.promoted_subscribe = None
            self._gying_search_cache = {
                "scope:象行记 2026": {"ts": time.time(), "state": {"success": True}, "rows": []}
            }

        @staticmethod
        def _provider_keyword(_subscribe):
            return "象行记 2026"

        @staticmethod
        def _gying_search_cache_key_v11223(keyword, subscribe=None):
            assert subscribe is not None
            return f"scope:{keyword}"

        @contextmanager
        def _gying_alias_scope_v11212(self, subscribe):
            assert subscribe is not None
            self.scope_active = True
            try:
                yield
            finally:
                self.scope_active = False

        def _gying_xunlei_precise_variant_v1125(self, _keyword):
            self.precise_scoped = self.scope_active
            return [], {"success": True}

        def _promote_search_bundle_v1125(self, _primary, _variants, subscribe=None):
            self.promoted_subscribe = subscribe

    subscribe = SimpleNamespace(id=126, name="象行记", year=2026)
    probe = Probe()
    result = probe._dispatch_viewing_external_v1113(subscribe)
    assert result["success"] is True
    assert probe.precise_scoped is True
    assert probe.promoted_subscribe is subscribe
