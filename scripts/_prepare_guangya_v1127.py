from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"

# ----------------------------------------------------------------------
# Runtime entry
# ----------------------------------------------------------------------
entry_path = PLUGIN / "__init__.py"
entry = entry_path.read_text(encoding="utf-8")
entry = entry.replace('"""光鸭转存助手 v1.12.6 运行入口。', '"""光鸭转存助手 v1.12.7 运行入口。', 1)
if "v1.12.7 修复“已找到资源/缺集但未提交光鸭”" not in entry:
    entry = entry.replace(
        "v1.12.6 快速追更：当天应播 TV/动漫的 AiringDue 改为每 10 分钟唤醒并使用独立 10 分钟主动检索窗口；电影继续 60 分钟；命中、已入库或在途后立即退出快追。\n",
        "v1.12.6 快速追更：当天应播 TV/动漫的 AiringDue 改为每 10 分钟唤醒并使用独立 10 分钟主动检索窗口；电影继续 60 分钟；命中、已入库或在途后立即退出快追。\n"
        "v1.12.7 修复“已找到资源/缺集但未提交光鸭”：S02+ 季发行年份不再被系列首播年份误杀；GYING 已命中且真实分享顶层名/文件结构一致时允许合法别名桥接；拆包 needs_review 在证据变化或 6 小时后自动重评，并补齐拆包决策日志。\n",
        1,
    )
if "from .resource_gate_v1127 import GuangYaResourceGateV1127Mixin" not in entry:
    entry = entry.replace(
        "from .fast_recall_v1126 import GuangYaFastRecallV1126Mixin\n",
        "from .fast_recall_v1126 import GuangYaFastRecallV1126Mixin\nfrom .resource_gate_v1127 import GuangYaResourceGateV1127Mixin\n",
        1,
    )
if "    GuangYaResourceGateV1127Mixin,\n    GuangYaFastRecallV1126Mixin," not in entry:
    entry = entry.replace(
        "    GuangYaPagePerfV1123Mixin,\n    GuangYaFastRecallV1126Mixin,",
        "    GuangYaPagePerfV1123Mixin,\n    GuangYaResourceGateV1127Mixin,\n    GuangYaFastRecallV1126Mixin,",
        1,
    )
entry = entry.replace('plugin_version = "1.12.6"', 'plugin_version = "1.12.7"', 1)
entry = entry.replace('build_id = "20260904-r52"', 'build_id = "20260905-r53"', 1)
entry_path.write_text(entry, encoding="utf-8")

# ----------------------------------------------------------------------
# Public metadata
# ----------------------------------------------------------------------
description = (
    "更新日历驱动的固定分流助手：5 分钟频道 Push 被动消费；当天应播 TV/动漫每 10 分钟快速追更；"
    "v1.12.7 修复观影已找到资源、缺集也已识别却未提交光鸭的问题，支持 S02+ 季发行年份与系列首播年份差异、"
    "强证据合法别名桥接，并让拆包 needs_review 在证据变化后自动恢复；来源优先级仍为观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K；"
    "非更新日不主动访问外部资源站，04:10 每日全员复核兜底。"
)
history_text = (
    "修复“资源已找到/缺集已识别但没有秒传或云添加”的后置门禁误杀：TV S02+ 若季号与剧集结构明确吻合，"
    "资源中的本季发行年份可不同于 MoviePilot 系列首播年份；GYING 搜索标题命中订阅、真实分享顶层名与内部文件名一致且年/季无冲突时，"
    "允许安全合法别名桥接（不做编辑距离模糊匹配，电影/错误季/S01 错年份继续硬拒绝）；Magnet/ED2K 拆包 needs_review 不再永久死亡，"
    "缺集/季/目标证据变化立即重评，证据不变每 6 小时最多复核一次；新增 missing/reserved/target/resolved/indexes/ambiguous 拆包日志。"
)

