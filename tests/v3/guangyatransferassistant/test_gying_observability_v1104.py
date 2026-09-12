from __future__ import annotations

import ast
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, Dict, List
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = PLUGIN / "__init__.py"
OBS = PLUGIN / "gying_observability_v1104.py"

entry_text = ENTRY.read_text(encoding="utf-8")
text = OBS.read_text(encoding="utf-8")


def test_observability_layer_parses_and_wraps_final_runtime():
    ast.parse(text, filename=str(OBS))
    ast.parse(entry_text, filename=str(ENTRY))
    assert "from .gying_observability_v1104 import GuangYaGyingObservabilityV1104Mixin" in entry_text
    start = entry_text.index("class GuangYaTransferAssistant")
    assert entry_text.index("GuangYaGyingObservabilityV1104Mixin,", start) < entry_text.index("GuangYaChannelUiV1101Mixin,", start)
    assert entry_text.index("GuangYaGyingObservabilityV1104Mixin,", start) < entry_text.index("GuangYaGyingHardeningMixin,", start)
    assert 'plugin_version = "2.0.13"' in entry_text


def test_observability_covers_all_real_gying_stages():
    for token in ("运行时初始化", "节点刷新完成", "检测到浏览器 PoW", "PoW通过", "登录检查", "登录结果", "会话结果", "搜索开始", "搜索请求完成", "详情接口响应", "协议候选预筛", "迅雷召回", "迅雷执行", "人工操作：测试观影会话", "viewing_observability_state"):
        assert token in text


def test_search_logs_separate_endpoint_health_exact_match_and_real_import():
    for token in (
        "接口健康=",
        "模糊卡片=",
        "当前媒体卡片=",
        "目标卡原始链接（待订阅行核验）=",
        "仅表示请求成功，尚未证明属于当前订阅",
        "不是入库结果",
        "真实文件身份与入队回执核验",
    ):
        assert token in text
    assert "downurl成功" not in text
    assert "搜索结果：成功=" not in text


def test_console_gets_explicit_viewing_test_action():
    assert '"测试观影"' in text
    assert '"/viewing/session/test"' in text
    assert '"刷新观影节点"' in text
    assert "_inject_viewing_test_button" in text


def test_observability_logs_do_not_pass_secret_values():
    tree = ast.parse(text, filename=str(OBS))
    lines = text.splitlines()
    forbidden = ("_viewing_cookie", "_viewing_password", "captcha_token", "passcode", "challenge_id")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "_gying_obs_log"):
            continue
        segment = "\n".join(lines[node.lineno - 1 : (node.end_lineno or node.lineno)])
        for token in forbidden:
            assert token not in segment


def test_observability_is_non_destructive():
    lowered = text.lower()
    for forbidden in ("create_transfer", "flash_upload", "create_task", "add_download", "downloadchain(", "qbittorrent", "transmission", "aria2"):
        assert forbidden not in lowered



def test_recent_gying_failure_is_promoted_to_operator_attention():
    method = text.split("    def _status_overview_v191(", 1)[1].split(
        "    @staticmethod\n    def _inject_viewing_test_button",
        1,
    )[0]
    assert 'recent_failure = bool(viewing.get("enabled")) and recent.get("success") is False' in method
    assert 'overview["attention_count"] = int(overview.get("attention_count") or 0) + 1' in method
    assert 'overview["overall"] = "warning"' in method


def test_public_text_redacts_query_and_runtime_secrets():
    tree = ast.parse(text, filename=str(OBS))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "GuangYaGyingObservabilityV1104Mixin")
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "_gying_public_text")
    method.decorator_list = []
    module = ast.Module(body=[method], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"Any": object, "re": __import__("re")}
    exec(compile(module, str(OBS), "exec"), namespace)
    redact = namespace["_gying_public_text"]

    raw = (
        "GET https://example.invalid/search?q=demo&token=SECRET "
        "password=hunter2 captcha_token=ABC device_id=DEV "
        "https://pan.xunlei.com/s/PRIVATEID?pwd=7788"
    )
    safe = redact(raw)
    for secret in ("SECRET", "hunter2", "ABC", "DEV", "PRIVATEID", "7788"):
        assert secret not in safe
    assert "?<redacted>" in safe
    assert "password=<redacted>" in safe
    assert "captcha_token=<redacted>" in safe
    assert "device_id=<redacted>" in safe
    assert "/s/<redacted>" in safe


def test_observability_sanitizes_persisted_message_and_log_arguments():
    assert '"message": self._gying_public_text(message, 300)' in text
    assert "safe_args = tuple(" in text
    assert "self._gying_public_text(value, 260)" in text



def test_observability_distinguishes_cache_from_real_network_and_node_failover():
    for token in (
        "证据=%s",
        "HTTP搜索请求=%s",
        "详情请求=%s",
        "详情失败=%s",
        "节点尝试=%s",
        "搜索节点链",
        "cache_hit=cache_hit",
        "network_requested=network_requested",
        "search_requests=search_requests",
        "failover_attempts=failover_attempts",
    ):
        assert token in text



