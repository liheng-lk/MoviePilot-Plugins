from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EMPTY = (ROOT / "plugins.v3/shukguangyadisk/organizer_empty_folder_guard_v3410.py").read_text(encoding="utf-8")


def test_v372_empty_guard_exports_source_fact_helpers_only():
    for token in ("_clear_stale_transient_state", "_live_primary_media_state", "_runtime_media_exts"):
        assert token in EMPTY
    assert "install_empty_folder_guard_v3410" not in EMPTY
