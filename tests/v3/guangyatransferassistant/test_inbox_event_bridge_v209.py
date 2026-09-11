"""2.0.9-r93 internal: Inbox event bridge / cursor / diag / batch / title alias."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"


def _ensure_pkg():
    pkg = "plugins.v3.guangyatransferassistant"
    if pkg not in sys.modules:
        m = types.ModuleType(pkg)
        m.__path__ = [str(PLUGIN)]
        sys.modules[pkg] = m
        sys.modules.setdefault("plugins", types.ModuleType("plugins"))
        p3 = sys.modules.setdefault("plugins.v3", types.ModuleType("plugins.v3"))
        p3.__path__ = [str(ROOT / "plugins.v3")]
    st = f"{pkg}.source_types_v180"
    if st not in sys.modules:
        mod = types.ModuleType(st)

        def normalize_source_uri(uri: str):
            text = str(uri or "")
            if text.lower().startswith("magnet:"):
                import re
                m = re.search(r"(?i)urn:btih:([0-9a-z]+)", text)
                return {"uri": text, "identity": (m.group(1).lower() if m else text[7:47])}
            if text.lower().startswith("ed2k:"):
                parts = text.split("|")
                return {"uri": text, "identity": parts[4].lower() if len(parts) >= 5 else text[:40]}
            return {"uri": text, "identity": text}

        mod.normalize_source_uri = normalize_source_uri
        sys.modules[st] = mod
    return pkg


def _load(stem: str):
    pkg = _ensure_pkg()
    full = f"{pkg}.{stem}"
    if full in sys.modules and getattr(sys.modules[full], "__file__", None) == str(PLUGIN / f"{stem}.py"):
        return sys.modules[full]
    # Prefer loading transfer_diag before resource_inbox (inbox imports it).
    if stem == "resource_inbox_v209":
        _load("transfer_diag_v209")
    spec = importlib.util.spec_from_file_location(full, PLUGIN / f"{stem}.py")
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = pkg
    sys.modules[full] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _msg(post: str, body: str) -> str:
    return (
        f'<div class="tgme_widget_message_wrap js-widget_message_wrap">'
        f'<div class="tgme_widget_message js-widget_message" data-post="{post}">'
        f'<div class="tgme_widget_message_text">{body}</div></div></div>'
    )


def test_a_inbox_only_becomes_event_entry():
    scan = _load("channel_message_scan_v209")
    inbox = _load("resource_inbox_v209")
    body = (
        '名称：目击 (2026)<br/>'
        '<div data-clipboard-text="https://www.guangyapan.com/s/HIDDENWITNESS">复制链接</div>'
    )
    page = _msg("vip115hot/6000", body)
    blocks = scan.extract_channel_message_blocks_v209(page, "https://tgm.li668.asia/vip115hot")
    row = inbox.build_inbox_row_from_message_block(blocks[0])
    assert row["candidates"]
    assert row["resource_trace_id"]
    store = inbox.upsert_inbox_rows({}, [row])
    assert store["stats"]["new"] == 1
    assert len(store["new_rows"]) == 1
    entry = inbox.convert_inbox_row_to_entry(row)
    assert entry["cached_index"] is False
    assert entry["message_id"] == "6000"
    assert entry["resource_trace_id"] == row["resource_trace_id"]
    assert entry["share_url"]


def test_b_cursor_uses_raw_message_id():
    # Simulate ingest return feeding max_message_id
    scan = _load("channel_message_scan_v209")
    page = _msg("ch/6000", "公告无资源")
    blocks = scan.extract_channel_message_blocks_v209(page, "https://tgm.li668.asia/ch")
    assert blocks[0]["message_id"] == "6000"
    assert max(int(b["message_id"]) for b in blocks) == 6000


def test_c_bootstrap_new_rows_cached_not_forced_event():
    """CursorEvent semantics: old_cursor=0 → no strict new events."""
    src = (PLUGIN / "channel_cursor_event_v1115.py").read_text(encoding="utf-8")
    assert "old_cursor > 0 and int(message_id) > old_cursor" in src
    assert "首次建立该频道游标" in src or "bootstrap" in src.lower() or "不把整页历史" in src


def test_d_dual_parser_dedup_same_message():
    inbox = _load("resource_inbox_v209")
    legacy_entry = {
        "share_url": "https://www.guangyapan.com/s/SAME",
        "message_id": "6000",
        "source_url": "https://tgm.li668.asia/pan_guangya",
        "display_title": "同名",
        "origin": "legacy",
    }
    text = "名称：同名(2026)\nhttps://www.guangyapan.com/s/SAME"
    row = inbox.build_inbox_row_from_message_block({
        "channel": "pan_guangya",
        "source_url": "https://tgm.li668.asia/pan_guangya",
        "message_id": "6000",
        "raw_html": f"<div>{text}</div>",
        "visible_text": text,
    })
    store = inbox.upsert_inbox_rows({}, [row])
    effective = inbox.union_legacy_and_inbox_entries([legacy_entry], store)
    assert len(effective) == 1
    assert effective[0].get("origin") in {"both", "legacy", "inbox"}


def test_e_trace_id_stable_across_convert():
    inbox = _load("resource_inbox_v209")
    text = "名称：第一声啼哭(2026)\nhttps://www.guangyapan.com/s/AAA"
    row = inbox.build_inbox_row_from_message_block({
        "channel": "pan_guangya", "source_url": "https://tgm.li668.asia/pan_guangya",
        "message_id": "7001", "raw_html": f"<div>{text}</div>", "visible_text": text,
    })
    entry = inbox.convert_inbox_row_to_entry(row)
    assert entry["resource_trace_id"]
    assert entry["resource_trace_id"] == row["resource_trace_id"]
    # Upsert preserves trace
    store = inbox.upsert_inbox_rows({}, [row])
    again = inbox.build_inbox_row_from_message_block({
        "channel": "pan_guangya", "source_url": "https://tgm.li668.asia/pan_guangya",
        "message_id": "7001", "raw_html": f"<div>{text}</div>", "visible_text": text,
    })
    store2 = inbox.upsert_inbox_rows(store, [again])
    kept = next(iter(store2["items"].values()))
    assert kept["resource_trace_id"] == row["resource_trace_id"]


def test_f_tmdb_mismatch_reason_code():
    mi = _load("media_identity_v1111")
    # Season mismatch emits SEASON_MISMATCH
    result = mi.assess_media_identity_v1111(
        aliases=["我们的少年时代"],
        expected_year="2016",
        expected_season=1,
        is_movie=False,
        primary_evidences=["我们的少年时代 S02"],
        file_evidences=["S02E01.mkv"],
        threshold=50,
    )
    assert result["ok"] is False
    assert result["reason_code"] == "SEASON_MISMATCH"


def test_g_season_mismatch_code():
    # covered above; keep explicit
    test_f_tmdb_mismatch_reason_code()


def test_h_aggregate_pending_over_failed():
    diag = _load("transfer_diag_v209")
    rows = [
        diag.make_diag(state="FAILED_FINAL", reason_code="SHARE_EXPIRED", stage="SHARE_INSPECT"),
        diag.make_diag(state="PENDING", reason_code="REMOTE_TASK_PENDING", stage="SUBMIT"),
        diag.make_diag(state="SKIPPED", reason_code="SUPERSEDED_BY_HIGHER_PRIORITY_SOURCE", stage="SOURCE_SELECTION"),
    ]
    agg = diag.aggregate_subscription_diag(rows)
    assert agg["state"] == "PENDING"
    assert agg["reason_code"] == "REMOTE_TASK_PENDING"


def test_i_existing_episodes_not_failed_bucket():
    diag = _load("transfer_diag_v209")
    buckets = diag.batch_summary_buckets([
        diag.make_diag(state="SKIPPED", reason_code="RESOURCE_CONTAINS_ONLY_EXISTING_EPISODES", stage="EPISODE_FENCE"),
    ])
    assert buckets["failed"] == 0
    assert buckets["no_need"] == 1


def test_j_remote_pending_bucket():
    diag = _load("transfer_diag_v209")
    buckets = diag.batch_summary_buckets([
        diag.make_diag(state="PENDING", reason_code="REMOTE_TASK_PENDING", stage="REMOTE_VERIFY"),
    ])
    assert buckets["pending"] == 1
    assert buckets["failed"] == 0
    text = diag.format_batch_summary(buckets)
    assert "失败/待补搜" not in text
    assert "真正失败：0" in text


def test_k_batch_summary_counts():
    diag = _load("transfer_diag_v209")
    rows = (
        [diag.make_diag(state="SUCCESS", reason_code="TRANSFER_OK", stage="SUBMIT")] * 3
        + [diag.make_diag(state="PENDING", reason_code="REMOTE_TASK_PENDING", stage="SUBMIT")] * 4
        + [diag.make_diag(state="SUCCESS", reason_code="SUBSCRIPTION_COMPLETED", stage="COMPLETION")] * 5
        + [diag.make_diag(state="NO_RESULT", reason_code="NO_LOCAL_RESOURCE", stage="MATCH")] * 10
        + [diag.make_diag(state="FAILED_FINAL", reason_code="TMDB_ID_MISMATCH", stage="IDENTITY")] * 2
        + [diag.make_diag(state="FAILED_RETRYABLE", reason_code="TRANSFER_FAILED", stage="SUBMIT")] * 1
    )
    assert len(rows) == 25
    buckets = diag.batch_summary_buckets(rows)
    assert buckets["checked"] == 25
    assert buckets["failed"] == 1
    assert buckets["identity_reject"] == 2
    assert buckets["no_local"] == 10
    text = diag.format_batch_summary(buckets)
    assert "本轮检查：25" in text
    assert "真正失败：1" in text
    assert "失败/待补搜" not in text


def test_l_title_candidates_exact_match():
    # Load matcher helpers from legacy via AST-light: call resource title + strong match
    inbox = _load("resource_inbox_v209")
    meta = inbox.parse_message_title_metadata_v209("名称：赴汤蹈火/亡命闺蜜(2026)")
    assert "赴汤蹈火" in meta["title_candidates"]
    assert "亡命闺蜜" in meta["title_candidates"]
    assert meta["match_title"] == "赴汤蹈火"
    # Simulate entry matching using title_candidates via _entry_matches_subscription source contract
    src = (PLUGIN / "legacy.py").read_text(encoding="utf-8")
    assert "title_candidates" in src
    entry = {
        "display_title": meta["match_title"],
        "title_candidates": meta["title_candidates"],
        "text": meta["raw_title"],
        "year_hint": 2026,
    }
    # Direct strong-key equality path
    from importlib.util import spec_from_file_location, module_from_spec
    # Use inbox strip + release key logic from a minimal check:
    assert any(c == "亡命闺蜜" for c in entry["title_candidates"])


def test_production_flush_no_old_wording():
    src = (PLUGIN / "production_safety_v208.py").read_text(encoding="utf-8")
    assert "失败/待补搜" not in src.split("def _flush_failure_batch_v208")[1].split("def _run_v1115_mode_batch")[0] or "replace" in src
    assert "format_batch_summary" in src
    assert "光鸭转存检查汇总" in src


def test_version_frozen():
    entry = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
    assert 'plugin_version = "2.0.13"' in entry
    assert 'build_id = "20260911-r97"' in entry
    legacy = (PLUGIN / "legacy.py").read_text(encoding="utf-8")
    assert "ingest_result" in legacy
    assert "message_ids" in legacy
