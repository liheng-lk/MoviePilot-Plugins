from pathlib import Path
import json

root = Path(__file__).resolve().parents[1]
plugin = root / "plugins.v3" / "shukguangyadisk"

patch = plugin / "organizer_monitor_v366.py"
text = patch.read_text(encoding="utf-8")

needle = "    _v366_known_scan_active: bool = False\n"
replacement = (
    "    _v366_known_scan_active: bool = False\n"
    "    # 手动整理必须保持‘已筛选成员’输入语义，禁止再次把整个目录交给 MoviePilot。\n"
    "    _v366_manual_scan_active: bool = False\n"
)
if "_v366_manual_scan_active" not in text:
    if needle not in text:
        raise RuntimeError("cannot locate v366 class state marker")
    text = text.replace(needle, replacement, 1)

needle = (
    "        monitor_root = self._v360_norm(self._organize_monitor_path)\n"
    "        normalized_group = self._v360_norm(group_path)\n"
    "        loose = normalized_group == monitor_root\n"
)
replacement = (
    "        monitor_root = self._v360_norm(self._organize_monitor_path)\n"
    "        normalized_group = self._v360_norm(group_path)\n"
    "        manual_safe_mode = bool(getattr(self, \"_v366_manual_scan_active\", False))\n"
    "        loose = normalized_group == monitor_root\n"
)
if "manual_safe_mode = bool(getattr(self, \"_v366_manual_scan_active\", False))" not in text:
    if needle not in text:
        raise RuntimeError("cannot locate v366 schedule header")
    text = text.replace(needle, replacement, 1)

needle = (
    "            directory_mode = bool(\n"
    "                all_primary_ready\n"
    "                and _can_use_native_directory_batch(\n"
)
replacement = (
    "            directory_mode = bool(\n"
    "                not manual_safe_mode\n"
    "                and all_primary_ready\n"
    "                and _can_use_native_directory_batch(\n"
)
if "not manual_safe_mode\n                and all_primary_ready" not in text:
    if needle not in text:
        raise RuntimeError("cannot locate directory_mode gate")
    text = text.replace(needle, replacement, 1)

needle = "        mode_text = \"MoviePilot原生目录（全成员ready）\" if directory_mode else \"已筛选成员\"\n"
replacement = (
    "        if directory_mode:\n"
    "            mode_text = \"MoviePilot原生目录（全成员ready）\"\n"
    "        elif manual_safe_mode:\n"
    "            mode_text = \"手动安全筛选成员\"\n"
    "        else:\n"
    "            mode_text = \"已筛选成员\"\n"
)
if "mode_text = \"手动安全筛选成员\"" not in text:
    if needle not in text:
        raise RuntimeError("cannot locate v366 mode log")
    text = text.replace(needle, replacement, 1)

api_marker = "    def api_organize_monitor_status(self) -> Dict[str, Any]:\n"
api_impl = '''    def api_organize_monitor_scan(self, payload: dict = None) -> Dict[str, Any]:
        """手动整理只允许使用已筛选成员，避免目录输入与历史单文件输入发生准入冲突。"""
        previous = bool(getattr(self, "_v366_manual_scan_active", False))
        self._v366_manual_scan_active = True
        try:
            return super().api_organize_monitor_scan(payload)
        finally:
            self._v366_manual_scan_active = previous

'''
if "def api_organize_monitor_scan(self, payload: dict = None)" not in text:
    if api_marker not in text:
        raise RuntimeError("cannot locate v366 status API marker")
    text = text.replace(api_marker, api_impl + api_marker, 1)

text = text.replace("【v3.6.6】", "【v3.6.7】")
text = text.replace('"monitor_engine_patch": "v3.6.6"', '"monitor_engine_patch": "v3.6.7"')
patch.write_text(text, encoding="utf-8")

batch = plugin / "organizer_folder_batch_v342.py"
batch_text = batch.read_text(encoding="utf-8")
old = "                original_fallback(self, member, success=success, message=message)\n"
new = (
    "                # 动态分派到最终插件实例，让 admission conflict guard 先于旧 retry fallback 生效。\n"
    "                self._fallback_terminal_state(member, success=success, message=message)\n"
)
compat_start = batch_text.index("        if not item.directory_mode:")
compat_end = batch_text.index("        directory_item = FileItem(", compat_start)
compat = batch_text[compat_start:compat_end]
if "self._fallback_terminal_state(member, success=success, message=message)" not in compat:
    if old not in compat:
        raise RuntimeError("cannot locate compatibility fallback call")
    compat = compat.replace(old, new, 1)
    batch_text = batch_text[:compat_start] + compat + batch_text[compat_end:]
