from __future__ import annotations

import json
from pathlib import Path

ROOT = Path('.')
PLUGIN = ROOT / 'plugins.v3' / 'guangyatransferassistant'
ENTRY = PLUGIN / '__init__.py'
LOCAL = PLUGIN / 'plugin.json'
PACKAGE = ROOT / 'package.v3.json'
README = PLUGIN / 'README.md'

VERSION = '1.12.13'
BUILD = '20260905-r59'
DESC = (
    '更新日历驱动的固定分流助手：5 分钟频道 Push 被动消费；当天应播 TV/动漫每 10 分钟快速追更；电影每 60 分钟复查。'
    'v1.12.13 修复媒体库已有剧集仍被迅雷秒传重复导入：TV 迅雷开始前读取 MoviePilot 媒体库真实缺集，最终允许集严格取“媒体库 missing ∩ 成功事实/订阅 missing - reservation - active claim”；'
    '生成 JSON 后在真正 batch import 前再次逐视频复核，任何文件只要包含已入库/已完成集就整文件拒绝，跨边界多集文件也不冒险导入；媒体库事实读取失败时本轮仅跳过迅雷并继续后续来源。'
    '电影路径、迅雷 JSON 1.1.3 与既有媒体身份/质量/Episode Fence/跨季栅栏保持不变；来源优先级仍为观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K。'
)
HISTORY = (
    '修复实机“媒体库已有 E01-E09、频道刚补 E10 后，迅雷仍秒传 E01-E06”的重复写入：旧链虽调用媒体库同步却丢弃其 missing 返回，随后仅依赖 cooperative 缺集状态，'
    '在媒体库与刚完成回执刷新不同步时可能把旧集重新放回迅雷 target。v1.12.13 将 TV 迅雷最终允许集固定为 library missing ∩ logical/fact missing，再扣除 reservation 与 active source claim；'
    'JSON batch import 前按真实文件集号二次硬过滤，E09-E11 这类同时覆盖已有与缺失集的多集文件整文件拒绝；若 MoviePilot 媒体库缺集事实读取失败则 fail closed 跳过迅雷、继续光鸭直接转存/Magnet/ED2K。'
    '电影、JSON 1.1.3 和既有全部安全门禁不变；来源优先级仍为观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K。'
)

# ---- final runtime metadata ----
entry = ENTRY.read_text(encoding='utf-8')
entry = entry.replace('光鸭转存助手 v1.12.12 运行入口', '光鸭转存助手 v1.12.13 运行入口', 1)
old_meta = '    plugin_version = "1.12.12"\n    build_id = "20260905-r58"'
new_meta = f'    plugin_version = "{VERSION}"\n    build_id = "{BUILD}"'
if old_meta not in entry:
    raise SystemExit('final runtime v1.12.12/r58 marker not found')
entry = entry.replace(old_meta, new_meta, 1)
if 'v1.12.13 修复媒体库已有剧集仍被迅雷秒传重复导入' not in entry:
    lines = entry.splitlines()
    insert_at = None
    for index, line in enumerate(lines):
        if line.startswith('v1.12.12 '):
            insert_at = index + 1
            break
    if insert_at is None:
        raise SystemExit('v1.12.12 entry history line not found')
    lines.insert(
        insert_at,
        'v1.12.13 修复媒体库已有剧集仍被迅雷秒传重复导入：TV 迅雷硬目标改为媒体库 missing 与成功事实/订阅 missing 的交集，并在 JSON batch import 前逐视频二次过滤；跨边界多集文件整文件拒绝，媒体库缺集事实读取失败时跳过迅雷但继续后续来源。',
    )
    entry = '\n'.join(lines) + ('\n' if entry.endswith('\n') else '')
ENTRY.write_text(entry, encoding='utf-8')

