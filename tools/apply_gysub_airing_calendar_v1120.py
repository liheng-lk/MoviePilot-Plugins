from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DAILY = ROOT / "plugins.v3" / "dailyassistant"
GYA = ROOT / "plugins.v3" / "guangyatransferassistant"

DAILY_HISTORY = (
    "新增逐集上映日历提供器：通过 MoviePilot TMDB season detail 缓存整季每集 air_date，"
    "并向光鸭转存助手提供插件间只读日历；季详情不可用时回退 next_episode_to_air。"
)
GYA_HISTORY = (
    "新增每日助手/TMDB 整季逐集上映日历驱动的 due_missing 调度：普通后台仅搜索已进入提前窗口的缺集，"
    "未来集不再重复访问频道/迅雷/观影；保留每日一次全员补漏；同订阅整条来源链串行化修复外部检索冷却竞争；"
    "修复旧分享 handled=True 误阻断仍缺集的 Magnet/ED2K；GYING 关键词降级复用 120 秒缓存。"
)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"cannot locate {label}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# DailyAssistant final MRO + version
# ---------------------------------------------------------------------------
daily_entry = DAILY / "__init__.py"
text = daily_entry.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from .hardening_v110 import DailyAssistantV110Mixin\n",
    "from .hardening_v110 import DailyAssistantV110Mixin\nfrom .airing_calendar_v120 import DailyAssistantCalendarV120Mixin\n",
    "DailyAssistant calendar import",
)
text = replace_once(
    text,
    "class DailyAssistant(DailyAssistantV110Mixin, DailyAssistantV100):\n    \"\"\"v1.1.2 最终运行类。\"\"\"\n\n    plugin_version = \"1.1.2\"",
    "class DailyAssistant(DailyAssistantCalendarV120Mixin, DailyAssistantV110Mixin, DailyAssistantV100):\n    \"\"\"v1.2.0 最终运行类：榜单 + GYSub + 整季逐集上映日历。\"\"\"\n\n    plugin_version = \"1.2.0\"",
    "DailyAssistant final class",
)
daily_entry.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# GuangYaTransferAssistant final MRO + version
# ---------------------------------------------------------------------------
gya_entry = GYA / "__init__.py"
text = gya_entry.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from .media_identity_guard_v1111 import GuangYaMediaIdentityGuardV1111Mixin\n",
    "from .media_identity_guard_v1111 import GuangYaMediaIdentityGuardV1111Mixin\nfrom .airing_scheduler_v1120 import GuangYaAiringSchedulerV1120Mixin\n",
    "GuangYa airing scheduler import",
)
text = replace_once(
    text,
    "class GuangYaTransferAssistant(\n    GuangYaMediaIdentityGuardV1111Mixin,",
    "class GuangYaTransferAssistant(\n    GuangYaAiringSchedulerV1120Mixin,\n    GuangYaMediaIdentityGuardV1111Mixin,",
    "GuangYa final MRO",
)
text = text.replace('plugin_version = "1.11.2"', 'plugin_version = "1.12.0"', 1)
text = text.replace('build_id = "20260903-r43"', 'build_id = "20260903-r44"', 1)
text = text.replace(
    '"""光鸭转存助手 v1.11.2 运行入口。',
    '"""光鸭转存助手 v1.12.0 运行入口。',
    1,
)
marker = "v1.11.2 补齐频道 ED2K 云添加：频道命中的 ED2K 单文件允许先 resolve，再用真实文件名/频道集号确认缺集并提交光鸭原生 cloudcollection。\n"
if "v1.12.0 改为逐集上映日历驱动" not in text:
    if marker not in text:
        raise RuntimeError("cannot locate GuangYa header history marker")
    text = text.replace(
        marker,
        marker
        + "v1.12.0 改为逐集上映日历驱动：普通后台只处理当前应播缺集，未来集等待更新窗口；每日全员补漏仍保留。\n",
        1,
    )
gya_entry.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# GYING fallback variants: distinct keyword already has a distinct 120s cache key.
# ---------------------------------------------------------------------------
gying = GYA / "gying_hardening_v193.py"
text = gying.read_text(encoding="utf-8")
old = "rows, state = super()._gying_raw_results(variant, force=force or index > 0)"
new = "rows, state = super()._gying_raw_results(variant, force=force)"
if new not in text:
    if old not in text:
        raise RuntimeError("cannot locate GYING fallback force expression")
    text = text.replace(old, new, 1)
