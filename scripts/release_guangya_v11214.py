from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
VERSION = "1.12.14"
BUILD = "20260905-r60"
OLD_VERSION = "1.12.13"
OLD_BUILD = "20260905-r59"

DESCRIPTION = (
    "更新日历驱动的固定分流助手：5 分钟频道 Push 被动消费；当天应播 TV/动漫每 10 分钟快速追更；"
    "电影每 60 分钟复查。v1.12.14 完成核心资源链统一：频道与观影均可贡献光鸭分享、迅雷分享、"
    "Magnet、ED2K；TV/动漫可按精确 TMDB 身份补充官方英文/原始标题召回。所有 TV 最终写盘统一收紧到"
    "“MoviePilot library missing ∩ logical/fact missing - reservation - other source claim”，当前来源不会扣除自身 claim；"
    "光鸭直接分享、Magnet、ED2K 与既有迅雷均执行不可分割物理视频 episodes ⊆ allowed missing，真实 payload 的"
    "标题/年份/季号硬冲突直接拒绝，媒体库缺集事实不可用时最终写盘 fail closed。来源优先级仍为"
    "观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K，目标缺口覆盖后立即短路；Magnet/ED2K 仍使用光鸭原生 cloudcollection。"
)

HISTORY = (
    "核心资源链统一：频道与观影均支持光鸭分享、迅雷分享、Magnet、ED2K；频道迅雷密码严格限定同一消息，"
    "观影光鸭分享通过临时 ResourceGroup 进入既有直接转存且不污染频道索引；TV/动漫新增精确 TMDB 官方英文/原始标题召回。"
    "所有 TV 最终允许集统一为 MoviePilot library missing ∩ logical/fact missing - reservation - other source claim，"
    "当前 source 不扣自身 claim；光鸭直接分享、Magnet、ED2K 与既有迅雷统一要求不可分割物理视频 episodes ⊆ allowed missing，"
    "真实 payload 标题/年份/季号硬冲突拒绝，MoviePilot 媒体库事实不可用时 fail closed。保持"
    "观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K，覆盖缺口即短路；Magnet/ED2K 继续使用光鸭原生 cloudcollection。"
)

README_SECTION = """

## v1.12.14：核心资源链统一与最终缺集硬栅栏

- 频道与观影 GYING 现在都可以贡献四类候选：光鸭分享、迅雷分享、Magnet、ED2K；频道迅雷密码只从同一条消息读取，观影光鸭分享以临时 ResourceGroup 进入既有直接转存链，不写入持久 Telegram 索引。
- TV/动漫在中文标题没有当前媒体可用候选时，可按订阅精确 TMDB ID 补充官方 `title/en_title/original_title/original_name` 等可信标题继续检索；不使用编辑距离、拼音或模糊标题猜测。
- TV 最终允许集统一收紧为 `MoviePilot library missing ∩ logical/fact missing - reservation - other source claim`；当前正在提交的 source 不会把自己的 claim 再扣一次。
- 光鸭直接分享、迅雷、Magnet、ED2K 的不可分割视频统一要求 `actual episodes ⊆ allowed missing`。例如只缺 E11 时，单集 E11 可以写入，`E09-E11` 或 `E09-E12` 整文件必须拒绝。
- 搜索卡片/频道标题只作为发现证据；真正提交前重新检查实际分享/resolve 文件。真实标题、年份或 Season 明确冲突时拒绝；`S01E11.mkv` 这类没有作品标题的弱文件名不会被伪造为冲突证据。
- 保持 `观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K`，一旦当前真实缺口被覆盖就停止后续来源。Magnet/ED2K 继续走光鸭原生 `cloudcollection`，不引入 MoviePilot 下载器。
"""

