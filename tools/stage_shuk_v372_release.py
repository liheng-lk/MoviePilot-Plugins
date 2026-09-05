from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
VERSION = "3.7.2"
HISTORY = (
    "整理核心 Phase 2 第二阶段：将 v3.4.9 folder success 成员终态核对与 v3.4.10 空/已搬空目录收口"
    "从 QueueRecovery 运行时 monkey patch 迁入最终 Execution fallback 显式生命周期；"
    "organizer_loss_guard_v349 与 organizer_empty_folder_guard_v3410 退化为纯 Preview/源事实 helper，"
    "不再改写 QueueRecovery。文件处置规则完全继承 v3.7.0：同大小复核后去重、不同大小版本化、"
    "未识别原地保留、网络/大小事实未知 fail closed；MoviePilot 识别/分类/命名、durable/pending/分页/Move 保护"
    "与光鸭认证/API/Storage 不变。"
)


def write_json(path: Path, obj: object) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# Python runtime version.
path = PLUGIN / "__init__.py"
text = path.read_text(encoding="utf-8")
text, count = re.subn(r'plugin_version = "3\.7\.1"', f'plugin_version = "{VERSION}"', text, count=1)
if count != 1:
    raise RuntimeError("__init__.py version anchor missing")
path.write_text(text, encoding="utf-8")

# Local plugin metadata.
path = PLUGIN / "plugin.json"
meta = json.loads(path.read_text(encoding="utf-8"))
if meta.get("version") != "3.7.1":
    raise RuntimeError(f"unexpected plugin version: {meta.get('version')}")
meta["version"] = VERSION
history = dict(meta.get("history") or {})
meta["history"] = {f"v{VERSION}": HISTORY, **{k: v for k, v in history.items() if k != f"v{VERSION}"}}
write_json(path, meta)

# Market entry: modify only Shuk object semantically and preserve every other plugin object.
path = ROOT / "package.v3.json"
package = json.loads(path.read_text(encoding="utf-8"))
transfer_before = json.dumps(package.get("GuangYaTransferAssistant"), ensure_ascii=False, sort_keys=True)
shuk = dict(package["ShukGuangYaDisk"])
if shuk.get("version") != "3.7.1":
    raise RuntimeError(f"unexpected market Shuk version: {shuk.get('version')}")
shuk["version"] = VERSION
history = dict(shuk.get("history") or {})
shuk["history"] = {f"v{VERSION}": HISTORY, **{k: v for k, v in history.items() if k != f"v{VERSION}"}}
package["ShukGuangYaDisk"] = shuk
if json.dumps(package.get("GuangYaTransferAssistant"), ensure_ascii=False, sort_keys=True) != transfer_before:
    raise RuntimeError("cross-plugin mutation detected")
write_json(path, package)

# Front-end cache buster.
path = PLUGIN / "dist" / "assets" / "remoteEntry.js"
text = path.read_text(encoding="utf-8")
old = "__federation_expose_AssistantPage-v352.js?v=3.7.1"
new = f"__federation_expose_AssistantPage-v352.js?v={VERSION}"
if text.count(old) != 1:
    raise RuntimeError("remoteEntry version anchor missing")
path.write_text(text.replace(old, new, 1), encoding="utf-8")

# Exact release contract for v3.7.2.
test_path = ROOT / "tests" / "v3" / "shukguangyadisk" / "test_release_v372.py"
test_path.write_text(f'''from __future__ import annotations\n\nimport json\nfrom pathlib import Path\n\nROOT = Path(__file__).resolve().parents[3]\nPLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"\nVERSION = "{VERSION}"\n\n\ndef test_v372_release_metadata_is_exact():\n    init_text = (PLUGIN / "__init__.py").read_text(encoding="utf-8")\n    plugin = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))\n    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))\n    remote = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")\n    assert f'plugin_version = "{{VERSION}}"' in init_text\n    assert plugin["version"] == VERSION\n    assert package["ShukGuangYaDisk"]["version"] == VERSION\n    assert f'?v={{VERSION}}' in remote\n    assert f'v{{VERSION}}' in plugin["history"]\n    assert plugin["history"][f'v{{VERSION}}'] == package["ShukGuangYaDisk"]["history"][f'v{{VERSION}}']\n\n\ndef test_v372_release_removes_two_more_runtime_installers_without_new_media_policy():\n    candidate = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")\n    loss = (PLUGIN / "organizer_loss_guard_v349.py").read_text(encoding="utf-8")\n    empty = (PLUGIN / "organizer_empty_folder_guard_v3410.py").read_text(encoding="utf-8")\n    execution = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")\n    for token in ("install_loss_guard_v349", "install_empty_folder_guard_v3410"):\n        assert token not in candidate\n        assert token not in loss\n        assert token not in empty\n    assert '"organizer_policy_version": "v3.7.2"' in execution\n    assert "_defer_unconfirmed_members(self, item, reason)" in execution\n    assert "_guangya_empty_folder_skip_v3410" in execution\n    policy = (PLUGIN / "organizer_policy.py").read_text(encoding="utf-8")\n    for disposition in ("LEAVE_UNRECOGNIZED", "DELETE_DUPLICATE", "ORGANIZE_VERSION", "BLOCK_SAFETY", "RETIRE_MISSING"):\n        assert disposition in policy\n\n\ndef test_v372_cross_plugin_market_entry_is_not_rolled_back():\n    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))\n    transfer = tuple(map(int, package["GuangYaTransferAssistant"]["version"].split(".")))\n    assert transfer >= (1, 12, 14)\n''', encoding="utf-8")

print("staged ShukGuangYaDisk v3.7.2 release metadata")
