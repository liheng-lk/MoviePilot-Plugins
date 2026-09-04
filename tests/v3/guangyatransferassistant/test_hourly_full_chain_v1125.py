from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
FINAL = (PLUGIN / "dispatch_policy_final_v1125.py").read_text(encoding="utf-8")
POLICY = (PLUGIN / "dispatch_policy_v1125.py").read_text(encoding="utf-8")
XUNLEI = (PLUGIN / "xunlei_flash_v193.py").read_text(encoding="utf-8")
VIEWING = (PLUGIN / "viewing_dispatch_v1113.py").read_text(encoding="utf-8")


def _method(text: str, name: str, next_name: str) -> str:
    start = text.index(f"    def {name}(")
    end = text.index(f"    def {next_name}(", start)
    return text[start:end]


def test_final_policy_parses():
    ast.parse(FINAL)


def test_hourly_selector_overrides_global_180_minute_cooldown():
    method = _method(FINAL, "_external_cooldown_due_v1125", "_record_auto_external_cooldown_v1125")
    assert "_hourly_due_cooldown_seconds_v1125" in method
    assert "60 * 60" in method
    assert "_external_search_cooldown_minutes_v1114" not in method


def test_airing_pull_claim_uses_dedicated_one_hour_window_only_for_due_mode():
    method = _method(FINAL, "_claim_external_search_round_v1114", "_spawn_route_prime")
    assert 'mode == "airing_pull"' in method
    assert "not force" in method
    assert "_hourly_due_cooldown_seconds_v1125" in method
    assert '"origin": "airing_full_chain_v1125"' in method
    assert "super()._claim_external_search_round_v1114" in method
    assert 'mode == "daily_repair_pull"' in method


def test_hourly_service_still_filters_due_media_before_dispatch():
    method = _method(POLICY, "_calendar_due_check_v1110", "_repair_signature_v1125")
    assert "due_ids = self._smart_pull_due_ids_v1125()" in method
    assert "_run_v1115_mode_batch(" in method
    assert '"airing_pull"' in method
    assert "force=False" in method


def test_airing_pull_runs_normal_full_source_chain_not_channel_only_path():
    xunlei_method = XUNLEI.split("    def _try_transfer_subscription_inner(", 1)[1].split(
        "    def api_xunlei_flash_test(", 1
    )[0]
    assert "flash = self._dispatch_xunlei_flash(subscribe)" in xunlei_method
    assert 'if flash.get("handled")' in xunlei_method
    assert "lower = super()._try_transfer_subscription_inner" in xunlei_method

    viewing_method = VIEWING.split("    def _try_transfer_subscription_inner(", 1)[1]
    assert "lower = dict(super()._try_transfer_subscription_inner" in viewing_method
    assert "viewing = self._dispatch_viewing_external_v1113(subscribe)" in viewing_method
    assert 'if viewing.get("actions")' in viewing_method


def test_documented_priority_matches_existing_full_chain_contract():
    assert "观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K" in FINAL
