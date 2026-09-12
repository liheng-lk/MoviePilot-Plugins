"""r103 regressions for summary dedup, channel->GYING fallback and numbered sequels."""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict, Iterable, List

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


def _exec_identity():
    ns = {}
    exec(compile(_bundled("media_identity_v1111"), "<media_identity_v1111>", "exec"), ns)
    return ns


def _exec_dedupe():
    diag_ns = {}
    exec(compile(_bundled("transfer_diag_v209"), "<transfer_diag_v209>", "exec"), diag_ns)
    prod_tree = ast.parse(_bundled("production_safety_v208"), filename="<production_safety_v208>")
    fn = next(node for node in prod_tree.body if isinstance(node, ast.FunctionDef) and node.name == "_dedupe_summary_diags_v208")
    ns = {
        "Any": Any, "Dict": Dict, "Iterable": Iterable, "List": List,
        "aggregate_subscription_diag": diag_ns["aggregate_subscription_diag"],
    }
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<dedupe>", "exec"), ns)
    return ns["_dedupe_summary_diags_v208"]


def test_summary_dedup_is_one_final_row_per_subscription_and_later_tie_wins():
    dedupe = _exec_dedupe()
    rows = [
        {"sid": 58, "state": "FAILED_FINAL", "reason_code": "SEASON_MISMATCH", "stage": "IDENTITY", "subscribe_title": "我们的少年时代2"},
        {"sid": 58, "state": "FAILED_FINAL", "reason_code": "SEASON_MISMATCH", "stage": "IDENTITY", "subscribe_title": "我们的少年时代2"},
        {"sid": 200, "state": "NO_RESULT", "reason_code": "NO_LOCAL_RESOURCE", "stage": "MATCH", "subscribe_title": "生逢其时"},
        {"sid": 200, "state": "NO_RESULT", "reason_code": "EXTERNAL_SEARCH_NO_RESULT", "stage": "EXTERNAL_SEARCH", "subscribe_title": "生逢其时"},
    ]
    result = dedupe(rows)
    assert len(result) == 2
    by_sid = {int(row["sid"]): row for row in result}
    assert by_sid[58]["reason_code"] == "SEASON_MISMATCH"
    assert by_sid[200]["reason_code"] == "EXTERNAL_SEARCH_NO_RESULT"


def test_numbered_sequel_season_alias_is_narrow_and_regular_cross_season_stays_blocked():
    ns = _exec_identity()
    helper = ns["sequel_numbered_title_season_alias_v1111"]
    assess = ns["assess_media_identity_v1111"]
    assert helper(["我们的少年时代2"], 1, {2}, ["我们的少年时代2 S02E01"], expected_year=2026)
    assert not helper(["我们的少年时代"], 1, {2}, ["我们的少年时代 S02E01"], expected_year=2026)
    allowed = assess(
        aliases=["我们的少年时代2"], expected_year=2026, expected_season=1, is_movie=False,
        primary_evidences=["我们的少年时代2 (2026) S02"], file_evidences=["我们的少年时代2.S02E01.mkv"],
    )
    blocked = assess(
        aliases=["我们的少年时代"], expected_year=2026, expected_season=1, is_movie=False,
        primary_evidences=["我们的少年时代 (2026) S02"], file_evidences=["我们的少年时代.S02E01.mkv"],
    )
    assert allowed["ok"] is True
    assert blocked["ok"] is False and blocked["reason_code"] == "SEASON_MISMATCH"


def test_channel_and_manual_refresh_have_bounded_gying_fallback_and_no_duplicate_heading():
    dispatch = _bundled("dispatch_policy_v1125")
    final_dispatch = _bundled("dispatch_policy_final_v1125")
    production = _bundled("production_safety_v208")
    assert "def _run_channel_then_due_gying_v103" in dispatch
    assert "allowed = set(self._smart_pull_due_ids_v1125())" in dispatch
    assert "频道后观影补搜" in dispatch
    assert '"airing_pull"' in dispatch
    assert '"手动刷新"' in final_dispatch
    assert "_run_channel_then_due_gying_v103" in final_dispatch
    assert "_dedupe_summary_diags_v208" in production
    assert 'body_lines[0].strip() == "⚠️ 光鸭转存检查汇总"' in production
