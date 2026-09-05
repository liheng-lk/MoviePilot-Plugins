from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
TESTS = ROOT / "tests" / "v3" / "shukguangyadisk"
VERSION = "3.7.3"
HISTORY = (
    "整理核心 Phase 2 第三阶段：将 v3.4.11 集数整组样本/弱命名 Preview 复核与 v3.4.12 分类一致性"
    "从连续运行时 monkey patch 迁入 loss guard 显式 Preview 上下文；删除 ContextVar episode sample bridge，"
    "整组成员直接传入 MoviePilot recommend_episode_format，并复用同一次目录识别得到的 meta 做 TV 约束，"
    "不再二次 recognize_by_path。文件处置规则完全继承 v3.7.0；MoviePilot 媒体身份/普通命名/目标目录、"
    "durable/pending/终态归属/分页/Move 保护及光鸭认证/API/Storage 均不变。"
)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepend_history(data: dict) -> None:
    old = dict(data.get("history") or {})
    data["history"] = {f"v{VERSION}": HISTORY, **{k: v for k, v in old.items() if k != f"v{VERSION}"}}


# Release metadata surfaces.
plugin_json = load_json(PLUGIN / "plugin.json")
plugin_json["version"] = VERSION
prepend_history(plugin_json)
dump_json(PLUGIN / "plugin.json", plugin_json)

package = load_json(ROOT / "package.v3.json")
shuk = dict(package["ShukGuangYaDisk"])
shuk["version"] = VERSION
prepend_history(shuk)
package["ShukGuangYaDisk"] = shuk
dump_json(ROOT / "package.v3.json", package)

init_path = PLUGIN / "__init__.py"
init_text = init_path.read_text(encoding="utf-8")
init_text, count = re.subn(r'plugin_version = "3\.7\.2"', f'plugin_version = "{VERSION}"', init_text, count=1)
if count != 1:
    raise RuntimeError("plugin_version 3.7.2 anchor missing")
init_path.write_text(init_text, encoding="utf-8")

remote_path = PLUGIN / "dist" / "assets" / "remoteEntry.js"
remote = remote_path.read_text(encoding="utf-8")
if "?v=3.7.2" not in remote:
    raise RuntimeError("remoteEntry 3.7.2 cache anchor missing")
remote_path.write_text(remote.replace("?v=3.7.2", f"?v={VERSION}"), encoding="utf-8")

execution_path = PLUGIN / "organizer_execution_v360.py"
execution = execution_path.read_text(encoding="utf-8")
if '"organizer_policy_version": "v3.7.2"' not in execution:
    raise RuntimeError("organizer policy 3.7.2 anchor missing")
execution = execution.replace('"organizer_policy_version": "v3.7.2"', '"organizer_policy_version": "v3.7.3"', 1)
execution = execution.replace(
    "【光鸭云盘助手】【整理核心 v3.7.2】policy 执行链已显式接管：",
    "【光鸭云盘助手】【整理核心 v3.7.3】policy/Preview 执行链已显式接管：",
    1,
)
execution = execution.replace(
    "冲突处置/预览补救/版本 Rename/重复终态/folder 终态核对不再使用运行时 monkey patch",
    "冲突处置/预览补救/版本 Rename/重复终态/folder 终态/集数与分类 Preview 上下文不再使用运行时 monkey patch",
    1,
)
execution_path.write_text(execution, encoding="utf-8")

# Extend the existing Phase 2 architecture record instead of creating another versioned doc.
doc_path = PLUGIN / "PHASE2_V372.md"
doc = doc_path.read_text(encoding="utf-8")
if "## v3.7.3 recognition / Preview continuation" not in doc:
    doc += '''\n## v3.7.3 recognition / Preview continuation\n\n- `install_episode_name_adapter_v3411()` 退出运行图；弱命名/整组集号兼容改为纯 helper。\n- `install_episode_sample_bridge_v3411()` 与整个 ContextVar bridge 模块删除；folder members 直接传给 MoviePilot `recommend_episode_format`。\n- `install_category_consistency_v3412()` 退出运行图；分类只由 MoviePilot `CategoryHelper` 在显式 Preview 上下文中复核。\n- `organizer_loss_guard_v349._build_moviepilot_kwargs()` 明确执行：一次 MoviePilot 目录识别 → 集数适配 → 分类一致性。\n- TV 约束重识别复用同一次目录识别的 `meta_info`，同一 Preview 构建过程不二次 `recognize_by_path`。\n- Preview 唯一目标校验通过后，再显式执行弱命名 season/episode 终态复核；任何不一致仍 fail closed。\n'''
doc_path.write_text(doc, encoding="utf-8")


