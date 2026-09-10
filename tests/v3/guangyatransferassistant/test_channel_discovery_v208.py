"""2.0.8 P1：六频道 discovery fixture — 按消息内容识别协议，不按频道名硬编码，无 115 API。"""

from __future__ import annotations

import html
import importlib.util
import re
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
PKG = "_guangya_channel_v208_test"
LEGACY_TEXT = (PLUGIN / "legacy.py").read_text(encoding="utf-8")


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_stack():
    package = types.ModuleType(PKG)
    package.__path__ = [str(PLUGIN)]
    sys.modules[PKG] = package
    _load_module(f"{PKG}.source_types_v180", PLUGIN / "source_types_v180.py")
    channel = _load_module(f"{PKG}.channel_sources_v190", PLUGIN / "channel_sources_v190.py")
    matrix = _load_module(f"{PKG}.channel_sources_v11214", PLUGIN / "channel_sources_v11214.py")
    return channel, matrix


channel, matrix = _load_stack()


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


def _legacy_stub():
    legacy = types.SimpleNamespace()
    legacy._extract_channel_entries = _original_extract
    legacy._entry_process_key = lambda entry: str(entry.get("share_id") or entry.get("message_id") or "")
    legacy._message_context_html = _message_context_html
    legacy._html_to_text = _html_to_text
    legacy._entry_metadata = _entry_metadata
    legacy.logger = types.SimpleNamespace(info=lambda *a, **k: None)
    legacy.DEFAULT_CHANNEL_URLS = [
        "https://tgm.li668.asia/regengguangya",
        "https://tgm.li668.asia/guangyapan_episode",
        "https://tgm.li668.asia/guangya_hdhive",
        "https://tgm.li668.asia/pan_guangya",
        "https://tgm.li668.asia/regeng115",
        "https://tgm.li668.asia/vip115hot",
    ]
    return legacy


def _install(legacy):
    channel.install_channel_multisource_compat(legacy)
    matrix.install_channel_source_matrix_v11214(legacy)
    return legacy


def test_default_channels_include_six_discovery_paths():
    assert "https://tgm.li668.asia/regengguangya" in LEGACY_TEXT
    assert "https://tgm.li668.asia/guangyapan_episode" in LEGACY_TEXT
    assert "https://tgm.li668.asia/guangya_hdhive" in LEGACY_TEXT
    assert "https://tgm.li668.asia/pan_guangya" in LEGACY_TEXT
    assert "https://tgm.li668.asia/regeng115" in LEGACY_TEXT
    assert "https://tgm.li668.asia/vip115hot" in LEGACY_TEXT
    # 明确不引入 115 网盘客户端
    assert "115Client" not in LEGACY_TEXT
    assert "115.com/share" not in LEGACY_TEXT.lower()


def test_fixture_vip115hot_xunlei_plus_ed2k_same_group():
    legacy = _install(_legacy_stub())
    page = '''
    <div data-post="vip115hot/9001">
      名称：脱敏剧 S01E02<br>TMDB: 111001<br>
      https://pan.xunlei.com/s/TESTXLSHARE01?pwd=ab12<br>
      提取码：ab12<br>
      ed2k://|file|Show.S01E02.1080p.mkv|1001|aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa|/<br>
      ed2k://|file|Show.S01E02.2160p.mkv|1002|bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb|/
    </div>
    '''
    rows = legacy._extract_channel_entries(page, "https://tgm.li668.asia/vip115hot", "vip115hot")
    assert len(rows) >= 1
    row = rows[0]
    assert row.get("xunlei_sources")
    assert str(row["xunlei_sources"][0].get("share_id")) == "TESTXLSHARE01"
    assert str(row["xunlei_sources"][0].get("passcode")) == "ab12"
    ed2k = [item for item in (row.get("external_sources") or []) if item.get("type") == "ed2k"]
    assert len(ed2k) == 2
    types_ = set(row.get("candidate_types") or [])
    assert "xunlei" in types_ and "ed2k" in types_
    assert "115" not in types_


