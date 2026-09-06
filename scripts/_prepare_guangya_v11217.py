from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
OLD_VERSION = "1.12.16"
OLD_BUILD = "20260906-r63"
NEW_VERSION = "1.12.17"
NEW_BUILD = "20260906-r64"

HISTORY_TEXT = (
    "v1.12.17 重构资源召回：参考 MoviePilot 的结构化 release title + canonical identity 消歧，以及 Telegram/PanSou 的频道关键词定向搜索；"
    "GYING 最多生成 8 档官方别名检索词，主动检查在频道缓存未命中时对配置频道执行最多 4 档 ?q= 定向搜索并有界并发；"
    "READNFO/语言/清晰度/来源/编码/发布组等只在召回阶段作为噪声剥离，明确 TMDB/年份/季冲突仍硬拒绝，无年份第二别名必须由 MoviePilot 识别为同一 canonical identity；"
    "定向搜索只补既有 7 天 cache/index，不推进 channel_cursors、不伪造新事件，5 分钟 channel_event 仍完全被动；"
    "v1.12.13~v1.12.16 的真实 payload 身份、权威缺集、reservation/source claim 与不可分割物理文件最终门禁全部保持。\n"
)


def update_entry() -> None:
    path = PLUGIN / "__init__.py"
    text = path.read_text(encoding="utf-8")
    text = text.replace('"""光鸭转存助手 v1.12.16 运行入口。', '"""光鸭转存助手 v1.12.17 运行入口。', 1)
    anchor = "v1.12.16 修复电影双语真实资源被身份门禁误杀："
    if anchor not in text:
        raise RuntimeError("entry v1.12.16 history anchor missing")
    if HISTORY_TEXT not in text:
        pos = text.index(anchor)
        start = text.rfind("\n", 0, pos) + 1
        text = text[:start] + HISTORY_TEXT + text[start:]
    marker = "class GuangYaTransferAssistant("
    head, tail = text.split(marker, 1)
    if f'plugin_version = "{OLD_VERSION}"' not in tail or f'build_id = "{OLD_BUILD}"' not in tail:
        raise RuntimeError("final runtime version/build anchor missing")
    tail = tail.replace(f'plugin_version = "{OLD_VERSION}"', f'plugin_version = "{NEW_VERSION}"', 1)
    tail = tail.replace(f'build_id = "{OLD_BUILD}"', f'build_id = "{NEW_BUILD}"', 1)
    path.write_text(head + marker + tail, encoding="utf-8")


def update_plugin_json() -> None:
    path = PLUGIN / "plugin.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["version"] = NEW_VERSION
    data["description"] = (
        "更新日历驱动的固定分流助手。v1.12.17 重构资源召回：GYING 使用官方别名多档检索，"
        "主动检查在频道缓存未命中时对配置 Telegram 频道执行有界 ?q= 定向搜索；release title 先结构化剥离 READNFO、语言、清晰度、来源、编码和发布组噪声，"
        "无年份第二别名必须经 MoviePilot canonical identity 消歧。明确 TMDB/年份/季冲突继续拒绝，频道定向搜索不推进游标、不伪造新事件，5 分钟频道 Push 仍被动。"
        "v1.12.13~v1.12.16 的真实 payload 身份、权威缺集与物理文件硬栅栏保持；来源优先级仍为观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K。"
    )
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def update_package() -> None:
    path = ROOT / "package.v3.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    item = data["GuangYaTransferAssistant"]
    item["version"] = NEW_VERSION
    item["description"] = (
        "更新日历驱动的固定分流助手：频道/观影统一支持光鸭分享、迅雷分享、Magnet、ED2K。"
        "v1.12.17 增加结构化 release title 召回、官方别名多档 GYING 检索及 Telegram 频道 ?q= 定向搜索；"
        "无年份歧义别名需 MoviePilot canonical identity 复核，明确 TMDB/年份/季冲突和最终真实 payload/缺集/物理文件安全门禁不放宽。"
        "来源优先级：观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K。"
    )
    history = dict(item.get("history") or {})
    history["v1.12.17"] = (
        "重构资源/频道召回：参考 MoviePilot 结构化资源匹配与同作品消歧，GYING 最多生成 8 档 canonical query；"
        "主动检查在频道 cache 未命中时对配置频道执行最多 4 档 Telegram ?q= 定向搜索并有界并发，结果只补 7 天 cache/index、不推进 channel_cursors、不伪造频道新事件；"
        "READNFO/语言/清晰度/来源/编码/发布组等仅作为召回噪声剥离，明确 TMDB/年份/季冲突仍拒绝，无年份第二别名必须经 MoviePilot 识别为同一 canonical identity；"
        "5 分钟 channel_event 继续被动，v1.12.13~v1.12.16 的已入库防重、真实 payload 身份、reservation/source claim 与不可分割物理文件最终栅栏完全保留。"
    )
    item["history"] = {"v1.12.17": history.pop("v1.12.17"), **history}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def update_readme() -> None:
    path = PLUGIN / "README.md"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    if "## v1.12.17" in text:
        return
    section = """## v1.12.17 - 结构化资源召回与频道定向搜索

- GYING 使用订阅/TMDB 官方标题、英文名、原名生成最多 8 档有界查询，不再只依赖单一中文展示名。
- 搜索候选先解析 release title，剥离 READNFO、语言、分辨率、来源、编码、字幕和发布组等技术噪声；明确年份、季号或 canonical ID 冲突仍直接拒绝。
- 无年份且只靠第二别名命中的同名候选必须再由 MoviePilot `recognize_by_meta` 确认为同一 TMDB/IMDb 作品，并缓存消歧结果。
- 新订阅、人工检查和主动 Pull 在频道缓存未命中时，对配置 Telegram 频道执行最多 4 档 `?q=` 定向搜索；多频道有界并发，成功/失败分别冷却，避免搜索风暴。
- 定向搜索只补既有 7 天频道 cache/index，不修改 `channel_cursors`，不把历史帖子伪造成新事件；5 分钟 `channel_event` 仍完全被动。
- 最终写盘继续执行 v1.12.13~v1.12.16 的真实 payload 身份、权威缺集、reservation/source claim 与不可分割物理文件硬栅栏；来源优先级不变。

"""
    path.write_text(section + text, encoding="utf-8")


