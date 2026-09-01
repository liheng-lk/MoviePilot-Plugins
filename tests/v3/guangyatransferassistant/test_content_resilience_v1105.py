from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
PATCH = (PLUGIN / "content_resilience_v1105.py").read_text(encoding="utf-8")


def test_v1105_layer_parses_and_is_outer_runtime_guard():
    ast.parse(PATCH)
    ast.parse(ENTRY)
    start = ENTRY.index("class GuangYaTransferAssistant")
    assert "from .content_resilience_v1105 import GuangYaContentResilienceV1105Mixin" in ENTRY
    assert ENTRY.index("GuangYaContentResilienceV1105Mixin,", start) < ENTRY.index("GuangYaGyingObservabilityV1104Mixin,", start)
    assert 'plugin_version = "1.10.6"' in ENTRY
    assert 'build_id = "20260902-r17"' in ENTRY


def test_share_episode_floor_is_raised_before_legacy_range_filter():
    method = PATCH.split("    def _plan_incremental_files(", 1)[1].split("    def _entry_processed", 1)[0]
    assert method.index("_sync_share_episode_floor_v1105") < method.index("super()._plan_incremental_files")
    sync = PATCH.split("    def _sync_share_episode_floor_v1105", 1)[1].split("    def _plan_incremental_files", 1)[0]
    assert "floor <= current_total" in sync
    assert 'SubscribeOper().update(sid, {"total_episode": floor, "lack_episode": lack})' in sync
    assert "【分享追更】" in sync
    assert "_episode_numbers(path)" in sync


def test_intro_outro_are_auxiliary_not_unparsed_episode_blockers():
    for token in ("片头", "片尾", "opening", "ending", "op\\d*", "ed\\d*", "trailer", "sample"):
        assert token in PATCH
    method = PATCH.split("    def _plan_incremental_files(", 1)[1].split("    def _entry_processed", 1)[0]
    assert "is_auxiliary_media_v1105(path)" in method
    assert 'stats["ignored_auxiliary"]' in method
    assert "已忽略 %s 个非正片辅助视频" in method


def test_processed_entry_is_bound_to_target_total_and_old_records_reopen_once():
    processed = PATCH.split("    def _entry_processed(", 1)[1].split("    def _mark_entry_processed", 1)[0]
    assert "_subscription_missing_episodes" in processed
    assert "stored_total <= 0" in processed
    assert "return False" in processed
    assert "return current_total <= stored_total" in processed
    mark = PATCH.split("    def _mark_entry_processed(", 1)[1].split("\n\n\n__all__", 1)[0]
    assert 'raw["target_total"]' in mark
    assert 'raw["target_start"]' in mark
    assert 'raw["target_missing"]' in mark


def test_v1105_does_not_touch_other_acquisition_or_download_paths():
    lowered = PATCH.lower()
    for forbidden in (
        "downloadchain(",
        "from app.chain.download",
        "flash_upload",
        "cloudcollection/v1/create_task",
        "_search_viewing",
        "_search_api_provider",
        "qbittorrent",
        "transmission",
        "aria2",
    ):
        assert forbidden not in lowered
