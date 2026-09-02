from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
FINAL = PLUGIN / "xunlei_final_v1114.py"
UI = PLUGIN / "gying_ui_v1109.py"
TEXT = FINAL.read_text(encoding="utf-8")
UI_TEXT = UI.read_text(encoding="utf-8")


def test_final_xunlei_layer_parses_and_precedes_governance():
    ast.parse(TEXT, filename=str(FINAL))
    ast.parse(UI_TEXT, filename=str(UI))
    assert "class GuangYaXunleiFinalV1114Mixin(GuangYaGovernanceV1114Mixin):" in TEXT
    assert "from .xunlei_final_v1114 import GuangYaXunleiFinalV1114Mixin" in UI_TEXT
    assert "class GuangYaGyingUiV1109Mixin(GuangYaXunleiFinalV1114Mixin):" in UI_TEXT


def test_real_configured_captcha_device_pair_does_not_force_client_version():
    method = TEXT.split("    def _xunlei_headers(", 1)[1].split(
        "    def _provider_candidate_matches(", 1
    )[0]
    assert 'configured_token = str(getattr(self, "_xunlei_captcha_token"' in method
    assert 'configured_device = str(getattr(self, "_xunlei_device_id"' in method
    assert 'headers.pop("x-client-version", None)' in method


def test_captcha_circuit_skips_remaining_xunlei_candidates_before_share_api():
    matcher = TEXT.split("    def _provider_candidate_matches(", 1)[1].split(
        "    def _dispatch_xunlei_flash(", 1
    )[0]
    assert '_xunlei_batch_active_v1114' in matcher
    assert '_xunlei_captcha_circuit_open_v1113' in matcher
    assert "return False" in matcher
    dispatch = TEXT.split("    def _dispatch_xunlei_flash(", 1)[1].split("\n\n\n__all__", 1)[0]
    assert "self._xunlei_batch_active_v1114 = True" in dispatch
    assert "self._xunlei_batch_active_v1114 = False" in dispatch
    assert "本批剩余迅雷候选已直接跳过" in dispatch
