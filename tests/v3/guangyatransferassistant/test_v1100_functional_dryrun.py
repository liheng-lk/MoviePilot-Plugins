import hashlib
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"


def _load_v1100_modules():
    package_name = "_gy_v1100_testpkg"
    pkg = types.ModuleType(package_name)
    pkg.__path__ = [str(PLUGIN)]
    sys.modules[package_name] = pkg

    helper = types.ModuleType(f"{package_name}.provider_sources_v192")

    def proxy_dict(_enabled):
        return {}

    def dedupe(rows):
        out = []
        seen = set()
        for row in rows or []:
            key = (str(row.get("type") or ""), str(row.get("uri") or row.get("url") or ""))
            if key in seen:
                continue
            seen.add(key)
            out.append(dict(row))
        return out

    def find_links(value, name="", provider=""):
        found = []

        def walk(node):
            if isinstance(node, dict):
                for item in node.values():
                    walk(item)
            elif isinstance(node, (list, tuple, set)):
                for item in node:
                    walk(item)
            else:
                text = str(node or "")
                for token in text.replace("\n", " ").split():
                    if token.startswith("magnet:?"):
                        found.append({"type": "magnet", "uri": token, "name": name, "provider": provider})
                    elif token.startswith("ed2k://"):
                        found.append({"type": "ed2k", "uri": token, "name": name, "provider": provider})

        walk(value)
        return found

    helper._proxy_dict = proxy_dict
    helper._dedupe_candidates = dedupe
    helper._find_links = find_links
    sys.modules[helper.__name__] = helper

    def load(name):
        spec = importlib.util.spec_from_file_location(f"{package_name}.{name}", PLUGIN / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    return load("provider_reliability_v1100"), load("xunlei_reliability_v1100"), load("diagnostics_v1100")


PROVIDER, XUNLEI, DIAGNOSTICS = _load_v1100_modules()


class _FakeProviderResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.headers = {"Content-Type": "application/json"}
        self.text = ""

    def json(self):
        return self._payload


class _FakeProviderSession:
    def __init__(self):
        self.proxies = {}
        self.calls = []

    def get(self, url, params=None, headers=None, **kwargs):
        self.calls.append({"url": url, "params": dict(params or {}), "headers": dict(headers or {}), **kwargs})
        if "q" in (params or {}):
            return _FakeProviderResponse({"data": []})
        return _FakeProviderResponse({
            "data": [
                {"title": "Demo", "link": "magnet:?xt=urn:btih:0123456789abcdef"},
                {"name": "Demo", "url": "ed2k://|file|Demo.mkv|123|0123456789ABCDEF|/"},
            ]
        })


class _FakeRapidResponse:
    def __init__(self, status, start, end, payload):
        self.status_code = status
        self.headers = {"Content-Range": f"bytes {start}-{end}/100000"} if status == 206 else {}
        self._payload = payload
        self.closed = False
        self.read_calls = 0

    @property
    def content(self):
        raise AssertionError("bounded CID code must never access response.content")

    def iter_content(self, chunk_size=8192):
        self.read_calls += 1
        for pos in range(0, len(self._payload), chunk_size):
            yield self._payload[pos:pos + chunk_size]

    def close(self):
        self.closed = True


class _FakeRapidSession:
    def __init__(self, ignore_second=False):
        self.proxies = {}
        self.calls = []
        self.responses = []
        self.ignore_second = ignore_second

    def get(self, _url, headers=None, **_kwargs):
        value = str((headers or {}).get("Range") or "")
        start, end = [int(part) for part in value.removeprefix("bytes=").split("-", 1)]
        index = len(self.calls)
        status = 200 if self.ignore_second and index == 1 else 206
        payload = bytes([index + 1]) * (end - start + 1)
        response = _FakeRapidResponse(status, start, end, payload)
        self.calls.append(value)
        self.responses.append(response)
        return response


class FunctionalDryRunTests(unittest.TestCase):
    def test_provider_query_and_token_compatibility_is_behavioral_not_only_static(self):
        variants = PROVIDER.GuangYaProviderReliabilityV1100Mixin._provider_query_variants("json", "Demo Show")
        self.assertEqual([key for key, _ in variants], ["q", "keyword", "kw", "search"])

        headers = PROVIDER.GuangYaProviderReliabilityV1100Mixin._provider_headers("secret-token")
        self.assertEqual(headers["X-API-Key"], "secret-token")
        self.assertEqual(headers["Authorization"], "Bearer secret-token")

        explicit = PROVIDER.GuangYaProviderReliabilityV1100Mixin._provider_headers("x-api-key:abc")
        self.assertEqual(explicit["X-API-Key"], "abc")
        self.assertNotIn("Authorization", explicit)

    def test_external_provider_retries_query_shape_and_returns_magnet_and_ed2k(self):
        fake = _FakeProviderSession()
        with patch.object(PROVIDER.requests, "Session", return_value=fake):
            class Dummy(PROVIDER.GuangYaProviderReliabilityV1100Mixin):
                _provider_proxy = False
                _provider_timeout = 5
                _provider_result_limit = 20

            rows, state = Dummy()._search_api_provider({
                "name": "mock",
                "kind": "json",
                "url": "https://example.invalid/search",
                "token": "secret-token",
            }, "Demo Show")

        self.assertTrue(state["success"])
        self.assertEqual(state["query_param"], "keyword")
        self.assertEqual([row["type"] for row in rows], ["magnet", "ed2k"])
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(fake.calls[0]["params"], {"q": "Demo Show"})
        self.assertEqual(fake.calls[1]["params"], {"keyword": "Demo Show"})
        self.assertEqual(fake.calls[1]["headers"]["X-API-Key"], "secret-token")

    def test_unified_search_really_merges_viewing_xunlei_magnet_and_ed2k(self):
        class Dummy(PROVIDER.GuangYaProviderReliabilityV1100Mixin):
            _viewing_enabled = True
            _provider_result_limit = 20

            @staticmethod
            def _parse_provider_defs():
                return []

            @staticmethod
            def _search_viewing(_keyword):
                return [
                    {"type": "magnet", "uri": "magnet:?xt=urn:btih:aa", "provider": "viewing"},
                    {"type": "ed2k", "uri": "ed2k://|file|Demo|1|AA|/", "provider": "viewing"},
                ], {"provider": "viewing", "success": True}

            @staticmethod
            def _search_viewing_xunlei(_keyword):
                return [{"type": "xunlei", "share_id": "share-1", "uri": "https://pan.xunlei.com/s/share-1"}], {"provider": "viewing_xunlei", "success": True}

        result = Dummy()._unified_provider_search("Demo Show")
        self.assertTrue(result["success"])
        self.assertEqual(result["counts"], {"xunlei": 1, "magnet": 1, "ed2k": 1})
        self.assertEqual(result["xunlei"][0]["share_id"], "share-1")

    def test_xunlei_cid_uses_exact_three_bounded_stream_ranges(self):
        fake = _FakeRapidSession()
        with patch.object(XUNLEI.requests, "Session", return_value=fake):
            class Dummy(XUNLEI.GuangYaXunleiReliabilityV1100Mixin):
                _provider_proxy = False
                _provider_timeout = 5

            digest = Dummy()._xunlei_compute_triple_cid("https://download.invalid/demo", 100000)

        sample = 20 * 1024
        expected = hashlib.sha1(bytes([1]) * sample + bytes([2]) * sample + bytes([3]) * sample).hexdigest()
        self.assertEqual(digest, expected)
        self.assertEqual(len(fake.calls), 3)
        self.assertTrue(all(response.closed for response in fake.responses))
        self.assertTrue(all(response.read_calls == 1 for response in fake.responses))

    def test_xunlei_cid_aborts_without_reading_body_when_nonzero_range_is_ignored(self):
        fake = _FakeRapidSession(ignore_second=True)
        with patch.object(XUNLEI.requests, "Session", return_value=fake):
            class Dummy(XUNLEI.GuangYaXunleiReliabilityV1100Mixin):
                _provider_proxy = False
                _provider_timeout = 5

            digest = Dummy()._xunlei_compute_triple_cid("https://download.invalid/demo", 100000)

        self.assertEqual(digest, "")
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(fake.responses[0].read_calls, 1)
        self.assertEqual(fake.responses[1].read_calls, 0)
        self.assertTrue(all(response.closed for response in fake.responses))

    def test_full_diagnostics_reports_exact_failed_stage_and_stays_non_destructive(self):
        class Dummy(DIAGNOSTICS.GuangYaDiagnosticsV1100Mixin):
            _viewing_enabled = True
            _xunlei_flash_enabled = True
            _selected_subscriptions = [1]

            @staticmethod
            def _parse_provider_defs():
                return [{"name": "mock"}]

            @staticmethod
            def api_provider_test():
                return {"success": True, "message": "资源来源检测完成", "providers": [
                    {"provider": "viewing", "success": True, "node": "https://gying.invalid"},
                    {"provider": "mock", "kind": "json", "success": True, "query_param": "keyword"},
                ]}

            @staticmethod
            def api_provider_search_selected():
                return {"success": True, "message": "搜索完成", "counts": {"xunlei": 1, "magnet": 2, "ed2k": 1}, "items": [
                    {"subscribe_id": 1, "name": "Demo", "success": True, "counts": {"xunlei": 1, "magnet": 2, "ed2k": 1}}
                ]}

            @staticmethod
            def api_xunlei_preflight():
                return {"rapid_ready": False, "message": "迅雷秒传链路尚未完全就绪", "stages": [
                    {"key": "guangya", "name": "光鸭运行时", "ok": True, "message": "ready"},
                    {"key": "xunlei_identity", "name": "迅雷匿名分享身份", "ok": False, "message": "captcha missing"},
                    {"key": "viewing", "name": "观影会话", "ok": True, "message": "ready", "node": "https://gying.invalid"},
                ]}

            @staticmethod
            def _now_text():
                return "2026-09-01 20:00:00"

            def save_data(self, key, value):
                self.saved = (key, value)

        dummy = Dummy()
        result = dummy.api_full_diagnostics()
        self.assertFalse(result["success"])
        self.assertTrue(any("迅雷匿名分享身份" in item for item in result["issues"]))
        rapid = next(row for row in result["checks"] if row["key"] == "xunlei_rapid")
        self.assertFalse(rapid["ok"])
        self.assertEqual(dummy.saved[0], "full_diagnostics_last")
        rendered = repr(result).lower()
        for forbidden in ("password", "cookie", "captcha_token", "secret-token"):
            self.assertNotIn(forbidden, rendered)


if __name__ == "__main__":
    unittest.main()