batch.write_text(batch_text, encoding="utf-8")

test_path = root / "tests" / "v3" / "shukguangyadisk" / "test_monitor_v366.py"
test_text = test_path.read_text(encoding="utf-8")
if "FOLDER_BATCH =" not in test_text:
    test_text = test_text.replace(
        'ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")\n',
        'ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")\n'
        'FOLDER_BATCH = (PLUGIN / "organizer_folder_batch_v342.py").read_text(encoding="utf-8")\n',
        1,
    )
additions = r'''


def test_v367_manual_scan_never_uses_native_directory_batch():
    schedule = PATCH[PATCH.index("def _v360_schedule_resource"):PATCH.index("@staticmethod\n    def _v366_is_admission_conflict")]
    manual_api = PATCH[PATCH.index("def api_organize_monitor_scan"):PATCH.index("def api_organize_monitor_status")]
    assert '_v366_manual_scan_active: bool = False' in PATCH
    assert 'manual_safe_mode = bool(getattr(self, "_v366_manual_scan_active", False))' in schedule
    assert 'not manual_safe_mode' in schedule
    assert 'mode_text = "手动安全筛选成员"' in schedule
    assert 'self._v366_manual_scan_active = True' in manual_api
    assert 'finally:' in manual_api
    assert 'self._v366_manual_scan_active = previous' in manual_api


def test_v367_selected_member_failure_uses_final_admission_guard():
    compat = FOLDER_BATCH[FOLDER_BATCH.index("if not item.directory_mode:"):FOLDER_BATCH.index("directory_item = FileItem(")]
    assert 'self._fallback_terminal_state(member, success=success, message=message)' in compat
    assert 'original_fallback(self, member, success=success, message=message)' not in compat
'''
if "def test_v367_manual_scan_never_uses_native_directory_batch" not in test_text:
    test_text += additions
test_path.write_text(test_text, encoding="utf-8")

summary = (
    "修复手动整理‘整理源文件已按不同输入准入’：手动扫描强制使用已筛选成员，禁止把整个 Season 目录再次作为另一种输入提交给 MoviePilot；"
    "逐文件兼容执行的终态回调改为动态走最终 admission guard，使不同输入准入冲突进入 blocked 而不是先落入普通 retry。"
)

entry = plugin / "__init__.py"
entry_text = entry.read_text(encoding="utf-8")
if 'plugin_version = "3.6.6"' not in entry_text and 'plugin_version = "3.6.7"' not in entry_text:
    raise RuntimeError("unexpected plugin version")
entry.write_text(entry_text.replace('plugin_version = "3.6.6"', 'plugin_version = "3.6.7"', 1), encoding="utf-8")

local_meta = plugin / "plugin.json"
meta = json.loads(local_meta.read_text(encoding="utf-8"))
meta["version"] = "3.6.7"
history = dict(meta.get("history") or {})
history.pop("v3.6.7", None)
meta["history"] = {"v3.6.7": summary, **history}
local_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

package = root / "package.v3.json"
data = json.loads(package.read_text(encoding="utf-8"))
shuk = dict(data["ShukGuangYaDisk"])
shuk["version"] = "3.6.7"
history = dict(shuk.get("history") or {})
history.pop("v3.6.7", None)
shuk["history"] = {"v3.6.7": summary, **history}
data["ShukGuangYaDisk"] = shuk
package.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

remote = plugin / "dist" / "assets" / "remoteEntry.js"
remote_text = remote.read_text(encoding="utf-8")
if "?v=3.6.6" not in remote_text and "?v=3.6.7" not in remote_text:
    raise RuntimeError("unexpected remoteEntry version token")
remote.write_text(remote_text.replace("?v=3.6.6", "?v=3.6.7"), encoding="utf-8")

contract = root / "tests" / "v3" / "shukguangyadisk" / "test_move_transaction_guard_v364.py"
contract_text = contract.read_text(encoding="utf-8")
contract_text = contract_text.replace('== "3.6.6"', '== "3.6.7"')
contract_text = contract_text.replace('plugin_version = "3.6.6"', 'plugin_version = "3.6.7"')
contract_text = contract_text.replace("?v=3.6.6", "?v=3.6.7")
contract.write_text(contract_text, encoding="utf-8")

workflow = root / ".github" / "workflows" / "hotfix-shukguangyadisk-manual-admission-v367-once.yml"
if workflow.exists():
    workflow.unlink()

# 脚本本身只用于候选生成，验证提交中不保留。
Path(__file__).unlink()
