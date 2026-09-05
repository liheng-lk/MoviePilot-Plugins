from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
CANDIDATE = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")
EXECUTION = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")
LOSS = (PLUGIN / "organizer_loss_guard_v349.py").read_text(encoding="utf-8")
EMPTY = (PLUGIN / "organizer_empty_folder_guard_v3410.py").read_text(encoding="utf-8")


def test_v372_removes_loss_and_empty_runtime_installers():
    for token in ("install_loss_guard_v349", "install_empty_folder_guard_v3410"):
        assert token not in CANDIDATE
        assert token not in LOSS
        assert token not in EMPTY
    assert "GuangYaQueueRecoveryMixin._execute_isolated_transfer" not in LOSS
    assert "GuangYaQueueRecoveryMixin._fallback_terminal_state" not in LOSS
    assert "GuangYaQueueRecoveryMixin._execute_isolated_transfer" not in EMPTY
    assert "GuangYaQueueRecoveryMixin._fallback_terminal_state" not in EMPTY


def test_v372_execution_owns_folder_terminal_reconciliation():
    for token in (
        "_defer_unconfirmed_members(self, item, reason)",
        "_guangya_empty_folder_skip_v3410",
        '"folder_partial" if deferred else "folder_completed"',
    ):
        assert token in EXECUTION, token
    match = __import__("re").search(r'"organizer_policy_version": "v(\d+)\.(\d+)\.(\d+)"', EXECUTION)
    assert match and tuple(map(int, match.groups())) >= (3, 7, 2)


def test_v372_keeps_helpers_not_second_policy():
    assert "def _audit_preview" in LOSS
    assert "def _build_moviepilot_kwargs" in LOSS
    assert "def _defer_unconfirmed_members" in LOSS
    assert "def _live_primary_media_state" in EMPTY
    assert "def _clear_stale_transient_state" in EMPTY
    for source in (LOSS, EMPTY):
        assert "FileDisposition" not in source
        assert "organizer_policy" not in source
