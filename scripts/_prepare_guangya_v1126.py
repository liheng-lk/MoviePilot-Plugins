from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


# Runtime entry: add the outer fast-recall mixin and publish version.
entry_path = PLUGIN / "__init__.py"
entry = entry_path.read_text(encoding="utf-8")
entry = entry.replace('光鸭转存助手 v1.12.5 运行入口。', '光鸭转存助手 v1.12.6 运行入口。', 1)
if 'v1.12.6 快速追更' not in entry:
    marker = 'v1.12.5 完成 Push/Pull 调度收口：5 分钟频道 Push 只消费已到达资源；每小时 AiringDue 只处理今日到期且仍未覆盖的媒体，并按观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K 跑完整来源链；同媒体小时复查窗口固定 60 分钟；04:10 每日全员复核继续先频道、再对真实剩余缺口强制补漏；稳定星期、日历故障退避、并发 trigger 与跨来源终止栅栏同步收口。\n'
    entry = entry.replace(marker, marker + 'v1.12.6 快速追更：当天应播 TV/动漫的 AiringDue 改为每 10 分钟唤醒并使用独立 10 分钟主动检索窗口；电影继续 60 分钟；命中、已入库或在途后立即退出快追。\n', 1)
import_line = 'from .fast_recall_v1126 import GuangYaFastRecallV1126Mixin\n'
if import_line not in entry:
    entry = entry.replace('from .episode_fence_final_v1124 import GuangYaEpisodeFenceFinalV1124Mixin\n', 'from .episode_fence_final_v1124 import GuangYaEpisodeFenceFinalV1124Mixin\n' + import_line, 1)
if '    GuangYaFastRecallV1126Mixin,\n' not in entry:
    entry = entry.replace('    GuangYaPagePerfV1123Mixin,\n', '    GuangYaPagePerfV1123Mixin,\n    GuangYaFastRecallV1126Mixin,\n', 1)
entry = entry.replace('    plugin_version = "1.12.5"\n    build_id = "20260904-r51"', '    plugin_version = "1.12.6"\n    build_id = "20260904-r52"', 1)
write(entry_path, entry)

# Local plugin metadata.
plugin_json = PLUGIN / "plugin.json"
local = json.loads(plugin_json.read_text(encoding="utf-8"))
local["version"] = "1.12.6"
local["description"] = (
    "更新日历驱动的固定分流助手：5 分钟频道 Push 只消费已到达资源；当天应播 TV/动漫由 AiringDue 每 10 分钟快速追更，"
    "每轮仍严格经过真实缺集、reservation/source claim 与终止栅栏，并按观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K 执行完整来源链；"
    "电影继续 60 分钟主动复查；非更新日剧集不主动访问外部资源站；04:10 每日全员复核继续兜底。"
)
write(plugin_json, json.dumps(local, ensure_ascii=False, indent=2) + "\n")

# Repository package index.
package_path = ROOT / "package.v3.json"
package = json.loads(package_path.read_text(encoding="utf-8"))
item = package["GuangYaTransferAssistant"]
item["version"] = "1.12.6"
item["description"] = local["description"]
labels = str(item.get("labels") or "")
for label in ("10分钟追更", "快速追更"):
    if label not in labels.split(","):
        labels = labels + ("," if labels else "") + label
item["labels"] = labels
history = dict(item.get("history") or {})
message = (
    "修复新剧集资源已经快速发布但插件最长接近 60 分钟才再次检索的问题：AiringDue 从每小时改为每 10 分钟唤醒；"
    "TV/动漫 airing_pull 使用独立 10 分钟外部检索窗口，电影仍维持 60 分钟；是否真正访问外部来源仍严格由 due_uncovered、"
    "reservation、source claim、episode fence 与媒体库完成事实决定，因此非更新日、已入库和在途订阅不会因高频时钟产生搜索；"
    "GYING 120 秒短缓存小于快追窗口，下一轮会重新获取站点结果；来源优先级保持观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K。"
)
item["history"] = {"v1.12.6": message, **{k: v for k, v in history.items() if k != "v1.12.6"}}
write(package_path, json.dumps(package, ensure_ascii=False, indent=2) + "\n")