def _live_probe_class():
    tree = ast.parse(text, filename=str(OBS))
    source_class = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "GuangYaGyingObservabilityV1104Mixin"
    )
    wanted = {"_viewing_probe_subscription_v1104", "api_viewing_live_search_probe"}
    methods = []
    for node in source_class.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            node.returns = None
            for arg in node.args.args:
                arg.annotation = None
            methods.append(node)
    probe = ast.ClassDef(
        name="LiveProbe",
        bases=[],
        keywords=[],
        body=methods,
        decorator_list=[],
    )
    module = ast.Module(body=[probe], type_ignores=[])
    ast.fix_missing_locations(module)
    ns = {"Any": Any, "Dict": Dict, "List": List}
    exec(compile(module, str(OBS), "exec"), ns)
    return ns["LiveProbe"]


def test_live_gying_probe_forces_real_search_and_returns_only_sanitized_evidence():
    Probe = _live_probe_class()

    class Harness(Probe):
        def __init__(self):
            self._viewing_enabled = True
            self._selected_subscriptions = [42]
            self.calls = []
            self.records = []

        @staticmethod
        def _find_subscription(sid):
            return SimpleNamespace(id=42, name="示例剧", year=2026, season=1, type="TV") if sid == 42 else None

        @staticmethod
        def _is_movie_subscription(_subscribe):
            return False

        @staticmethod
        def _subscription_missing_episodes(_subscribe):
            return [5]

        @staticmethod
        def _provider_keyword(_subscribe):
            return "示例剧 2026 S01"

        @contextmanager
        def _gying_alias_scope_v11212(self, subscribe):
            assert subscribe.id == 42
            self.calls.append(("scope", subscribe.id))
            yield

        def _gying_raw_results(self, keyword, force=False):
            self.calls.append(("search", keyword, bool(force)))
            return (
                [
                    {"url": "https://pan.xunlei.com/s/SECRET?pwd=7788", "resource_kind": "pan"},
                    {"url": "magnet:?xt=urn:btih:ABC"},
                    {"url": "ed2k://|file|demo.mkv|100|HASH|/"},
                ],
                {
                    "success": True,
                    "node": "https://b.example",
                    "attempted_nodes": ["https://a.example", "https://b.example"],
                    "failover_attempts": 2,
                    "cache_hit": False,
                    "network_requested": True,
                    "search_request_count_total": 2,
                    "detail_request_count_total": 3,
                    "detail_failure_count_this_call": 1,
                    "search_mode": "browser",
                    "raw_cards": 5,
                    "matched_cards": 2,
                    "detail_cards": 2,
                    "message": "ok",
                },
            )

        @staticmethod
        def _gying_node_label(value):
            return str(value or "")

        @staticmethod
        def _gying_public_text(value, limit=300):
            return str(value or "")[:limit]

        def _gying_obs_log(self, *args):
            self.calls.append(("log", args))

        def _gying_obs_record(self, stage, **fields):
            self.records.append((stage, fields))

        def _upsert_source(self, *_args, **_kwargs):
            raise AssertionError("live probe must not create source")

        def _spawn_source_dispatch(self, *_args, **_kwargs):
            raise AssertionError("live probe must not dispatch transfer")

    h = Harness()
    result = h.api_viewing_live_search_probe()

    assert result["success"] is True
    assert result["subscribe_id"] == 42
    assert result["network_requested"] is True
    assert result["search_requests"] == 2
    assert result["detail_requests"] == 3
    assert result["detail_failures"] == 1
    assert result["attempted_nodes"] == ["https://a.example", "https://b.example"]
    assert result["xunlei"] == 1
    assert result["magnet"] == 1
    assert result["ed2k"] == 1
    assert ("search", "示例剧 2026 S01", True) in h.calls
    assert h.records[-1][0] == "live_search_probe"

    serialized = repr(result)
    for secret in ("SECRET", "7788", "magnet:?xt=", "ed2k://|file|"):
        assert secret not in serialized


def test_live_gying_probe_requires_real_network_evidence_even_if_state_says_success():
    Probe = _live_probe_class()

    class Harness(Probe):
        _viewing_enabled = True
        _selected_subscriptions = [42]

        @staticmethod
        def _find_subscription(_sid):
            return SimpleNamespace(id=42, name="示例剧", year=2026, season=1, type="TV")

        @staticmethod
        def _is_movie_subscription(_subscribe):
            return False

        @staticmethod
        def _subscription_missing_episodes(_subscribe):
            return [5]

        @staticmethod
        def _provider_keyword(_subscribe):
            return "示例剧 2026 S01"

        def _gying_raw_results(self, _keyword, force=False):
            assert force is True
            return [], {
                "success": True,
                "cache_hit": True,
                "network_requested": False,
                "search_request_count_this_call": 0,
                "message": "cached only",
            }

        @staticmethod
        def _gying_node_label(value):
            return str(value or "")

        @staticmethod
        def _gying_public_text(value, limit=300):
            return str(value or "")[:limit]

        @staticmethod
        def _gying_obs_log(*_args):
            return None

        @staticmethod
        def _gying_obs_record(*_args, **_kwargs):
            return None

    out = Harness().api_viewing_live_search_probe()
    assert out["success"] is False
    assert out["network_requested"] is False
    assert out["search_requests"] == 0


def test_live_gying_probe_has_dedicated_api_and_page_action():
    assert '"/viewing/search/probe"' in text
    assert '"实时搜观影"' in text
    assert "api_viewing_live_search_probe" in text
    assert "强制实时搜索一个固定订阅，仅返回脱敏搜索证据" in text
