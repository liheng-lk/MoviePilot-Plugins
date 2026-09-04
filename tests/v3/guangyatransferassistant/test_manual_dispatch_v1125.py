from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
MANUAL = PLUGIN / "manual_dispatch_v1125.py"
ENTRY = PLUGIN / "__init__.py"
LEGACY = PLUGIN / "legacy.py"
PAGE_AUTH = PLUGIN / "page_auth_v172.py"
EXPERIENCE = PLUGIN / "experience_v170.py"

manual_text = MANUAL.read_text(encoding="utf-8")
entry_text = ENTRY.read_text(encoding="utf-8")
legacy_text = LEGACY.read_text(encoding="utf-8")
page_auth_text = PAGE_AUTH.read_text(encoding="utf-8")
experience_text = EXPERIENCE.read_text(encoding="utf-8")


def _method(name: str, next_name: str | None = None) -> str:
    start = manual_text.index(f"    def {name}(")
    if next_name:
        return manual_text[start:manual_text.index(f"    def {next_name}(", start)]
    return manual_text[start:]


def test_manual_dispatch_parses_and_sits_before_final_policy():
    ast.parse(manual_text, filename=str(MANUAL))
    ast.parse(entry_text, filename=str(ENTRY))
    assert "from .manual_dispatch_v1125 import GuangYaManualDispatchV1125Mixin" in entry_text
    start = entry_text.index("class GuangYaTransferAssistant(")
    page = entry_text.index("GuangYaPagePerfV1123Mixin,", start)
    manual = entry_text.index("GuangYaManualDispatchV1125Mixin,", start)
    final = entry_text.index("GuangYaDispatchPolicyFinalV1125Mixin,", start)
    preview = entry_text.index("GuangYaDispatchPolicyV1125Mixin,", start)
    assert page < manual < final < preview


def test_page_check_missing_original_contract_is_force_true_and_async_trigger_restores_it():
    original = legacy_text.split("    def api_check_missing(", 1)[1].split("    def api_recheck_pending(", 1)[0]
    assert "_manual_transfer_guard(subscribe)" in original
    assert "_prepare_cache_first_manual_check(subscribe" in original
    assert "_try_transfer_subscription(subscribe, force=True, refresh_channel=False)" in original
    assert '"/check_missing": "状态页立即检查缺集"' in page_auth_text

    dispatch = _method("_run_dispatch_trigger_v1125")
    runner = _method("_run_manual_api_v1125", "_run_route_activation_v1125")
    assert '"状态页立即检查缺集"' in manual_text
    assert '"消息立即检查"' in manual_text
    assert "self.api_check_missing(subscribe_id=sid)" in runner
    assert "pending_only=False" in dispatch


def test_pending_recheck_keeps_force_false_but_bypasses_airing_date_gate_only_in_its_thread():
    original = legacy_text.split("    def api_recheck_pending(", 1)[1].split("    def api_reset_state(", 1)[0]
    assert "_try_transfer_subscription(subscribe, force=False)" in original
    assert '"/recheck_pending": "状态页复查待落盘"' in page_auth_text

    dispatch = _method("_run_dispatch_trigger_v1125")
    runner = _method("_run_manual_api_v1125", "_run_route_activation_v1125")
    gate = _method("_airing_gate_v1120", "_run_manual_api_v1125")
    assert "self.api_recheck_pending(subscribe_id=sid)" in runner
    assert "pending_only=True" in dispatch
    assert 'local.pending_recheck = True' in runner
    assert 'delattr(local, "pending_recheck")' in runner
    assert 'getattr(local, "pending_recheck", False)' in gate
    assert '"calendar_available": False' in gate
    assert '"pending_recheck_bypass_v1125": True' in gate
    assert "return dict(super()._airing_gate_v1120" in gate
    assert "force=True" not in runner


def test_message_gycheck_uses_same_force_manual_boundary():
    handler = experience_text.split("    def _handle_check_existing_command(", 1)[1].split(
        "    def _handle_explain_existing_command(", 1
    )[0]
    assert 'trigger="消息立即检查"' in handler
    assert '"消息立即检查"' in manual_text


def test_route_takeover_is_channel_first_then_existing_smart_pull_not_force():
    route = _method("_run_route_activation_v1125", "_run_dispatch_trigger_v1125")
    assert '"消息切换路线"' in manual_text
    assert '"页面切换光鸭路线"' in manual_text
    assert "_cached_matches_for_subscription(subscribe)" in route
    assert "self.refresh_channels(force=True)" in route
    assert 'super()._run_dispatch_trigger_v1125(active, "新订阅资源匹配")' in route
    assert "_try_transfer_subscription" not in route
    assert "force=True" not in route


def test_bulk_console_processing_is_not_silently_upgraded_to_unbounded_force():
    # 控制台批量“处理缺集”可能一次覆盖大量订阅；它继续走 FinalPolicy 的智能日历/冷却路径。
    assert '"控制台处理缺集"' not in manual_text.split("_manual_force_triggers_v1125", 1)[1].split("}", 1)[0]


def test_manual_boundary_does_not_reimplement_transfer_or_download_business():
    lowered = manual_text.lower()
    for forbidden in (
        "downloadchain(",
        "from app.chain.download",
        "qbittorrent",
        "transmission",
        "aria2",
        "_xunlei_import_json_batch",
        "cloudcollection",
        "_dispatch_xunlei_flash(",
    ):
        assert forbidden not in lowered
