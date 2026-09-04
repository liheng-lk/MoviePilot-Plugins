from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
TEST_ROOT = ROOT / "tests"

# Only active runtime layers that still carried preview provenance are normalized.
RUNTIME_FILES = [
    "dispatch_policy_v1125.py",
    "dispatch_policy_final_v1125.py",
    "gying_recall_guard_v1125.py",
    "gying_hardening_v193.py",
    "gying_observability_v1104.py",
    "page_perf_v1123.py",
]

for name in RUNTIME_FILES:
    path = PLUGIN / name
    text = path.read_text(encoding="utf-8")
    text = text.replace("20260904-r51-preview", "20260904-r51")
    text = text.replace("20260904-r50-preview", "20260904-r51")
    text = text.replace("v1.12.5 预览：", "v1.12.5：")
    text = text.replace("v1.12.5 预览", "v1.12.5")
    text = text.replace("v1.12.4-preview", "v1.12.4")
    path.write_text(text, encoding="utf-8")
    ast.parse(text, filename=str(path))

# Current-release assertions live only in GuangYa tests. Historical package changelog
# and unrelated plugin tests are intentionally untouched.
test_paths = sorted(TEST_ROOT.glob("test_guangya*.py")) + sorted(
    (TEST_ROOT / "v3" / "guangyatransferassistant").glob("test_*.py")
)
for path in test_paths:
    text = path.read_text(encoding="utf-8")
    text = text.replace("1.12.4", "1.12.5")
    text = text.replace("20260904-r50-preview", "20260904-r51")
    text = text.replace("20260904-r51-preview", "20260904-r51")
    text = text.replace("20260904-r50", "20260904-r51")
    path.write_text(text, encoding="utf-8")
    ast.parse(text, filename=str(path))

# Dedicated final-release marker: prevent entry / local manifest / package index drift.
marker = TEST_ROOT / "v3" / "guangyatransferassistant" / "test_release_v1125_marker.py"
marker.write_text(
    '''from __future__ import annotations\n\nimport ast\nimport json\nfrom pathlib import Path\n\n\nROOT = Path(__file__).resolve().parents[3]\nPLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"\nENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")\nLOCAL = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))\nPACKAGE = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]\nFINAL = (PLUGIN / "dispatch_policy_final_v1125.py").read_text(encoding="utf-8")\nXUNLEI = (PLUGIN / "xunlei_flash_v193.py").read_text(encoding="utf-8")\n\n\ndef test_v1125_release_metadata_is_single_truth():\n    assert 'plugin_version = "1.12.5"' in ENTRY\n    assert 'build_id = "20260904-r51"' in ENTRY\n    assert LOCAL["version"] == "1.12.5"\n    assert PACKAGE["version"] == "1.12.5"\n    assert "v1.12.5" in PACKAGE["history"]\n\n\ndef test_v1125_release_has_no_active_preview_marker():\n    for name in (\n        "dispatch_policy_v1125.py",\n        "dispatch_policy_final_v1125.py",\n        "gying_recall_guard_v1125.py",\n        "gying_hardening_v193.py",\n        "gying_observability_v1104.py",\n        "page_perf_v1123.py",\n    ):\n        text = (PLUGIN / name).read_text(encoding="utf-8")\n        ast.parse(text, filename=name)\n        assert "r51-preview" not in text\n        assert "r50-preview" not in text\n\n\ndef test_v1125_hourly_full_chain_contract_is_published():\n    assert "_hourly_due_cooldown_seconds_v1125 = 60 * 60" in FINAL\n    assert 'mode == "airing_pull"' in FINAL\n    assert '"origin": "airing_full_chain_v1125"' in FINAL\n    assert "观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K" in FINAL\n    assert "每小时 AiringDue" in PACKAGE["history"]["v1.12.5"]\n\n\ndef test_v1125_runtime_mro_keeps_final_dispatch_authority():\n    start = ENTRY.index("class GuangYaTransferAssistant(")\n    assert ENTRY.index("GuangYaDispatchPolicyFinalV1125Mixin,", start) < ENTRY.index(\n        "GuangYaDispatchPolicyV1125Mixin,", start\n    )\n\n\ndef test_v1125_normal_chain_still_uses_xunlei_then_fallback():\n    method = XUNLEI.split("    def _try_transfer_subscription_inner(", 1)[1].split(\n        "    def api_xunlei_flash_test(", 1\n    )[0]\n    assert "flash = self._dispatch_xunlei_flash(subscribe)" in method\n    assert 'if flash.get("handled")' in method\n    assert "super()._try_transfer_subscription_inner" in method\n''',
    encoding="utf-8",
)

# README release note: preserve all historical sections.
readme = PLUGIN / "README.md"
text = readme.read_text(encoding="utf-8")
if "## v1.12.5" not in text:
    heading = """## v1.12.5：每小时今日到期媒体完整资源链\n\n- 5 分钟频道 Push 只消费已经到达的频道资源，不再借频道 tick 主动访问 GYING。\n- 每小时 AiringDue 只选择今天应播、MoviePilot 仍确认缺失且未被在途任务覆盖的媒体。\n- 今日到期媒体使用独立 60 分钟复查窗口，执行顺序保持：观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K。\n- 非更新日剧集不主动访问外部资源站；稳定更新星期可作为排期事实，日历服务异常时采用短退避并保留安全 fallback。\n- 每日 04:10 全员复核继续先消费频道，再重算真实剩余缺口并强制补漏。\n- 继续保留媒体身份门禁、缺集 planner、跨来源 reservation/source claim 与成功集终止栅栏，避免重复秒传/云添加。\n\n"""
    pos = text.find("\n## ")
    if pos >= 0:
        text = text[: pos + 1] + heading + text[pos + 1 :]
    else:
        text += "\n\n" + heading
    readme.write_text(text, encoding="utf-8")

# Final metadata sanity.
entry = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
assert 'plugin_version = "1.12.5"' in entry
assert 'build_id = "20260904-r51"' in entry
assert local["version"] == package["version"] == "1.12.5"
assert "v1.12.5" in package["history"]
