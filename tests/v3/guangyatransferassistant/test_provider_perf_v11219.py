from __future__ import annotations

import importlib.util
import sys
import threading
import time
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
PROVIDER = PLUGIN / "provider_reliability_v1100.py"


def _load_provider_module():
    package_name = "_gy_provider_perf_v11219_testpkg"
    pkg = types.ModuleType(package_name)
    pkg.__path__ = [str(PLUGIN)]
    sys.modules[package_name] = pkg

    if "requests" not in sys.modules:
        requests_stub = types.ModuleType("requests")

        class Response:
            pass

        class Session:
            def __init__(self):
                self.proxies = {}

        requests_stub.Response = Response
        requests_stub.Session = Session
        sys.modules["requests"] = requests_stub

    helper = types.ModuleType(f"{package_name}.provider_sources_v192")

    def proxy_dict(_enabled):
        return {}

    def dedupe(rows):
        output = []
        seen = set()
        for raw in rows or []:
            row = dict(raw)
            key = (
                str(row.get("type") or ""),
                str(row.get("identity") or row.get("uri") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            output.append(row)
        return output

    def find_links(_value, name="", provider=""):
        return []

    helper._proxy_dict = proxy_dict
    helper._dedupe_candidates = dedupe
    helper._find_links = find_links
    sys.modules[helper.__name__] = helper

    spec = importlib.util.spec_from_file_location(
        f"{package_name}.provider_reliability_v1100",
        PROVIDER,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MOD = _load_provider_module()


def test_bounded_ordered_map_is_really_concurrent_but_keeps_input_order():
    barrier = threading.Barrier(4)
    lock = threading.Lock()
    active = 0
    max_active = 0

    def worker(value):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        try:
            if value < 4:
                barrier.wait(timeout=5)
            time.sleep((5 - value) * 0.002)
            return value
        finally:
            with lock:
                active -= 1

    result = MOD._bounded_ordered_map_v11219(worker, list(range(6)), max_workers=99)
    assert result == list(range(6))
    assert 2 <= max_active <= 4


def test_source_tier_remains_harder_than_quality_learning():
    rank = MOD._candidate_rank_key_v11219
    worst_magnet = rank("magnet", True, 3, 99, 0, -100, 99, 99)
    best_ed2k = rank("ed2k", True, 0, 0, 99, 100, 0, 0)
    assert worst_magnet < best_ed2k


def test_late_high_quality_candidate_can_win_before_global_limit():
    class Dummy(MOD.GuangYaProviderReliabilityV1100Mixin):
        _provider_result_limit = 1

        @staticmethod
        def _search_viewing(_keyword):
            return [{
                "type": "magnet",
                "identity": "early-low",
                "uri": "magnet:?xt=urn:btih:early-low",
                "provider": "early",
                "name": "Demo",
            }], {"provider": "viewing", "success": True}

        @staticmethod
        def _parse_provider_defs():
            return [{"name": "late", "kind": "json", "url": "mock://late", "token": ""}]

        @staticmethod
        def _search_api_provider(_item, _keyword):
            return [{
                "type": "magnet",
                "identity": "late-high",
                "uri": "magnet:?xt=urn:btih:late-high",
                "provider": "late",
                "name": "Demo",
            }], {"provider": "late", "success": True}

        @staticmethod
        def _candidate_quality_key_v11219(row):
            return f"magnet|{row.get('provider')}"

        @staticmethod
        def _candidate_quality_snapshot_v11219():
            return {
                "magnet|early": {"success": 0, "failure": 8},
                "magnet|late": {"success": 8, "failure": 0},
            }

        @staticmethod
        def _candidate_rank_local_v11219():
            return types.SimpleNamespace(subscribe=None, uncovered=set())

    result = Dummy()._search_external_providers("Demo")
    assert result["candidate_pool_v11219"] == {"raw": 2, "deduped": 2, "returned": 1}
    assert result["data"][0]["provider"] == "late"
    assert result["data"][0]["candidate_score_v11219"] > 0


def test_duplicate_identity_keeps_better_ranked_source_not_first_configured_source():
    class Dummy(MOD.GuangYaProviderReliabilityV1100Mixin):
        _provider_result_limit = 5

        @staticmethod
        def _search_viewing(_keyword):
            return [{
                "type": "magnet",
                "identity": "same-resource",
                "uri": "magnet:?xt=urn:btih:same-resource",
                "provider": "low",
                "name": "Demo",
            }], {"provider": "viewing", "success": True}

        @staticmethod
        def _parse_provider_defs():
            return [{"name": "high", "kind": "json", "url": "mock://high", "token": ""}]

        @staticmethod
        def _search_api_provider(_item, _keyword):
            return [{
                "type": "magnet",
                "identity": "same-resource",
                "uri": "magnet:?xt=urn:btih:same-resource",
                "provider": "high",
                "name": "Demo",
            }], {"provider": "high", "success": True}

        @staticmethod
        def _candidate_quality_key_v11219(row):
            return f"magnet|{row.get('provider')}"

        @staticmethod
        def _candidate_quality_snapshot_v11219():
            return {
                "magnet|low": {"success": 0, "failure": 20},
                "magnet|high": {"success": 20, "failure": 0},
            }

        @staticmethod
        def _candidate_rank_local_v11219():
            return types.SimpleNamespace(subscribe=None, uncovered=set())

    result = Dummy()._search_external_providers("Demo")
    assert result["candidate_pool_v11219"] == {"raw": 2, "deduped": 1, "returned": 1}
    assert result["data"][0]["provider"] == "high"


def test_parallel_provider_results_are_collected_in_config_order_even_when_completion_order_differs():
    class Dummy(MOD.GuangYaProviderReliabilityV1100Mixin):
        @staticmethod
        def _parse_provider_defs():
            return [
                {"name": "slow-first", "kind": "json", "url": "mock://1", "token": ""},
                {"name": "fast-second", "kind": "json", "url": "mock://2", "token": ""},
                {"name": "medium-third", "kind": "json", "url": "mock://3", "token": ""},
            ]

        @staticmethod
        def _search_api_provider(item, _keyword):
            delays = {"slow-first": 0.04, "fast-second": 0.0, "medium-third": 0.02}
            time.sleep(delays[item["name"]])
            return [{
                "type": "magnet",
                "identity": item["name"],
                "uri": f"magnet:?xt=urn:btih:{item['name']}",
                "provider": item["name"],
            }], {"provider": item["name"], "success": True}

    rows, states, workers = Dummy()._parallel_api_provider_search_v11219("Demo")
    assert workers == 3
    assert [row["provider"] for row in rows] == ["slow-first", "fast-second", "medium-third"]
    assert [state["provider"] for state in states] == ["slow-first", "fast-second", "medium-third"]


def test_one_unexpected_provider_worker_failure_does_not_cancel_other_sources():
    class Dummy(MOD.GuangYaProviderReliabilityV1100Mixin):
        @staticmethod
        def _parse_provider_defs():
            return [
                {"name": "broken", "kind": "json", "url": "mock://broken", "token": ""},
                {"name": "good", "kind": "json", "url": "mock://good", "token": ""},
            ]

        @staticmethod
        def _search_api_provider(item, _keyword):
            if item["name"] == "broken":
                raise RuntimeError("boom")
            return [{
                "type": "magnet",
                "identity": "good",
                "uri": "magnet:?xt=urn:btih:good",
                "provider": "good",
            }], {"provider": "good", "success": True}

    rows, states, workers = Dummy()._parallel_api_provider_search_v11219("Demo")
    assert workers == 2
    assert [row["provider"] for row in rows] == ["good"]
    assert states[0]["provider"] == "broken" and states[0]["success"] is False
    assert states[1]["provider"] == "good" and states[1]["success"] is True


def test_gying_is_not_submitted_to_provider_thread_pool_and_dispatch_logic_is_untouched():
    text = PROVIDER.read_text(encoding="utf-8")
    parallel = text.split("    def _parallel_api_provider_search_v11219", 1)[1].split("    def _rank_provider_pool_v11219", 1)[0]
    external = text.split("    def _search_external_providers", 1)[1].split("    def _unified_provider_search", 1)[0]
    assert "self._search_api_provider(item, keyword)" in parallel
    assert "_search_viewing(" not in parallel
    assert "self._search_viewing(keyword)" in external
    assert external.index("self._search_viewing(keyword)") < external.index("self._parallel_api_provider_search_v11219(keyword)")
    for forbidden in ("_upsert_source(", "_spawn_source_dispatch(", "cloudcollection", "_offline_request("):
        assert forbidden not in parallel
        assert forbidden not in external
