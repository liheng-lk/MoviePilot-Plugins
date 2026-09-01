from __future__ import annotations

import html
import importlib.util
import re
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
PKG = "_guangya_channel_v190_test"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_channel_module():
    package = types.ModuleType(PKG)
    package.__path__ = [str(PLUGIN)]
    sys.modules[PKG] = package
    _load_module(f"{PKG}.source_types_v180", PLUGIN / "source_types_v180.py")
    return _load_module(f"{PKG}.channel_sources_v190", PLUGIN / "channel_sources_v190.py")


channel = _load_channel_module()


def _message_context_html(page_text: str, position: int) -> str:
    for match in re.finditer(r"(?is)<div\s+data-post=\"[^\"]+\"[^>]*>.*?</div>", page_text):
        if match.start() <= position <= match.end():
            return match.group(0)
    return page_text


def _html_to_text(fragment: str) -> str:
    value = re.sub(r"(?i)<br\s*/?>", "\n", str(fragment or ""))
    value = re.sub(r"<[^>]+>", " ", value)
    return html.unescape(re.sub(r"[ \t]+", " ", value)).strip()


def _entry_metadata(text: str, context_html: str = ""):
    post = re.search(r"data-post=\"[^\"]+/(\d+)\"", context_html)
    title = re.search(r"名称\s*[：:]\s*([^\n]+)", text)
    tmdb = re.search(r"TMDB\s*[：:]\s*(\d+)", text, re.I)
    episode = re.search(r"(S\d{1,2}E\d{1,4}|第\d{1,4}集)", text, re.I)
    return {
        "message_id": post.group(1) if post else "",
        "display_title": title.group(1).strip() if title else "",
        "tmdb_id": tmdb.group(1) if tmdb else "",
        "episode_hint": episode.group(1) if episode else "",
        "total_episode_hint": None,
        "year_hint": 2026,
    }


def _original_extract(page_text: str, source_url: str, source_label: str):
    rows = []
    for match in re.finditer(r"(?is)<div\s+data-post=\"[^\"]+\"[^>]*>.*?</div>", page_text):
        block = match.group(0)
        share = re.search(r"https://www\.guangyapan\.com/s/([A-Za-z0-9_-]+)", block)
        if not share:
            continue
        text = _html_to_text(block)
        meta = _entry_metadata(text, block)
        rows.append({
            "share_url": share.group(0),
            "share_id": share.group(1),
            "text": text,
            "source_url": source_url,
            "source_label": source_label,
            "priority": 0,
            "stale": False,
            "cached_index": False,
            "link_style": "明文链接",
            **meta,
        })
    return rows


def _entry_process_key(entry):
    return str(entry.get("share_id") or "")


def _legacy_stub():
    legacy = types.SimpleNamespace()
    legacy._extract_channel_entries = _original_extract
    legacy._entry_process_key = _entry_process_key
    legacy._message_context_html = _message_context_html
    legacy._html_to_text = _html_to_text
    legacy._entry_metadata = _entry_metadata
    return legacy


def test_share_magnet_ed2k_in_same_message_become_one_resource_group():
    legacy = _legacy_stub()
    channel.install_channel_multisource_compat(legacy)
    page = '''
    <div data-post="regengguangya/12345">
      名称：示例剧 S01E05<br>TMDB: 123456<br>
      https://www.guangyapan.com/s/shareA<br>
      magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567&dn=Show.S01E05.2160p<br>
      ed2k://|file|Show.S01E05.1080p.mkv|123456|0123456789abcdef0123456789abcdef|/
    </div>
    '''
    rows = legacy._extract_channel_entries(page, "https://tgm.li668.asia/regengguangya", "热更")
    assert len(rows) == 1
    row = rows[0]
    assert row["share_id"] == "shareA"
    assert row["resource_group_id"]
    assert row["candidate_types"] == ["guangya", "magnet", "ed2k"]
    assert [item["type"] for item in row["external_sources"]] == ["magnet", "ed2k"]


def test_external_only_channel_message_is_not_dropped():
    legacy = _legacy_stub()
    channel.install_channel_multisource_compat(legacy)
    page = '''
    <div data-post="yunpanguangya/222">
      名称：只发磁力的剧 S01E06<br>TMDB: 654321<br>
      magnet:?xt=urn:btih:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa&dn=Show.S01E06.1080p
    </div>
    '''
    rows = legacy._extract_channel_entries(page, "https://tgm.li668.asia/yunpanguangya", "分享")
    assert len(rows) == 1
    row = rows[0]
    assert row["share_url"] == ""
    assert row["message_id"] == "222"
    assert row["candidate_types"] == ["magnet"]
    assert legacy._entry_process_key(row)


def test_duplicate_magnet_in_one_post_is_collapsed_by_btih_identity():
    legacy = _legacy_stub()
    channel.install_channel_multisource_compat(legacy)
    page = '''
    <div data-post="yunpanguangya/333">
      名称：重复链接 S01E07<br>
      magnet:?xt=urn:btih:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb&dn=A<br>
      magnet:?xt=urn:btih:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb&dn=B
    </div>
    '''
    rows = legacy._extract_channel_entries(page, "https://tgm.li668.asia/yunpanguangya", "分享")
    assert len(rows) == 1
    assert len(rows[0]["external_sources"]) == 1
    assert rows[0]["external_sources"][0]["identity"] == "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
