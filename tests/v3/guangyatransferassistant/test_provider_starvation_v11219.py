from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
PROVIDER = PLUGIN / "provider_reliability_v1100.py"


def _load_provider_module():
    package_name = "_gy_provider_starvation_v11219_testpkg"
    pkg = types.ModuleType(package_name)
    pkg.__path__ = [str(PLUGIN)]
    sys.modules[package_name] = pkg

    if "requests" not in sys.modules:
        requests_stub = types.ModuleType("requests")
        requests_stub.Response = type("Response", (), {})
        requests_stub.Session = type("Session", (), {"__init__": lambda self: setattr(self, "proxies", {})})
        sys.modules["requests"] = requests_stub

    helper = types.ModuleType(f"{package_name}.provider_sources_v192")
    helper._proxy_dict = lambda _enabled: {}

    def dedupe(rows):
        output = []
        seen = set()
        for raw in rows or []:
            row = dict(raw)
            key = (str(row.get("type") or ""), str(row.get("identity") or row.get("uri") or ""))
            if key in seen:
                continue
            seen.add(key)
            output.append(row)
        return output

    helper._dedupe_candidates = dedupe
    helper._find_links = lambda *_args, **_kwargs: []
    sys.modules[helper.__name__] = helper

    spec = importlib.util.spec_from_file_location(f"{package_name}.provider_reliability_v1100", PROVIDER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MOD = _load_provider_module()


def test_wrong_media_magnet_cannot_starve_valid_ed2k_before_final_limit():
    subscribe = types.SimpleNamespace(name="Target Show", year=2026, season=1, type="电视剧")

    class Dummy(MOD.GuangYaProviderReliabilityV1100Mixin):
        _provider_result_limit = 1

        @staticmethod
        def _search_viewing(_keyword):
            return [
                {
                    "type": "magnet",
                    "identity": "wrong-1",
                    "uri": "magnet:?xt=urn:btih:wrong-1",
                    "provider": "bad",
                    "name": "Wrong Show (2026) S01E01",
                },
                {
                    "type": "magnet",
                    "identity": "wrong-2",
                    "uri": "magnet:?xt=urn:btih:wrong-2",
                    "provider": "bad",
                    "name": "Another Show (2026) S01E01",
                },
            ], {"provider": "viewing", "success": True}

        @staticmethod
        def _parse_provider_defs():
            return [{"name": "good", "kind": "json", "url": "mock://good", "token": ""}]

        @staticmethod
        def _search_api_provider(_item, _keyword):
            return [{
                "type": "ed2k",
                "identity": "valid-ed2k",
                "uri": "ed2k://|file|Target.Show.S01E01.mkv|1|AA|/",
                "provider": "good",
                "name": "Target Show (2026) S01E01",
            }], {"provider": "good", "success": True}

        @staticmethod
        def _candidate_quality_key_v11219(row):
            return f"{row.get('type')}|{row.get('provider')}"

        @staticmethod
        def _candidate_quality_snapshot_v11219():
            return {}

        @staticmethod
        def _candidate_rank_local_v11219():
            return types.SimpleNamespace(subscribe=subscribe, uncovered={1})

        @staticmethod
        def _provider_candidate_matches(_subscribe, row):
            return str(row.get("identity") or "") == "valid-ed2k"

        @staticmethod
        def _is_movie_subscription(_subscribe):
            return False

        @staticmethod
        def _candidate_episode_hint_v1125(_subscribe, row):
            return {1} if "E01" in str(row.get("name") or "") else set()

    result = Dummy()._search_external_providers("Target Show 2026 S01")
    assert len(result["data"]) == 1
    assert result["data"][0]["identity"] == "valid-ed2k"
    assert result["data"][0]["type"] == "ed2k"


def test_manual_keyword_search_without_subscription_context_keeps_cross_media_results_visible():
    class Dummy(MOD.GuangYaProviderReliabilityV1100Mixin):
        @staticmethod
        def _candidate_quality_key_v11219(row):
            return f"{row.get('type')}|{row.get('provider')}"

        @staticmethod
        def _candidate_quality_snapshot_v11219():
            return {}

        @staticmethod
        def _candidate_rank_local_v11219():
            return types.SimpleNamespace(subscribe=None, uncovered=set())

    rows = [
        {"type": "magnet", "identity": "a", "uri": "magnet:?xt=urn:btih:a", "provider": "p"},
        {"type": "ed2k", "identity": "b", "uri": "ed2k://|file|B|1|BB|/", "provider": "p"},
    ]
    ranked = Dummy()._rank_provider_pool_v11219(rows)
    assert {row["identity"] for row in ranked} == {"a", "b"}
