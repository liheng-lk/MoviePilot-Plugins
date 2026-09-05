from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
BRIDGE = (PLUGIN / "movie_bilingual_identity_v11216.py").read_text(encoding="utf-8")
XUNLEI = (PLUGIN / "xunlei_flash_v193.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")


def test_bilingual_bridge_is_syntax_valid_and_only_wraps_xunlei_identity_gate():
    ast.parse(BRIDGE)
    assert "def _xunlei_json_identity_matches_v1123" in BRIDGE
    assert "实际资源顶层标题与订阅不一致" in BRIDGE
    assert "def _provider_candidate_matches" not in BRIDGE
    assert "def _planner_file_selection" not in BRIDGE
    assert "def _xunlei_import_json_batch_v1123" not in BRIDGE


def test_bridge_does_not_introduce_fuzzy_or_cross_source_download_logic():
    lowered = BRIDGE.lower()
    for forbidden in (
        "levenshtein", "sequenceMatcher".lower(), "fuzzywuzzy", "pinyin", "downloadchain",
        "cloudcollection/v1/create_task", "userres", "magnet:?", "ed2k://",
    ):
        assert forbidden not in lowered


def test_existing_source_priority_and_short_circuit_remain_unchanged():
    method = XUNLEI.split("    def _try_transfer_subscription_inner(", 1)[1].split(
        "    def api_xunlei_flash_test", 1
    )[0]
    assert "flash = self._dispatch_xunlei_flash(subscribe)" in method
    assert 'if flash.get("handled"):' in method
    assert "super()._try_transfer_subscription_inner" in method
    assert "观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K" in ENTRY
