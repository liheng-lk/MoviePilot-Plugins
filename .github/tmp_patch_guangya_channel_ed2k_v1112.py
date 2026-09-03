from pathlib import Path
import json

ROOT = Path('.')
PLUGIN = ROOT / 'plugins.v3/guangyatransferassistant'
planner_path = PLUGIN / 'resource_planner_v190.py'
text = planner_path.read_text(encoding='utf-8')

old = '''        # Magnet 往往是整季/更新包，只有 resolve 后才能知道内部文件；先让它尝试覆盖当前未覆盖缺集。\n        if str(source.get("type") or "") == "magnet":\n            return set(uncovered)\n        return set()\n'''
new = '''        # Magnet/ED2K 都允许先进入光鸭 resolve：\n        # - Magnet 常见整季/更新包，需要解析内部文件后才能确认缺集；\n        # - ED2K 是单文件链接，频道标题或文件名可能不带可直接识别的集号，\n        #   但 resolve 后的真实文件名仍可安全确认。这里只做“待解析候选”，\n        #   最终集号仍必须在 _resolve_offline_source 中回填并通过缺集门禁。\n        if str(source.get("type") or "") in {"magnet", "ed2k"}:\n            return set(uncovered)\n        return set()\n'''
if old not in text:
    raise SystemExit('candidate fallback block not found')
text = text.replace(old, new, 1)

needle = '''        selection = self._planner_file_selection(source, subscribe, data)\n        indexes = list(selection.get("indexes") or [])\n        subfiles = bt_info.get("subfiles") if isinstance(bt_info, dict) else None\n'''
insert = '''        selection = self._planner_file_selection(source, subscribe, data)\n        indexes = list(selection.get("indexes") or [])\n        subfiles = bt_info.get("subfiles") if isinstance(bt_info, dict) else None\n\n        # ED2K 通常是“单文件云添加”，resolve_res 不一定返回 btResInfo.subfiles。\n        # 旧逻辑在这种情况下会创建任务，但 resolved_episodes 为空；完成后无法把该集\n        # 写回 MoviePilot，也可能让后续扫描再次命中同一集。现在用真实 resolve 文件名\n        # + 频道 episode_hint 做最后一次高置信集号确认，并把实际命中的缺集回填。\n        source_type = str(source.get("type") or "").strip().lower()\n        no_subfiles = not (isinstance(subfiles, list) and subfiles)\n        if source_type == "ed2k" and not self._is_movie_subscription(subscribe) and no_subfiles:\n            season_hint = getattr(subscribe, "season", None)\n            episode_hint = str(source.get("episode_hint") or "").strip()\n            actual_names = []\n            for value in (resolved_name, bt_info.get("fileName") if isinstance(bt_info, dict) else ""):\n                value = str(value or "").strip()\n                if value and value not in actual_names:\n                    actual_names.append(value)\n            actual_episodes = set()\n            threshold = float(self._episode_auto_confidence or AUTO_SELECT_CONFIDENCE)\n            for value in actual_names:\n                result = resolve_episode(\n                    value,\n                    package_paths=actual_names,\n                    season_hint=season_hint,\n                    episode_hint=episode_hint,\n                )\n                actual_episodes.update(reliable_episode_set(result, threshold))\n            if not actual_episodes and episode_hint:\n                hinted = resolve_episode(episode_hint, season_hint=season_hint)\n                actual_episodes.update(reliable_episode_set(hinted, 0.99))\n\n            missing_now = {\n                int(value) for value in (self._subscription_missing_episodes(subscribe) or [])\n                if int(value or 0) > 0\n            }\n            configured_target = {\n                int(value) for value in (source.get("target_episodes") or [])\n                if str(value).isdigit() and int(value) > 0\n            }\n            allowed_target = (configured_target or missing_now).intersection(missing_now)\n            matched_episodes = actual_episodes.intersection(allowed_target)\n            if not matched_episodes:\n                detail = ", ".join(actual_names[:2]) or str(source.get("name") or "ED2K 单文件")\n                raise RuntimeError(\n                    f"{_AMBIGUOUS_PREFIX}ED2K 已解析但真实文件无法确认覆盖当前缺集：{detail}"\n                )\n            selection["episodes"] = sorted(matched_episodes)\n            self._plugin_log(\n                "INFO",\n                "【光鸭转存助手】【频道云添加】ED2K 单文件解析命中缺集=%s，允许提交光鸭 cloudcollection",\n                ",".join(f"E{value:02d}" for value in sorted(matched_episodes)),\n            )\n'''
if needle not in text:
    raise SystemExit('resolve insertion point not found')
text = text.replace(needle, insert, 1)
planner_path.write_text(text, encoding='utf-8')

entry_path = PLUGIN / '__init__.py'
entry = entry_path.read_text(encoding='utf-8')
entry = entry.replace('"""光鸭转存助手 v1.11.1 运行入口。', '"""光鸭转存助手 v1.11.2 运行入口。', 1)
entry = entry.replace(
    '同时增加跨来源集级终止栅栏：秒传/分享转存/Magnet/ED2K 共用已成功集与在途集，成功一集立即终止该集其它任务。\n',
    '同时增加跨来源集级终止栅栏：秒传/分享转存/Magnet/ED2K 共用已成功集与在途集，成功一集立即终止该集其它任务。\n'
    'v1.11.2 补齐频道 ED2K 云添加：频道命中的 ED2K 单文件允许先 resolve，再用真实文件名/频道集号确认缺集并提交光鸭原生 cloudcollection。\n',
    1,
)
entry = entry.replace('plugin_version = "1.11.1"\n    build_id = "20260903-r42"', 'plugin_version = "1.11.2"\n    build_id = "20260903-r43"', 1)
entry_path.write_text(entry, encoding='utf-8')

