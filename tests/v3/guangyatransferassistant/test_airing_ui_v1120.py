from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
UI = (PLUGIN / "airing_ui_v1120.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")


def test_airing_ui_parses_and_is_below_receipt_without_stealing_scheduler_authority():
    ast.parse(UI)
    assert "from .airing_ui_v1120 import GuangYaAiringUiV1120Mixin" in ENTRY
    head = ENTRY.split("class GuangYaTransferAssistant(", 1)[1].split("):", 1)[0]
    mixins = [line.strip().rstrip(",") for line in head.splitlines() if line.strip()]
    assert mixins[:7] == [
        "GuangYaAiringWeeklyV1121Mixin",
        "GuangYaAiringSchedulerV1120Mixin",
        "GuangYaMediaIdentityGuardV1111Mixin",
        "GuangYaReleaseV1110Mixin",
        "GuangYaEpisodeFenceFinalV1124Mixin",
        "GuangYaReceiptCompletionV1124Mixin",
        "GuangYaAiringUiV1120Mixin",
    ]


def test_airing_ui_exposes_estimated_hour_and_early_window():
    assert '"calendar_default_hour"' in UI
    assert '"calendar_early_hours"' in UI
    assert "日期默认更新时间（本地小时）" in UI
    assert "提前检查窗口（小时）" in UI
    assert "默认 20:00" in UI
    assert "默认提前 12 小时" in UI
    assert 'defaults.setdefault("calendar_default_hour", 20)' in UI
    assert 'defaults.setdefault("calendar_early_hours", 12)' in UI


def test_airing_ui_merges_new_fields_after_legacy_full_config_save():
    method = UI[UI.index("def _save_config"):]
    assert "super()._save_config()" in method
    assert "config = self.get_config() or {}" in method
    assert "config.update({" in method
    assert '"calendar_default_hour"' in method
    assert '"calendar_early_hours"' in method
    assert "self.update_config(config)" in method