plugin_json_path = PLUGIN / "plugin.json"
plugin_json = json.loads(plugin_json_path.read_text(encoding="utf-8"))
plugin_json["version"] = "1.12.7"
plugin_json["description"] = description
plugin_json_path.write_text(json.dumps(plugin_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

package_path = ROOT / "package.v3.json"
package = json.loads(package_path.read_text(encoding="utf-8"))
row = package["GuangYaTransferAssistant"]
row["version"] = "1.12.7"
row["description"] = description
labels = [value.strip() for value in str(row.get("labels") or "").split(",") if value.strip()]
for value in ("资源门禁", "季发行年份", "合法别名", "拆包恢复", "needs_review"):
    if value not in labels:
        labels.append(value)
row["labels"] = ",".join(labels)
history = dict(row.get("history") or {})
row["history"] = {"v1.12.7": history_text, **history}
package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

readme_path = PLUGIN / "README.md"
readme = readme_path.read_text(encoding="utf-8")
release_note = """

## v1.12.7：资源找到但未提交光鸭修复

- TV S02+：系列首播年份与本季发行年份不同不再直接误杀；必须同时满足正确季号与剧集结构。
- 合法别名：GYING 搜索标题命中订阅，且真实分享顶层名与内部文件名自洽、年/季无冲突时允许安全桥接；不做模糊猜测。
- 拆包恢复：Magnet/ED2K 的 `needs_review` 在缺集/季/目标证据变化时立即重评，证据不变每 6 小时最多复核一次。
- 新增 `【拆包v1.12.7】` 日志，一次显示 `missing / reserved / target / resolved / indexes / ambiguous`，便于直接定位“找到了为什么没执行”。
- 来源优先级与终态安全栅栏不变：观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K。
""".rstrip()
if "## v1.12.7：资源找到但未提交光鸭修复" not in readme:
    marker = "\n## "
    pos = readme.find(marker)
    if pos >= 0:
        readme = readme[:pos] + release_note + "\n" + readme[pos:]
    else:
        readme += release_note + "\n"
readme_path.write_text(readme, encoding="utf-8")

# ----------------------------------------------------------------------
# Tests: migrate only current-release expectations; historical source layer markers remain unchanged.
# ----------------------------------------------------------------------
for path in (ROOT / "tests").rglob("test_*.py"):
    text = path.read_text(encoding="utf-8")
    original = text
    # Current public version assertions consistently use the latest version literal.
    text = text.replace('"1.12.6"', '"1.12.7"')
    text = text.replace("'1.12.6'", "'1.12.7'")

    # Runtime ENTRY build moves to r53; never rewrite historical module markers such as FAST/guard_text/text.
    lines = []
    for line in text.splitlines(keepends=True):
        lowered = line.lower()
        if 'build_id = "20260904-r52"' in line and "entry" in lowered:
            line = line.replace('build_id = "20260904-r52"', 'build_id = "20260905-r53"')
        lines.append(line)
    text = "".join(lines)
    if text != original:
        path.write_text(text, encoding="utf-8")


def add_gate_to_mro(path: Path, old_slice: str, new_slice: str) -> None:
    text = path.read_text(encoding="utf-8")
    if '"GuangYaResourceGateV1127Mixin"' not in text:
        text, count = re.subn(
            r'(?m)^(\s*)"GuangYaPagePerfV1123Mixin",\n\1"GuangYaFastRecallV1126Mixin",',
            lambda match: (
                f'{match.group(1)}"GuangYaPagePerfV1123Mixin",\n'
                f'{match.group(1)}"GuangYaResourceGateV1127Mixin",\n'
                f'{match.group(1)}"GuangYaFastRecallV1126Mixin",'
            ),
            text,
            count=1,
        )
        assert count == 1, path
    text = text.replace(old_slice, new_slice, 1)
    path.write_text(text, encoding="utf-8")


add_gate_to_mro(ROOT / "tests/test_guangya_receipt_completion_v1124.py", "mixins[:10]", "mixins[:11]")
add_gate_to_mro(ROOT / "tests/test_guangya_release_v1110.py", "mixins[:10]", "mixins[:11]")
add_gate_to_mro(ROOT / "tests/v3/guangyatransferassistant/test_airing_ui_v1120.py", "mixins[:11]", "mixins[:12]")

# Preserve explicit historical v1.12.6 source-layer assertions where the variable is not ENTRY.
fast_test = ROOT / "tests/v3/guangyatransferassistant/test_fast_recall_v1126.py"
fast_text = fast_test.read_text(encoding="utf-8")
# Its version/build assertions inspect ENTRY and correctly stay at 1.12.7/r53; FAST itself is intentionally untouched.
fast_test.write_text(fast_text, encoding="utf-8")

# New release contract must also prove v1.12.6 history remains published.
gate_test = ROOT / "tests/v3/guangyatransferassistant/test_resource_gate_v1127.py"
gate_text = gate_test.read_text(encoding="utf-8")
if "def test_v1127_public_metadata_keeps_v1126_history" not in gate_text:
    gate_text += '''\n\ndef test_v1127_public_metadata_keeps_v1126_history():\n    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]\n    plugin = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))\n    assert package["version"] == plugin["version"] == "1.12.7"\n    assert "v1.12.7" in package["history"]\n    assert "v1.12.6" in package["history"]\n    entry = ENTRY.read_text(encoding="utf-8")\n    assert 'plugin_version = "1.12.7"' in entry\n    assert 'build_id = "20260905-r53"' in entry\n'''
    gate_text = gate_text.replace("import ast\n", "import ast\nimport json\n", 1)
    gate_test.write_text(gate_text, encoding="utf-8")

Path(__file__).unlink()
