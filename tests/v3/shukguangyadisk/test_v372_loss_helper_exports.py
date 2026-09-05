from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LOSS = (ROOT / "plugins.v3/shukguangyadisk/organizer_loss_guard_v349.py").read_text(encoding="utf-8")


def test_v372_loss_guard_exports_helpers_only():
    for token in ("_audit_preview", "_build_moviepilot_kwargs", "_defer_unconfirmed_members", "_preview_result"):
        assert token in LOSS
    assert "install_loss_guard_v349" not in LOSS