# v3.7.2 release tests become historical floors after v3.7.3.
(TESTS / "test_release_v372.py").write_text(r'''from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"


def test_v372_release_metadata_is_preserved_as_floor():
    init_text = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
    plugin = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    remote = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")
    match = re.search(r'plugin_version = "(\d+)\.(\d+)\.(\d+)"', init_text)
    assert match and tuple(map(int, match.groups())) >= (3, 7, 2)
    assert tuple(map(int, plugin["version"].split("."))) >= (3, 7, 2)
    assert tuple(map(int, package["ShukGuangYaDisk"]["version"].split("."))) >= (3, 7, 2)
    assert f'?v={plugin["version"]}' in remote
    assert "v3.7.2" in plugin["history"]
    assert plugin["history"]["v3.7.2"] == package["ShukGuangYaDisk"]["history"]["v3.7.2"]


def test_v372_release_removes_two_more_runtime_installers_without_new_media_policy():
    candidate = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")
    loss = (PLUGIN / "organizer_loss_guard_v349.py").read_text(encoding="utf-8")
    empty = (PLUGIN / "organizer_empty_folder_guard_v3410.py").read_text(encoding="utf-8")
    execution = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")
    for token in ("install_loss_guard_v349", "install_empty_folder_guard_v3410"):
        assert token not in candidate
        assert token not in loss
        assert token not in empty
    match = re.search(r'"organizer_policy_version": "v(\d+)\.(\d+)\.(\d+)"', execution)
    assert match and tuple(map(int, match.groups())) >= (3, 7, 2)
    assert "_defer_unconfirmed_members(self, item, reason)" in execution
    assert "_guangya_empty_folder_skip_v3410" in execution
    policy = (PLUGIN / "organizer_policy.py").read_text(encoding="utf-8")
    for disposition in ("LEAVE_UNRECOGNIZED", "DELETE_DUPLICATE", "ORGANIZE_VERSION", "BLOCK_SAFETY", "RETIRE_MISSING"):
        assert disposition in policy


def test_v372_cross_plugin_market_entry_is_not_rolled_back():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    transfer = tuple(map(int, package["GuangYaTransferAssistant"]["version"].split(".")))
    assert transfer >= (1, 12, 14)
''', encoding="utf-8")

phase372_path = TESTS / "test_organizer_phase2_v372_contract.py"
phase372 = phase372_path.read_text(encoding="utf-8")
phase372 = phase372.replace(
    '''        '"folder_partial" if deferred else "folder_completed"',
        '"organizer_policy_version": "v3.7.2"',
    ):
        assert token in EXECUTION, token
''',
    '''        '"folder_partial" if deferred else "folder_completed"',
    ):
        assert token in EXECUTION, token
    match = __import__("re").search(r'"organizer_policy_version": "v(\\d+)\\.(\\d+)\\.(\\d+)"', EXECUTION)
    assert match and tuple(map(int, match.groups())) >= (3, 7, 2)
''',
    1,
)
phase372_path.write_text(phase372, encoding="utf-8")


# Exact v3.7.3 release contract.
(TESTS / "test_release_v373.py").write_text(r'''from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
VERSION = "3.7.3"


def test_v373_release_metadata_is_exact_and_cross_plugin_safe():
    init_text = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
    plugin = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    remote = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")
    execution = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")
    assert f'plugin_version = "{VERSION}"' in init_text
    assert plugin["version"] == VERSION
    assert package["ShukGuangYaDisk"]["version"] == VERSION
    assert f'?v={VERSION}' in remote
    assert f'v{VERSION}' in plugin["history"]
    assert plugin["history"][f'v{VERSION}'] == package["ShukGuangYaDisk"]["history"][f'v{VERSION}']
    assert '"organizer_policy_version": "v3.7.3"' in execution
    assert tuple(map(int, package["GuangYaTransferAssistant"]["version"].split("."))) >= (1, 12, 14)


def test_v373_release_removes_three_recognition_preview_installers_and_bridge_module():
    candidate = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")
    episode = (PLUGIN / "organizer_episode_name_adapter_v3411.py").read_text(encoding="utf-8")
    category = (PLUGIN / "organizer_category_consistency_v3412.py").read_text(encoding="utf-8")
    loss = (PLUGIN / "organizer_loss_guard_v349.py").read_text(encoding="utf-8")
    for token in (
        "install_episode_name_adapter_v3411",
        "install_episode_sample_bridge_v3411",
        "install_category_consistency_v3412",
    ):
        assert token not in candidate
    assert not (PLUGIN / "organizer_episode_sample_bridge_v3411.py").exists()
    assert "_build_moviepilot_kwargs =" not in episode
    assert "_audit_preview =" not in episode
    assert "_build_moviepilot_kwargs =" not in category
    assert "apply_episode_name_adapter(" in loss
    assert "apply_category_consistency(" in loss
    assert "audit_episode_expectations(" in loss


def test_v373_release_keeps_one_disposition_policy_and_moviepilot_authority():
    policy = (PLUGIN / "organizer_policy.py").read_text(encoding="utf-8")
    episode = (PLUGIN / "organizer_episode_name_adapter_v3411.py").read_text(encoding="utf-8")
    category = (PLUGIN / "organizer_category_consistency_v3412.py").read_text(encoding="utf-8")
    assert "recommend_episode_format(" in episode
    assert "FormatParser(eformat=template)" in episode
    assert "CategoryHelper" in category
    for disposition in ("LEAVE_UNRECOGNIZED", "DELETE_DUPLICATE", "ORGANIZE_VERSION", "BLOCK_SAFETY", "RETIRE_MISSING"):
        assert disposition in policy
    for source in (episode, category):
        for forbidden in ("tmdb_id=", "media_id=", "DirectoryHelper().get_dir(", "self._guangya_api.move", "self._guangya_api.copy"):
            assert forbidden not in source
''', encoding="utf-8")

print("staged ShukGuangYaDisk v3.7.3 release metadata")
