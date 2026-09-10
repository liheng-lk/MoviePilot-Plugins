from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict, Tuple


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
RECALL = PLUGIN / "gying_recall_guard_v1125.py"
PROVIDER = PLUGIN / "provider_reliability_v1100.py"


def _load_functions(path: Path, names: set[str], globals_extra: dict):
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    module = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(module)
    ns = {"Any": Any, "Dict": Dict, "Tuple": Tuple, **globals_extra}
    exec(compile(module, str(path), "exec"), ns)
    return ns


def test_provider_and_recall_quality_scores_are_formula_identical():
    recall = _load_functions(
        RECALL,
        {"_nonnegative_int_v11219", "candidate_quality_score_v11219"},
        {},
    )
    provider = _load_functions(
        PROVIDER,
        {"_nonnegative_int_v11219", "_quality_score_v11219"},
        {},
    )
    samples = [
        {},
        {"success": 1, "failure": 0},
        {"success": 0, "failure": 1},
        {"success": 3, "failure": 2},
        {"success": 20, "failure": 20},
        {"success": 200, "failure": 3},
        {"success": "broken", "failure": -8},
    ]
    for stats in samples:
        assert recall["candidate_quality_score_v11219"](stats) == provider["_quality_score_v11219"](stats)


def test_provider_and_recall_rank_keys_are_formula_identical():
    tiers = {"magnet": 0, "ed2k": 1}
    recall = _load_functions(
        RECALL,
        {"candidate_rank_key_v11219"},
        {"_EXTERNAL_SOURCE_TIER_V11219": tiers},
    )
    provider = _load_functions(
        PROVIDER,
        {"_candidate_rank_key_v11219"},
        {"_EXTERNAL_SOURCE_TIER_V11219": tiers},
    )
    rank_a = recall["candidate_rank_key_v11219"]
    rank_b = provider["_candidate_rank_key_v11219"]
    for source_type in ("magnet", "ed2k", "unknown"):
        for eligible in (False, True):
            for coverage in (0, 1, 2, 3):
                for quality in (-100, -25, 0, 25, 100):
                    args = (source_type, eligible, coverage, 2, 3, quality, 1, 7)
                    assert rank_a(*args) == rank_b(*args)


def test_runtime_mro_places_provider_reliability_before_recall_guard():
    entry = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
    class_body = entry.split("class GuangYaTransferAssistant(", 1)[1].split("):", 1)[0]
    assert class_body.index("GuangYaProviderReliabilityV1100Mixin") < class_body.index("GuangYaGyingRecallGuardV1125Mixin")
