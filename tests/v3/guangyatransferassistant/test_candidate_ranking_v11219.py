from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict, Tuple


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
GUARD = PLUGIN / "gying_recall_guard_v1125.py"
ENTRY = PLUGIN / "__init__.py"

text = GUARD.read_text(encoding="utf-8")
entry = ENTRY.read_text(encoding="utf-8")


def _helper_namespace():
    tree = ast.parse(text, filename=str(GUARD))
    wanted = {
        "_nonnegative_int_v11219",
        "_nonnegative_float_v11219",
        "candidate_quality_score_v11219",
        "candidate_rank_key_v11219",
    }
    body = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            body.append(node)
    module = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(module)
    ns = {
        "Any": Any,
        "Dict": Dict,
        "Tuple": Tuple,
        "_EXTERNAL_SOURCE_TIER_V11219": {"magnet": 0, "ed2k": 1},
    }
    exec(compile(module, str(GUARD), "exec"), ns)
    return ns


def _last_method(name: str, next_name: str | None = None) -> str:
    marker = f"    def {name}("
    start = text.rindex(marker)
    if next_name:
        end = text.index(f"    def {next_name}(", start)
        return text[start:end]
    return text[start:]


def test_v11219_guard_parses_without_premature_public_version_bump():
    ast.parse(text, filename=str(GUARD))
    ast.parse(entry, filename=str(ENTRY))
    assert "v1.12.19 开发阶段只增加安全排序与来源质量学习" in text
    assert 'plugin_version = "2.0.8"' in entry


def test_quality_score_is_neutral_without_samples_and_bounded_with_outcomes():
    score = _helper_namespace()["candidate_quality_score_v11219"]
    assert score({}) == 0
    assert score({"success": 8, "failure": 0}) > 0
    assert score({"success": 0, "failure": 8}) < 0
    assert -100 <= score({"success": 999999, "failure": 0}) <= 100
    assert -100 <= score({"success": 0, "failure": 999999}) <= 100


def test_dirty_quality_timestamps_fail_closed_to_zero():
    safe_float = _helper_namespace()["_nonnegative_float_v11219"]
    assert safe_float("broken") == 0.0
    assert safe_float(-123) == 0.0
    assert safe_float("12.5") == 12.5
    store = _last_method("_candidate_quality_store_v11219", "_candidate_quality_snapshot_v11219")
    assert '_nonnegative_float_v11219(value.get("updated_at"))' in store
    assert '_nonnegative_float_v11219(raw.get("updated_at"))' in store


def test_gying_search_and_viewing_auto_terminal_history_share_one_quality_key():
    method = _last_method("_candidate_quality_key_v11219", "_candidate_quality_store_v11219")
    assert 'origin_key == "viewing_auto"' in method
    assert 'provider = source_label or "GYING"' in method
    assert 'if provider in {"viewing", "gying"}:' in method
    assert 'provider = "gying"' in method


def test_fixed_source_tier_cannot_be_overturned_by_learning_or_coverage():
    rank = _helper_namespace()["candidate_rank_key_v11219"]
    worst_magnet = rank("magnet", True, 3, 99, 0, -100, 99, 99)
    best_ed2k = rank("ed2k", True, 0, 0, 99, 100, 0, 0)
    assert worst_magnet < best_ed2k


def test_learning_only_breaks_ties_inside_same_source_tier():
    rank = _helper_namespace()["candidate_rank_key_v11219"]
    high_quality = rank("magnet", True, 0, 0, 1, 70, 0, 10)
    low_quality = rank("magnet", True, 0, 0, 1, -70, 0, 0)
    assert high_quality < low_quality


def test_provider_dispatch_is_wrapped_not_reimplemented():
    method = _last_method("_dispatch_provider_candidate", "_search_external_providers")
    assert "local.subscribe = subscribe" in method
    assert "local.uncovered = set(uncovered or set())" in method
    assert "return super()._dispatch_provider_candidate(subscribe, uncovered)" in method
    for forbidden in ("_upsert_source(", "_spawn_source_dispatch(", "normalize_source_uri", "cloudcollection"):
        assert forbidden not in method


def test_external_provider_search_only_reorders_super_results():
    method = _last_method("_search_external_providers", "_xunlei_candidate_priority_v1125")
    assert "result = dict(super()._search_external_providers(keyword) or {})" in method
    assert 'rows = [dict(row) for row in (result.get("data") or []) if isinstance(row, dict)]' in method
    assert "candidate_rank_key_v11219(" in method
    assert "ranked.sort(key=lambda item: item[0])" in method
    assert 'result["data"] = [row for _key, row in ranked]' in method
    assert 'result["candidate_ranking_v11219"] = True' in method
    for forbidden in ("requests.", "session.get", "_gying_detail(", "_offline_request("):
        assert forbidden not in method


def test_quality_learning_observes_only_real_terminal_state_transitions():
    method = _last_method("_update_source", "_dispatch_provider_candidate")
    assert '_TERMINAL_SOURCE_OUTCOME_V11219 = {"completed": True, "failed": False}' in text
    assert "if target_state not in _TERMINAL_SOURCE_OUTCOME_V11219:" in method
    assert "return super()._update_source(source_id, **fields)" in method
    assert "before_state != target_state" in method
    assert "_record_candidate_quality_outcome_v11219" in method
    for transient in ("retry", "waiting", "submitted", "dispatching", "queued"):
        assert f'"{transient}":' not in text.split("_TERMINAL_SOURCE_OUTCOME_V11219 =", 1)[1].split("}", 1)[0]


def test_xunlei_keeps_existing_missing_priority_as_prefix():
    method = _last_method("_xunlei_candidate_priority_v1125")
    assert "base = tuple(super()._xunlei_candidate_priority_v1125(subscribe, row, missing))" in method
    assert "return (*base, package_penalty, len(extras), -len(overlap), passcode_penalty)" in method
    assert "_candidate_episode_hint_v1125" in method


def test_v11219_layer_does_not_add_local_download_or_bypass_final_gates():
    v11219 = text.split("_GuangYaGyingRecallGuardV1125Base =", 1)[1].lower()
    for forbidden in (
        "downloadchain(",
        "from app.chain.download",
        "qbittorrent",
        "transmission",
        "aria2",
        "_xunlei_import_json_batch",
        "_xunlei_share_info(",
        "_planner_file_selection(",
    ):
        assert forbidden not in v11219
