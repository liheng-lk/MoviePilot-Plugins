from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
CURRENT_VERSION = "1.12.16"
CURRENT_BUILD = "20260906-r63"
OLD_VERSION = "1.12.15"
OLD_BUILD = "20260906-r62"


def prepare_metadata() -> None:
    entry_path = PLUGIN / "__init__.py"
    entry = entry_path.read_text(encoding="utf-8")
    entry = entry.replace('"""光鸭转存助手 v1.12.15 运行入口。', '"""光鸭转存助手 v1.12.16 运行入口。', 1)
    anchor = "v1.12.15 修复频道已有资源但未触发转存："
    if anchor not in entry:
        raise RuntimeError("v1.12.15 entry history anchor missing")
    history_line = (
        "v1.12.16 修复电影双语真实资源被身份门禁误杀：仅在观影 discovery 已命中订阅、"
        "真实分享顶层同时包含订阅标题与第二语言标题、年份精确一致且真实视频文件精确命中该第二语言标题时救回；"
        "错误电影、错误年份、纯外文无同分享桥接、电视剧仍硬拒绝，不引入模糊匹配。\n"
    )
    if history_line not in entry:
        pos = entry.index(anchor)
        line_start = entry.rfind("\n", 0, pos) + 1
        entry = entry[:line_start] + history_line + entry[line_start:]
    marker = "class GuangYaTransferAssistant("
    head, tail = entry.split(marker, 1)
    tail = tail.replace('plugin_version = "1.12.15"', 'plugin_version = "1.12.16"', 1)
    tail = tail.replace('build_id = "20260906-r62"', 'build_id = "20260906-r63"', 1)
    entry_path.write_text(head + marker + tail, encoding="utf-8")

    plugin_json = PLUGIN / "plugin.json"
    plugin = json.loads(plugin_json.read_text(encoding="utf-8"))
    plugin["version"] = CURRENT_VERSION
    plugin["description"] = (
        "更新日历驱动的固定分流助手：5 分钟频道 Push 被动消费并补偿复核 7 天频道缓存；当天应播 TV/动漫每 10 分钟快速追更；电影每 60 分钟复查。"
        "v1.12.16 修复电影双语真实资源身份误杀：仅当观影发现已命中订阅、同一真实迅雷分享顶层同时包含订阅标题与第二语言标题、年份精确一致，且真实视频文件精确命中该第二语言标题时允许救回；错误年份/错误电影/纯外文无桥接/TV 仍拒绝，不使用模糊匹配。"
        "v1.12.15 的频道缓存补偿与新增订阅先强刷配置频道、必要时有界历史回溯继续保留；v1.12.14 的 MoviePilot 权威缺集、真实 payload 身份和不可分割物理文件硬栅栏保持。"
        "来源优先级仍为观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K，Magnet/ED2K 使用光鸭原生 cloudcollection。"
    )
    plugin_json.write_text(json.dumps(plugin, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    package_path = ROOT / "package.v3.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    item = package["GuangYaTransferAssistant"]
    item["version"] = CURRENT_VERSION
    item["description"] = (
        "更新日历驱动的固定分流助手：频道/观影统一支持光鸭分享、迅雷分享、Magnet、ED2K；"
        "v1.12.16 增加严格电影双语真实资源身份桥，仅在 discovery、同分享双语顶层、年份与真实视频第二语言标题形成闭环时救回，"
        "错误电影/年份/无桥接/TV 继续拒绝；v1.12.15 新订阅频道预热与历史回溯、v1.12.14 权威缺集和物理文件硬栅栏保持。"
        "来源优先级：观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K。"
    )
    history = dict(item.get("history") or {})
    history["v1.12.16"] = (
        "修复《荣光与暗影》类电影双语真实资源被迅雷身份门禁误杀：仅在观影 discovery 已命中订阅、"
        "同一真实分享顶层同时包含订阅标题与第二语言标题、资源年份精确一致且真实视频文件精确命中第二语言标题时救回；"
        "PASS_CODE_ERROR/分享删除继续失败，错误电影/错误年份/纯外文无同分享桥接/TV 继续硬拒绝，"
        "不引入编辑距离、拼音或包含式模糊匹配；来源优先级与 v1.12.15 频道缓存、新订阅预热、v1.12.14 权威缺集/物理文件安全规则不变。"
    )
    item["history"] = {"v1.12.16": history.pop("v1.12.16"), **history}
    package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    readme_path = PLUGIN / "README.md"
    if readme_path.exists():
        readme = readme_path.read_text(encoding="utf-8")
        if "## v1.12.16" not in readme:
            readme = (
                "## v1.12.16 - 电影双语真实资源身份修复\n\n"
                "- 修复同一电影在观影/迅雷中以‘中文标题 + 第二语言标题’展示、实际视频使用第二语言标题时被误判为跨媒体的问题。\n"
                "- 仅在 discovery 命中订阅、同一真实分享形成双语闭环、年份精确一致且真实视频精确命中第二语言标题时救回。\n"
                "- 错误电影、错误年份、纯外文无同分享桥接、电视剧继续拒绝；不使用模糊标题匹配。\n"
                "- 来源优先级与 v1.12.15 频道预热、v1.12.14 防重复/缺集硬栅栏保持不变。\n\n"
                + readme
            )
            readme_path.write_text(readme, encoding="utf-8")


def migrate_assert_lines(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    out = []
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        # Only current-release assertions. Historical SOURCE/PATCH/module-marker assertions are deliberately untouched.
        current_ref = (
            "assert" in stripped
            and any(token in line for token in (
                "ENTRY", "entry_text", "entry", "package[", "PACKAGE[", "plugin[", "PLUGIN_JSON", "local[", "LOCAL["
            ))
        )
        if current_ref:
            line = line.replace(OLD_VERSION, CURRENT_VERSION).replace(OLD_BUILD, CURRENT_BUILD)
        out.append(line)
    path.write_text("".join(out), encoding="utf-8")


def migrate_contracts() -> None:
    root_files = [
        "tests/test_guangya_channel_ed2k_v1112.py",
        "tests/test_guangya_episode_fence_v1124.py",
        "tests/test_guangya_media_identity_v1111.py",
        "tests/test_guangya_release_v1110.py",
    ]
    for rel in root_files:
        path = ROOT / rel
        text = path.read_text(encoding="utf-8").replace(OLD_VERSION, CURRENT_VERSION).replace(OLD_BUILD, CURRENT_BUILD)
        path.write_text(text, encoding="utf-8")

    shuk = ROOT / "tests/v3/shukguangyadisk/test_release_v370.py"
    text = shuk.read_text(encoding="utf-8")
    text = text.replace(
        'package["GuangYaTransferAssistant"]["version"] == "1.12.15"',
        'package["GuangYaTransferAssistant"]["version"] == "1.12.16"',
    )
    shuk.write_text(text, encoding="utf-8")

    v3_files = [
        "test_airing_scheduler_v1120.py", "test_airing_weekly_v1121.py", "test_channel_reconcile_v11215.py",
        "test_command_bridge_v1128.py", "test_config_providers_v192.py", "test_content_resilience_v1105.py",
        "test_core_pipeline_v11214.py", "test_dispatch_policy_v1125.py", "test_fast_recall_v1126.py",
        "test_gying_auth_v1107.py", "test_gying_autologin_v1109.py", "test_gying_hardening_v193.py",
        "test_gying_observability_v1104.py", "test_gying_pansou_v1110.py", "test_gying_pow_v1111.py",
        "test_gying_transport_v1108.py", "test_gying_xunlei_recall_v1125.py", "test_mp_sdk_compat_v195.py",
        "test_multisource_v180_contract.py", "test_page_perf_v1123.py", "test_plugin_contract.py",
        "test_release_v1109_marker.py", "test_release_v1111_marker.py", "test_release_v11213_marker.py",
        "test_release_v1125_marker.py", "test_resource_gate_v1127.py", "test_resource_planner_v190_contract.py",
        "test_status_ui_v191.py", "test_subscribe_contract_v196.py", "test_v1100_ui_runtime.py",
        "test_v180_metadata_contract.py", "test_viewing_dispatch_v1113.py", "test_xunlei_flash_v193.py",
        "test_xunlei_hardening_v193.py",
    ]
    base = ROOT / "tests/v3/guangyatransferassistant"
    for name in v3_files:
        migrate_assert_lines(base / name)

    # One legacy test uses generic variable `text` for the final runtime entry build marker.
    compat = base / "test_episode_compat_v171.py"
    text = compat.read_text(encoding="utf-8")
    text = text.replace('assert \'build_id = "20260906-r62"\' in text', 'assert \'build_id = "20260906-r63"\' in text')
    compat.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    prepare_metadata()
    migrate_contracts()
