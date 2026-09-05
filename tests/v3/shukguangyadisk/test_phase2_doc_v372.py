from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
DOC = (PLUGIN / "PHASE2_V372.md").read_text(encoding="utf-8")


def test_v372_architecture_record_matches_explicit_runtime_boundary():
    for token in (
        "install_loss_guard_v349()",
        "install_empty_folder_guard_v3410()",
        "Execution._fallback_terminal_state",
        "_defer_unconfirmed_members",
        "organizer_policy.py",
        "v3.6.20",
    ):
        assert token in DOC, token
