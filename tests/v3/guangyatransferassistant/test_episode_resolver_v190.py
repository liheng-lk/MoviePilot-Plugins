from __future__ import annotations

import runpy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RESOLVER = ROOT / "plugins.v3" / "guangyatransferassistant" / "episode_resolver_v190.py"
NS = runpy.run_path(str(RESOLVER))
resolve_episode = NS["resolve_episode"]
reliable_episode_set = NS["reliable_episode_set"]


def test_explicit_episode_forms_are_high_confidence():
    cases = {
        "Show.S01E05.mkv": (1, [5]),
        "Show.S01.EP.06.mkv": (1, [6]),
        "Show.1x07.mkv": (1, [7]),
        "Show.E08-E10.mkv": (None, [8, 9, 10]),
        "Show.S01E11E12.mkv": (1, [11, 12]),
        "某剧 第13-15集.mp4": (None, [13, 14, 15]),
        "动画 第16话.mkv": (None, [16]),
        "Show.Episode.17.mkv": (None, [17]),
    }
    for path, (season, episodes) in cases.items():
        result = resolve_episode(path)
        assert result["season"] == season, (path, result)
        assert result["episodes"] == episodes, (path, result)
        assert result["confidence"] == 1.0
        assert reliable_episode_set(result) == set(episodes)


def test_specials_are_season_zero():
    for path, episode in (("Show.SP01.mkv", 1), ("Show.OVA02.mkv", 2), ("番外03.mp4", 3)):
        result = resolve_episode(path)
        assert result["season"] == 0
        assert result["episodes"] == [episode]
        assert reliable_episode_set(result) == {episode}


def test_bare_numeric_files_need_context_but_can_use_season_or_package_sequence():
    weak = resolve_episode("05.mkv")
    assert weak["episodes"] == [5]
    assert weak["confidence"] < 0.90
    assert reliable_episode_set(weak) == set()

    season_context = resolve_episode("05.mkv", season_hint=1)
    assert season_context["season"] == 1
    assert reliable_episode_set(season_context) == {5}

    package = ["01.mkv", "02.mkv", "03.mkv", "04.mkv", "05.mkv"]
    sequence = resolve_episode("04.mkv", package_paths=package)
    assert sequence["confidence"] >= 0.90
    assert reliable_episode_set(sequence) == {4}


def test_release_style_number_before_quality_is_supported_without_grabbing_quality_number():
    result = resolve_episode("Show.Name.05.2160p.WEB-DL.mkv", season_hint=1)
    selected = reliable_episode_set(result)
    assert selected == {5}
    assert result["confidence"] >= 0.90
    assert 2160 not in selected

    result = resolve_episode("Show.Name.06.WEB-DL.H265.10bit.mkv", season_hint=1)
    selected = reliable_episode_set(result)
    assert selected == {6}
    assert result["confidence"] >= 0.90
    assert 265 not in selected


def test_episode_hint_can_confirm_a_weak_name():
    result = resolve_episode("[05].mkv", season_hint=1, episode_hint="更新至第5集")
    assert result["confidence"] >= 0.96
    assert reliable_episode_set(result) == {5}


def test_long_anime_absolute_episode_is_not_misread_as_season_number():
    result = resolve_episode("[ANi] One Piece - 1134 [1080P].mkv", episode_hint="第1134话")
    assert result["absolute_episode"] == 1134
    assert reliable_episode_set(result) == {1134}


def test_noise_numbers_and_unknown_letters_are_never_auto_selected():
    for path in (
        "Show.2026.1080p.H265.10bit.mkv",
        "1080p.mkv",
        "H265.mkv",
        "2026.mkv",
        "A.mkv",
        "B.mkv",
        "C.mkv",
    ):
        result = resolve_episode(path, season_hint=1)
        assert reliable_episode_set(result) == set(), (path, result)


def test_unknown_abc_package_is_not_guessed_by_file_order():
    package = ["A.mkv", "B.mkv", "C.mkv"]
    for path in package:
        result = resolve_episode(path, package_paths=package, season_hint=1)
        assert result["episodes"] == []
        assert result["reason"] == "unparsed"
        assert reliable_episode_set(result) == set()
