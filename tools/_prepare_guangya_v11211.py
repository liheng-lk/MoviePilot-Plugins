from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = PLUGIN / "__init__.py"
LOCAL = PLUGIN / "plugin.json"
PACKAGE = ROOT / "package.v3.json"
README = PLUGIN / "README.md"

OLD_VERSION = "1.12.10"
NEW_VERSION = "1.12.11"
OLD_BUILD = "20260905-r56"
NEW_BUILD = "20260905-r57"


def patch_entry() -> None:
    text = ENTRY.read_text(encoding="utf-8")
    text = text.replace(
        '"""光鸭转存助手 v1.12.10 运行入口。',
        '"""光鸭转存助手 v1.12.11 运行入口。',
        1,
    )
    marker = (
        "v1.12.10 修复同一迅雷分享被同媒体不同季重复消费：无季号整包先校验完整集号结构，"
        "成功后持久占用真实 share，同系列迅雷流程串行化；显式多季包仍由既有 planner 拆分。\n"
    )
    release = (
        "v1.12.11 修复 /gycheck 只检查频道却未保证主动资源链的问题：人工立即检查先强刷并消费频道，"
        "频道仍未覆盖时以 force=True 立即执行观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K；"
        "人工操作绕过自动检索冷却，但继续保留媒体身份、年份、质量、Episode Fence、reservation/source claim "
        "与 v1.12.10 迅雷跨季物理资源栅栏。\n"
    )
    if release not in text:
        if marker not in text:
            raise RuntimeError("v1.12.10 changelog marker not found")
        text = text.replace(marker, marker + release, 1)
    old_public = f'    plugin_version = "{OLD_VERSION}"\n    build_id = "{OLD_BUILD}"'
    new_public = f'    plugin_version = "{NEW_VERSION}"\n    build_id = "{NEW_BUILD}"'
    if old_public not in text and new_public not in text:
        raise RuntimeError("public version marker not found")
    text = text.replace(old_public, new_public, 1)
    ENTRY.write_text(text, encoding="utf-8")


def description() -> str:
    return (
        "更新日历驱动的固定分流助手：5 分钟频道 Push 被动消费；当天应播 TV/动漫每 10 分钟快速追更；"
        "电影每 60 分钟复查并在新订阅时立即进入资源链。v1.12.11 修复 /gycheck 人工立即检查只看到频道结果的问题："
        "先强刷/消费频道，未覆盖时立即强制执行观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K，人工检查绕过自动检索冷却；"
        "仍严格保留媒体身份、年份、质量、Episode Fence、跨来源在途门禁及 v1.12.10 迅雷跨季物理资源栅栏。"
    )


def patch_local() -> None:
    data = json.loads(LOCAL.read_text(encoding="utf-8"))
    data["version"] = NEW_VERSION
    data["description"] = description()
    LOCAL.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def patch_package() -> None:
    data = json.loads(PACKAGE.read_text(encoding="utf-8"))
    row = data["GuangYaTransferAssistant"]
    row["version"] = NEW_VERSION
    row["description"] = description()
    history = row.get("history") if isinstance(row.get("history"), dict) else {}
    updated = {
        "v1.12.11": (
            "修复 /gycheck 名为‘立即检查’但实际可能只停留在频道检查的问题：人工检查现在先强刷并消费频道，"
            "再对真实剩余缺口以 force=True 立即执行观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K；"
            "频道命中 0 条不再阻止观影检索，人工检查绕过自动检索冷却，但不绕过媒体身份、年份、质量、"
            "Episode Fence、reservation/source claim 或 v1.12.10 迅雷跨季物理资源栅栏。"
        )
    }
    for key, value in history.items():
        if key not in updated:
            updated[key] = value
    row["history"] = updated
    PACKAGE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def patch_readme() -> None:
    text = README.read_text(encoding="utf-8")
    heading = "## v1.12.11：/gycheck 人工完整资源检查"
    if heading in text:
        return
    block = (
        "\n## v1.12.11：/gycheck 人工完整资源检查\n\n"
        "- `/gycheck` 不再只是把订阅送入通用后台检查；它现在有独立的人工完整链语义。\n"
        "- 第一阶段强制刷新一次频道并只消费频道资源；若频道已经覆盖目标，立即终止后续外部访问。\n"
        "- 若频道命中为 0 或仍未覆盖，重新计算电影待处理事实/剧集真实缺口，然后以 `force=True` 进入完整来源链：观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K。\n"
        "- 人工 `force=True` 只绕过 10/60/180 分钟自动检索冷却；媒体身份、年份、质量、Episode Fence、reservation/source claim、迅雷跨季物理资源栅栏全部继续生效。\n"
        "- 消息回执会明确提示‘频道为 0 不会停止后续观影检索’，避免把频道诊断误解为整条资源链的最终结果。\n"
    )
    README.write_text(text.rstrip() + "\n" + block, encoding="utf-8")


