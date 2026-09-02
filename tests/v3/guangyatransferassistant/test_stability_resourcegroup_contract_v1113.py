from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
STABILITY = PLUGIN / "stability_v1106.py"
PLANNER = PLUGIN / "resource_planner_v190.py"
ENTRY = PLUGIN / "__init__.py"


def _method(path: Path, class_name: str, method_name: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == method_name:
                    return child
    raise AssertionError(f"missing {class_name}.{method_name}")


def test_stability_upsert_transparently_forwards_resourceplanner_metadata():
    stability = _method(STABILITY, "GuangYaStabilityV1106Mixin", "_upsert_source")
    planner = _method(PLANNER, "GuangYaResourcePlannerMixin", "_upsert_source")

    planner_metadata = {
        "resource_group_id",
        "target_episodes",
        "episode_hint",
        "source_label",
        "message_id",
        "candidate_rank",
    }
    planner_kwonly = {arg.arg for arg in planner.args.kwonlyargs}
    assert planner_metadata <= planner_kwonly

    # Stability sits before ResourcePlanner in the final MRO, so it must not freeze the
    # keyword-only contract. **metadata is the compatibility boundary for later planner fields.
    assert stability.args.kwarg is not None
    assert stability.args.kwarg.arg == "metadata"
    rendered = ast.unparse(stability)
    assert "**metadata" in rendered
    assert "super()._upsert_source" in rendered


def test_final_mro_still_places_stability_before_resourceplanner():
    entry = ENTRY.read_text(encoding="utf-8")
    start = entry.index("class GuangYaTransferAssistant(")
    assert entry.index("GuangYaStabilityV1106Mixin,", start) < entry.index(
        "GuangYaResourcePlannerMixin,", start
    )
