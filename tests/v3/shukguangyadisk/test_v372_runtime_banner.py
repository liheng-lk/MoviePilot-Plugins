from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXEC = (ROOT / "plugins.v3/shukguangyadisk/organizer_execution_v360.py").read_text(encoding="utf-8")


def test_v372_runtime_banner_reports_explicit_folder_terminal_core():
    assert "【整理核心 v3.7.2】" in EXEC
    assert "folder 终态核对不再使用运行时 monkey patch" in EXEC
