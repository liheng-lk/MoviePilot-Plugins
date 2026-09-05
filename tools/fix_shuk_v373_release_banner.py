from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXECUTION = ROOT / "plugins.v3" / "shukguangyadisk" / "organizer_execution_v360.py"
text = EXECUTION.read_text(encoding="utf-8")
old = "【光鸭云盘助手】【整理核心 v3.7.3】policy/Preview 执行链已显式接管："
new = "【光鸭云盘助手】【整理核心 v3.7.3】policy 执行链已显式接管："
if old not in text:
    raise RuntimeError("v3.7.3 staged banner anchor missing")
text = text.replace(old, new, 1)
EXECUTION.write_text(text, encoding="utf-8")
print("v3.7.3 organizer banner compatibility preserved")
