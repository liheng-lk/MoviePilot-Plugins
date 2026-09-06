from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
VERSION = "1.12.18"
BUILD = "20260906-r65"
HISTORY = (
    "候选排序与频道来源质量：在 v1.12.17 宽召回之后按 canonical identity、当前缺集覆盖、"
    "额外集 spillover 与真实 Telegram 终态质量对同阶段候选排序；频道质量只从 completed / failed / "
    "needs_review 派生并采用 Beta 平滑，少量样本不会压过媒体身份。迅雷优先当前缺集且夹带更少的分享，"
    "提取码只作同分信号。只改变尝试顺序，不改变观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K，"
    "v1.12.13~v1.12.16 最终真实 payload、权威缺集、reservation/source claim 与物理文件硬栅栏保持。"
)


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"{label} anchor missing: {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Final runtime public truth.
entry = PLUGIN / "__init__.py"
replace_once(entry, '"""光鸭转存助手 v1.12.17 运行入口。', '"""光鸭转存助手 v1.12.18 运行入口。', "entry doc version")
text = entry.read_text(encoding="utf-8")
release_line = (
    "v1.12.18 候选排序与来源质量：同阶段候选以 canonical identity 为主，TV 当前缺集精确覆盖优先，"
    "Telegram 频道只按真实 completed/failed/needs_review 终态做 Beta 平滑质量修正；迅雷分享减少 spillover 优先；"
    "仅调整尝试顺序，固定来源优先级与最终写盘硬栅栏全部保持。\n"
)
if release_line not in text:
    anchor = "v1.12.17 重构资源召回："
    pos = text.find(anchor)
    if pos < 0:
        raise SystemExit("entry v1.12.17 history anchor missing")
    line_end = text.find("\n", pos)
    if line_end < 0:
        raise SystemExit("entry v1.12.17 history line end missing")
    text = text[: line_end + 1] + release_line + text[line_end + 1 :]
text = text.replace('    plugin_version = "1.12.17"\n    build_id = "20260906-r64"', f'    plugin_version = "{VERSION}"\n    build_id = "{BUILD}"', 1)
entry.write_text(text, encoding="utf-8")

ranking = PLUGIN / "candidate_ranking_v11218.py"
replace_once(ranking, 'build_id = "20260906-r65-preview"', f'build_id = "{BUILD}"', "ranking build")

