from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"


def test_v11218_public_release_truth_and_ranking_layer_are_consistent():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    entry = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
    ranking = (PLUGIN / "candidate_ranking_v11218.py").read_text(encoding="utf-8")
    assert package["version"] == local["version"] == "1.12.18"
    assert 'plugin_version = "1.12.18"' in entry
    assert 'build_id = "20260906-r65"' in entry
    assert 'build_id = "20260906-r65"' in ranking
    assert "v1.12.18" in package.get("history", {})


def test_v11218_keeps_wide_recall_strict_write_and_fixed_source_priority():
    ranking = (PLUGIN / "candidate_ranking_v11218.py").read_text(encoding="utf-8")
    planner = (PLUGIN / "resource_planner_v190.py").read_text(encoding="utf-8")
    bridge = (PLUGIN / "movie_bilingual_identity_v11216.py").read_text(encoding="utf-8")
    assert "class GuangYaCandidateRankingV11218Mixin(GuangYaSearchRecallV11217Mixin):" in ranking
    assert "class GuangYaMovieBilingualIdentityV11216Mixin(GuangYaCandidateRankingV11218Mixin):" in bridge
    assert 'external.sort(key=lambda row: 0 if str(row.get("type") or "") == "magnet" else 1)' in planner
    assert 'rank = 1 if source_type == "magnet" else 2' in planner
    for forbidden in ("qbittorrent", "transmission", "cloudcollection/v1/create_task", "userres/rapid"):
        assert forbidden not in ranking.lower()
