from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one occurrence, got {count}: {old!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def migrate_entry() -> None:
    path = PLUGIN / "__init__.py"
    text = path.read_text(encoding="utf-8")
    text = text.replace("光鸭转存助手 v1.12.14 运行入口。", "光鸭转存助手 v1.12.15 运行入口。", 1)
    anchor = (
        "v1.12.14 统一核心资源链：频道/观影均支持光鸭分享、迅雷分享、Magnet、ED2K；TV/动漫按精确 TMDB 官方标题补召回；"
        "所有 TV 最终写盘收紧到 library missing ∩ logical/fact missing - reservation - other source claim，并对光鸭分享、迅雷、Magnet、ED2K 统一执行不可分割物理文件 episodes ⊆ allowed missing 与实际 payload 身份门禁。\n"
    )
    addition = (
        "v1.12.15 修复频道已有资源但未触发转存：严格 Telegram 游标首次 bootstrap、插件重启或一次性事件未形成时，5 分钟频道 Push 会被动复核 7 天缓存；"
        "仅对仍有真实未覆盖缺口且缓存匹配条目实际含光鸭分享、迅雷、Magnet 或 ED2K 的订阅补偿进入 channel_event；不主动访问 GYING、不消耗外部检索冷却，v1.12.14 的媒体身份、权威缺集与物理文件硬栅栏全部保持。\n"
    )
    if addition not in text:
        if anchor not in text:
            raise SystemExit("entry history anchor missing")
        text = text.replace(anchor, anchor + addition, 1)
    old = '    plugin_version = "1.12.14"\n    build_id = "20260905-r60"\n'
    new = '    plugin_version = "1.12.15"\n    build_id = "20260905-r61"\n'
    if old not in text:
        raise SystemExit("entry current marker missing")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def migrate_reconcile_layer() -> None:
    path = PLUGIN / "channel_reconcile_v11215.py"
    text = path.read_text(encoding="utf-8")
    text = text.replace("v1.12.15 候选：频道缓存被动补偿触发。", "v1.12.15：频道缓存被动补偿触发。", 1)
    text = text.replace(
        "候选阶段故意不修改最终 ``plugin_version/build_id``；只有行为测试与标准 CI 全绿后，\n"
        "才把公开版本从 v1.12.14/r60 迁移为 v1.12.15/r61。\n",
        "",
    )
    marker = (
        "class GuangYaChannelReconcileV11215Mixin(GuangYaCorePipelineFinalV11214Mixin):\n"
        "    \"\"\"让“频道已有资源”本身成为可恢复的被动事实，而不是一次性事件。\"\"\"\n"
    )
    if 'plugin_version = "1.12.15"' not in text:
        if marker not in text:
            raise SystemExit("reconcile class marker missing")
        text = text.replace(
            marker,
            marker + '\n    plugin_version = "1.12.15"\n    build_id = "20260905-r61"\n',
            1,
        )
    path.write_text(text, encoding="utf-8")


def migrate_manifests() -> None:
    description = (
        "更新日历驱动的固定分流助手：5 分钟频道 Push 被动消费并补偿复核 7 天频道缓存；当天应播 TV/动漫每 10 分钟快速追更；电影每 60 分钟复查。"
        "v1.12.15 修复频道已经存在匹配资源但首次游标/bootstrap/重启未形成“新事件”时既有订阅不转存的问题：仅对仍有真实未覆盖缺口且缓存中实际包含光鸭分享、迅雷、Magnet 或 ED2K 的订阅补偿进入 channel_event，不主动访问 GYING、不消耗外部检索冷却。"
        "v1.12.14 的四源统一、MoviePilot library/logical/reservation/source-claim 缺集硬栅栏、真实 payload 身份门禁和不可分割物理文件 episodes ⊆ allowed missing 全部保持；来源优先级仍为观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K，Magnet/ED2K 使用光鸭原生 cloudcollection。"
    )
    history = (
        "修复“频道已经有资源但既有订阅未转存”的事件空窗：严格 Telegram 游标继续只判定本轮新增消息，但 5 分钟频道 Push 同时被动复核 7 天频道缓存；首次游标 bootstrap、插件重启或一次性新事件未形成时，只要活跃固定分流订阅仍有真实未覆盖缺口，且缓存匹配条目实际含光鸭分享、迅雷、Magnet 或 ED2K，就补偿进入既有 channel_event。"
        "title-only、stale、集号不覆盖、已入库/已完成/reservation/其它 source claim 已覆盖的订阅均不触发；补偿不访问 GYING、不消耗外部检索冷却，最终仍服从 v1.12.14 的 MoviePilot 权威缺口、真实 payload 身份门禁与不可分割物理文件 episodes ⊆ allowed missing。来源优先级与光鸭原生 cloudcollection 路线不变。"
    )

    path = PLUGIN / "plugin.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["description"] = description
    data["version"] = "1.12.15"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    path = ROOT / "package.v3.json"
    package = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=OrderedDict)
    row = package["GuangYaTransferAssistant"]
    row["description"] = description
    row["version"] = "1.12.15"
    labels = [x.strip() for x in str(row.get("labels") or "").split(",") if x.strip()]
    for label in ("频道补偿", "缓存补偿"):
        if label not in labels:
            labels.append(label)
    row["labels"] = ",".join(labels)
    prior = OrderedDict(row.get("history") or {})
    merged = OrderedDict([("v1.12.15", history)])
    for key, value in prior.items():
        if key != "v1.12.15":
            merged[key] = value
    row["history"] = merged
    path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def migrate_docs() -> None:
    path = ROOT / "docs" / "guangyatransferassistant-v11215-channel-reconcile.md"
    text = path.read_text(encoding="utf-8")
    text = text.replace("# GuangYaTransferAssistant v1.12.15 候选验收", "# GuangYaTransferAssistant v1.12.15 发布验收", 1)
    text = text.replace("v1.12.15 候选只补偿被动事件触发", "v1.12.15 只补偿被动事件触发", 1)
    text = text.replace("## 候选测试", "## 发布测试", 1)
    text = text.replace(
        "公开版本在正式 PR CI 通过前继续保持 `1.12.14 / 20260905-r60`。",
        "公开版本：`1.12.15 / 20260905-r61`。",
    )
    path.write_text(text, encoding="utf-8")


