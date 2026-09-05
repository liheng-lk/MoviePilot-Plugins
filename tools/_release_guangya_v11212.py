from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = PLUGIN / "__init__.py"
LOCAL = PLUGIN / "plugin.json"
PACKAGE = ROOT / "package.v3.json"
README = PLUGIN / "README.md"
OLD_VERSION = "1.12.11"
NEW_VERSION = "1.12.12"
OLD_BUILD = "20260905-r57"
NEW_BUILD = "20260905-r58"


def release_description() -> str:
    return (
        "更新日历驱动的固定分流助手：5 分钟频道 Push 被动消费；当天应播 TV/动漫每 10 分钟快速追更；"
        "电影每 60 分钟复查。v1.12.12 修复 GYING 网页明明存在资源但插件检索不到的前置关键词断层："
        "电影先用 MoviePilot 中文标题检索，当前媒体仍未命中时再按同一 TMDB 身份和年份使用官方英文/原始标题精确复查；"
        "无关搜索卡片不再提前终止降级，认证/节点/HTTP 失败仍立即停止。该能力同时覆盖观影迅雷召回和 GYING Magnet/ED2K，"
        "不使用编辑距离、拼音或模糊跨媒体匹配。来源优先级仍为观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K，"
        "并继续保留 /gycheck 人工完整链、媒体身份、年份、质量、Episode Fence、跨来源在途门禁及迅雷跨季物理栅栏。"
    )


def patch_entry() -> None:
    text = ENTRY.read_text(encoding="utf-8")
    text = text.replace(
        '"""光鸭转存助手 v1.12.11 运行入口。',
        '"""光鸭转存助手 v1.12.12 运行入口。',
        1,
    )
    marker = (
        "v1.12.11 修复 /gycheck 只检查频道却未保证主动资源链的问题：人工立即检查先强刷并消费频道，"
        "频道仍未覆盖时以 force=True 立即执行观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K；"
        "人工操作绕过自动检索冷却，但继续保留媒体身份、年份、质量、Episode Fence、reservation/source claim "
        "与 v1.12.10 迅雷跨季物理资源栅栏。\n"
    )
    release = (
        "v1.12.12 修复 GYING 前置搜索未使用精确 TMDB 官方别名的问题：电影中文标题未命中当前媒体时，"
        "继续用同一 TMDB 身份与年份下的官方英文/原始标题搜索；无关卡片不再阻止降级，网络/认证失败仍硬停止；"
        "观影迅雷召回与 GYING Magnet/ED2K 共用该语义，不引入模糊匹配。\n"
    )
    if release not in text:
        if marker not in text:
            raise RuntimeError("v1.12.11 entry marker missing")
        text = text.replace(marker, marker + release, 1)
    old_public = f'    plugin_version = "{OLD_VERSION}"\n    build_id = "{OLD_BUILD}"'
    new_public = f'    plugin_version = "{NEW_VERSION}"\n    build_id = "{NEW_BUILD}"'
    if old_public not in text and new_public not in text:
        raise RuntimeError("public version marker missing")
    text = text.replace(old_public, new_public, 1)
    ENTRY.write_text(text, encoding="utf-8")


