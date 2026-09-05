from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXEC = (ROOT / "plugins.v3/shukguangyadisk/organizer_execution_v360.py").read_text(encoding="utf-8")


def test_v372_folder_success_still_defers_members_without_mp_terminal_event():
    assert "文件夹整理返回成功，但未收到该成员的 MoviePilot 单文件最终事件" in EXEC
    assert "_defer_unconfirmed_members(self, item, reason)" in EXEC