# README release note.
readme_path = PLUGIN / "README.md"
readme = readme_path.read_text(encoding="utf-8")
section = '''## v1.12.6：当天更新剧 10 分钟快速追更\n\n- AiringDue 从每 60 分钟唤醒改为每 10 分钟唤醒，缩短资源刚发布后的发现延迟。\n- 只有 TV/动漫的 `airing_pull` 使用 10 分钟检索窗口；电影继续 60 分钟。\n- 10 分钟只是调度时钟，真正搜索仍要求当前存在 `due_uncovered`，且没有 reservation/source claim；已入库、已在途和非更新日不会打外部资源站。\n- GYING 同查询缓存只有 120 秒，小于快追窗口；上一轮没资源不会把下一轮锁在旧空结果里。\n- 来源顺序不变：观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K。\n- 5 分钟频道 Push 仍只消费已到达频道资源，不借频道 tick 主动访问 GYING。\n\n'''
if '## v1.12.6：当天更新剧 10 分钟快速追更' not in readme:
    readme = readme.replace('# 光鸭转存助手\n\n', '# 光鸭转存助手\n\n' + section, 1)
write(readme_path, readme)

# Current-version test expectations. Historical implementation build markers stay untouched;
# only assertions against the public entry/package version are migrated.
for path in (ROOT / "tests").rglob("test_*.py"):
    text = path.read_text(encoding="utf-8")
    original = text
    text = text.replace('plugin_version = "1.12.5"', 'plugin_version = "1.12.6"')
    text = text.replace('== "1.12.5"', '== "1.12.6"')
    text = text.replace('Equal(package["version"], "1.12.5")', 'Equal(package["version"], "1.12.6")')
    text = text.replace('Equal(local["version"], "1.12.5")', 'Equal(local["version"], "1.12.6")')
    # Entry build assertions use r52. Do not touch tests that explicitly inspect FINAL/PATCH historical mixins.
    if ('ENTRY' in text or 'entry' in text or 'self.entry' in text) and 'FINAL' not in text and 'PATCH' not in text:
        text = text.replace('build_id = "20260904-r51"', 'build_id = "20260904-r52"')
    if text != original:
        write(path, text)

# Dedicated v1.12.6 contract tests.
test_path = ROOT / "tests" / "v3" / "guangyatransferassistant" / "test_fast_recall_v1126.py"
write(test_path, '''from pathlib import Path\n\nROOT = Path(__file__).resolve().parents[3]\nPLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"\nENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")\nFAST = (PLUGIN / "fast_recall_v1126.py").read_text(encoding="utf-8")\nFINAL = (PLUGIN / "dispatch_policy_final_v1125.py").read_text(encoding="utf-8")\nDISPATCH = (PLUGIN / "dispatch_policy_v1125.py").read_text(encoding="utf-8")\n\n\ndef test_fast_recall_is_outer_than_v1125_dispatch_layers():\n    assert "from .fast_recall_v1126 import GuangYaFastRecallV1126Mixin" in ENTRY\n    head = ENTRY.split("class GuangYaTransferAssistant(", 1)[1].split("):", 1)[0]\n    assert head.index("GuangYaFastRecallV1126Mixin") < head.index("GuangYaDispatchPolicyFinalV1125Mixin")\n    assert 'plugin_version = "1.12.6"' in ENTRY\n    assert 'build_id = "20260904-r52"' in ENTRY\n\n\ndef test_airing_service_wakes_every_ten_minutes():\n    assert '_fast_recall_minutes_v1126 = 10' in FAST\n    assert '"GuangYaTransferAssistantAiringDue"' in FAST\n    assert 'kwargs["minutes"] = int(self._fast_recall_minutes_v1126)' in FAST\n\n\ndef test_tv_claim_is_ten_minutes_but_movie_keeps_v1125_window():\n    assert 'self._is_movie_subscription(subscribe)' in FAST\n    assert 'return bool(super()._claim_external_search_round_v1114(subscribe, force=force))' in FAST\n    assert 'cooldown = max(60, int(self._fast_recall_minutes_v1126) * 60)' in FAST\n    assert '"origin": "airing_fast_recall_v1126"' in FAST\n    assert '_hourly_due_cooldown_seconds_v1125 = 60 * 60' in FINAL\n\n\ndef test_five_minute_channel_tick_still_never_becomes_active_gying_poll():\n    assert 'local.channel_only = True' in DISPATCH\n    assert 'if bool(getattr(local, "channel_only", False)):' in DISPATCH\n    assert 'return []' in DISPATCH\n    assert '观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K' in FAST\n''')

# Remove one-shot migration artifacts before the validated commit.
for relative in ("scripts/_prepare_guangya_v1126.py", ".github/workflows/prepare-guangya-v1126.yml"):
    path = ROOT / relative
    if path.exists():
        path.unlink()
