from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = PLUGIN / "__init__.py"
RELIABILITY = PLUGIN / "xunlei_reliability_v1100.py"
RECALL = PLUGIN / "gying_recall_guard_v1125.py"

entry_text = ENTRY.read_text(encoding="utf-8")
reliability_text = RELIABILITY.read_text(encoding="utf-8")
recall_text = RECALL.read_text(encoding="utf-8")


def _method(text: str, name: str, next_name: str | None = None) -> str:
    start = text.index(f"    def {name}(")
    if next_name:
        return text[start:text.index(f"    def {next_name}(", start)]
    return text[start:]


def test_xunlei_recall_circuit_patch_parses_and_sits_above_recall_guard():
    ast.parse(reliability_text, filename=str(RELIABILITY))
    ast.parse(recall_text, filename=str(RECALL))
    ast.parse(entry_text, filename=str(ENTRY))
    start = entry_text.index("class GuangYaTransferAssistant(")
    reliability = entry_text.index("GuangYaXunleiReliabilityV1100Mixin,", start)
    recall = entry_text.index("GuangYaGyingRecallGuardV1125Mixin,", start)
    hardening = entry_text.index("GuangYaGyingHardeningMixin,", start)
    assert reliability < recall < hardening


def test_captcha_circuit_is_sticky_across_keyword_rounds_without_faking_handled():
    merge = _method(reliability_text, "_merge_xunlei_rounds_v1125", "_dispatch_viewing_external_v1113")
    assert "super()._merge_xunlei_rounds_v1125(base, extra)" in merge
    assert '(base or {}).get("captcha_circuit_open")' in merge
    assert '(extra or {}).get("captcha_circuit_open")' in merge
    assert 'merged["captcha_circuit_open"] = True' in merge
    assert 'getattr(self, "_recall_retry_local_v1125", None)' in merge
    assert ".stop_after_failure = True" in merge
    # captcha 熔断只终止迅雷关键词扩大，不能伪造媒体已覆盖；后续 Magnet/ED2K 仍可正常回退。
    assert 'merged["handled"] = True' not in merge
    assert 'merged["success"] = True' not in merge


def test_recall_loop_observes_sticky_circuit_after_merge_before_widening_keyword():
    dispatch = _method(recall_text, "_dispatch_xunlei_flash", "_dispatch_viewing_external_v1113")
    lower_call = dispatch.index("super()._dispatch_xunlei_flash(subscribe)")
    merge = dispatch.index("_merge_xunlei_rounds_v1125", lower_call)
    stop = dispatch.index('getattr(local, "stop_after_failure", False)', merge)
    widen = dispatch.index("local.start_index = next_index", stop)
    assert lower_call < merge < stop < widen


def test_runtimefix_circuit_reset_cannot_escape_one_top_level_recall_round():
    runtime_fix = (PLUGIN / "runtime_fix_v1113.py").read_text(encoding="utf-8")
    lower_dispatch = _method(runtime_fix, "_dispatch_xunlei_flash", "_notify_cloud_completed_v1113")
    assert "self._xunlei_captcha_circuit_open_v1113 = False" in lower_dispatch
    # 这个历史每次下层调用重置仍保留，但上层 reliability merge 会把返回事实提升到整个 recall round。
    merge = _method(reliability_text, "_merge_xunlei_rounds_v1125", "_dispatch_viewing_external_v1113")
    assert 'captcha_open = bool((base or {}).get("captcha_circuit_open")) or bool(' in merge
    assert "stop_after_failure = True" in merge


def test_external_governance_blocks_recall_guard_before_any_wide_gying_request():
    guard = _method(reliability_text, "_dispatch_viewing_external_v1113", "_xunlei_compute_triple_cid")
    assert 'not bool(getattr(self, "_provider_auto_search", True))' in guard
    assert 'not bool(getattr(self, "_external_auto_dispatch", True))' in guard
    assert 'mode == "channel_event"' in guard
    assert 'getattr(self, "_external_round_ok_v1114", None)' in guard
    assert 'not bool(round_ok(subscribe))' in guard
    assert '"cooldown": True' in guard
    # 只有全部治理条件允许后才进入 RecallGuard 的实际扩词逻辑。
    super_pos = guard.index("super()._dispatch_viewing_external_v1113(subscribe)")
    channel_pos = guard.index('mode == "channel_event"')
    cooldown_pos = guard.index("not bool(round_ok(subscribe))")
    assert channel_pos < super_pos
    assert cooldown_pos < super_pos


def test_channel_event_cannot_use_stale_search_bundle_to_reenter_gying():
    guard = _method(reliability_text, "_dispatch_viewing_external_v1113", "_xunlei_compute_triple_cid")
    channel = guard.split('if mode == "channel_event":', 1)[1].split("round_ok =", 1)[0]
    assert '"channel_only": True' in channel
    assert "禁止主动 GYING" in channel
    assert "super()._dispatch_viewing_external_v1113" not in channel