def migrate_current_release_tests() -> None:
    # New v1.12.15 contract.
    path = ROOT / "tests/v3/guangyatransferassistant/test_channel_reconcile_v11215.py"
    replace_once(
        path,
        'def test_candidate_keeps_public_release_at_v11214_until_full_ci_is_green():\n'
        '    assert \'plugin_version = "1.12.14"\' in ENTRY\n'
        '    assert \'build_id = "20260905-r60"\' in ENTRY\n'
        '    assert \'"version": "1.12.14"\' in PLUGIN_JSON\n'
        '    assert \'plugin_version = "1.12.15"\' not in SOURCE\n',
        'def test_v11215_public_release_is_promoted_after_candidate_ci_is_green():\n'
        '    assert \'plugin_version = "1.12.15"\' in ENTRY\n'
        '    assert \'build_id = "20260905-r61"\' in ENTRY\n'
        '    assert \'"version": "1.12.15"\' in PLUGIN_JSON\n'
        '    assert \'plugin_version = "1.12.15"\' in SOURCE\n'
        '    assert \'build_id = "20260905-r61"\' in SOURCE\n',
    )

    # Root tests below assert the *current public release*, not the historical module marker.
    replacements = {
        "tests/test_guangya_channel_ed2k_v1112.py": [
            ('self.assertEqual(package["version"], "1.12.14")', 'self.assertEqual(package["version"], "1.12.15")'),
            ('self.assertEqual(local["version"], "1.12.14")', 'self.assertEqual(local["version"], "1.12.15")'),
            ('self.assertIn(\'plugin_version = "1.12.14"\', entry)', 'self.assertIn(\'plugin_version = "1.12.15"\', entry)'),
            ('self.assertIn(\'build_id = "20260905-r60"\', entry)', 'self.assertIn(\'build_id = "20260905-r61"\', entry)'),
        ],
        "tests/test_guangya_episode_fence_v1124.py": [
            ('self.assertIn(\'build_id = "20260905-r60"\', self.entry)', 'self.assertIn(\'build_id = "20260905-r61"\', self.entry)'),
        ],
        "tests/test_guangya_media_identity_v1111.py": [
            ('self.assertIn(\'plugin_version = "1.12.14"\', entry)', 'self.assertIn(\'plugin_version = "1.12.15"\', entry)'),
            ('self.assertIn(\'build_id = "20260905-r60"\', entry)', 'self.assertIn(\'build_id = "20260905-r61"\', entry)'),
            ('self.assertEqual(package["version"], "1.12.14")', 'self.assertEqual(package["version"], "1.12.15")'),
            ('self.assertEqual(local["version"], "1.12.14")', 'self.assertEqual(local["version"], "1.12.15")'),
        ],
        "tests/test_guangya_release_v1110.py": [
            ('self.assertIn(\'plugin_version = "1.12.14"\', ENTRY)', 'self.assertIn(\'plugin_version = "1.12.15"\', ENTRY)'),
            ('self.assertIn(\'build_id = "20260905-r60"\', ENTRY)', 'self.assertIn(\'build_id = "20260905-r61"\', ENTRY)'),
            ('self.assertEqual(package["GuangYaTransferAssistant"]["version"], "1.12.14")', 'self.assertEqual(package["GuangYaTransferAssistant"]["version"], "1.12.15")'),
            ('self.assertEqual(PLUGIN_JSON["version"], "1.12.14")', 'self.assertEqual(PLUGIN_JSON["version"], "1.12.15")'),
        ],
    }
    for rel, pairs in replacements.items():
        path = ROOT / rel
        for old, new in pairs:
            replace_once(path, old, new)


def main() -> None:
    migrate_entry()
    migrate_reconcile_layer()
    migrate_manifests()
    migrate_docs()
    migrate_current_release_tests()


if __name__ == "__main__":
    main()
