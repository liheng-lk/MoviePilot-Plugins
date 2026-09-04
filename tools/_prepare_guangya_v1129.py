from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = PLUGIN / "__init__.py"
LOCAL = PLUGIN / "plugin.json"
PACKAGE = ROOT / "package.v3.json"
README = PLUGIN / "README.md"

OLD_VERSION = "1.12.8"
NEW_VERSION = "1.12.9"
OLD_BUILD = "20260905-r54"
NEW_BUILD = "20260905-r55"


def patch_entry() -> None:
    text = ENTRY.read_text(encoding="utf-8")
    text = text.replace(
        '"""光鸭转存助手 v1.12.8 运行入口。',
        '"""光鸭转存助手 v1.12.9 运行入口。',
        1,
    )
    marker = (
        "v1.12.8 修复 /gysub 消息入口：最终插件类显式注册 routing PluginAction 桥，不再依赖继承层隐式事件绑定；"
        "合法直订请求先即时回执，再执行 TMDB 识别和订阅创建，避免上游变慢时消息端表现为无响应。\n"
    )
    release = (
        "v1.12.9 修复电影观影已命中但真实英文原名被媒体身份门禁误杀：仅按订阅精确 TMDB ID 从 MoviePilot MediaChain "
        "补全官方 title/en_title/original_title 等可信别名；错误 TMDB/年份仍拒绝，不引入模糊电影匹配。\n"
    )
    if release not in text:
        if marker not in text:
            raise RuntimeError("v1.12.8 changelog marker not found")
        text = text.replace(marker, marker + release, 1)

    import_line = "from .movie_identity_v1129 import GuangYaMovieIdentityV1129Mixin\n"
    if import_line not in text:
        anchor = "from .resource_gate_v1127 import GuangYaResourceGateV1127Mixin\n"
        if anchor not in text:
            raise RuntimeError("resource gate import anchor not found")
        text = text.replace(anchor, import_line + anchor, 1)

    mro_line = "    GuangYaMovieIdentityV1129Mixin,\n"
    if mro_line not in text:
        anchor = "    GuangYaResourceGateV1127Mixin,\n"
        if anchor not in text:
            raise RuntimeError("resource gate MRO anchor not found")
        text = text.replace(anchor, mro_line + anchor, 1)

    old_public = f'    plugin_version = "{OLD_VERSION}"\n    build_id = "{OLD_BUILD}"'
    new_public = f'    plugin_version = "{NEW_VERSION}"\n    build_id = "{NEW_BUILD}"'
    if old_public not in text and new_public not in text:
        raise RuntimeError("final public version marker not found")
    text = text.replace(old_public, new_public, 1)
    ENTRY.write_text(text, encoding="utf-8")


def patch_local_metadata() -> None:
    data = json.loads(LOCAL.read_text(encoding="utf-8"))
    data["version"] = NEW_VERSION
    data["description"] = (
        "更新日历驱动的固定分流助手：5 分钟频道 Push 被动消费；当天应播 TV/动漫每 10 分钟快速追更；"
        "电影每 60 分钟复查并在新订阅时立即进入资源链。v1.12.9 修复电影观影已命中但真实迅雷包使用英文原名/官方原名时被媒体身份门禁误杀："
        "仅按订阅精确 TMDB ID 通过 MoviePilot MediaChain 补全官方 title/en_title/original_title 等可信别名；"
        "错误 TMDB/年份仍拒绝。来源优先级：观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K。"
    )
    LOCAL.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def patch_package() -> None:
    data = json.loads(PACKAGE.read_text(encoding="utf-8"))
    row = data["GuangYaTransferAssistant"]
    row["version"] = NEW_VERSION
    row["description"] = (
        "更新日历驱动的固定分流助手：5 分钟频道 Push 被动消费；当天应播 TV/动漫每 10 分钟快速追更；"
        "电影每 60 分钟复查并在新订阅时立即进入资源链。v1.12.9 修复电影观影已命中但真实迅雷包使用英文原名/官方原名时被媒体身份门禁误杀："
        "仅按订阅精确 TMDB ID 通过 MoviePilot MediaChain 补全官方 title/en_title/original_title 等可信别名；"
        "错误 TMDB/年份仍拒绝。来源优先级：观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K。"
    )
    history = row.get("history")
    if not isinstance(history, dict):
        history = {}
    new_history = {
        "v1.12.9": (
            "修复电影观影已搜索到资源但真实迅雷包使用英文原名/官方原名时被媒体身份门禁误杀；"
            "仅按订阅精确 TMDB ID 通过 MoviePilot MediaChain 补全官方 title/en_title/original_title 等可信别名，"
            "并继续严格校验 TMDB 身份、年份与电影季号冲突，不引入模糊电影匹配。"
        )
    }
    for key, value in history.items():
        if key not in new_history:
            new_history[key] = value
    row["history"] = new_history
    PACKAGE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def patch_readme() -> None:
    text = README.read_text(encoding="utf-8")
    heading = "## v1.12.9：电影精确 TMDB 官方别名桥接\n"
    if heading in text:
        return
    block = (
        "\n## v1.12.9：电影精确 TMDB 官方别名桥接\n\n"
        "- 修复电影在观影已经命中，但迅雷真实资源使用英文原名/官方原名时被最终媒体身份门禁误杀的问题。\n"
        "- 仅当订阅具备明确 TMDB 身份时，通过 MoviePilot `MediaChain.recognize_media` 按同一 TMDB ID 读取官方 `title/en_title/original_title/original_name` 等字段作为可信别名。\n"
        "- 返回 TMDB ID 或年份与订阅冲突时不采纳别名；电影资源出现季号仍按原门禁拒绝。\n"
        "- 不使用编辑距离或模糊标题救回，因此不会因相似片名放宽跨媒体安全边界。\n"
        "- 典型修复场景：订阅中文名“失控陪审团”，真实资源 `Runaway.Jury.2003...`。\n"
    )
    README.write_text(text.rstrip() + "\n" + block, encoding="utf-8")


def patch_tests() -> None:
    roots = [ROOT / "tests"]
    for root in roots:
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            updated = text.replace(f'"{OLD_VERSION}"', f'"{NEW_VERSION}"')
            updated = updated.replace(f'"{OLD_BUILD}"', f'"{NEW_BUILD}"')
            updated = updated.replace(f"'{OLD_VERSION}'", f"'{NEW_VERSION}'")
            updated = updated.replace(f"'{OLD_BUILD}'", f"'{NEW_BUILD}'")
            if updated != text:
                path.write_text(updated, encoding="utf-8")


def verify() -> None:
    entry = ENTRY.read_text(encoding="utf-8")
    assert f'plugin_version = "{NEW_VERSION}"' in entry
    assert f'build_id = "{NEW_BUILD}"' in entry
    assert "GuangYaMovieIdentityV1129Mixin" in entry
    head = entry.split("class GuangYaTransferAssistant(", 1)[1].split("):", 1)[0]
    assert head.index("GuangYaMovieIdentityV1129Mixin") < head.index("GuangYaResourceGateV1127Mixin")
    local = json.loads(LOCAL.read_text(encoding="utf-8"))
    package = json.loads(PACKAGE.read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    assert local["version"] == package["version"] == NEW_VERSION
    assert "v1.12.9" in package["history"]
    assert "v1.12.8" in package["history"]


if __name__ == "__main__":
    patch_entry()
    patch_local_metadata()
    patch_package()
    patch_readme()
    patch_tests()
    verify()