def patch_nested_contract_tests() -> None:
    movie_test = ROOT / "tests" / "v3" / "guangyatransferassistant" / "test_movie_identity_v1129.py"
    text = movie_test.read_text(encoding="utf-8")
    text = text.replace(
        '"GuangYaXunleiSeasonFenceV11210Mixin": _XunleiFenceBase,',
        '"GuangYaManualCheckV11211Mixin": _XunleiFenceBase,',
        1,
    )
    movie_test.write_text(text, encoding="utf-8")

    season_test = ROOT / "tests" / "v3" / "guangyatransferassistant" / "test_xunlei_season_fence_v11210.py"
    text = season_test.read_text(encoding="utf-8")
    old = (
        '    assert "from .xunlei_season_fence_v11210 import GuangYaXunleiSeasonFenceV11210Mixin" in movie\n'
        '    assert "class GuangYaMovieIdentityV1129Mixin(GuangYaXunleiSeasonFenceV11210Mixin):" in movie\n'
    )
    new = (
        '    manual = (PLUGIN / "manual_check_v11211.py").read_text(encoding="utf-8")\n'
        '    ast.parse(manual, filename=str(PLUGIN / "manual_check_v11211.py"))\n'
        '    assert "from .manual_check_v11211 import GuangYaManualCheckV11211Mixin" in movie\n'
        '    assert "class GuangYaMovieIdentityV1129Mixin(GuangYaManualCheckV11211Mixin):" in movie\n'
        '    assert "from .xunlei_season_fence_v11210 import GuangYaXunleiSeasonFenceV11210Mixin" in manual\n'
        '    assert "class GuangYaManualCheckV11211Mixin(GuangYaXunleiSeasonFenceV11210Mixin):" in manual\n'
    )
    if old not in text and new not in text:
        raise RuntimeError("season-fence nested contract marker not found")
    text = text.replace(old, new, 1)
    season_test.write_text(text, encoding="utf-8")


def patch_current_release_tests() -> None:
    # 这两个测试显式验证历史层版本，不能被当前发布号机械替换。
    excluded = {
        ROOT / "tests" / "v3" / "guangyatransferassistant" / "test_xunlei_season_fence_v11210.py",
        ROOT / "tests" / "v3" / "guangyatransferassistant" / "test_manual_check_v11211.py",
    }
    for path in (ROOT / "tests").rglob("*.py"):
        if path in excluded:
            continue
        text = path.read_text(encoding="utf-8")
        updated = text.replace(f'"{OLD_VERSION}"', f'"{NEW_VERSION}"')
        updated = updated.replace(f"'{OLD_VERSION}'", f"'{NEW_VERSION}'")
        updated = updated.replace(f'"{OLD_BUILD}"', f'"{NEW_BUILD}"')
        updated = updated.replace(f"'{OLD_BUILD}'", f"'{NEW_BUILD}'")
        if updated != text:
            path.write_text(updated, encoding="utf-8")


def verify() -> None:
    entry = ENTRY.read_text(encoding="utf-8")
    movie = (PLUGIN / "movie_identity_v1129.py").read_text(encoding="utf-8")
    manual = (PLUGIN / "manual_check_v11211.py").read_text(encoding="utf-8")
    season = (PLUGIN / "xunlei_season_fence_v11210.py").read_text(encoding="utf-8")
    assert f'plugin_version = "{NEW_VERSION}"' in entry
    assert f'build_id = "{NEW_BUILD}"' in entry
    assert "class GuangYaMovieIdentityV1129Mixin(GuangYaManualCheckV11211Mixin):" in movie
    assert "class GuangYaManualCheckV11211Mixin(GuangYaXunleiSeasonFenceV11210Mixin):" in manual
    assert 'plugin_version = "1.12.10"' in season
    assert 'build_id = "20260905-r56"' in season
    local = json.loads(LOCAL.read_text(encoding="utf-8"))
    package = json.loads(PACKAGE.read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    assert local["version"] == package["version"] == NEW_VERSION
    assert "v1.12.11" in package["history"] and "v1.12.10" in package["history"]
    assert "频道命中 0 条" in package["history"]["v1.12.11"]


if __name__ == "__main__":
    patch_entry()
    patch_local()
    patch_package()
    patch_readme()
    patch_nested_contract_tests()
    patch_current_release_tests()
    verify()