def patch_json_metadata() -> None:
    local = json.loads(LOCAL.read_text(encoding="utf-8"))
    local["version"] = NEW_VERSION
    local["description"] = release_description()
    LOCAL.write_text(json.dumps(local, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    data = json.loads(PACKAGE.read_text(encoding="utf-8"))
    row = data["GuangYaTransferAssistant"]
    row["version"] = NEW_VERSION
    row["description"] = release_description()
    labels = [item.strip() for item in str(row.get("labels") or "").split(",") if item.strip()]
    for label in ("TMDB官方别名", "英文原名检索"):
        if label not in labels:
            labels.append(label)
    row["labels"] = ",".join(labels)
    history = row.get("history") if isinstance(row.get("history"), dict) else {}
    new_history = {
        "v1.12.12": (
            "修复观影网页存在资源但 GYING 插件搜索因关键词断层无法发现的问题：订阅电影先保留中文标题/年份搜索，"
            "若返回的只是无关卡片或没有当前媒体候选，则按订阅精确 TMDB ID 读取并校验官方 title/en_title/original_title，"
            "继续尝试如 Runaway Jury 2003 的精确官方别名；中文首轮已命中时立即短路，不额外访问站点。"
            "认证、节点和 HTTP 搜索失败仍立即停止，错误 TMDB/年份不会贡献别名，不做编辑距离、拼音或模糊匹配。"
            "观影迅雷召回及 GYING Magnet/ED2K 共用该检索语义；/gycheck 完整链、来源优先级、Episode Fence、"
            "reservation/source claim 与 v1.12.10 迅雷跨季物理资源栅栏保持不变。"
        )
    }
    for key, value in history.items():
        if key not in new_history:
            new_history[key] = value
    row["history"] = new_history
    PACKAGE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def patch_readme() -> None:
    text = README.read_text(encoding="utf-8")
    heading = "## v1.12.12：GYING 精确官方别名前置检索"
    if heading in text:
        return
    block = (
        "\n## v1.12.12：GYING 精确官方别名前置检索\n\n"
        "- 修复电影官方英文名只用于‘搜索后身份判断’，却没有进入‘搜索前关键词’的问题。\n"
        "- 例如 `失控陪审团 (2003)` 会先搜索 `失控陪审团 2003`；当前媒体未命中时，再使用同一 TMDB 身份校验出的 `Runaway Jury 2003`。\n"
        "- GYING 返回其它影片卡片不再被当成当前媒体搜索成功；只有实际候选通过当前订阅身份判断才停止别名降级。\n"
        "- 中文首轮已命中时不会多打一轮英文请求；认证、节点或 HTTP 搜索失败时也不会用别名轮询掩盖故障。\n"
        "- 只接受 MoviePilot 当前订阅精确 TMDB ID + 年份校验后的官方标题，不使用编辑距离、拼音、相似片名等模糊救回。\n"
        "- 观影迅雷秒传与 GYING Magnet/ED2K 使用相同前置别名语义；最终来源优先级和全部安全门禁不变。\n"
        "- MoviePilot 原生全局搜索并未把 GYING 注册成 Indexer；本修复覆盖光鸭转存助手自己的统一 Provider 搜索和订阅资源链。\n"
    )
    README.write_text(text.rstrip() + "\n" + block, encoding="utf-8")


def patch_current_release_tests() -> None:
    historical = {
        ROOT / "tests" / "v3" / "guangyatransferassistant" / "test_manual_check_v11211.py",
        ROOT / "tests" / "v3" / "guangyatransferassistant" / "test_xunlei_season_fence_v11210.py",
        ROOT / "tests" / "v3" / "guangyatransferassistant" / "test_movie_identity_v1129.py",
        ROOT / "tests" / "v3" / "guangyatransferassistant" / "test_gying_alias_query_v11212.py",
    }
    for path in (ROOT / "tests").rglob("*.py"):
        if path in historical:
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
    alias = (PLUGIN / "gying_alias_query_v11212.py").read_text(encoding="utf-8")
    manual = (PLUGIN / "manual_check_v11211.py").read_text(encoding="utf-8")
    season = (PLUGIN / "xunlei_season_fence_v11210.py").read_text(encoding="utf-8")
    movie = (PLUGIN / "movie_identity_v1129.py").read_text(encoding="utf-8")
    assert f'plugin_version = "{NEW_VERSION}"' in entry
    assert f'build_id = "{NEW_BUILD}"' in entry
    assert 'plugin_version = "1.12.12"' in alias and 'build_id = "20260905-r58"' in alias
    assert 'plugin_version = "1.12.11"' in manual and 'build_id = "20260905-r57"' in manual
    assert 'plugin_version = "1.12.10"' in season and 'build_id = "20260905-r56"' in season
    assert 'plugin_version = "1.12.9"' in movie and 'build_id = "20260905-r55"' in movie
    local = json.loads(LOCAL.read_text(encoding="utf-8"))
    package = json.loads(PACKAGE.read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    assert local["version"] == package["version"] == NEW_VERSION
    assert "v1.12.12" in package["history"] and "v1.12.11" in package["history"]
    assert "Runaway Jury 2003" in package["history"]["v1.12.12"]
    head = entry.split("class GuangYaTransferAssistant(", 1)[1].split("):", 1)[0]
    assert "GuangYaGyingAliasQueryV11212Mixin" not in head


if __name__ == "__main__":
    patch_entry()
    patch_json_metadata()
    patch_readme()
    patch_current_release_tests()
    verify()
