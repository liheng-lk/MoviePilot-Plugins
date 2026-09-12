from __future__ import annotations

import runpy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
RESOLVER = PLUGIN / "episode_resolver_v190.py"
CORE = PLUGIN / "core_pipeline_v11214.py"


def _resolver_ns():
    return runpy.run_path(str(RESOLVER))


def test_explicit_payload_season_wins_over_subscription_hint():
    ns = _resolver_ns()
    resolve_episode = ns["resolve_episode"]

    result = resolve_episode(
        "Divas Hit the Road (2014) - S06E04 - 2160p.WEB-DL.H265.mp4",
        season_hint=3,
    )
    assert result["season"] == 6
    assert result["episodes"] == [4]
    assert result["confidence"] == 1.0

    nested = resolve_episode(
        "Season 06/04.mp4",
        package_paths=["Season 06/03.mp4", "Season 06/04.mp4", "Season 06/05.mp4"],
        season_hint=3,
    )
    assert nested["season"] == 6
    assert nested["episodes"] == [4]


def test_subscription_season_hint_remains_fallback_for_weak_names():
    ns = _resolver_ns()
    resolve_episode = ns["resolve_episode"]

    result = resolve_episode(
        "04.mp4",
        package_paths=["03.mp4", "04.mp4", "05.mp4"],
        season_hint=3,
    )
    assert result["season"] == 3
    assert result["episodes"] == [4]
    assert float(result["confidence"]) >= 0.90


def test_final_physical_gate_rejects_cross_season_before_episode_subset_check():
    text = CORE.read_text(encoding="utf-8")
    method = text.split("    def _resolved_episode_set_v11214(", 1)[1].split(
        "    # ------------------------------------------------------------------", 1
    )[0]
    assert "expected_season" in method
    assert "actual_season" in method
    assert "actual_season != expected_season" in method
    assert "【光鸭转存助手】【季范围门禁】" in method
    assert method.index("actual_season != expected_season") < method.index(
        "return set(reliable_episode_set(result, threshold))"
    )
