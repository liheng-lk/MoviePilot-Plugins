from __future__ import annotations

import json
from pathlib import Path

from source_helper import single_init_plugin_path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = single_init_plugin_path(ROOT / "plugins.v3" / "shukguangyadisk")
RENAME = (PLUGIN / "guangya_rename_integrity_v3414.py").read_text(encoding="utf-8")
MOVE = (PLUGIN / "guangya_move_confirmation_v360.py").read_text(encoding="utf-8")
TXN = (PLUGIN / "guangya_move_transaction_guard_v364.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")


def test_single_episode_same_range_is_normalized_at_all_storage_boundaries():
    for token in (
        "_SAME_EPISODE_RANGE_RE",
        "_normalize_same_episode_range_name",
        "S01E181-E181",
        "_normalize_same_episode_range_name(str(name or current_name).strip())",
        "new_name = _normalize_same_episode_range_name(new_name)",
    ):
        assert token in RENAME, token
    assert "_normalize_same_episode_range_name(raw_target_name)" in MOVE
    assert "单集重复区间已收口" in MOVE
    assert "_normalize_same_episode_range_name(str(new_name or source_name))" in TXN


def test_multi_episode_ranges_are_not_collapsed_by_pattern_contract():
    assert "(?P=ep)" in RENAME
    assert r"\s*-\s*E" in RENAME
    assert "S01E181-E182" not in RENAME


def test_v3916_release_versions_are_synchronized():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["ShukGuangYaDisk"]
    plugin = json.loads((ROOT / "plugins.v3/shukguangyadisk/plugin.json").read_text(encoding="utf-8"))
    remote = (ROOT / "plugins.v3/shukguangyadisk/dist/assets/remoteEntry.js").read_text(encoding="utf-8")
    assert package["version"] == "3.9.16"
    assert plugin["version"] == "3.9.16"
    assert 'plugin_version = "3.9.16"' in ENTRY
    assert "__federation_expose_AssistantPage-v352.js?v=3.9.16" in remote
