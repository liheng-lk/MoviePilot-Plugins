from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
PROVIDER = PLUGIN / "provider_reliability_v1100.py"


def _load_provider_module():
    package_name = "_gy_failure_attribution_v11219_testpkg"
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
    helper._dedupe_candidates = lambda rows: list(rows or [])
    helper._find_links = lambda *_args, **_kwargs: []
    sys.modules[helper.__name__] = helper

    spec = importlib.util.spec_from_file_location(f"{package_name}.provider_reliability_v1100", PROVIDER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MOD = _load_provider_module()


class _LearningSink:
    def __init__(self):
        self.learned = []
        self.logs = []

    def _record_candidate_quality_outcome_v11219(self, row, success):
        self.learned.append((dict(row), bool(success)))

    def _plugin_log(self, *args):
        self.logs.append(args)


class _Dummy(MOD.GuangYaProviderReliabilityV1100Mixin, _LearningSink):
    pass


def test_success_always_reaches_learning_sink():
    obj = _Dummy()
    row = {"id": "s1", "state": "completed", "provider": "demo"}
    obj._record_candidate_quality_outcome_v11219(row, True)
    assert obj.learned == [(row, True)]


def test_real_remote_task_status_5_is_source_attributable():
    obj = _Dummy()
    row = {
        "id": "s2",
        "state": "failed",
        "task_id": "task-real",
        "task_status": 5,
        "last_error": "光鸭任务部分完成或添加失败，已达到自动重试上限",
    }
    assert obj._candidate_failure_is_source_attributable_v11219(row) is True
    obj._record_candidate_quality_outcome_v11219(row, False)
    assert obj.learned == [(row, False)]


def test_resolved_rule_mismatch_and_no_media_are_source_attributable():
    obj = _Dummy()
    rows = [
        {"id": "rule", "state": "failed", "last_error": "订阅规则不匹配：分辨率不满足"},
        {"id": "empty", "state": "failed", "last_error": "光鸭已解析来源，但未发现可选的视频或字幕文件"},
    ]
    for row in rows:
        assert obj._candidate_failure_is_source_attributable_v11219(row) is True
        obj._record_candidate_quality_outcome_v11219(row, False)
    assert obj.learned == [(rows[0], False), (rows[1], False)]


def test_platform_network_admin_and_target_failures_do_not_poison_provider_quality():
    obj = _Dummy()
    rows = [
        {"id": "deleted", "state": "failed", "last_error": "绑定的 MoviePilot 订阅已不存在"},
        {"id": "network", "state": "failed", "last_error": "HTTPSConnectionPool: Read timed out"},
        {"id": "api", "state": "failed", "last_error": "创建光鸭云添加任务失败：HTTP 503"},
        {"id": "target", "state": "failed", "last_error": "目标目录创建失败"},
        {"id": "status-only", "state": "failed", "task_status": 5, "last_error": "没有真实 taskId"},
    ]
    for row in rows:
        assert obj._candidate_failure_is_source_attributable_v11219(row) is False
        obj._record_candidate_quality_outcome_v11219(row, False)
    assert obj.learned == []
    assert len(obj.logs) == len(rows)


def test_attribution_guard_calls_super_instead_of_writing_quality_store_itself():
    text = PROVIDER.read_text(encoding="utf-8")
    method = text.split("    def _record_candidate_quality_outcome_v11219", 1)[1].split(
        "    def _parse_provider_defs", 1
    )[0]
    assert "super()._record_candidate_quality_outcome_v11219(row, True)" in method
    assert "super()._record_candidate_quality_outcome_v11219(row, False)" in method
    for forbidden in ("save_data(", "get_data(", "candidate_quality_v11219"):
        assert forbidden not in method
