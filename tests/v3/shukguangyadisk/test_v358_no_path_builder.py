from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PATCH = (ROOT / "plugins.v3" / "shukguangyadisk" / "organizer_season_context_v358.py").read_text(encoding="utf-8")


def test_v358_never_builds_destination_path_itself():
    forbidden = ("DirectoryHelper", "get_rename_path", "target_directory", "rename_dict")
    for token in forbidden:
        assert token not in PATCH
