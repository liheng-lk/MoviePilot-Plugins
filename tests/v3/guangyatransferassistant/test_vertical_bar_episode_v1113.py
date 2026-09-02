from __future__ import annotations

import importlib.util
import runpy
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
COMPAT = PLUGIN / "episode_compat_v171.py"
RESOLVER = PLUGIN / "episode_resolver_v190.py"

spec = importlib.util.spec_from_file_location("guangya_episode_compat_vertical_bar", COMPAT)
compat = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(compat)

resolver_ns = runpy.run_path(str(RESOLVER))
resolve_episode = resolver_ns["resolve_episode"]
reliable_episode_set = resolver_ns["reliable_episode_set"]


def test_legacy_compat_accepts_common_vertical_bar_quality_separators():
    for path, expected in (
        ("01丨4K.mp4", 1),
        ("02｜2160p.mkv", 2),
        ("03|WEB-DL.mkv", 3),
    ):
        assert compat.extract_quality_suffix_episode(path) == expected

    for path in ("01丨04.mp4", "2160丨4K.mkv", "264丨4K.mp4"):
        assert compat.extract_quality_suffix_episode(path) is None


def test_installed_legacy_patch_recovers_real_world_vertical_bar_name():
    legacy = SimpleNamespace(_episode_numbers=lambda path: (None, []))
    compat.install_episode_filename_compat(legacy)
    assert legacy._episode_numbers("01丨4K.mp4") == (None, [1])


def test_resourceplanner_resolver_accepts_vertical_bar_names_with_season_context():
    package = [f"{index:02d}丨4K.mp4" for index in range(1, 12)]
    for episode in (1, 7, 11):
        result = resolve_episode(
            f"{episode:02d}丨4K.mp4",
            package_paths=package,
            season_hint=1,
        )
        assert result["reason"].startswith("quality-suffix")
        assert result["confidence"] >= 0.90
        assert reliable_episode_set(result) == {episode}


def test_vertical_bar_numeric_range_is_not_misread_as_quality_suffix():
    result = resolve_episode("07丨11.mp4", season_hint=1)
    assert reliable_episode_set(result) == set()
