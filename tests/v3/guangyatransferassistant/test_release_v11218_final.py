from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"


def test_final_v11218_tree_is_publishable():
    entry = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
    plugin = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    ranking = (PLUGIN / "candidate_ranking_v11218.py").read_text(encoding="utf-8")
    recall = (PLUGIN / "search_recall_v11217.py").read_text(encoding="utf-8")
    bilingual = (PLUGIN / "movie_bilingual_identity_v11216.py").read_text(encoding="utf-8")
    planner = (PLUGIN / "resource_planner_v190.py").read_text(encoding="utf-8")

    assert 'plugin_version = "1.12.18"' in entry
    assert 'build_id = "20260906-r65"' in entry
    assert plugin["version"] == "1.12.18"
    assert package["GuangYaTransferAssistant"]["version"] == "1.12.18"
    assert "v1.12.18" in package["GuangYaTransferAssistant"]["history"]

    assert 'class GuangYaCandidateRankingV11218Mixin(GuangYaSearchRecallV11217Mixin):' in ranking
    assert 'build_id = "20260906-r65"' in ranking
    assert 'class GuangYaSearchRecallV11217Mixin' in recall
    assert 'class GuangYaMovieBilingualIdentityV11216Mixin(GuangYaCandidateRankingV11218Mixin):' in bilingual
    assert 'plugin_version = "1.12.16"' in bilingual
    assert 'build_id = "20260906-r63"' in bilingual

    assert 'external.sort(key=lambda row: 0 if str(row.get("type") or "") == "magnet" else 1)' in planner
    assert 'rank = 1 if source_type == "magnet" else 2' in planner
    assert "观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K" in entry


def test_final_v11218_release_tooling_is_removed():
    assert not (ROOT / "scripts/_prepare_guangya_v11218.py").exists()
    assert not (ROOT / ".github/workflows/prepare-guangya-v11218.yml").exists()
