from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
RECOVERY = PLUGIN / "auto_recovery_v11224.py"
FAST = PLUGIN / "fast_recall_v1126.py"
LEGACY = PLUGIN / "legacy.py"

recovery_text = RECOVERY.read_text(encoding="utf-8")
fast_text = FAST.read_text(encoding="utf-8")
legacy_text = LEGACY.read_text(encoding="utf-8")


def test_v11224_files_parse_and_recovery_is_wired_into_final_mro_chain():
    ast.parse(recovery_text, filename=str(RECOVERY))
    ast.parse(fast_text, filename=str(FAST))
    assert "from .auto_recovery_v11224 import GuangYaAutoRecoveryV11224Mixin" in fast_text
    class_head = fast_text.split("class GuangYaFastRecallV1126Mixin(", 1)[1].split("):", 1)[0]
    assert class_head.index("GuangYaChannelTitleRenameV11226Mixin") < class_head.index("GuangYaAutoRecoveryV11224Mixin") < class_head.index("GuangYaMediaMatchV11219Mixin")


def test_v11224_growing_channel_share_is_rechecked_but_file_level_dedup_remains_authoritative():
    method = recovery_text.split("    def _entry_processed(", 1)[1].split(
        "    # ------------------------------------------------------------------\n    # handled", 1
    )[0]
    assert "_recovery_uncovered_v11224" in method
    assert '"synced", "no_new_episode", "transferred", "legacy_synced", "processed"' in method
    assert "_processed_recheck_minutes_v11224" in method
    assert "return False" in method
    # Legacy still performs actual file/inventory/media-fact dedup after a message is reopened.
    assert "_plan_incremental_files" in legacy_text
    assert "_semantic_fact_exists" in legacy_text
    assert "_remember_assets" in legacy_text


def test_v11224_handled_is_not_allowed_to_hide_a_real_gap():
    method = recovery_text.split("    def _try_transfer_subscription_inner(", 1)[1].split(
        "    # ------------------------------------------------------------------\n    # 非更新日", 1
    )[0]
    assert "gap = self._recovery_uncovered_v11224(subscribe)" in method
    assert "前序返回 handled=True 但真实缺口仍存在" in method
    assert "self._dispatch_viewing_external_v1113(subscribe)" in method
    assert 'result["handled"] = False' in method
    assert 'mode == "channel_event"' in method


def test_v11224_movie_gap_ignores_new_retry_and_unconfirmed_completed_sources():
    gap = recovery_text.split("    def _recovery_uncovered_v11224(", 1)[1].split(
        "    # ------------------------------------------------------------------\n    # 频道增长分享", 1
    )[0]
    assert "_movie_transfer_confirmed" in gap
    assert 'state in {"dispatching", "submitted", "queued", "waiting"}' in gap
    assert '"new"' not in gap
    assert '"retry"' not in gap
    assert '"completed"' not in gap


def test_v11224_off_day_recovery_is_hourly_and_does_not_expand_all_future_missing():
    method = recovery_text.split("    def _smart_pull_due_ids_v1125(", 1)[1].split(
        "    # ------------------------------------------------------------------\n    # 命名", 1
    )[0]
    assert "_off_day_recovery_minutes_v11224 = 60" in recovery_text
    assert 'row.get("off_day_missing")' in method
    assert 'row.get("unscheduled_missing")' in method
    assert "today + datetime.timedelta(days=1)" in method
    assert 'row.get("future_missing")' not in method


def _load_prefix_helpers():
    tree = ast.parse(recovery_text, filename=str(RECOVERY))
    wanted = {"_norm_name_v11224", "_safe_name_v11224", "_prefix_name_v11224"}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    module = ast.Module(body=nodes, type_ignores=[])
    namespace = {"Any": object, "re": re, "_FORBIDDEN_NAME_V11224": re.compile(r'[\\/:*?"<>|\x00-\x1f]+')}
    exec(compile(module, str(RECOVERY), "exec"), namespace)
    return namespace["_prefix_name_v11224"]


def test_v11224_recognition_folder_is_a_real_filename_prefix_and_not_appended_suffix():
    prefix = _load_prefix_helpers()
    assert prefix("Demo.S01E03.1080p.mkv", "Demo (2026)") == "Demo (2026) - Demo.S01E03.1080p.mkv"
    assert prefix("Demo (2026) - S01E03.mkv", "Demo (2026)") == "Demo (2026) - S01E03.mkv"
    assert prefix("E03.mkv", "Demo/Bad:Name (2026)").startswith("Demo Bad Name (2026) - ")


def test_v11224_naming_covers_xunlei_cloudadd_and_post_verified_share_restore():
    assert "def _rapid_transfer_xunlei_file" in recovery_text
    assert "def _resolve_offline_source" in recovery_text
    restore = recovery_text.split("    def _restore_items(", 1)[1]
    assert "super()._restore_items" in restore
    assert "completed_items" in restore
    assert "_rename_restored_media_v11224" in restore
    rename = recovery_text.split("    def _rename_restored_media_v11224(", 1)[1].split(
        "    def _restore_items(", 1
    )[0]
    assert "api.get_item" in rename
    assert "client.rename" in rename
    assert "_is_video(path) or _is_subtitle(path)" in rename
