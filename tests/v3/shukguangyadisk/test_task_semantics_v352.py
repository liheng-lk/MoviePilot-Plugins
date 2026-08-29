from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
PATCH = (PLUGIN / "organizer_task_semantics_v352.py").read_text(encoding="utf-8")
FILTER = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")


def test_confirmed_movie_never_runs_episode_template_recommenders():
    assert "MoviePilot 已确认电影，跳过电视剧集数模板推荐" in PATCH
    assert "confirmed_movie_skip_episode_recommend" in PATCH
    assert "_loss_guard._moviepilot_episode_format = moviepilot_episode_format" in PATCH
    assert "_episode_adapter._mp_member_recommend = member_recommend" in PATCH
    assert "if _is_confirmed_movie(path):" in PATCH


def test_sidecars_are_not_independent_task_members():
    assert 'kwargs["files"] = primary' in PATCH
    assert "_primary_media_files(files)" in PATCH
    assert "字幕/音频不再单独计入整理任务" in PATCH
    assert "TransferComplete/TransferFailed" in PATCH


def test_old_sidecar_retry_state_is_pruned_without_touching_video_state():
    assert 'for bucket in ("stabilizing", "inflight", "retry", "blocked")' in PATCH
    assert "if _is_video_path(path):" in PATCH
    assert "mapping.pop(path, None)" in PATCH
    assert "sidecar_state_pruned_total" in PATCH
    assert "_prune_sidecar_transient_state(self)" in PATCH


def test_task_semantics_is_installed_after_sticky_and_graceful_stop():
    assert "from .organizer_task_semantics_v352 import install_task_semantics_v352" in FILTER
    assert "install_task_semantics_v352()" in FILTER
    assert FILTER.index("install_tv_sticky_graceful_stop_v352()") < FILTER.index("install_task_semantics_v352()")
