from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"


def test_v372_loss_empty_never_reintroduce_queue_recovery_monkey_patch():
    for name in ("organizer_loss_guard_v349.py", "organizer_empty_folder_guard_v3410.py"):
        text = (PLUGIN / name).read_text(encoding="utf-8")
        assert "GuangYaQueueRecoveryMixin" not in text