# Local plugin metadata.
plugin_json = PLUGIN / "plugin.json"
plugin = json.loads(plugin_json.read_text(encoding="utf-8"))
plugin["version"] = VERSION
plugin["description"] = (
    "更新日历驱动的固定分流助手。v1.12.18 在 v1.12.17 结构化宽召回基础上新增可解释候选排序："
    "canonical identity 为主，TV 优先当前缺集精确覆盖且少夹带的资源；Telegram 频道质量只从真实"
    " completed/failed/needs_review 终态派生并做 Beta 平滑，迅雷候选同样优先当前缺集且 spillover 更少的分享。"
    "仅改变同阶段尝试顺序，不改变 5 分钟频道 Push 被动语义、频道游标、最终媒体/缺集/物理文件硬栅栏；"
    "来源优先级仍为观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K。"
)
plugin_json.write_text(json.dumps(plugin, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# Marketplace metadata/history.
package_path = ROOT / "package.v3.json"
package = json.loads(package_path.read_text(encoding="utf-8"))
row = package["GuangYaTransferAssistant"]
row["version"] = VERSION
row["description"] = plugin["description"]
history = dict(row.get("history") or {})
new_history = {f"v{VERSION}": HISTORY}
new_history.update(history)
row["history"] = new_history
package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# Root contracts below describe the final public release truth, not historical
# layer versions. Migrate only these named assertions; all v1.12.17 layer/history
# markers elsewhere remain untouched.
root_contracts = ROOT / "tests"
channel_ed2k = root_contracts / "test_guangya_channel_ed2k_v1112.py"
for old, new, label in (
    ('self.assertEqual(package["version"], "1.12.17")', 'self.assertEqual(package["version"], "1.12.18")', "root channel package"),
    ('self.assertEqual(local["version"], "1.12.17")', 'self.assertEqual(local["version"], "1.12.18")', "root channel local"),
    ('self.assertIn(\'plugin_version = "1.12.17"\', entry)', 'self.assertIn(\'plugin_version = "1.12.18"\', entry)', "root channel plugin version"),
    ('self.assertIn(\'build_id = "20260906-r64"\', entry)', 'self.assertIn(\'build_id = "20260906-r65"\', entry)', "root channel build"),
):
    replace_once(channel_ed2k, old, new, label)

episode_fence = root_contracts / "test_guangya_episode_fence_v1124.py"
replace_once(
    episode_fence,
    'self.assertIn(\'build_id = "20260906-r64"\', self.entry)',
    'self.assertIn(\'build_id = "20260906-r65"\', self.entry)',
    "root episode fence build",
)

media_identity = root_contracts / "test_guangya_media_identity_v1111.py"
for old, new, label in (
    ('self.assertIn(\'plugin_version = "1.12.17"\', entry)', 'self.assertIn(\'plugin_version = "1.12.18"\', entry)', "root media plugin version"),
    ('self.assertIn(\'build_id = "20260906-r64"\', entry)', 'self.assertIn(\'build_id = "20260906-r65"\', entry)', "root media build"),
    ('self.assertEqual(package["version"], "1.12.17")', 'self.assertEqual(package["version"], "1.12.18")', "root media package"),
    ('self.assertEqual(local["version"], "1.12.17")', 'self.assertEqual(local["version"], "1.12.18")', "root media local"),
):
    replace_once(media_identity, old, new, label)

release_v1110 = root_contracts / "test_guangya_release_v1110.py"
for old, new, label in (
    ('self.assertIn(\'plugin_version = "1.12.17"\', ENTRY)', 'self.assertIn(\'plugin_version = "1.12.18"\', ENTRY)', "root release plugin version"),
    ('self.assertIn(\'build_id = "20260906-r64"\', ENTRY)', 'self.assertIn(\'build_id = "20260906-r65"\', ENTRY)', "root release build"),
    ('self.assertEqual(package["GuangYaTransferAssistant"]["version"], "1.12.17")', 'self.assertEqual(package["GuangYaTransferAssistant"]["version"], "1.12.18")', "root release package"),
    ('self.assertEqual(PLUGIN_JSON["version"], "1.12.17")', 'self.assertEqual(PLUGIN_JSON["version"], "1.12.18")', "root release local"),
):
    replace_once(release_v1110, old, new, label)

# ShukGuangYaDisk owns an explicit cross-plugin floor contract: this assertion
# protects the transfer assistant from rollback, so its expected current version
# must advance with GuangYaTransferAssistant without touching any Shuk behavior.
shuk_release_floor = ROOT / "tests" / "v3" / "shukguangyadisk" / "test_release_v370.py"
replace_once(
    shuk_release_floor,
    'assert package["GuangYaTransferAssistant"]["version"] == "1.12.17"',
    'assert package["GuangYaTransferAssistant"]["version"] == "1.12.18"',
    "shuk cross-plugin transfer assistant floor",
)

# Run 3 proved the remaining GuangYa V3 failures are exclusively stale current
# public-version/build assertions. Scope this migration to the exact failing files
# from that run; do not touch v1.12.17 feature/history contracts elsewhere.
v3_current_contract_files = {
    "test_airing_scheduler_v1120.py",
    "test_airing_weekly_v1121.py",
    "test_channel_reconcile_v11215.py",
    "test_command_bridge_v1128.py",
    "test_config_providers_v192.py",
    "test_content_resilience_v1105.py",
    "test_core_pipeline_v11214.py",
    "test_dispatch_policy_v1125.py",
    "test_episode_compat_v171.py",
    "test_fast_recall_v1126.py",
    "test_gying_auth_v1107.py",
    "test_gying_autologin_v1109.py",
    "test_gying_hardening_v193.py",
    "test_gying_observability_v1104.py",
    "test_gying_pansou_v1110.py",
    "test_gying_pow_v1111.py",
    "test_gying_transport_v1108.py",
    "test_gying_xunlei_recall_v1125.py",
    "test_mp_sdk_compat_v195.py",
    "test_multisource_v180_contract.py",
    "test_page_perf_v1123.py",
    "test_plugin_contract.py",
    "test_release_v1109_marker.py",
    "test_release_v1111_marker.py",
    "test_release_v11213_marker.py",
    "test_release_v11216_marker.py",
    "test_release_v11217_final.py",
    "test_release_v11217_marker.py",
    "test_release_v1125_marker.py",
    "test_resource_gate_v1127.py",
    "test_resource_planner_v190_contract.py",
    "test_status_ui_v191.py",
    "test_subscribe_contract_v196.py",
    "test_v1100_ui_runtime.py",
    "test_v180_metadata_contract.py",
    "test_viewing_dispatch_v1113.py",
    "test_xunlei_flash_v193.py",
    "test_xunlei_hardening_v193.py",
}
v3_contract_root = ROOT / "tests" / "v3" / "guangyatransferassistant"
for filename in sorted(v3_current_contract_files):
    path = v3_contract_root / filename
    if not path.exists():
        raise SystemExit(f"missing V3 current-release contract: {path}")
    text = path.read_text(encoding="utf-8")
    # Exact quoted bare values are current release truth in this curated failure
    # set. Historical keys use the prefixed form "v1.12.17" and therefore remain.
    text = text.replace('"1.12.17"', '"1.12.18"')
    text = text.replace('"20260906-r64"', '"20260906-r65"')
    path.write_text(text, encoding="utf-8")

# README release note immediately before v1.12.17.
readme = PLUGIN / "README.md"
text = readme.read_text(encoding="utf-8")
section = f"""## v1.12.18 - 候选排序与频道来源质量\n\n- 资源召回仍由 v1.12.17 负责；本版只优化同阶段候选的尝试顺序，不扩大搜索范围。\n- 频道候选以 canonical identity/结构化标题分为主；电视剧明确覆盖当前缺集且额外 spillover 更少者优先，缓存新鲜度只作为同分项。\n- Telegram 来源质量只从现有 SourceStore 的真实终态派生：`completed` 计成功，`failed`/`needs_review` 计失败，`new`/`queued`/`waiting` 不计入。\n- 来源质量采用 Beta(2,2) 平滑与样本权重，修正值限制在 ±18；历史样本少的频道不会因为一次成功或失败长期霸榜/垫底。\n- 迅雷候选优先明确覆盖当前 missing 且夹带额外集更少的分享，再比较 canonical identity；提取码完整只作很小的同分信号。\n- 固定来源优先级保持：观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K；Magnet/ED2K 仍只走光鸭原生 `cloudcollection`。\n- v1.12.13~v1.12.16 的真实 payload 身份、权威缺集、reservation/source claim 与不可分割物理文件最终硬栅栏全部保持。\n\n"""
if section not in text:
    anchor = "## v1.12.17 - 结构化资源召回与频道定向搜索"
    if anchor not in text:
        raise SystemExit("README v1.12.17 anchor missing")
    text = text.replace(anchor, section + anchor, 1)
readme.write_text(text, encoding="utf-8")

# Exact current-release contract for the final candidate tree.
release_test = ROOT / "tests" / "v3" / "guangyatransferassistant" / "test_release_v11218_marker.py"
release_test.write_text(
    '''from __future__ import annotations\n\nimport json\nfrom pathlib import Path\n\nROOT = Path(__file__).resolve().parents[3]\nPLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"\n\n\ndef test_v11218_public_release_truth_and_ranking_layer_are_consistent():\n    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]\n    local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))\n    entry = (PLUGIN / "__init__.py").read_text(encoding="utf-8")\n    ranking = (PLUGIN / "candidate_ranking_v11218.py").read_text(encoding="utf-8")\n    assert package["version"] == local["version"] == "1.12.18"\n    assert 'plugin_version = "1.12.18"' in entry\n    assert 'build_id = "20260906-r65"' in entry\n    assert 'build_id = "20260906-r65"' in ranking\n    assert "v1.12.18" in package.get("history", {})\n\n\ndef test_v11218_keeps_wide_recall_strict_write_and_fixed_source_priority():\n    ranking = (PLUGIN / "candidate_ranking_v11218.py").read_text(encoding="utf-8")\n    planner = (PLUGIN / "resource_planner_v190.py").read_text(encoding="utf-8")\n    bridge = (PLUGIN / "movie_bilingual_identity_v11216.py").read_text(encoding="utf-8")\n    assert "class GuangYaCandidateRankingV11218Mixin(GuangYaSearchRecallV11217Mixin):" in ranking\n    assert "class GuangYaMovieBilingualIdentityV11216Mixin(GuangYaCandidateRankingV11218Mixin):" in bridge\n    assert 'external.sort(key=lambda row: 0 if str(row.get("type") or "") == "magnet" else 1)' in planner\n    assert 'rank = 1 if source_type == "magnet" else 2' in planner\n    for forbidden in ("qbittorrent", "transmission", "cloudcollection/v1/create_task", "userres/rapid"):\n        assert forbidden not in ranking.lower()\n''',
    encoding="utf-8",
)