package_path = ROOT / 'package.v3.json'
package = json.loads(package_path.read_text(encoding='utf-8'))
item = package['GuangYaTransferAssistant']
item['version'] = '1.11.2'
item['description'] = (
    '固定分流与多来源订阅助手：频道光鸭分享、Magnet/ED2K 会按同一 ResourceGroup 自动决策；'
    'ED2K 单文件可先解析真实文件名再确认缺集并调用光鸭原生云添加；迅雷秒传与全部来源继续共用集级终态和媒体身份门禁。'
)
history = dict(item.get('history') or {})
item['history'] = {
    'v1.11.2': '补齐频道 ED2K 自动云添加：频道扫描命中 ED2K 时不再只等待直接转存；允许先调用光鸭 resolve_res，用真实文件名/频道集号确认当前缺集后提交 cloudcollection，并回填 resolved_episodes，完成后立即更新订阅进度、阻止同集重复。',
    **history,
}
package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

plugin_json_path = PLUGIN / 'plugin.json'
plugin_json = json.loads(plugin_json_path.read_text(encoding='utf-8'))
plugin_json['version'] = '1.11.2'
plugin_json['description'] = item['description']
plugin_json_path.write_text(json.dumps(plugin_json, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

readme_path = PLUGIN / 'README.md'
readme = readme_path.read_text(encoding='utf-8')
section = '''## v1.11.2：频道 ED2K 自动云添加\n\n- 频道扫描同时识别光鸭分享、Magnet 与 ED2K；同一消息继续按 ResourceGroup 决策。\n- 若直接转存不能覆盖当前缺集，而频道中有合适 ED2K，插件会调用光鸭原生 `cloudcollection` 云添加。\n- ED2K 单文件允许先 `resolve_res`，再依据真实文件名和频道集号确认缺集；不确认集号则进入保护状态，不整包误存。\n- ED2K 完成后会回填实际集号并立即更新 MoviePilot 订阅进度，与迅雷秒传/直接转存/Magnet 共用同集终止栅栏。\n\n'''
if '## v1.11.2：频道 ED2K 自动云添加' not in readme:
    readme = section + readme
readme_path.write_text(readme, encoding='utf-8')

# 当前版本契约断言统一升级；历史实现文件本身不改版本标记。
for root in (ROOT / 'tests', ROOT / 'tests/v3/guangyatransferassistant'):
    for path in root.glob('test_guangya_*.py') if root.name == 'tests' else root.glob('test_*.py'):
        original = path.read_text(encoding='utf-8')
        updated = original.replace('1.11.1', '1.11.2').replace('20260903-r42', '20260903-r43')
        if updated != original:
            path.write_text(updated, encoding='utf-8')

# 新增核心回归：保证 ED2K 能进入 resolve-first 云添加，并把真实单文件集号回填。
test_path = ROOT / 'tests/test_guangya_channel_ed2k_v1112.py'
test_path.write_text('''from __future__ import annotations\n\nimport json\nimport unittest\nfrom pathlib import Path\n\nROOT = Path(__file__).resolve().parents[1]\nPLUGIN = ROOT / "plugins.v3/guangyatransferassistant"\n\n\nclass GuangYaChannelEd2kV1112Tests(unittest.TestCase):\n    def test_ed2k_channel_candidate_gets_resolve_first_chance(self):\n        text = (PLUGIN / "resource_planner_v190.py").read_text(encoding="utf-8")\n        method = text.split("    def _candidate_target_episodes(", 1)[1].split("    def _save_resource_plan", 1)[0]\n        self.assertIn('{"magnet", "ed2k"}', method)\n        self.assertIn('return set(uncovered)', method)\n\n    def test_single_file_ed2k_backfills_real_episode_before_cloud_create(self):\n        text = (PLUGIN / "resource_planner_v190.py").read_text(encoding="utf-8")\n        method = text.split("    def _resolve_offline_source(", 1)[1].split("    def _mark_offline_failure", 1)[0]\n        self.assertIn('source_type == "ed2k"', method)\n        self.assertIn('no_subfiles', method)\n        self.assertIn('resolve_episode(', method)\n        self.assertIn('matched_episodes = actual_episodes.intersection(allowed_target)', method)\n        self.assertIn('selection["episodes"] = sorted(matched_episodes)', method)\n        self.assertIn('【频道云添加】', method)\n        self.assertIn('ED2K 已解析但真实文件无法确认覆盖当前缺集', method)\n\n    def test_release_metadata_is_v1112(self):\n        entry = (PLUGIN / "__init__.py").read_text(encoding="utf-8")\n        package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]\n        local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))\n        self.assertEqual(package["version"], "1.11.2")\n        self.assertEqual(local["version"], "1.11.2")\n        self.assertIn('plugin_version = "1.11.2"', entry)\n        self.assertIn('build_id = "20260903-r43"', entry)\n        self.assertIn('v1.11.2', package.get("history") or {})\n\n\nif __name__ == "__main__":\n    unittest.main()\n''', encoding='utf-8')
