from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
LOCAL = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
PACKAGE = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
FINAL = (PLUGIN / "dispatch_policy_final_v1125.py").read_text(encoding="utf-8")
XUNLEI = (PLUGIN / "xunlei_flash_v193.py").read_text(encoding="utf-8")


def test_v1125_release_metadata_is_single_truth():
    assert 'plugin_version = "1.12.7"' in ENTRY
    assert 'build_id = "20260905-r53"' in ENTRY
    assert LOCAL["version"] == "1.12.7"
    assert PACKAGE["version"] == "1.12.7"
    assert "v1.12.5" in PACKAGE["history"]


def test_v1125_release_has_no_active_preview_marker():
    for name in (
        "dispatch_policy_v1125.py",
        "dispatch_policy_final_v1125.py",
        "gying_recall_guard_v1125.py",
        "gying_hardening_v193.py",
        "gying_observability_v1104.py",
        "page_perf_v1123.py",
    ):
        text = (PLUGIN / name).read_text(encoding="utf-8")
        ast.parse(text, filename=name)
        assert "r51-preview" not in text
        assert "r50-preview" not in text


def test_v1125_hourly_full_chain_contract_is_published():
    assert "_hourly_due_cooldown_seconds_v1125 = 60 * 60" in FINAL
    assert 'mode == "airing_pull"' in FINAL
    assert '"origin": "airing_full_chain_v1125"' in FINAL
    assert "观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K" in FINAL
    assert "每小时 AiringDue" in PACKAGE["history"]["v1.12.5"]


def test_v1125_runtime_mro_keeps_final_dispatch_authority():
    start = ENTRY.index("class GuangYaTransferAssistant(")
    assert ENTRY.index("GuangYaDispatchPolicyFinalV1125Mixin,", start) < ENTRY.index(
        "GuangYaDispatchPolicyV1125Mixin,", start
    )


def test_v1125_normal_chain_still_uses_xunlei_then_fallback():
    method = XUNLEI.split("    def _try_transfer_subscription_inner(", 1)[1].split(
        "    def api_xunlei_flash_test(", 1
    )[0]
    assert "flash = self._dispatch_xunlei_flash(subscribe)" in method
    assert 'if flash.get("handled")' in method
    assert "super()._try_transfer_subscription_inner" in method
