from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
PATCH = (PLUGIN / "organizer_conflict_resolution_v353.py").read_text(encoding="utf-8")
FILTER = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")
RUNTIME = (PLUGIN / "organizer_runtime.py").read_text(encoding="utf-8")


def test_movie_duplicates_wait_for_real_moviepilot_history_before_delete():
    assert "同目标同大小视为重复副本" in PATCH
    assert "history_id" in PATCH
    assert "api.delete(current)" in PATCH
    record_tail = PATCH[PATCH.index("def record(self: Any, event: Any, success: bool)") :]
    assert "if not success or not history_id:" in record_tail
    assert "target=_delete_duplicate_worker" in record_tail
    assert record_tail.index("if not success or not history_id:") < record_tail.index("target=_delete_duplicate_worker")
    assert "duplicate_deleted_after_keeper" in PATCH


def test_different_size_collisions_use_moviepilot_transfer_rename_versions():
    assert "TransferRename" in PATCH
    assert "版本{int(version)}" in PATCH
    assert "_single_preview_target" in PATCH
    assert "版本化目标已存在，拒绝覆盖" in PATCH
    assert 'data.updated = True' in PATCH
    assert 'data.updated_str = updated' in PATCH
    assert "organizer_transfer_rename" in RUNTIME
    assert 'getattr(ChainEventType, "TransferRename", None)' in RUNTIME


def test_tv_different_episode_collision_is_local_isolation_not_whole_season_block():
    assert "_episode_identity" in PATCH
    assert "不同/未知剧集身份被 MoviePilot 规划到同一目标，仅隔离本冲突组" in PATCH
    assert "episode_end" in PATCH
    assert "当前 Season 其它安全集继续整理" in PATCH
    assert "episode_conflict_isolated" in PATCH
    assert "for source, member in sorted(members.items()" in PATCH


def test_tv_same_episode_can_dedupe_or_keep_multiple_versions():
    assert "_group_unique_representatives" in PATCH
    assert "同一冲突身份内按字节大小去重" in PATCH
    assert "len(representatives) > 1" in PATCH
    assert "versions[source] = number" in PATCH
    assert "重复副本待删除" in PATCH


def test_unknown_sizes_are_never_auto_deleted():
    assert "未知大小永远不自动删除" in PATCH
    assert "if size is None:" in PATCH
    assert "unique_unknown.append(source)" in PATCH


def test_conflict_resolver_is_final_scheduler_patch():
    assert "from .organizer_conflict_resolution_v353 import install_conflict_resolution_v353" in FILTER
    assert "install_conflict_resolution_v353()" in FILTER
    assert FILTER.index("install_task_semantics_v352()") < FILTER.index("install_conflict_resolution_v353()")


def test_no_custom_media_business_rules_are_introduced():
    forbidden = (
        "CategoryHelper",
        "get_tv_category",
        "get_movie_category",
        "TmdbChain(",
        "DoubanChain(",
    )
    for token in forbidden:
        assert token not in PATCH
