from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"


def test_v372_helper_modules_do_not_patch_runtime_classes():
    for name in ("organizer_loss_guard_v349.py", "organizer_empty_folder_guard_v3410.py"):
        text = (PLUGIN / name).read_text(encoding="utf-8")
        assert "._execute_isolated_transfer =" not in text
        assert "._fallback_terminal_state =" not in text
