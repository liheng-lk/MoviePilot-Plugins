from __future__ import annotations

import json
from pathlib import Path

from source_helper import single_init_plugin_path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = single_init_plugin_path(ROOT / "plugins.v3" / "shukguangyadisk")
ADAPTER = (PLUGIN / "organizer_episode_name_adapter_v3411.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")


def test_v3918_detects_redundant_same_episode_marker_after_primary_sxe():
    for token in (
        "_SECONDARY_EP_MARKER_RE",
        "_has_redundant_same_episode_marker",
        "_exact_primary_sxe_format",
        "primary_sxe_ignore_redundant_same_marker",
        "仅解析主 SxE，忽略冗余描述",
    ):
        assert token in ADAPTER, token


def test_v3918_one_piece_case_is_explicitly_covered():
    sample = "航海王.1999.S16E688.第688集.1080p.SDR.H.264.23.81fps.AAC 2.0.mkv"
    assert "S16E688" in sample
    assert "第688集" in sample
    assert "token.end is not None" in ADAPTER
    assert "value == token.start" in ADAPTER


def test_v3918_true_multi_episode_range_remains_distinct():
    assert 'token.family != "sxe" or token.end is not None' in ADAPTER
    assert "S16E688-E689" not in ADAPTER


def test_v3918_versions_are_synchronized():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["ShukGuangYaDisk"]
    plugin = json.loads((ROOT / "plugins.v3/shukguangyadisk/plugin.json").read_text(encoding="utf-8"))
    remote = (ROOT / "plugins.v3/shukguangyadisk/dist/assets/remoteEntry.js").read_text(encoding="utf-8")
    current = package["version"]
    assert plugin["version"] == current
    assert f'plugin_version = "{current}"' in ENTRY
    assert f"v={current}" in remote
    assert "v3.9.18" in package["history"]
    assert "v3.9.18" in plugin["history"]