def migrate_current_release_assertions() -> None:
    # 只迁移引用“当前入口/市场元数据”的断言。历史层源码的 v1.12.16/r63 必须保留。
    for path in (ROOT / "tests").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        out = []
        changed = False
        for line in text.splitlines(keepends=True):
            stripped = line.strip()
            current_ref = (
                "assert" in stripped
                and any(token in line for token in (
                    "ENTRY", "entry_text", "entry", "PLUGIN_JSON", "plugin_json", "package[", "PACKAGE[",
                    "plugin[", "local[", "LOCAL[", "package.get", "plugin.get"
                ))
            )
            if current_ref:
                new_line = line.replace(OLD_VERSION, NEW_VERSION).replace(OLD_BUILD, NEW_BUILD)
                changed = changed or new_line != line
                line = new_line
            out.append(line)
        if changed:
            path.write_text("".join(out), encoding="utf-8")

    # v1.12.16 marker 第一条描述的是“当前公开真值”，其余两条验证历史桥与安全层，保留旧版本语义。
    marker = ROOT / "tests/v3/guangyatransferassistant/test_release_v11216_marker.py"
    if marker.exists():
        text = marker.read_text(encoding="utf-8")
        text = text.replace("def test_v11216_public_release_truth_is_consistent():", "def test_v11217_public_release_truth_promotes_v11216_history():")
        marker.write_text(text, encoding="utf-8")

    # 新发布合同：当前版本之外，再确认新召回层确实接入且安全边界可见。
    release_test = ROOT / "tests/v3/guangyatransferassistant/test_release_v11217_marker.py"
    release_test.write_text(
        '''from __future__ import annotations\n\nimport json\nfrom pathlib import Path\n\nROOT = Path(__file__).resolve().parents[3]\nPLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"\nENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")\nRECALL = (PLUGIN / "search_recall_v11217.py").read_text(encoding="utf-8")\nBRIDGE = (PLUGIN / "movie_bilingual_identity_v11216.py").read_text(encoding="utf-8")\nPLUGIN_JSON = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))\nPACKAGE = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))\n\n\ndef test_v11217_public_release_truth_is_consistent():\n    assert 'plugin_version = "1.12.17"' in ENTRY\n    assert 'build_id = "20260906-r64"' in ENTRY\n    assert PLUGIN_JSON["version"] == "1.12.17"\n    assert PACKAGE["GuangYaTransferAssistant"]["version"] == "1.12.17"\n    assert "v1.12.17" in PACKAGE["GuangYaTransferAssistant"]["history"]\n    assert "v1.12.16" in PACKAGE["GuangYaTransferAssistant"]["history"]\n\n\ndef test_v11217_recall_is_nested_without_replacing_v11216_final_identity_bridge():\n    assert "from .search_recall_v11217 import GuangYaSearchRecallV11217Mixin" in BRIDGE\n    assert "class GuangYaMovieBilingualIdentityV11216Mixin(GuangYaSearchRecallV11217Mixin):" in BRIDGE\n    assert 'plugin_version = "1.12.16"' in BRIDGE\n    assert 'build_id = "20260906-r63"' in BRIDGE\n\n\ndef test_v11217_is_wide_recall_strict_write_and_passive_tick_safe():\n    assert "_release_title_candidates_v11217" in RECALL\n    assert "_same_work_disambiguation_v11217" in RECALL\n    assert "recognize_by_meta" in RECALL\n    assert "_targeted_channel_search_v11217" in RECALL\n    assert "channel_event" in RECALL\n    assert "channel_cursors" in RECALL\n    assert "DownloadChain" not in RECALL\n    assert "cloudcollection/v1/create_task" not in RECALL\n    assert "rapid_transfer" not in RECALL\n    assert "观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K" in ENTRY\n''',
        encoding="utf-8",
    )


def main() -> None:
    update_entry()
    update_plugin_json()
    update_package()
    update_readme()
    migrate_current_release_assertions()


if __name__ == "__main__":
    main()
