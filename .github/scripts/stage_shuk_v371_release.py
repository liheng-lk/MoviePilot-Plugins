from __future__ import annotations

from pathlib import Path

ROOT = Path("plugins.v3/shukguangyadisk")
VERSION = "3.7.1"
OLD = "3.7.0"
HISTORY = (
    "整理核心 Phase 2：将冲突处置、目录 Preview 缺员补救、旧 preview retry 唤醒从运行时 monkey patch "
    "迁入最终 Execution 核心显式调用；版本化 TransferRename 与重复副本终态清理也由 Execution 明确桥接。"
    "删除 install_conflict_resolution_v353 / install_preview_partial_v355 / install_preview_retry_wakeup_v356 三个行为 installer，"
    "helper 不再改写 QueueRecovery、FolderStream 或 Organizer 类方法。文件处置规则完全继承 v3.7.0：未识别原地保留、"
    "同大小复核后去重、不同大小版本化、未知事实 fail closed；v3.6.20 终态归属门禁仍位于 duplicate cleanup 外层，"
    "115/本地事件不能进入光鸭终态副作用。光鸭认证/API/存储、MoviePilot 识别/分类/普通命名、durable/pending/分页与 Move 保护均不变。"
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = read(path)
    if old not in text:
        raise AssertionError(f"release patch point changed: {label}")
    write(path, text.replace(old, new, 1))


# Runtime/public metadata.
replace_once(ROOT / "__init__.py", f'plugin_version = "{OLD}"', f'plugin_version = "{VERSION}"', "runtime version")
replace_once(
    ROOT / "dist/assets/remoteEntry.js",
    f"__federation_expose_AssistantPage-v352.js?v={OLD}",
    f"__federation_expose_AssistantPage-v352.js?v={VERSION}",
    "federation cache version",
)

plugin_path = ROOT / "plugin.json"
plugin = read(plugin_path)
if f'"version": "{OLD}"' not in plugin:
    raise AssertionError("plugin.json version base changed")
plugin = plugin.replace(f'"version": "{OLD}"', f'"version": "{VERSION}"', 1)
marker = '  "history": {\n'
if marker not in plugin:
    raise AssertionError("plugin.json history marker missing")
plugin = plugin.replace(marker, marker + f'    "v{VERSION}": "{HISTORY}",\n', 1)
write(plugin_path, plugin)

package_path = Path("package.v3.json")
package = read(package_path)
start = package.find('  "ShukGuangYaDisk": {')
end = package.find('\n  },', start)
if start < 0 or end < 0:
    raise AssertionError("ShukGuangYaDisk package section missing")
section = package[start:end]
if f'"version": "{OLD}"' not in section:
    raise AssertionError("package Shuk version base changed")
section = section.replace(f'"version": "{OLD}"', f'"version": "{VERSION}"', 1)
marker = '    "history": {\n'
if marker not in section:
    raise AssertionError("package Shuk history marker missing")
section = section.replace(marker, marker + f'      "v{VERSION}": "{HISTORY}",\n', 1)
write(package_path, package[:start] + section + package[end:])

# v3.7.0 test becomes a floor/history contract instead of blocking later patch releases.
test370 = Path("tests/v3/shukguangyadisk/test_release_v370.py")
text = read(test370)
old_func_start = text.find("def test_v370_release_metadata_is_consistent():\n")
next_func = text.find("\ndef test_v370_preserves_current_transfer_assistant_release():\n", old_func_start)
if old_func_start < 0 or next_func < 0:
    raise AssertionError("v3.7.0 release contract function changed")
new_func = '''def test_v370_release_metadata_is_preserved_as_floor():
    import re

    init_text = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
    plugin = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    remote = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")

    match = re.search(r'plugin_version = "(\\d+)\\.(\\d+)\\.(\\d+)"', init_text)
    assert match and tuple(map(int, match.groups())) >= (3, 7, 0)
    assert tuple(map(int, plugin["version"].split("."))) >= (3, 7, 0)
    assert tuple(map(int, package["ShukGuangYaDisk"]["version"].split("."))) >= (3, 7, 0)
    assert f'?v={plugin["version"]}' in remote
    assert "v3.7.0" in plugin["history"]
    assert "v3.7.0" in package["ShukGuangYaDisk"]["history"]
'''
text = text[:old_func_start] + new_func + text[next_func + 1:]
write(test370, text)

# Exact v3.7.1 release contract.
test371 = Path("tests/v3/shukguangyadisk/test_release_v371.py")
write(test371, f'''from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
VERSION = "{VERSION}"


def test_v371_release_metadata_is_exact_and_cross_plugin_safe():
    init_text = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
    plugin = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    remote = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")
    assert f'plugin_version = "{{VERSION}}"' in init_text
    assert plugin["version"] == VERSION
    assert package["ShukGuangYaDisk"]["version"] == VERSION
    assert f'?v={{VERSION}}' in remote
    assert f'v{{VERSION}}' in plugin["history"]
    assert f'v{{VERSION}}' in package["ShukGuangYaDisk"]["history"]
    assert package["GuangYaTransferAssistant"]["version"] == "1.12.14"


def test_v371_release_is_phase2_architecture_only():
    execution = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")
    candidate = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")
    for token in (
        "install_conflict_resolution_v353",
        "install_preview_partial_v355",
        "install_preview_retry_wakeup_v356",
    ):
        assert token not in candidate
    assert '"organizer_policy_version": "v3.7.1"' in execution
    assert "_execute_conflict_aware(self, item)" in execution
    assert "rescue_partial_preview_if_needed(self, item, result)" in execution
''')

print("staged ShukGuangYaDisk v3.7.1 release")
