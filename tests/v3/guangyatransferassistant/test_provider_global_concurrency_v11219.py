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
    package_name = "_gy_provider_global_concurrency_v11219_testpkg"
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


def test_two_simultaneous_searches_share_one_process_wide_four_slot_budget():
    lock = threading.Lock()
    start = threading.Barrier(2)
    active = 0
    max_active = 0

    definitions = [
        {"name": f"p{index}", "kind": "json", "url": f"mock://p{index}", "token": ""}
        for index in range(4)
    ]

    class Dummy(MOD.GuangYaProviderReliabilityV1100Mixin):
        @staticmethod
        def _parse_provider_defs():
            return [dict(row) for row in definitions]

        @staticmethod
        def _search_api_provider(item, keyword):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            try:
                # 足够长，确保两个外层搜索的 worker 窗口发生重叠。
                time.sleep(0.035)
                provider = str(item["name"])
                return [{
                    "type": "magnet",
                    "identity": f"{keyword}-{provider}",
                    "uri": f"magnet:?xt=urn:btih:{keyword}-{provider}",
                    "provider": provider,
                }], {"provider": provider, "success": True}
            finally:
                with lock:
                    active -= 1

    outputs = {}

    def run_search(name):
        start.wait(timeout=5)
        outputs[name] = Dummy()._parallel_api_provider_search_v11219(name)

    threads = [threading.Thread(target=run_search, args=(name,)) for name in ("alpha", "beta")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()

    assert set(outputs) == {"alpha", "beta"}
    # 单次仍有并发价值，但两个同时搜索绝不能膨胀为 8 路 Provider 请求。
    assert 2 <= max_active <= 4

    for name in ("alpha", "beta"):
        rows, states, workers = outputs[name]
        assert workers == 4
        assert [row["provider"] for row in rows] == ["p0", "p1", "p2", "p3"]
        assert [state["provider"] for state in states] == ["p0", "p1", "p2", "p3"]
        assert all(str(row["identity"]).startswith(f"{name}-") for row in rows)


def test_global_provider_budget_is_bounded_and_wraps_only_api_provider_call():
    text = PROVIDER.read_text(encoding="utf-8")
    assert "_PROVIDER_API_MAX_WORKERS_V11219 = 4" in text
    assert (
        "_PROVIDER_API_GLOBAL_SEMAPHORE_V11219 = "
        "threading.BoundedSemaphore(_PROVIDER_API_MAX_WORKERS_V11219)"
    ) in text

    method = text.split("    def _parallel_api_provider_search_v11219", 1)[1].split(
        "    def _rank_provider_pool_v11219", 1
    )[0]
    assert "with _PROVIDER_API_GLOBAL_SEMAPHORE_V11219:" in method
    assert "self._search_api_provider(item, keyword)" in method
    assert "_search_viewing(" not in method
