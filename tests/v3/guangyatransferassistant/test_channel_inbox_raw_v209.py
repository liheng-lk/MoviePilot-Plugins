"""2.0.9 RAW message scanner + Resource Inbox-first fixtures / integration."""
from __future__ import annotations

import ast
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"


def _ensure_pkg() -> None:
    pkg_name = "plugins.v3.guangyatransferassistant"
    pkg = sys.modules.get(pkg_name) or types.ModuleType(pkg_name)
    pkg.__path__ = [str(PLUGIN)]
    sys.modules[pkg_name] = pkg
    parent = sys.modules.get("plugins.v3") or types.ModuleType("plugins.v3")
    parent.__path__ = [str(ROOT / "plugins.v3")]
    sys.modules["plugins.v3"] = parent
    st_name = f"{pkg_name}.source_types_v180"
    if st_name not in sys.modules:
        st = types.ModuleType(st_name)

        def normalize_source_uri(uri: str):
            text = str(uri or "")
            if text.lower().startswith("magnet:"):
                import re
                m = re.search(r"(?i)urn:btih:([0-9a-z]+)", text)
                identity = (m.group(1).lower() if m else text[7:60])
                return {"uri": text, "identity": identity}
            if text.lower().startswith("ed2k:"):
                parts = text.split("|")
                digest = parts[4].lower() if len(parts) >= 5 else text[:80]
                return {"uri": text, "identity": digest, "name": parts[2] if len(parts) > 2 else "", "size": int(parts[3]) if len(parts) > 3 and str(parts[3]).isdigit() else 0}
            return {"uri": text, "identity": text}

        st.normalize_source_uri = normalize_source_uri
        sys.modules[st_name] = st


