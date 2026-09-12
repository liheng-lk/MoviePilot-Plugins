from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path
from types import SimpleNamespace


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ENTRY = (ROOT / "plugins.v3" / "guangyatransferassistant" / "__init__.py").read_text(encoding="utf-8")


def _harness():
    path = HERE / "final_plugin_harness_v211.py"
    name = "r101_final_plugin_harness"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _tv():
    return SimpleNamespace(
        id=8,
        name="汴京上元局",
        type="电视剧",
        season=1,
        start_episode=1,
        total_episode=20,
        note=[],
        state="R",
        best_version=0,
    )


def test_target_sensitive_cooldown_reopens_once_for_new_or_recovered_gaps():
    h = _harness()
    store = {
        "external_search_guard": {
            "8": {
                "last_at": time.time() - 10 * 60,
                "last_time": "2026-09-12 23:14:00",
                "cooldown_minutes": 180,
            }
        }
    }
    plugin = h.make_final_plugin(store=store)
    plugin._is_movie_subscription = lambda sub: False
    plugin._route_source_mode_value_v1115 = lambda: ""
    plugin._now_text = lambda: "2026-09-12 23:24:00"

    targets = {1, 2, 3}
    plugin._subscription_missing_episodes = lambda sub: sorted(targets)

    # Legacy guard has a recent negative-search timestamp but no target snapshot.
    # The current real gap must get one immediate search instead of waiting ~170 min.
    assert plugin._claim_external_search_round_v1114(_tv(), force=False) is True
    row = store["external_search_guard"]["8"]
    assert row["target_episodes_v213"] == [1, 2, 3]
    assert row["origin"] == "target_changed_v213"

    # Same target set remains governed by the normal cooldown.
    assert plugin._claim_external_search_round_v1114(_tv(), force=False) is False

    # A newly aired/reopened E04 is a new target and bypasses the old negative result once.
    targets.add(4)
    assert plugin._claim_external_search_round_v1114(_tv(), force=False) is True
    assert store["external_search_guard"]["8"]["target_episodes_v213"] == [1, 2, 3, 4]


def test_r101_source_keeps_cooldown_scope_narrow():
    start = ENTRY.rindex("\nclass GuangYaTransferAssistant(")
    final = ENTRY[start:]
    method = final.split("    def _claim_external_search_round_v1114(", 1)[1].split(
        "\n    def _normalize_transfer_candidate", 1
    )[0]
    assert "expanded = set(current) - previous" in method
    assert "target_episodes_v213" in method
    assert "检索冷却重开v2.1.3" in method
    assert "super()._claim_external_search_round_v1114(subscribe, force=False)" in method
    assert "if current and expanded" in method
