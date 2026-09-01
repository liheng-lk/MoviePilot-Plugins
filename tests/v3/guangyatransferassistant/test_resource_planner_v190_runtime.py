from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
PKG = "_guangya_v190_runtime_test"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_planner_module():
    package = types.ModuleType(PKG)
    package.__path__ = [str(PLUGIN)]
    sys.modules[PKG] = package
    _load_module(f"{PKG}.episode_resolver_v190", PLUGIN / "episode_resolver_v190.py")
    _load_module(f"{PKG}.source_types_v180", PLUGIN / "source_types_v180.py")

    legacy = types.ModuleType(f"{PKG}.legacy")
    video_exts = {".mkv", ".mp4", ".ts", ".m2ts", ".avi", ".mov", ".webm"}
    subtitle_exts = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".sup"}
    legacy._is_video = lambda name: Path(str(name).lower()).suffix in video_exts
    legacy._is_subtitle = lambda name: Path(str(name).lower()).suffix in subtitle_exts
    legacy._entry_match_reason = lambda entry, subscribe: (True, "test")
    sys.modules[f"{PKG}.legacy"] = legacy
    return _load_module(f"{PKG}.resource_planner_v190", PLUGIN / "resource_planner_v190.py")


planner_module = _load_planner_module()


class _Base:
    _media_only = True

    def _is_movie_subscription(self, subscribe):
        return bool(getattr(subscribe, "movie", False))

    def _subscription_missing_episodes(self, subscribe):
        return list(getattr(subscribe, "missing", []))

    def _pending_reservations(self, subscribe):
        return {"episodes": set(getattr(subscribe, "reserved", [])), "paths": set(), "movie": False}


class _Planner(planner_module.GuangYaResourcePlannerMixin, _Base):
    pass


def _resolve_data(names):
    return {
        "btResInfo": {
            "fileName": "Demo",
            "subfiles": [
                {"fileIndex": index, "fileName": name, "fileSize": 1000 + index}
                for index, name in enumerate(names)
            ],
        }
    }


def test_only_missing_episode_indexes_and_matching_subtitles_are_selected():
    planner = _Planner()
    planner._episode_auto_confidence = 0.90
    subscribe = SimpleNamespace(season=1, missing=[2, 3], reserved=[], movie=False)
    source = {"target_episodes": [2, 3], "episode_hint": ""}
    data = _resolve_data([
        "Show.S01E01.mkv",
        "Show.S01E02.mkv",
        "Show.S01E03.mkv",
        "sample.mkv",
        "Show.S01E03.zh-CN.ass",
        "Show.S01E04.srt",
    ])
    result = planner._planner_file_selection(source, subscribe, data)
    assert result["ambiguous"] is False
    assert result["episodes"] == [2, 3]
    assert result["indexes"] == [1, 2, 4]
    assert 3 not in result["indexes"]  # sample.mkv must never hitchhike.
    assert 5 not in result["indexes"]  # E04 subtitle is unrelated.


def test_pending_direct_share_reservation_blocks_same_episode_from_magnet():
    planner = _Planner()
    planner._episode_auto_confidence = 0.90
    subscribe = SimpleNamespace(season=1, missing=[2, 3], reserved=[2], movie=False)
    source = {"target_episodes": [2, 3], "episode_hint": ""}
    result = planner._planner_file_selection(
        source,
        subscribe,
        _resolve_data(["Show.S01E02.mkv", "Show.S01E03.mkv"]),
    )
    assert result["episodes"] == [3]
    assert result["indexes"] == [1]


def test_numeric_package_can_be_split_by_sequence_context():
    planner = _Planner()
    planner._episode_auto_confidence = 0.90
    subscribe = SimpleNamespace(season=1, missing=[3], reserved=[], movie=False)
    source = {"target_episodes": [3], "episode_hint": ""}
    result = planner._planner_file_selection(
        source,
        subscribe,
        _resolve_data(["01.mkv", "02.mkv", "03.mkv", "04.mkv"]),
    )
    assert result["episodes"] == [3]
    assert result["indexes"] == [2]


def test_abc_files_are_ambiguous_and_never_selected_by_order():
    planner = _Planner()
    planner._episode_auto_confidence = 0.90
    subscribe = SimpleNamespace(season=1, missing=[2], reserved=[], movie=False)
    source = {"target_episodes": [2], "episode_hint": ""}
    result = planner._planner_file_selection(
        source,
        subscribe,
        _resolve_data(["A.mkv", "B.mkv", "C.mkv"]),
    )
    assert result["ambiguous"] is True
    assert result["indexes"] == []
    assert result["episodes"] == []


def test_single_unknown_video_is_allowed_only_when_post_explicitly_identifies_the_one_missing_episode():
    planner = _Planner()
    planner._episode_auto_confidence = 0.90
    subscribe = SimpleNamespace(season=1, missing=[5], reserved=[], movie=False)
    source = {"target_episodes": [5], "episode_hint": "第5集"}
    result = planner._planner_file_selection(source, subscribe, _resolve_data(["unknown.mkv"]))
    assert result["ambiguous"] is False
    assert result["episodes"] == [5]
    assert result["indexes"] == [0]


def test_multi_episode_file_is_selected_as_one_indivisible_file():
    planner = _Planner()
    planner._episode_auto_confidence = 0.90
    subscribe = SimpleNamespace(season=1, missing=[6], reserved=[], movie=False)
    source = {"target_episodes": [6], "episode_hint": ""}
    result = planner._planner_file_selection(
        source,
        subscribe,
        _resolve_data(["Show.S01E05E06.mkv"]),
    )
    assert result["episodes"] == [6]
    assert result["indexes"] == [0]


def test_weak_subtitle_can_follow_only_one_selected_video_in_same_folder():
    planner = _Planner()
    planner._episode_auto_confidence = 0.90
    subscribe = SimpleNamespace(season=1, missing=[5], reserved=[], movie=False)
    source = {"target_episodes": [5], "episode_hint": ""}
    result = planner._planner_file_selection(
        source,
        subscribe,
        _resolve_data(["E05/Show.S01E05.mkv", "E05/Chinese.ass", "E06/English.ass"]),
    )
    assert result["indexes"] == [0, 1]