# ---- local plugin manifest ----
local = json.loads(LOCAL.read_text(encoding='utf-8'))
local['description'] = DESC
local['version'] = VERSION
LOCAL.write_text(json.dumps(local, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

# ---- package index ----
package = json.loads(PACKAGE.read_text(encoding='utf-8'))
row = package['GuangYaTransferAssistant']
row['description'] = DESC
row['version'] = VERSION
labels = [value.strip() for value in str(row.get('labels') or '').split(',') if value.strip()]
for value in ('迅雷防重复', '已入库硬栅栏', '最终导入过滤'):
    if value not in labels:
        labels.append(value)
row['labels'] = ','.join(labels)
old_history = dict(row.get('history') or {})
row['history'] = {'v1.12.13': HISTORY, **{k: v for k, v in old_history.items() if k != 'v1.12.13'}}
PACKAGE.write_text(json.dumps(package, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

# ---- README ----
readme = README.read_text(encoding='utf-8')
heading = '## v1.12.13：迅雷已入库集最终硬栅栏'
if heading not in readme:
    readme += f'''\n\n{heading}\n\n- 修复实机：MoviePilot 媒体库已有 E01-E09，频道刚补 E10 后，迅雷完整包仍可能把 E01-E06 再次秒传。\n- TV 迅雷开始前必须成功读取 MoviePilot 媒体库缺集事实；允许集严格为 `library missing ∩ logical/fact missing - reservation - active claim`。\n- 两份强事实允许处于不同刷新时序，但只能通过交集继续收紧。例如媒体库给出 E10-E30、频道成功事实封住 E10，即得到 E11-E30。\n- JSON 1.1.3 仍完整生成，但真正 batch import 前再按文件级集号做一次硬过滤；视频只要包含任一非当前缺集，整文件拒绝。\n- `E09-E11` 这类横跨“已有 + 缺失”的多集文件按不可分割文件处理，不会为了 E11 顺带重复 E09/E10。\n- 若 MoviePilot 媒体库缺集事实无法读取，本轮只禁用迅雷秒传并继续光鸭直接转存、Magnet、ED2K，不以不确定状态冒险写入。\n- 电影路径不变；来源优先级仍为：观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K。\n'''
README.write_text(readme, encoding='utf-8')

# ---- migrate tests that assert the CURRENT public release ----
# v1.12.12 alias layer is historical and must stay r58, so its dedicated test is excluded.
exclude = {'test_gying_alias_query_v11212.py'}
paths = list((ROOT / 'tests').glob('test_guangya*.py'))
paths += list((ROOT / 'tests' / 'v3' / 'guangyatransferassistant').glob('test_*.py'))
for path in paths:
    if path.name in exclude:
        continue
    text = path.read_text(encoding='utf-8')
    updated = text.replace('"1.12.12"', '"1.12.13"').replace("'1.12.12'", "'1.12.13'")
    updated = updated.replace('20260905-r58', BUILD)
    if updated != text:
        path.write_text(updated, encoding='utf-8')

# Dedicated release marker locks the exact bug and the historical layers.
release_test = ROOT / 'tests' / 'v3' / 'guangyatransferassistant' / 'test_release_v11213_marker.py'
release_test.write_text('''from __future__ import annotations\n\nimport ast\nimport json\nfrom pathlib import Path\n\nROOT = Path(__file__).resolve().parents[3]\nPLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"\nENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")\nFENCE = (PLUGIN / "xunlei_existing_fence_v11213.py").read_text(encoding="utf-8")\nALIAS = (PLUGIN / "gying_alias_query_v11212.py").read_text(encoding="utf-8")\nLOCAL = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))\nPACKAGE = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]\n\n\ndef test_v11213_public_release_is_single_truth():\n    assert LOCAL["version"] == PACKAGE["version"] == "1.12.13"\n    assert 'plugin_version = "1.12.13"' in ENTRY\n    assert 'build_id = "20260905-r59"' in ENTRY\n    assert "v1.12.13" in PACKAGE["history"]\n\n\ndef test_v11213_hard_fence_is_nested_without_moving_top_level_mro():\n    ast.parse(FENCE)\n    assert 'plugin_version = "1.12.13"' in FENCE\n    assert 'build_id = "20260905-r59"' in FENCE\n    assert "GuangYaXunleiExistingEpisodeFenceV11213Mixin" not in ENTRY.split("class GuangYaTransferAssistant(", 1)[1].split("):", 1)[0]\n    assert "from .xunlei_existing_fence_v11213 import GuangYaXunleiExistingEpisodeFenceV11213Mixin" in (PLUGIN / "manual_check_v11211.py").read_text(encoding="utf-8")\n\n\ndef test_v11213_keeps_v11212_alias_layer_historical_marker():\n    assert 'plugin_version = "1.12.12"' in ALIAS\n    assert 'build_id = "20260905-r58"' in ALIAS\n\n\ndef test_v11213_release_documents_fail_closed_and_final_import_filter():\n    history = PACKAGE["history"]["v1.12.13"]\n    assert "library missing" in history\n    assert "logical/fact missing" in history\n    assert "batch import" in history\n    assert "fail closed" in history\n    assert "E09-E11" in history\n\n\ndef test_v11213_source_priority_is_unchanged():\n    text = LOCAL["description"] + PACKAGE["description"]\n    assert "观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K" in text\n''', encoding='utf-8')

print('GuangYaTransferAssistant release migration prepared:', VERSION, BUILD)
