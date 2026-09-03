from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_required(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"cannot locate retained contract in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# DailyAssistant 旧层仍必须紧跟新日历层，Loader 仍只暴露最终 DailyAssistant。
old_daily = "class DailyAssistant(DailyAssistantV110Mixin, DailyAssistantV100):"
new_daily = "class DailyAssistant(DailyAssistantCalendarV120Mixin, DailyAssistantV110Mixin, DailyAssistantV100):"
for name in ("test_dailyassistant_v110.py", "test_dailyassistant_loader_v111.py"):
    replace_required(ROOT / "tests" / name, old_daily, new_daily)

# 光鸭旧的 identity -> release -> final fence -> receipt 相对顺序继续保持，
# 只是 v1.12.0 的 airing scheduler 成为最外层调度权威。
old_mixins = '''        self.assertEqual(mixins[:4], [
            "GuangYaMediaIdentityGuardV1111Mixin",
            "GuangYaReleaseV1110Mixin",
            "GuangYaEpisodeFenceFinalV1124Mixin",
            "GuangYaReceiptCompletionV1124Mixin",
        ])'''
new_mixins = '''        self.assertEqual(mixins[:5], [
            "GuangYaAiringSchedulerV1120Mixin",
            "GuangYaMediaIdentityGuardV1111Mixin",
            "GuangYaReleaseV1110Mixin",
            "GuangYaEpisodeFenceFinalV1124Mixin",
            "GuangYaReceiptCompletionV1124Mixin",
        ])'''
for name in ("test_guangya_release_v1110.py", "test_guangya_receipt_completion_v1124.py"):
    replace_required(ROOT / "tests" / name, old_mixins, new_mixins)

# v1.8.0 的“原生云添加”能力仍然存在，描述不能因为新日历特性而丢失该合同。
package_path = ROOT / "package.v3.json"
package = json.loads(package_path.read_text(encoding="utf-8"))
item = package["GuangYaTransferAssistant"]
description = str(item.get("description") or "")
if "原生云添加" not in description:
    item["description"] = description.rstrip("。") + "；Magnet/ED2K 继续使用光鸭原生云添加。"
package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

plugin_path = ROOT / "plugins.v3" / "guangyatransferassistant" / "plugin.json"
plugin = json.loads(plugin_path.read_text(encoding="utf-8"))
description = str(plugin.get("description") or "")
if "原生云添加" not in description:
    plugin["description"] = description.rstrip("。") + "；Magnet/ED2K 继续使用光鸭原生云添加。"
plugin_path.write_text(json.dumps(plugin, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

print("updated retained MRO/metadata contracts for v1.12.0")