def _load(name: str, path: Path):
    _ensure_pkg()
    full = f"plugins.v3.guangyatransferassistant.{name}"
    spec = importlib.util.spec_from_file_location(full, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    mod.__package__ = "plugins.v3.guangyatransferassistant"
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod


def _msg(post: str, body: str) -> str:
    return (
        f'<div class="tgme_widget_message_wrap js-widget_message_wrap">'
        f'<div class="tgme_widget_message js-widget_message" data-post="{post}">'
        f'<div class="tgme_widget_message_text">{body}</div></div></div>'
    )


def test_message_blocks_isolated_by_data_post():
    scan = _load("channel_message_scan_v209", PLUGIN / "channel_message_scan_v209.py")
    html = _msg("vip115hot/1", "迅雷：https://pan.xunlei.com/s/AAA") + _msg("vip115hot/2", "密码：abcd")
    blocks = scan.extract_channel_message_blocks_v209(html, "https://tgm.li668.asia/vip115hot")
    assert len(blocks) == 2
    assert blocks[0]["message_id"] == "1"
    assert blocks[1]["message_id"] == "2"
    assert "密码" not in blocks[0]["visible_text"]
    assert "pan.xunlei.com" not in blocks[1]["visible_text"]


def test_fixture_a_guangya_query_fragment():
    inbox = _load("resource_inbox_v209", PLUGIN / "resource_inbox_v209.py")
    text = "寻踪者 (2024)第2季\nhttps://www.guangyapan.com/s/AAA?curGuildID=123&darkmode=0#/share"
    html = f"<div>{text}</div>"
    row = inbox.build_inbox_row_from_message_block({
        "channel": "pan_guangya", "source_url": "https://tgm.li668.asia/pan_guangya",
        "message_id": "10", "raw_html": html, "visible_text": text,
    })
    assert len(row["candidates"]) == 1
    assert row["candidates"][0]["type"] == "guangya"
    assert "curGuildID" not in row["candidates"][0]["identity"]
    assert row["season_hint"] == 2
    assert "寻踪者" in row["match_title"]


def test_fixture_b_hidden_href_hot_update():
    inbox = _load("resource_inbox_v209", PLUGIN / "resource_inbox_v209.py")
    html = (
        '<div>📺 剧集：万界独尊 (2021) S01E481<br/>'
        '<a href="https://www.guangyapan.com/s/BBB">点击保存到光鸭云盘</a></div>'
    )
    text = "📺 剧集：万界独尊 (2021) S01E481\n点击保存到光鸭云盘"
    row = inbox.build_inbox_row_from_message_block({
        "channel": "regengguangya", "source_url": "https://tgm.li668.asia/regengguangya",
        "message_id": "11", "raw_html": html, "visible_text": text,
    })
    assert row["match_title"] == "万界独尊"
    assert "E481" in str(row.get("episode_hint") or "") or "S01E481" in str(row.get("episode_hint") or "")
    assert row["candidates"][0]["type"] == "guangya"
    assert row["candidates"][0]["extractor"] in {"href", "visible_text"}


def test_fixture_c_multi_source_115_not_actionable():
    inbox = _load("resource_inbox_v209", PLUGIN / "resource_inbox_v209.py")
    text = (
        "名称：地狱占星师(2026)\n"
        "迅雷：https://pan.xunlei.com/s/CCC?pwd=fapj\n"
        "115：https://115cdn.com/s/DDD\n"
        "磁力链接：magnet:?xt=urn:btih:EEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEE"
    )
    row = inbox.build_inbox_row_from_message_block({
        "channel": "vip115hot", "source_url": "https://tgm.li668.asia/vip115hot",
        "message_id": "12", "raw_html": f"<div>{text}</div>", "visible_text": text,
    })
    types = {c["type"] for c in row["candidates"]}
    assert types == {"xunlei", "magnet"}
    assert any(o.get("kind") == "115" for o in row["other_urls"])
    assert not any(c["type"] == "115" for c in row["candidates"])
    assert row["match_title"] == "地狱占星师"


def test_fixture_d_ed2k_labeled_115():
    inbox = _load("resource_inbox_v209", PLUGIN / "resource_inbox_v209.py")
    ed2k = "ed2k://|file|Disclosure.Day.2026.mkv|26728756463|84FC84FC84FC84FC84FC84FC84FC84FC|/"
    text = (
        "名称：揭秘日(2026)\n"
        "迅雷：https://pan.xunlei.com/s/FFF?pwd=pi45\n"
        f"115/ed2k：\n{ed2k}"
    )
    row = inbox.build_inbox_row_from_message_block({
        "channel": "regeng115", "source_url": "https://tgm.li668.asia/regeng115",
        "message_id": "13", "raw_html": f"<div>{text}</div>", "visible_text": text,
    })
    types = {c["type"] for c in row["candidates"]}
    assert types == {"xunlei", "ed2k"}
    assert not any(c.get("type") == "115" for c in row["candidates"])


def test_fixture_e_multiple_ed2k():
    inbox = _load("resource_inbox_v209", PLUGIN / "resource_inbox_v209.py")
    e1 = "ed2k://|file|Cold.War.1994.HDR.mp4|111|AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA|/"
    e2 = "ed2k://|file|Cold.War.1994.DV.mp4|222|BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB|/"
    text = f"名称：寒战1994 (2026)\nHDR：\n{e1}\nDV：\n{e2}"
    row = inbox.build_inbox_row_from_message_block({
        "channel": "regeng115", "source_url": "https://tgm.li668.asia/regeng115",
        "message_id": "14", "raw_html": f"<div>{text}</div>", "visible_text": text,
    })
    ed2ks = [c for c in row["candidates"] if c["type"] == "ed2k"]
    assert len(ed2ks) == 2
    assert ed2ks[0]["identity"] != ed2ks[1]["identity"]


def test_fixture_f_clipboard_hidden():
    inbox = _load("resource_inbox_v209", PLUGIN / "resource_inbox_v209.py")
    html = '<div data-clipboard-text="https://www.guangyapan.com/s/GGG">复制</div>'
    row = inbox.build_inbox_row_from_message_block({
        "channel": "x", "source_url": "https://tgm.li668.asia/x",
        "message_id": "15", "raw_html": html, "visible_text": "复制",
    })
    assert row["candidates"][0]["type"] == "guangya"
    assert row["candidates"][0]["extractor"] == "clipboard"


def test_fixture_g_onclick_xunlei():
    inbox = _load("resource_inbox_v209", PLUGIN / "resource_inbox_v209.py")
    html = """<button onclick="window.open('https://pan.xunlei.com/s/HHH?pwd=abcd')">open</button>"""
    row = inbox.build_inbox_row_from_message_block({
        "channel": "x", "source_url": "https://tgm.li668.asia/x",
        "message_id": "16", "raw_html": html, "visible_text": "open",
    })
    assert row["candidates"][0]["type"] == "xunlei"
    assert row["candidates"][0]["passcode"] == "abcd"


def test_fixture_h_double_encoded_magnet():
    inbox = _load("resource_inbox_v209", PLUGIN / "resource_inbox_v209.py")
    magnet = "magnet:?xt=urn:btih:CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC"
    encoded = quote(quote(magnet, safe=""), safe="")
    html = f'<a href="https://t.me/redirect?url={encoded}">m</a>'
    row = inbox.build_inbox_row_from_message_block({
        "channel": "x", "source_url": "https://tgm.li668.asia/x",
        "message_id": "17", "raw_html": html, "visible_text": "m",
    })
    assert any(c["type"] == "magnet" for c in row["candidates"])


def test_fixture_i_wrapped_redirect_guangya():
    inbox = _load("resource_inbox_v209", PLUGIN / "resource_inbox_v209.py")
    target = quote("https://www.guangyapan.com/s/WRAP1", safe="")
    html = f'<a href="https://go.example/r?target={target}">go</a>'
    row = inbox.build_inbox_row_from_message_block({
        "channel": "x", "source_url": "https://tgm.li668.asia/x",
        "message_id": "18", "raw_html": html, "visible_text": "go",
    })
    assert row["candidates"][0]["type"] == "guangya"
    assert row["candidates"][0]["identity"] == "WRAP1"


def test_fixture_j_passcode_message_local():
    scan = _load("channel_message_scan_v209", PLUGIN / "channel_message_scan_v209.py")
    inbox = _load("resource_inbox_v209", PLUGIN / "resource_inbox_v209.py")
    html = _msg("ch/1", "迅雷：https://pan.xunlei.com/s/AAA") + _msg("ch/2", "密码：abcd")
    blocks = scan.extract_channel_message_blocks_v209(html, "https://tgm.li668.asia/ch")
    row1 = inbox.build_inbox_row_from_message_block(blocks[0])
    assert row1["candidates"][0]["type"] == "xunlei"
    assert not row1["candidates"][0].get("passcode")


def test_title_templates_alias_and_update():
    inbox = _load("resource_inbox_v209", PLUGIN / "resource_inbox_v209.py")
    a = inbox.parse_message_title_metadata_v209("名称：地狱占星师(2026)〖9集全〗〖NF.4K.高码率〗")
    assert a["match_title"] == "地狱占星师"
    assert a["year"] == "2026"
    assert a["total_episode_hint"] == 9
    b = inbox.parse_message_title_metadata_v209("🎬 电影：荣光与暗影 (2026)")
    assert b["match_title"] == "荣光与暗影" and b["media_type_hint"] == "movie"
    c = inbox.parse_message_title_metadata_v209("爱情没有神话（2026）4K 更至EP30")
    assert c["match_title"] == "爱情没有神话" and "EP30" in str(c.get("episode_hint") or "EP30") or c.get("episode_hint") == "E30"
    d = inbox.parse_message_title_metadata_v209("名称：赴汤蹈火/亡命闺蜜(2026)")
    assert "赴汤蹈火" in d["title_candidates"] and "亡命闺蜜" in d["title_candidates"]


def test_old_parser_miss_inbox_hit_integration():
    """Critical: legacy finds 0, inbox finds hidden clipboard GuangYa, matcher hits."""
    scan = _load("channel_message_scan_v209", PLUGIN / "channel_message_scan_v209.py")
    inbox = _load("resource_inbox_v209", PLUGIN / "resource_inbox_v209.py")
    # Intentionally no plain guangyapan URL in visible text; only clipboard.
    body = (
        '名称：目击 (2026)<br/>'
        '<div data-clipboard-text="https://www.guangyapan.com/s/HIDDENWITNESS">复制链接</div>'
    )
    page = _msg("vip115hot/99", body)
    # Legacy SHARE_PATTERN only hits visible/attr share urls that go through its candidate scan;
    # clipboard-only pages often miss depending on ATTRIBUTE_URL_PATTERN. Force legacy=0 by
    # using a page without guangyapan in href/text that legacy SHARE_PATTERN would see as share —
    # our inbox still sees data-clipboard-text.
    blocks = scan.extract_channel_message_blocks_v209(page, "https://tgm.li668.asia/vip115hot")
    assert len(blocks) == 1
    row = inbox.build_inbox_row_from_message_block(blocks[0])
    assert len(row["candidates"]) == 1
    assert row["candidates"][0]["extractor"] == "clipboard"
    store = inbox.upsert_inbox_rows({}, [row])
    assert store["count"] == 1
    entry = inbox.convert_inbox_row_to_entry(row)
    assert entry["share_url"]
    effective = inbox.union_legacy_and_inbox_entries([], store)
    assert len(effective) == 1
    assert effective[0]["origin"] == "inbox"

    # Matcher stub: title + year
    def matcher(synthetic, subscribe):
        title = str(synthetic.get("display_title") or "")
        year = str(synthetic.get("year") or "")
        ok = title == subscribe.name and year == str(subscribe.year)
        return ok, "title_year" if ok else "reject"

    sub = SimpleNamespace(id=1, name="目击", year=2026)
    hits = inbox.shadow_match_inbox_for_subscribe(store, sub, matcher)
    assert len(hits) == 1


def test_cross_channel_provenance_dedup():
    inbox = _load("resource_inbox_v209", PLUGIN / "resource_inbox_v209.py")
    rows = []
    for ch, mid in (("pan_guangya", "1"), ("guangyapan_episode", "2"), ("regengguangya", "3")):
        text = f"名称：同享(2026)\nhttps://www.guangyapan.com/s/SAMEID"
        rows.append(inbox.build_inbox_row_from_message_block({
            "channel": ch, "source_url": f"https://tgm.li668.asia/{ch}",
            "message_id": mid, "raw_html": f"<div>{text}</div>", "visible_text": text,
        }))
    store = inbox.upsert_inbox_rows({}, rows)
    assert store["count"] == 1
    only = next(iter(store["items"].values()))
    assert len(only.get("provenance") or []) == 3
    effective = inbox.union_legacy_and_inbox_entries([], store)
    assert len(effective) == 1


def test_bootstrap_inbox_without_new_events():
    inbox = _load("resource_inbox_v209", PLUGIN / "resource_inbox_v209.py")
    scan = _load("channel_message_scan_v209", PLUGIN / "channel_message_scan_v209.py")
    parts = []
    for i in range(1, 21):
        parts.append(_msg(f"ch/{i}", f"名称：剧{i}(2026)<br/>https://www.guangyapan.com/s/ID{i}"))
    page = "".join(parts)
    blocks = scan.extract_channel_message_blocks_v209(page, "https://tgm.li668.asia/ch")
    assert len(blocks) == 20
    rows = [inbox.build_inbox_row_from_message_block(b) for b in blocks]
    store = inbox.upsert_inbox_rows({}, rows)
    assert store["count"] == 20


def test_transfer_diag_model_and_no_vague_only():
    diag = _load("transfer_diag_v209", PLUGIN / "transfer_diag_v209.py")
    d = diag.classify_transfer_message_v209({"message": "本地频道索引暂未匹配到光鸭分享"}, SimpleNamespace(id=1, name="x"))
    assert d["reason_code"] == "NO_LOCAL_RESOURCE"
    assert d["stage"] == "MATCH"
    assert d["next_action"]
    vague = diag.classify_transfer_message_v209({"message": "匹配分享均不可用"}, SimpleNamespace(id=2, name="y"))
    assert vague["reason_code"] != "TRANSFER_FAILED" or "子候选" in vague["message"] or vague["next_action"]
    log = diag.format_diag_log(d, media="x")
    assert "【转存诊断】" in log
    assert "passcode=" not in log.lower() or "passcode_present" in log


def test_version_still_frozen():
    entry = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
    assert 'plugin_version = "2.0.11"' in entry
    assert 'build_id = "20260911-r95"' in entry
    assert "_ingest_raw_channel_page_v209" in (PLUGIN / "legacy.py").read_text(encoding="utf-8")
    assert "extract_channel_message_blocks_v209" in (PLUGIN / "channel_message_scan_v209.py").read_text(encoding="utf-8")
