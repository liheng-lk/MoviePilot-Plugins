from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
GOV = PLUGIN / "governance_v1114.py"
UI = PLUGIN / "gying_ui_v1109.py"
TEXT = GOV.read_text(encoding="utf-8")
UI_TEXT = UI.read_text(encoding="utf-8")


def _method(name: str, next_name: str) -> str:
    return TEXT.split(f"    def {name}(", 1)[1].split(f"    def {next_name}(", 1)[0]


def test_governance_layer_parses_and_is_final_gying_ui_parent():
    ast.parse(TEXT, filename=str(GOV))
    ast.parse(UI_TEXT, filename=str(UI))
    assert "class GuangYaGovernanceV1114Mixin(GuangYaRuntimeFixV1113Mixin):" in TEXT
    assert "from .governance_v1114 import GuangYaGovernanceV1114Mixin" in UI_TEXT
    assert "class GuangYaGyingUiV1109Mixin(GuangYaGovernanceV1114Mixin):" in UI_TEXT
    assert 'build_id = "20260902-r25"' in UI_TEXT


def test_periodic_active_subscription_is_dropped_instead_of_recheck_loop():
    block = _method("_queue_async_route_check", "_external_search_state_v1114")
    assert "ids.intersection(active)" in block
    assert "ids -= active" in block
    assert "不生成补偿轮" in block
    assert "super()._queue_async_route_check(ids, trigger=trigger)" in block


def test_external_search_has_persistent_per_subscription_cooldown_and_force_escape():
    block = _method("_claim_external_search_round_v1114", "_try_transfer_subscription")
    assert 'self.get_data("external_search_guard")' in TEXT
    assert "if force:" in block
    assert "cooldown_minutes" in block
    assert 'self.save_data("external_search_guard", state)' in block
    dispatch = _method("_dispatch_xunlei_flash", "_dispatch_viewing_external_v1113")
    assert "订阅已无缺集，跳过迅雷外部检索" in dispatch
    assert "迅雷外部检索处于冷却期" in dispatch


def test_cloud_and_xunlei_completion_paths_call_official_completion_gate():
    xunlei = _method("_dispatch_xunlei_flash", "_dispatch_viewing_external_v1113")
    poll = _method("_poll_offline_source", "_custom_reject_terms_v1114")
    assert "self._finish_subscription_if_complete(subscribe)" in xunlei
    assert "self._finish_subscription_if_complete(subscribe)" in poll
    assert 'result["subscription_completed"] = True' in poll


def test_quality_gate_blocks_bphdtv_low_quality_and_low_resolution():
    assert "bphdtv\\.com" in TEXT.lower()
    assert "更多电视剧集下载请访问" in TEXT
    assert "更多剧集打包下载请访问" in TEXT
    quality = _method("_quality_reject_reason_v1114", "_subfile_name_v1114")
    assert "_POISON_MEDIA_RE_V1114.search" in quality
    assert "_LOW_QUALITY_RE_V1114.search" in quality
    assert "_RESOLUTION_RE_V1114.findall" in quality
    planner = _method("_planner_file_selection", "_viewing_external_candidates_v1113")
    assert "quality_rejected" in planner
    assert "未检测到字幕信号" in planner


def test_quality_and_cooldown_controls_are_exposed_in_config():
    for key in (
        "external_search_cooldown_minutes",
        "quality_min_resolution",
        "quality_min_video_mb",
        "quality_reject_low_tags",
        "quality_require_subtitle",
        "quality_custom_reject",
    ):
        assert key in TEXT