ACCEPTANCE = """# GuangYaTransferAssistant v1.12.14 发布验收

- 版本：`1.12.14`
- Build：`20260905-r60`
- 目标：把资源发现、媒体身份、真实缺口、物理文件与最终写盘收口成跨来源统一不变量，避免漏资源、串媒体和已有剧集重复进入云盘。

## 1. 来源矩阵

频道与观影 GYING 均允许产生：

1. 光鸭分享 → 直接增量转存；
2. 迅雷分享 → JSON 1.1.3 秒传；
3. Magnet → 光鸭原生 cloudcollection；
4. ED2K → 光鸭原生 cloudcollection。

频道迅雷提取码只允许来自同一条 Telegram 消息；观影光鸭分享只在当前订阅线程中临时注入 ResourceGroup，不污染持久频道索引。

## 2. 媒体身份

发现标题只做候选预筛，最终以实际分享/resolve payload 为准。明确的标题、年份、Season 冲突硬拒绝。TV/动漫可以使用同一 TMDB ID 返回的官方英文/原始标题扩大 GYING 精确召回，但禁止编辑距离、拼音或其它模糊作品猜测。

## 3. TV 权威缺口

最终允许写盘集合必须满足：

```text
allowed = MoviePilot library missing
          ∩ logical/fact missing
          - reservation
          - other active source claims
```

当前正在 resolve/create 的 source 必须从 `other active source claims` 中排除，不能自己把自己扣空。MoviePilot 媒体库事实无法可靠读取时，TV 最终写盘 fail closed。

## 4. 不可分割物理文件

所有来源统一遵循：

```text
actual physical video episodes ⊆ allowed missing
```

示例：当前只缺 E11。

- `Show.S01E11.mkv` → 允许；
- `Show.S01E09-E11.mkv` → 拒绝整文件；
- `Show.S01E09-E12.mkv` → 拒绝整文件；
- 已入库/已完成/其它来源在途的集数不能因为切换来源重新进入 allowed。

## 5. 来源优先级与短路

固定优先级：

```text
观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K
```

前一来源一旦覆盖当前真实缺口，后续来源不再提交。Magnet/ED2K 不经过 MoviePilot 下载器。

## 6. 发布门禁

候选业务门禁在公开版本迁移前已全绿：GitHub Actions run `33962451418`，包括 Python syntax、95 个根单测、GuangYa V3 合同、依赖 manifest、JSON 索引和生成物检查。

正式发布仍要求：

- 迁移 `__init__.py / plugin.json / package.v3.json` 到 v1.12.14/r60；
- 当前版本合同全部迁移；历史 v1.12.13/v1.12.12/v1.12.10 模块标记继续保留；
- PR 正式 CI 全绿；
- 合并 main 后 main push CI 再次全绿。
"""


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def require_replace(text: str, old: str, new: str, *, count: int = 1) -> str:
    actual = text.count(old)
    if actual != count:
        raise RuntimeError(f"release migration expected {count} occurrence(s), got {actual}: {old[:120]!r}")
    return text.replace(old, new, count)


def migrate_entry() -> None:
    path = PLUGIN / "__init__.py"
    text = path.read_text(encoding="utf-8")
    text = require_replace(text, '"""光鸭转存助手 v1.12.13 运行入口。', '"""光鸭转存助手 v1.12.14 运行入口。')
    old = (
        "v1.12.13 修复媒体库已有剧集仍被迅雷秒传重复导入：TV 迅雷硬目标改为媒体库 missing 与成功事实/订阅 missing 的交集，"
        "并在 JSON batch import 前逐视频二次过滤；跨边界多集文件整文件拒绝，媒体库缺集事实读取失败时跳过迅雷但继续后续来源。\n"
    )
    new = old + (
        "v1.12.14 统一核心资源链：频道/观影均支持光鸭分享、迅雷分享、Magnet、ED2K；TV/动漫按精确 TMDB 官方标题补召回；"
        "所有 TV 最终写盘收紧到 library missing ∩ logical/fact missing - reservation - other source claim，并对光鸭分享、迅雷、"
        "Magnet、ED2K 统一执行不可分割物理文件 episodes ⊆ allowed missing 与实际 payload 身份门禁。\n"
    )
    text = require_replace(text, old, new)
    text = require_replace(text, '    plugin_version = "1.12.13"\n    build_id = "20260905-r59"', '    plugin_version = "1.12.14"\n    build_id = "20260905-r60"')
    write(path, text)


def migrate_json_metadata() -> None:
    plugin_path = PLUGIN / "plugin.json"
    local = json.loads(plugin_path.read_text(encoding="utf-8"))
    if local.get("version") != OLD_VERSION:
        raise RuntimeError(f"unexpected plugin.json version: {local.get('version')}")
    local["version"] = VERSION
    local["description"] = DESCRIPTION
    write(plugin_path, json.dumps(local, ensure_ascii=False, indent=2) + "\n")

    package_path = ROOT / "package.v3.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    row = package.get("GuangYaTransferAssistant")
    if not isinstance(row, dict) or row.get("version") != OLD_VERSION:
        raise RuntimeError("GuangYaTransferAssistant package metadata is not at v1.12.13")
    row["version"] = VERSION
    row["description"] = DESCRIPTION
    labels = [item.strip() for item in str(row.get("labels") or "").split(",") if item.strip()]
    for label in ("四源统一", "缺集硬栅栏"):
        if label not in labels:
            labels.append(label)
    row["labels"] = ",".join(labels)
    history = dict(row.get("history") or {})
    if "v1.12.14" in history:
        raise RuntimeError("v1.12.14 history already exists before migration")
    row["history"] = {"v1.12.14": HISTORY, **history}
    write(package_path, json.dumps(package, ensure_ascii=False, indent=2) + "\n")


