from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
FINAL = PLUGIN / "dispatch_policy_final_v1125.py"
ENTRY = PLUGIN / "__init__.py"

final_text = FINAL.read_text(encoding="utf-8")
entry_text = ENTRY.read_text(encoding="utf-8")


def _method(name: str, next_name: str | None = None) -> str:
    start = final_text.index(f"    def {name}(")
    if next_name:
        return final_text[start:final_text.index(f"    def {next_name}(", start)]
    return final_text[start:]


def test_final_dispatch_parses_and_is_cooperative_runtime_authority():
    ast.parse(final_text, filename=str(FINAL))
    ast.parse(entry_text, filename=str(ENTRY))
    assert "class GuangYaDispatchPolicyFinalV1125Mixin:" in final_text
    assert "_DispatchPolicyPreviewV1125" not in final_text
    assert 'build_id = "20260904-r51-preview"' in final_text
    start = entry_text.index("class GuangYaTransferAssistant(")
    final_pos = entry_text.index("GuangYaDispatchPolicyFinalV1125Mixin,", start)
    preview_pos = entry_text.index("GuangYaDispatchPolicyV1125Mixin,", start)
    weekly_pos = entry_text.index("GuangYaAiringWeeklyV1121Mixin,", start)
    assert final_pos < preview_pos < weekly_pos


def test_stable_weekday_is_schedule_fact_not_calendar_failure_fallback():
    gate = _method("_airing_gate_v1120", "_record_auto_external_cooldown_v1125")
    assert 'not bool(result.get("calendar_available"))' in gate
    assert 'result.get("weekday") is not None' in gate
    assert 'result["calendar_available"] = True' in gate
    assert 'result["calendar_available_basis_v1125"] = "stable_weekday"' in gate
    assert 'bool(result.get("passive_channel_bypass_v1125"))' in gate


def test_daily_automatic_force_records_cooldown_but_manual_force_does_not():
    claim = _method("_claim_external_search_round_v1114", "_spawn_route_prime")
    record = _method("_record_auto_external_cooldown_v1125", "_claim_external_search_round_v1114")
    assert 'mode == "daily_repair_pull"' in claim
    assert "if not allowed or not force:" in claim
    assert '_record_auto_external_cooldown_v1125(subscribe, "daily_repair_pull")' in claim
    assert 'self.save_data("external_search_guard", state)' in record
    for manual in ("手动", "人工", "立即", "控制台"):
        assert manual not in claim


def test_new_subscription_prime_refreshes_channel_once_without_direct_gying_force():
    prime = _method("_spawn_route_prime", "_run_reliability_route_batch")
    assert "_cached_matches_for_subscription(subscribe)" in prime
    assert "self.refresh_channels(force=True)" in prime
    assert 'trigger="新订阅资源匹配"' in prime
    assert "仅按更新日历判断是否主动搜索" in prime
    assert "观影立即搜索" not in prime
    assert "_run_v1115_mode_batch" not in prime


def test_new_subscription_is_channel_first_then_date_gated_non_force_pull():
    method = _method("_run_reliability_route_batch")
    assert 'if "新订阅资源匹配" not in text:' in method
    channel = method.index('"新订阅资源匹配·频道阶段"')
    selector = method.index("_smart_pull_due_ids_v1125()")
    pull = method.index('"新订阅资源匹配·更新日历主动拉取"')
    assert channel < selector < pull
    assert '"channel_event"' in method
    assert '"airing_pull"' in method
    assert method.count("force=False") >= 2
    assert "pull_ids = [sid for sid in ids if sid in allowed]" in method
    assert '"subscription_prime"' not in method


def test_final_dispatch_does_not_reimplement_download_or_transfer_business_chain():
    lowered = final_text.lower()
    for forbidden in (
        "downloadchain(",
        "from app.chain.download",
        "qbittorrent",
        "transmission",
        "aria2",
        "_xunlei_import_json_batch",
        "cloudcollection",
    ):
        assert forbidden not in lowered
