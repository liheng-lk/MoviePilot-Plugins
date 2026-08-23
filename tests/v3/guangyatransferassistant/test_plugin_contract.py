import ast
import hashlib
import html
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, unquote, urljoin, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "plugins.v3" / "guangyatransferassistant" / "__init__.py"
text = SRC.read_text(encoding="utf-8")
tree = ast.parse(text)

# 执行 class 之前的常量与纯函数，不依赖 MoviePilot 运行时。
nodes = []
for node in tree.body:
    if isinstance(node, ast.ClassDef):
        break
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.FunctionDef)):
        if isinstance(node, ast.FunctionDef):
            node.returns = None
            for arg in node.args.args:
                arg.annotation = None
        nodes.append(node)
mod = ast.Module(body=nodes, type_ignores=[])
ast.fix_missing_locations(mod)
ns = {
    "ast": ast, "hashlib": hashlib, "html": html, "re": re,
    "parse_qs": parse_qs, "urlencode": urlencode, "unquote": unquote,
    "urljoin": urljoin, "urlsplit": urlsplit, "urlunsplit": urlunsplit,
    "Any": Any, "Dict": Dict, "Iterable": Iterable, "List": List,
    "Optional": Optional, "Tuple": Tuple,
}
exec(compile(mod, str(SRC), "exec"), ns)


def test_hidden_visible_and_wrapped_links():
    hidden = '''<div class="tgme_widget_message_wrap" data-post="regengguangya/100">
    <div>名称：花开锦绣 (2026) [2160P]<br>集数：第23-25集 / 全36集<br>TMDB：287496</div>
    <a class="tgme_widget_message_inline_button" href="https://www.guangyapan.com/s/hiddenABC">🔗 光鸭云盘：查看资源</a>
    </div>'''
    items = ns["_extract_channel_entries"](hidden, "https://tgm.li668.asia/regengguangya", "影视热更")
    assert len(items) == 1
    assert items[0]["share_id"] == "hiddenABC"
    assert items[0]["tmdb_id"] == "287496"
    assert "23-25" in items[0]["episode_hint"]
    assert "按钮" in items[0]["link_style"]

    data_url = '''<div data-post="regengguangya/1001">名称：属性按钮测试 (2026)
    <button data-url="https://www.guangyapan.com/s/dataURL123">光鸭云盘：查看资源</button></div>'''
    items = ns["_extract_channel_entries"](data_url, "https://tgm.li668.asia/regengguangya", "影视热更")
    assert len(items) == 1 and items[0]["share_id"] == "dataURL123"
    assert items[0]["link_style"] in ("隐藏按钮", "链接属性")

    visible = '''<div data-post="yunpanguangya/101">名称：杀手妈咪 유부녀 킬러 (2026) [1080P] [更至8集]
    链接：www.guangyapan.com/s/plainXYZ</div>'''
    items = ns["_extract_channel_entries"](visible, "https://tgm.li668.asia/yunpanguangya", "资源分享")
    assert len(items) == 1 and items[0]["share_id"] == "plainXYZ"
    assert items[0]["link_style"] == "明文链接"

    wrapped = '''<div data-post="regengguangya/102">名称：包装测试 (2026)
    <a href="/redirect?url=https%3A%2F%2Fwww.guangyapan.com%2Fs%2Fwrap123%3Fcode%3DAb12">查看资源</a></div>'''
    items = ns["_extract_channel_entries"](wrapped, "https://tgm.li668.asia/regengguangya", "影视热更")
    assert len(items) == 1 and items[0]["share_id"] == "wrap123"
    assert "code=Ab12" in items[0]["share_url"]
    assert "按钮" in items[0]["link_style"] or "包装" in items[0]["link_style"]


def test_message_boundary_and_tmdb_exact_match():
    page = '''<div data-post="regengguangya/201">名称：花开锦绣 (2026)<br>TMDB: 287496
    <a href="https://www.guangyapan.com/s/a201">查看资源</a></div>
    <div data-post="regengguangya/202">名称：完全不同 (2025)<br>TMDB: 999999
    <a href="https://www.guangyapan.com/s/a202">查看资源</a></div>'''
    items = ns["_extract_channel_entries"](page, "https://tgm.li668.asia/regengguangya", "影视热更")
    first = next(item for item in items if item["share_id"] == "a201")
    assert "999999" not in first["text"]
    assert ns["_entry_matches_subscription"](first, "标题甚至不同也可由ID确认", 2026, 1, "themoviedb", "287496") is True
    assert ns["_entry_matches_subscription"](first, "花开锦绣", 2026, 1, "themoviedb", "999999") is False


def test_pagination_episode_and_path_safety():
    html_page = '''<a href="/regengguangya?before=123">Older</a>
    <a href="/other?before=1">Other</a><a href="/regengguangya">Same</a>'''
    pages = ns["_extract_pagination_urls"](html_page, "https://tgm.li668.asia/regengguangya")
    assert pages == ["https://tgm.li668.asia/regengguangya?before=123"]
    season, eps = ns["_episode_numbers"]("Show.S01E23-E25.2160p.WEB-DL.mkv")
    assert season == 1 and eps == [23, 24, 25]
    _, eps = ns["_episode_numbers"]("第8-10集.mp4")
    assert eps == [8, 9, 10]
    assert ns["_safe_relative_path"]("../../Season 1/../E01.mkv") == "Season 1/E01.mkv"


def test_version_and_safety_contracts():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    local = json.loads((ROOT / "plugins.v3" / "guangyatransferassistant" / "plugin.json").read_text(encoding="utf-8"))
    assert package["version"] == "1.2.0" and local["version"] == "1.2.0"
    assert 'plugin_version = "1.2.0"' in text
    for token in (
        "隐藏按钮", "包装按钮", "_extract_pagination_urls", "tmdb_id", "TMDB精确",
        "strict_subscription_rules", "best_version", "filter_groups", "state not in (\"N\", \"R\")",
        "sync_subscription_progress", "SubscribeOper().update", "_episode_numbers",
        "max_files_per_run", "retry_minutes", "旧缓存", "stale", "clear_inventory",
        "【光鸭转存助手】【进度】", "【光鸭转存助手】【规则】", "【光鸭转存助手】【重试】",
    ):
        assert token in text, token
    assert "subscribe_search" in text and "new_subscribe_search" in text
    assert "SubscribeChain().search" in text
    assert "/nd.bizuserres.s/v1/restore_share" in text
    assert "transfer_inventory" in text and "legacy_fingerprint" in text
    assert "✅ 光鸭转存成功" in text and "⚠️ 光鸭转存失败" in text


def test_asset_identity_keeps_v11_compatibility_when_digest_absent():
    old_style = hashlib.sha256("season 1/e01.mkv|100".encode("utf-8")).hexdigest()
    assert ns["_asset_identity"]("Season 1/E01.mkv", 100) == old_style
    assert ns["_asset_identity"]("Season 1/E01.mkv", 100, "abc") != old_style
