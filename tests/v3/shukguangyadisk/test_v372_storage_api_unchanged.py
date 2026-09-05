from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LOSS = (ROOT / "plugins.v3/shukguangyadisk/organizer_loss_guard_v349.py").read_text(encoding="utf-8")
EMPTY = (ROOT / "plugins.v3/shukguangyadisk/organizer_empty_folder_guard_v3410.py").read_text(encoding="utf-8")


def test_v372_helper_migration_does_not_touch_guangya_write_api():
    for source in (LOSS, EMPTY):
        assert "move_item(" not in source
        assert "copy_item(" not in source
        assert "delete_file(" not in source
