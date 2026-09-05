from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"


def test_v372_loss_and_empty_helpers_do_not_define_file_disposition():
    for name in ("organizer_loss_guard_v349.py", "organizer_empty_folder_guard_v3410.py"):
        text = (PLUGIN / name).read_text(encoding="utf-8")
        assert "class FileDisposition" not in text
        assert "def decide_existing_target" not in text
        assert "def decide_failed_execution" not in text
