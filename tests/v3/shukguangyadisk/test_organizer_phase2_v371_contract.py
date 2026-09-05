from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
CANDIDATE = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")
EXECUTION = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")
CONFLICT = (PLUGIN / "organizer_conflict_resolution_v353.py").read_text(encoding="utf-8")
PREVIEW = (PLUGIN / "organizer_preview_partial_v355.py").read_text(encoding="utf-8")
WAKE = (PLUGIN / "organizer_preview_retry_wakeup_v356.py").read_text(encoding="utf-8")
SCOPE = (PLUGIN / "organizer_terminal_event_scope_v3620.py").read_text(encoding="utf-8")
PENDING = (PLUGIN / "organizer_pending_revisit_v361.py").read_text(encoding="utf-8")
RULES = (PLUGIN / "ORGANIZER_RULES.md").read_text(encoding="utf-8")


def test_phase2_removes_three_runtime_behavior_installers():
    for token in (
        "install_conflict_resolution_v353",
        "install_preview_partial_v355",
        "install_preview_retry_wakeup_v356",
    ):
        assert token not in CANDIDATE
    assert "GuangYaQueueRecoveryMixin._execute_isolated_transfer = execute" not in CONFLICT
    assert "GuangYaQueueRecoveryMixin._execute_isolated_transfer = execute" not in PREVIEW
    assert "GuangYaFolderStreamMixin.run_organize_monitor_scan = run_scan" not in WAKE


def test_execution_core_explicitly_owns_policy_preview_and_events():
    for token in (
        "_execute_conflict_aware(self, item)",
        "rescue_partial_preview_if_needed(self, item, result)",
        "apply_version_rename_event(self, event)",
        "handle_duplicate_terminal_event(self, event, success)",
        "_wake_legacy_preview_retries(self)",
        '"organizer_policy_version": "v3.7.1"',
    ):
        assert token in EXECUTION, token


def test_phase2_helpers_do_not_import_runtime_classes_to_patch():
    for source in (CONFLICT, PREVIEW, WAKE):
        assert "._execute_isolated_transfer =" not in source
        assert ".run_organize_monitor_scan =" not in source
    assert "不得再修改" in RULES


def test_terminal_scope_stays_outside_execution_duplicate_cleanup():
    # Final MRO starts with PendingRevisit before Execution. v3.6.20 wraps Pending's terminal
    # method, so other-storage events return before Execution can consume duplicate waiters.
    plugin_init = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
    pending_pos = plugin_init.index("GuangYaOrganizerPendingRevisitV361Mixin,")
    execution_pos = plugin_init.index("GuangYaOrganizerExecutionV360Mixin,")
    assert pending_pos < execution_pos
    assert "GuangYaOrganizerPendingRevisitV361Mixin._record_terminal_transfer = scoped_pending_record" in SCOPE
    assert "if not terminal_event_owned_v3620(self, event):" in SCOPE
    assert "super()._record_terminal_transfer(event, success)" in PENDING
    execution_record = EXECUTION[EXECUTION.index("def _record_terminal_transfer"):EXECUTION.index("def _fallback_terminal_state")]
    assert "super()._record_terminal_transfer(event, success)" in execution_record
    assert "handle_duplicate_terminal_event(self, event, success)" in execution_record
