from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
OLD_BUILD = "20260905-r61"
NEW_BUILD = "20260906-r62"

DESCRIPTION = (
    "更新日历驱动的固定分流助手：5 分钟频道 Push 被动消费并补偿复核 7 天频道缓存；当天应播 TV/动漫每 10 分钟快速追更；电影每 60 分钟复查。"
    "v1.12.15 修复两类频道资源空窗：既有订阅在首次游标/bootstrap/重启未形成新事件时，会从 7 天缓存补偿进入 channel_event；新增订阅则固定先强刷全部配置频道并写入本地缓存，再做资源匹配。"
    "若新增订阅强刷后仍未命中且频道健康，会按配置 history_pages 有界回溯游标之前的频道历史，仅把解析结果补入 7 天 cache，不推进/回退 channel_cursors，也不把旧消息伪造成新事件。"
    "所有频道路径均不主动访问 GYING、不消耗外部检索冷却；v1.12.14 的 MoviePilot library/logical/reservation/source-claim 缺集硬栅栏、真实 payload 身份门禁和不可分割物理文件 episodes ⊆ allowed missing 全部保持。"
    "来源优先级仍为观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K，Magnet/ED2K 使用光鸭原生 cloudcollection。"
)

HISTORY = (
    "修复“频道有资源但没有转存”的两类触发空窗。其一，严格 Telegram 游标继续只判定本轮新增消息，但 5 分钟频道 Push 会同时被动复核 7 天缓存；首次游标 bootstrap、插件重启或一次性事件未形成时，只有活跃固定分流订阅仍有真实未覆盖缺口且缓存实际含光鸭分享、迅雷、Magnet 或 ED2K，才补偿进入 channel_event。"
    "其二，新增订阅不再先读旧缓存再补一次增量刷新，而是固定先强刷全部配置频道、等待单飞刷新完成、写入 7 天 cache 后再匹配；若仍未命中且频道健康，则按配置 history_pages 有界回溯当前 Telegram cursor 之前的历史页，复用既有频道解析器并只补 cache，不修改 channel_cursors、不生成 _channel_new_entries，也不把历史资源伪装成新消息。"
    "频道失败/退避时跳过额外历史回溯，并明确区分‘本地缓存未命中’与‘频道没有资源’。title-only、stale、集号不覆盖、已入库/已完成/reservation/其它 source claim 已覆盖的订阅均不触发；全链不访问 GYING、不消耗外部检索冷却，最终继续服从 v1.12.14 的真实 payload 身份门禁、MoviePilot 权威缺口与不可分割物理文件 episodes ⊆ allowed missing。来源优先级和光鸭原生 cloudcollection 路线不变。"
)

INIT_OLD = (
    "v1.12.15 修复频道已有资源但未触发转存：严格 Telegram 游标首次 bootstrap、插件重启或一次性事件未形成时，5 分钟频道 Push 会被动复核 7 天缓存；"
    "仅对仍有真实未覆盖缺口且缓存匹配条目实际含光鸭分享、迅雷、Magnet 或 ED2K 的订阅补偿进入 channel_event；"
    "不主动访问 GYING、不消耗外部检索冷却，v1.12.14 的媒体身份、权威缺集与物理文件硬栅栏全部保持。"
)
INIT_NEW = (
    "v1.12.15 修复频道已有资源但未触发转存：既有订阅在严格 Telegram 游标 bootstrap、插件重启或一次性事件未形成时由 7 天缓存补偿；"
    "新增订阅固定先强刷全部配置频道、写入缓存后再匹配，若仍未命中且频道健康则按 history_pages 有界回溯当前游标之前的历史页，只补 cache、不修改 channel_cursors、不伪造新事件；"
    "所有频道路径均不主动访问 GYING、不消耗外部检索冷却，v1.12.14 的媒体身份、权威缺集与物理文件硬栅栏全部保持。"
)


def replace_build_markers() -> int:
    roots = [PLUGIN, ROOT / "tests", ROOT / "docs"]
    changed = 0
    for base in roots:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".py", ".md", ".json"}:
                continue
            text = path.read_text(encoding="utf-8")
            if OLD_BUILD not in text:
                continue
            path.write_text(text.replace(OLD_BUILD, NEW_BUILD), encoding="utf-8")
            changed += 1
    return changed


def update_entry() -> None:
    path = PLUGIN / "__init__.py"
    text = path.read_text(encoding="utf-8")
    if INIT_OLD not in text:
        raise SystemExit("v1.12.15 entry history anchor missing")
    text = text.replace(INIT_OLD, INIT_NEW, 1)
    if f'build_id = "{NEW_BUILD}"' not in text:
        raise SystemExit("final entry build marker missing after build migration")
    path.write_text(text, encoding="utf-8")


def update_plugin_json() -> None:
    path = PLUGIN / "plugin.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != "1.12.15":
        raise SystemExit(f"unexpected plugin version: {data.get('version')}")
    data["description"] = DESCRIPTION
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def update_package() -> None:
    path = ROOT / "package.v3.json"
    package = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=OrderedDict)
    row = package.get("GuangYaTransferAssistant")
    if not isinstance(row, dict) or row.get("version") != "1.12.15":
        raise SystemExit("GuangYaTransferAssistant package row is not v1.12.15")
    row["description"] = DESCRIPTION
    labels = [value.strip() for value in str(row.get("labels") or "").split(",") if value.strip()]
    for value in ("新增订阅预热", "频道历史回溯"):
        if value not in labels:
            labels.append(value)
    row["labels"] = ",".join(labels)
    history = OrderedDict(row.get("history") or {})
    if "v1.12.15" not in history:
        raise SystemExit("v1.12.15 package history missing")
    history["v1.12.15"] = HISTORY
    row["history"] = history
    path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def update_release_doc() -> None:
    path = ROOT / "docs" / "guangyatransferassistant-v11215-channel-reconcile.md"
    text = path.read_text(encoding="utf-8")
    marker = "## 发布测试\n"
    addition = (
        "## 新订阅频道预热\n\n"
        "新增订阅固定执行 `强刷全部配置频道 -> 等待单飞刷新完成 -> 写入 7 天 cache -> 匹配新订阅`。"
        "若增量刷新后仍未命中且频道健康，再按配置 `history_pages` 有界回溯当前 Telegram cursor 之前的历史页。"
        "回溯复用既有频道解析器，只调用 cache 写入，不修改 `channel_cursors`，也不生成 `_channel_new_entries_v1115`，因此旧消息不会被伪造成新事件。"
        "频道失败或退避时不绕过 Reliability 继续历史抓取，并明确记录‘本地缓存未命中’不等于‘频道没有资源’。\n\n"
    )
    if "## 新订阅频道预热" not in text:
        if marker not in text:
            raise SystemExit("release doc test section missing")
        text = text.replace(marker, addition + marker, 1)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    count = replace_build_markers()
    if count < 2:
        raise SystemExit(f"expected multiple r61 build markers, changed {count}")
    update_entry()
    update_plugin_json()
    update_package()
    update_release_doc()
    print(f"migrated {count} files from {OLD_BUILD} to {NEW_BUILD}")


if __name__ == "__main__":
    main()