def migrate_readme_and_acceptance() -> None:
    readme = PLUGIN / "README.md"
    text = readme.read_text(encoding="utf-8")
    if "## v1.12.14：核心资源链统一与最终缺集硬栅栏" not in text:
        text = text.rstrip() + README_SECTION + "\n"
        write(readme, text)
    acceptance = ROOT / "docs" / "guangyatransferassistant-v11214-release.md"
    write(acceptance, ACCEPTANCE)


def migrate_tests() -> None:
    historical = {
        ROOT / "tests" / "v3" / "guangyatransferassistant" / "test_xunlei_existing_fence_v11213.py",
        ROOT / "tests" / "v3" / "guangyatransferassistant" / "test_release_v11213_marker.py",
        ROOT / "tests" / "v3" / "guangyatransferassistant" / "test_core_pipeline_v11214.py",
    }
    paths = list((ROOT / "tests").glob("test_guangya*.py"))
    paths += list((ROOT / "tests" / "v3" / "guangyatransferassistant").glob("test_*.py"))
    for path in sorted(set(paths)):
        if path in historical:
            continue
        text = path.read_text(encoding="utf-8")
        updated = text.replace(OLD_VERSION, VERSION).replace(OLD_BUILD, BUILD)
        if updated != text:
            write(path, updated)

    release13 = ROOT / "tests" / "v3" / "guangyatransferassistant" / "test_release_v11213_marker.py"
    text = release13.read_text(encoding="utf-8")
    text = text.replace("def test_v11213_public_release_is_single_truth():", "def test_v11214_public_release_is_single_truth_while_v11213_fence_stays_historical():")
    text = require_replace(text, '    assert LOCAL["version"] == PACKAGE["version"] == "1.12.13"', '    assert LOCAL["version"] == PACKAGE["version"] == "1.12.14"')
    text = require_replace(text, '    assert \'plugin_version = "1.12.13"\' in ENTRY', '    assert \'plugin_version = "1.12.14"\' in ENTRY')
    text = require_replace(text, '    assert \'build_id = "20260905-r59"\' in ENTRY', '    assert \'build_id = "20260905-r60"\' in ENTRY')
    write(release13, text)

    core_test = ROOT / "tests" / "v3" / "guangyatransferassistant" / "test_core_pipeline_v11214.py"
    text = core_test.read_text(encoding="utf-8")
    text = text.replace(
        "def test_current_public_release_remains_v11213_until_full_gate_passes():",
        "def test_current_public_release_is_v11214_after_full_gate_passes():",
    )
    text = require_replace(text, '    assert \'plugin_version = "1.12.13"\' in ENTRY', '    assert \'plugin_version = "1.12.14"\' in ENTRY')
    text = require_replace(text, '    assert \'build_id = "20260905-r59"\' in ENTRY', '    assert \'build_id = "20260905-r60"\' in ENTRY')
    write(core_test, text)


def verify_release_truth() -> None:
    entry = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
    local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    assert local["version"] == package["version"] == VERSION
    assert f'plugin_version = "{VERSION}"' in entry
    assert f'build_id = "{BUILD}"' in entry
    assert "v1.12.14" in package["history"]

    # Historical safety layers keep their own markers; release migration must never rewrite them.
    fence13 = (PLUGIN / "xunlei_existing_fence_v11213.py").read_text(encoding="utf-8")
    alias12 = (PLUGIN / "gying_alias_query_v11212.py").read_text(encoding="utf-8")
    season10 = (PLUGIN / "xunlei_season_fence_v11210.py").read_text(encoding="utf-8")
    assert 'plugin_version = "1.12.13"' in fence13 and 'build_id = "20260905-r59"' in fence13
    assert 'plugin_version = "1.12.12"' in alias12 and 'build_id = "20260905-r58"' in alias12
    assert 'plugin_version = "1.12.10"' in season10 and 'build_id = "20260905-r56"' in season10


if __name__ == "__main__":
    migrate_entry()
    migrate_json_metadata()
    migrate_readme_and_acceptance()
    migrate_tests()
    verify_release_truth()
    print("GuangYaTransferAssistant v1.12.14 release migration prepared")