def test_fixture_regeng115_multi_ed2k_finditer():
    legacy = _install(_legacy_stub())
    page = '''
    <div data-post="regeng115/9002">
      名称：多集脱敏 S01<br>
      E01 ed2k://|file|E01.mkv|11|11111111111111111111111111111111|/<br>
      E02 ed2k://|file|E02.mkv|22|22222222222222222222222222222222|/<br>
      E03 ed2k://|file|E03.mkv|33|33333333333333333333333333333333|/
    </div>
    '''
    rows = legacy._extract_channel_entries(page, "https://tgm.li668.asia/regeng115", "regeng115")
    assert rows
    ed2k = [item for item in (rows[0].get("external_sources") or []) if item.get("type") == "ed2k"]
    assert len(ed2k) == 3


def test_fixture_guangyapan_episode_single_share():
    legacy = _install(_legacy_stub())
    page = '''
    <div data-post="guangyapan_episode/9003">
      名称：单集脱敏 S01E08<br>TMDB: 222002<br>
      https://www.guangyapan.com/s/EpisodeOnly01
    </div>
    '''
    rows = legacy._extract_channel_entries(
        page, "https://tgm.li668.asia/guangyapan_episode", "guangyapan_episode"
    )
    assert len(rows) == 1
    assert rows[0]["share_id"] == "EpisodeOnly01"
    assert "guangya" in (rows[0].get("candidate_types") or [])


def test_fixture_pan_guangya_season_pack():
    legacy = _install(_legacy_stub())
    page = '''
    <div data-post="pan_guangya/9004">
      名称：整季脱敏 S01<br>
      https://www.guangyapan.com/s/SeasonPack01?code=zz99
    </div>
    '''
    rows = legacy._extract_channel_entries(page, "https://tgm.li668.asia/pan_guangya", "pan_guangya")
    assert rows and rows[0]["share_id"] == "SeasonPack01"


def test_fixture_guangya_hdhive_mixed_links():
    legacy = _install(_legacy_stub())
    page = '''
    <div data-post="guangya_hdhive/9005">
      名称：混合脱敏 (2026)<br>
      https://www.guangyapan.com/s/HiveShare01<br>
      magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567&dn=Hive<br>
      <a href="https://pan.xunlei.com/s/HiveXL01?pwd=qq11">迅雷</a>
    </div>
    '''
    rows = legacy._extract_channel_entries(
        page, "https://tgm.li668.asia/guangya_hdhive", "guangya_hdhive"
    )
    assert rows
    row = rows[0]
    assert row.get("share_id") == "HiveShare01"
    assert any(item.get("type") == "magnet" for item in (row.get("external_sources") or []))
    assert row.get("xunlei_sources")


def test_fixture_regengguangya_xunlei_or_guangya_plus_ed2k():
    legacy = _install(_legacy_stub())
    page = '''
    <div data-post="regengguangya/9006">
      名称：热更脱敏 S01E01<br>
      https://www.guangyapan.com/s/HotShare01<br>
      ed2k://|file|Hot.S01E01.mkv|55|55555555555555555555555555555555|/
    </div>
    '''
    rows = legacy._extract_channel_entries(
        page, "https://tgm.li668.asia/regengguangya", "regengguangya"
    )
    assert rows
    row = rows[0]
    assert row["share_id"] == "HotShare01"
    assert any(item.get("type") == "ed2k" for item in (row.get("external_sources") or []))


def test_channel_name_does_not_force_protocol():
    """vip115hot 消息若只有光鸭分享，应识别为 guangya，而非 115。"""
    legacy = _install(_legacy_stub())
    page = '''
    <div data-post="vip115hot/9007">
      名称：仅光鸭<br>
      https://www.guangyapan.com/s/OnlyGy01
    </div>
    '''
    rows = legacy._extract_channel_entries(page, "https://tgm.li668.asia/vip115hot", "vip115hot")
    assert rows
    types_ = rows[0].get("candidate_types") or []
    assert types_ == ["guangya"] or types_[0] == "guangya"
    assert "115" not in types_


def test_ed2k_from_href_attribute():
    legacy = _install(_legacy_stub())
    page = '''
    <div data-post="regeng115/9008">
      名称：按钮链接<br>
      <a href="ed2k://|file|Btn.mkv|9|99999999999999999999999999999999|/">下载</a>
    </div>
    '''
    rows = legacy._extract_channel_entries(page, "https://tgm.li668.asia/regeng115", "regeng115")
    assert rows
    ed2k = [item for item in (rows[0].get("external_sources") or []) if item.get("type") == "ed2k"]
    assert len(ed2k) == 1
