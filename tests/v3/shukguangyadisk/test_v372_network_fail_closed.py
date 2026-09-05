from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GUARD = (ROOT / "plugins.v3/shukguangyadisk/organizer_empty_folder_guard_v3410.py").read_text(encoding="utf-8")
CONFLICT = (ROOT / "plugins.v3/shukguangyadisk/organizer_conflict_resolution_v353.py").read_text(encoding="utf-8")


def test_v372_network_source_check_never_becomes_empty_success():
    assert 'return "network"' in GUARD
    assert 'if live_state == "network":' in CONFLICT
    assert "return False, live_detail" in CONFLICT
