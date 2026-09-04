from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
OBS = (PLUGIN / "gying_observability_v1104.py").read_text(encoding="utf-8")


def _method(name: str, next_name: str) -> str:
    return OBS[OBS.index(f"    def {name}("):OBS.index(f"    def {next_name}(")]


def test_v1125_observability_parses_and_marks_preview_build():
    ast.parse(OBS)
    assert 'build_id = "20260904-r51-preview"' in OBS
    assert "当前订阅召回" in OBS


def test_v1125_xunlei_recall_log_contains_search_and_missing_dimensions():
    method = _method("_search_viewing_xunlei", "_dispatch_xunlei_flash")
    for token in (
        "_gying_xunlei_context_v1125",
        "_subscription_missing_episodes(subscribe)",
        "_xunlei_candidate_priority_v1125",
        'state.get("cards")',
        'state.get("detail_cards")',
        'state.get("xunlei_resources")',
        'state.get("query_fallback")',
        "迅雷召回：订阅=",
        "当前缺集=%s",
        "直接覆盖=%s",
        "迅雷未命中：订阅=",
    ):
        assert token in method


def test_v1125_diagnostics_never_log_share_identity_or_passcode():
    method = _method("_search_viewing_xunlei", "_dispatch_xunlei_flash")
    assert 'row.get("share_id")' not in method
    assert 'row.get("identity")' not in method
    assert 'row.get("passcode")' not in method


def test_v1125_xunlei_dispatch_log_closes_recall_to_execution_loop():
    method = _method("_dispatch_xunlei_flash", "_status_overview_v191")
    for token in (
        "super()._dispatch_xunlei_flash(subscribe)",
        'result.get("shares")',
        'result.get("successful_files")',
        'result.get("episodes")',
        'result.get("handled")',
        "迅雷执行：订阅=#%s",
        '"xunlei_dispatch"',
    ):
        assert token in method
