from __future__ import annotations

import json
from pathlib import Path

VERSION = "3.7.0"
OLD_VERSION = "3.6.21"
HISTORY = (
    "整理核心第一阶段收口：新增唯一 organizer_policy 文件处置表，识别失败且源仍存在的媒体原地保留，"
    "不移动、不删除、不改名、不进入 retry；源明确消失只退休本地状态，不再制造 completed 历史。"
    "MoviePilot Preview 已确定最终目标时，目标存在且源/目标精确字节大小一致才允许删除重复源，删除前"
    "再次复核大小与 fileId；大小不同统一通过 MoviePilot TransferRename 生成版本N并二次 Preview 确认，"
    "大小未知或目标事实不可读一律保持原位。该规则覆盖单文件与 Season 批次每个成员，duplicate_targets "
    "不再绕过已有目标策略。自动整理本地历史从 1000 条收敛为近期 120 条，状态页仅展示最近 20 条；"
    "新增 ORGANIZER_RULES.md 冻结规则，后续不再新增 v3.x 行为补丁模块，逐步迁移旧兼容层到统一五层核心。"
)

ROOT = Path("plugins.v3/shukguangyadisk")

# __init__.py
path = ROOT / "__init__.py"
text = path.read_text(encoding="utf-8")
needle = f'plugin_version = "{OLD_VERSION}"'
assert needle in text, "plugin_version base changed"
path.write_text(text.replace(needle, f'plugin_version = "{VERSION}"', 1), encoding="utf-8")

# plugin.json
path = ROOT / "plugin.json"
data = json.loads(path.read_text(encoding="utf-8"))
assert data.get("version") == OLD_VERSION, data.get("version")
data["version"] = VERSION
old_history = dict(data.get("history") or {})
data["history"] = {f"v{VERSION}": HISTORY, **old_history}
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# package.v3.json: only modify ShukGuangYaDisk textual object so other plugins keep exact main content.
path = Path("package.v3.json")
package_text = path.read_text(encoding="utf-8")
package_before = json.loads(package_text)
assert package_before["GuangYaTransferAssistant"]["version"] == "1.12.14"
marker = '"ShukGuangYaDisk": {'
marker_pos = package_text.index(marker)
brace_start = package_text.index("{", marker_pos)


def matching_brace(text: str, start: int) -> int:
    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return idx
    raise AssertionError("unterminated ShukGuangYaDisk object")


brace_end = matching_brace(package_text, brace_start)
section = package_text[marker_pos:brace_end + 1]
version_needle = f'"version": "{OLD_VERSION}"'
assert version_needle in section, "package Shuk version base changed"
section = section.replace(version_needle, f'"version": "{VERSION}"', 1)
history_needle = '"history": {\n'
assert history_needle in section
history_line = f'      "v{VERSION}": {json.dumps(HISTORY, ensure_ascii=False)},\n'
section = section.replace(history_needle, history_needle + history_line, 1)
package_text = package_text[:marker_pos] + section + package_text[brace_end + 1:]
path.write_text(package_text, encoding="utf-8")
package_after = json.loads(package_text)
for key, value in package_before.items():
    if key == "ShukGuangYaDisk":
        continue
    assert package_after[key] == value, f"unrelated package entry changed: {key}"
assert package_after["ShukGuangYaDisk"]["version"] == VERSION
assert package_after["GuangYaTransferAssistant"]["version"] == "1.12.14"

# Federation cache-buster.
path = ROOT / "dist/assets/remoteEntry.js"
text = path.read_text(encoding="utf-8")
needle = f"__federation_expose_AssistantPage-v352.js?v={OLD_VERSION}"
assert needle in text, "remoteEntry version base changed"
path.write_text(text.replace(needle, f"__federation_expose_AssistantPage-v352.js?v={VERSION}", 1), encoding="utf-8")

# Status distinguishes current organizer policy from legacy hardening layer versions.
path = ROOT / "organizer_execution_v360.py"
text = path.read_text(encoding="utf-8")
needle = '            "organizer_engine": "v3.6.0",\n'
assert needle in text, "status insertion point changed"
replacement = needle + f'            "organizer_policy_version": "v{VERSION}",\n'
path.write_text(text.replace(needle, replacement, 1), encoding="utf-8")

# Replace misleading old startup banner with one current policy banner.
path = ROOT / "organizer_conflict_resolution_v353.py"
text = path.read_text(encoding="utf-8")
old = '    logger.info("【光鸭云盘助手】【v3.5.3】电影重复目标与剧集局部冲突消歧已启用")\n'
new = (
    '    logger.info(\n'
    '        "【光鸭云盘助手】【整理策略 v3.7.0】统一文件处置已启用："\n'
    '        "未识别原地保留；同大小精准去重；不同大小多版本；未知事实安全阻断"\n'
    '    )\n'
)
assert old in text, "legacy startup banner changed"
path.write_text(text.replace(old, new, 1), encoding="utf-8")