gying.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Local GYA metadata (DailyAssistant intentionally has no plugin.json in this repo).
# ---------------------------------------------------------------------------
gya_meta_path = GYA / "plugin.json"
gya_meta = json.loads(gya_meta_path.read_text(encoding="utf-8"))
gya_meta["version"] = "1.12.0"
gya_meta["description"] = (
    "逐集上映日历驱动的固定分流助手：每日助手/TMDB 计算当前应补集，未来集不重复访问外部资源站；"
    "光鸭分享、迅雷秒传、Magnet/ED2K 共用集级终态、在途门禁和媒体身份校验。"
)
gya_meta_path.write_text(json.dumps(gya_meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Marketplace package metadata, preserving existing history.
# ---------------------------------------------------------------------------
package_path = ROOT / "package.v3.json"
package = json.loads(package_path.read_text(encoding="utf-8"))

daily = dict(package["DailyAssistant"])
daily["version"] = "1.2.0"
daily["description"] = (
    "全媒体榜单发现 + GYSub 助手，并提供整季逐集上映日历给光鸭转存助手，用当前应播集驱动追更。"
)
daily_history = dict(daily.get("history") or {})
daily_history.pop("v1.2.0", None)
daily["history"] = {"v1.2.0": DAILY_HISTORY, **daily_history}
package["DailyAssistant"] = daily

gya = dict(package["GuangYaTransferAssistant"])
gya["version"] = "1.12.0"
gya["description"] = (
    "逐集上映日历驱动的固定转存助手：普通后台只补当前应播缺集，未来集等待更新窗口；"
    "光鸭/迅雷/Magnet/ED2K 共用集级终态、在途门禁与媒体身份校验。"
)
gya_history = dict(gya.get("history") or {})
gya_history.pop("v1.12.0", None)
gya["history"] = {"v1.12.0": GYA_HISTORY, **gya_history}
package["GuangYaTransferAssistant"] = gya

package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# README release notes, without rewriting historical sections.
# ---------------------------------------------------------------------------
daily_readme = DAILY / "README.md"
text = daily_readme.read_text(encoding="utf-8")
if "## v1.2.0：逐集上映日历" not in text:
    anchor = "# 每日助手\n"
    block = (
        "\n## v1.2.0：逐集上映日历\n\n"
        "- 为 GYSub/光鸭转存提供 TMDB 整季逐集 `air_date` 日历，不再只知道下一集。\n"
        "- 通过 MoviePilot `MediaChain.tmdb_info(..., season=...)` 公共合同读取季详情；不可用时回退 `next_episode_to_air`。\n"
        "- 日历缓存 6 小时；每日助手不可用时，光鸭转存助手仍可自行回退 TMDB，不形成硬依赖。\n"
    )
    text = replace_once(text, anchor, anchor + block, "DailyAssistant README header")
    daily_readme.write_text(text, encoding="utf-8")

gya_readme = GYA / "README.md"
text = gya_readme.read_text(encoding="utf-8")
if "## v1.12.0：逐集上映日历驱动" not in text:
    anchor = "# 光鸭转存助手"
    if anchor in text:
        pos = text.index("\n", text.index(anchor)) + 1
        block = (
            "\n## v1.12.0：逐集上映日历驱动\n\n"
            "- 普通后台检查只处理 `due_missing`，尚未进入更新窗口的未来集不访问频道/迅雷/观影。\n"
            "- 默认在 TMDB 日期当天 20:00 前 12 小时进入提前检查窗口；只有日期精度时明确作为估算时间。\n"
            "- 每日 04:10 全员补漏仍保留，可发现提前放出或排期数据遗漏。\n"
            "- 修复旧分享 `handled=True` 误阻断仍缺集的 Magnet/ED2K，以及同订阅外部检索冷却并发竞争。\n"
        )
        text = text[:pos] + block + text[pos:]
        gya_readme.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Current-release test contracts only. Keep historical "v1.x.y" assertions intact.
# ---------------------------------------------------------------------------
for path in (ROOT / "tests").rglob("*.py"):
    source = path.read_text(encoding="utf-8")
    updated = source
    if "DailyAssistant" in source or "dailyassistant" in source.lower():
        updated = re.sub(r"(?<!v)1\.1\.2", "1.2.0", updated)
    if "GuangYaTransferAssistant" in source or "guangyatransferassistant" in source.lower() or "GUANGYA" in source:
        updated = re.sub(r"(?<!v)1\.11\.2", "1.12.0", updated)
        updated = updated.replace("20260903-r43", "20260903-r44")
    if updated != source:
        path.write_text(updated, encoding="utf-8")

print("applied DailyAssistant 1.2.0 + GuangYaTransferAssistant 1.12.0 airing calendar integration")
