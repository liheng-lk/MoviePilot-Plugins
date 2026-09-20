from __future__ import annotations

import json
from pathlib import Path

from source_helper import single_init_plugin_path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = single_init_plugin_path(ROOT / "plugins.v3" / "shukguangyadisk")
CONFLICT = (PLUGIN / "organizer_conflict_resolution_v353.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")


def test_v3919_transfer_rename_normalizes_all_same_episode_ranges():
    for token in (
        "_normalize_same_episode_range_name(render_str)",
        'data.source = "光鸭云盘助手-v3.9.19"',
        "模板命名修正",
        "TransferRename 收口",
    ):
        assert token in CONFLICT, token


def test_v3919_examples_are_same_episode_ranges():
    samples = [
        "予你远方 - S01E12-E12 - 三个人的局 - WEB-DL 2160p - H265.mkv",
        "航海王 - S16E688-E688 - 命悬一线 - SDR 1080p - H264.mkv",
        "遮天 - S01E181-E181 - WEB-DL 2160p - H265.mkv",
    ]
    assert all("-E" in value for value in samples)
    assert "_apply_version_to_render(updated" in CONFLICT


def test_v3919_versions_are_synchronized():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["ShukGuangYaDisk"]
    plugin = json.loads((ROOT / "plugins.v3/shukguangyadisk/plugin.json").read_text(encoding="utf-8"))
    remote = (ROOT / "plugins.v3/shukguangyadisk/dist/assets/remoteEntry.js").read_text(encoding="utf-8")
    current = package["version"]
    assert plugin["version"] == current
    assert f'plugin_version = "{current}"' in ENTRY
    assert f"v={current}" in remote
    assert "v3.9.19" in package["history"]
    assert "v3.9.19" in plugin["history"]
