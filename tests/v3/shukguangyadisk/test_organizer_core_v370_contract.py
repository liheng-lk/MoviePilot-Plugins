from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
POLICY = (PLUGIN / "organizer_policy.py").read_text(encoding="utf-8")
STATE = (PLUGIN / "organizer_state.py").read_text(encoding="utf-8")
EXEC = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")
HISTORY = (PLUGIN / "organizer_folder_history.py").read_text(encoding="utf-8")
CONFLICT = (PLUGIN / "organizer_conflict_resolution_v353.py").read_text(encoding="utf-8")
SOURCE = (PLUGIN / "organizer_source_terminal_v3618.py").read_text(encoding="utf-8")


def test_v370_has_one_canonical_file_disposition_table():
    for token in (
        'LEAVE_UNRECOGNIZED = "leave_unrecognized"',
        'DELETE_DUPLICATE = "delete_duplicate"',
        'ORGANIZE_VERSION = "organize_version"',
        'RETRY_TRANSIENT = "retry_transient"',
        'BLOCK_SAFETY = "block_safety"',
    ):
        assert token in POLICY


def test_unrecognized_present_source_is_parked_without_retry():
    assert "probe_source_presence_v3618" in EXEC
    assert "FileDisposition.LEAVE_UNRECOGNIZED" in EXEC
    assert "mark_non_actionable" in EXEC
    assert "不移动、不删除、不改名、不重试" in EXEC
    assert "def mark_non_actionable" in STATE


def test_source_presence_is_three_state_and_missing_retirement_stays_history_free():
    for token in ("SourcePresence.PRESENT", "SourcePresence.MISSING", "SourcePresence.UNKNOWN"):
        assert token in SOURCE
    assert "def retire_path" in STATE


def test_single_existing_target_uses_same_size_delete_different_size_version_policy():
    assert "def _handle_single_existing_target" in CONFLICT
    assert "FileDisposition.DELETE_DUPLICATE" in CONFLICT
    assert "【整理策略】【同大小去重】" in CONFLICT
    assert "FileDisposition.ORGANIZE_VERSION" in POLICY
    assert "【整理策略】【不同大小多版本】" in CONFLICT
    assert "plugin._state().retire_path(path=path)" in CONFLICT


def test_history_is_bounded_observability_not_second_database():
    assert "_monitor_history_limit = 120" in HISTORY
    assert "_folder_history_group_limit = 12" in HISTORY
    assert "_folder_history_detail_limit = 20" in HISTORY
    assert 'data["history"] = raw_history[-20:][::-1]' in HISTORY
    assert "_history_compacted_v370" in HISTORY


def test_rules_freeze_new_version_patch_proliferation():
    rules = (PLUGIN / "ORGANIZER_RULES.md").read_text(encoding="utf-8")
    assert "不得继续新增同类行为补丁" in rules
    assert "organizer_policy.py" in rules
