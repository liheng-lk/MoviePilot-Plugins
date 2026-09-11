"""2.0.9-r93：same-cycle production bridge + structured diag / trace continuity."""
from __future__ import annotations

import ast
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"


def _ensure_pkg() -> str:
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
        # Always reload transfer_diag / foundation when testing continuity after edits.
        if stem not in {"transfer_diag_v209", "resource_inbox_v209", "channel_message_scan_v209"}:
            return sys.modules[full]
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


def _safety_ns() -> Dict[str, Any]:
    diag = _load("transfer_diag_v209")
    ms_spec = importlib.util.spec_from_file_location("media_source_v209_for_diag", PLUGIN / "media_source_v209.py")
    ms = importlib.util.module_from_spec(ms_spec)
    assert ms_spec.loader is not None
    ms_spec.loader.exec_module(ms)
    return {
        "Any": Any,
        "Dict": Dict,
        "Iterable": __import__("typing").Iterable,
        "List": List,
        "Optional": Optional,
        "threading": __import__("threading"),
        "time": __import__("time"),
        "copy": __import__("copy"),
        "is_tmdb_source": ms.is_tmdb_source,
        "normalize_media_source_token": ms.normalize_media_source_token,
        "classify_transfer_message_v209": diag.classify_transfer_message_v209,
        "batch_summary_buckets": diag.batch_summary_buckets,
        "format_batch_summary": diag.format_batch_summary,
    }


def _bind_safety():
    src = (PLUGIN / "production_safety_v208.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "GuangYaProductionSafetyV208Mixin")
    module = ast.Module(body=[cls], type_ignores=[])
    ast.fix_missing_locations(module)
    ns = _safety_ns()
    exec(compile(module, "<safety_diag>", "exec"), ns)
    return ns["GuangYaProductionSafetyV208Mixin"]


# ---------------------------------------------------------------------------
# TEST A / B / C — same-cycle production bridge
# ---------------------------------------------------------------------------

class _Harness:
    """Minimal production-shaped harness: ingest → cursor event → matcher → transfer."""

    def __init__(self):
        self._data: Dict[str, Any] = {
            "channel_index": {"items": []},
            "channel_cursors": {},
            "channel_resource_inbox_v1": {"items": {}, "count": 0},
        }
        self._selected_subscriptions = [200]
        self._channel_new_entries_v1115: List[Dict[str, Any]] = []
        self.transfer_calls: List[Any] = []
        self.matcher_calls = 0
        self.queued_sids: List[int] = []
        self._notify = False
        self._auto_transfer_on_refresh = True
        self._media_only = True
        self._current_subscription_candidate_diags_v209 = []
        self._subscription_run_seq_v209 = 0
        self._resource_trace_max_v209 = 3000
        self._resource_trace_lock_v209 = __import__("threading").RLock()
        inbox = _load("resource_inbox_v209")
        scan = _load("channel_message_scan_v209")
        self._inbox = inbox
        self._scan = scan
        # Bind foundation helpers we need without full MRO.
        foundation = _load("foundation_ops_v209")
        # Pull methods onto instance via types
        for name in (
            "_begin_subscription_run_v209",
            "_append_candidate_diag_v209",
            "_trace_transfer_result_v209",
            "_resource_trace_id_v209",
            "_resource_trace_v209",
            "_ingest_raw_channel_page_v209",
            "_channel_slug_from_source_v209",
        ):
            if hasattr(foundation.GuangYaFoundationOpsV209Mixin, name):
                setattr(self, name, types.MethodType(getattr(foundation.GuangYaFoundationOpsV209Mixin, name), self))

    def get_data(self, key: str):
        return self._data.get(key)

    def save_data(self, key: str, value: Any):
        self._data[key] = value

    def _plugin_log(self, *args, **kwargs):
        return None

    def _is_guangya_route(self, subscribe):
        return True

    def _is_movie_subscription(self, subscribe):
        return True

    def _list_subscriptions(self, *_a, **_k):
        return [SimpleNamespace(id=200, name="目击", year=2026, season=None, tmdbid=111)]

    def _entry_can_cover_missing_v1115(self, entry, subscribe):
        return True

    def _subscriptions_for_new_channel_entries_v1115(self) -> List[int]:
        entries = list(getattr(self, "_channel_new_entries_v1115", []) or [])
        if not entries:
            return []
        matched = []
        for sub in self._list_subscriptions("N,R"):
            self.matcher_calls += 1
            for entry in entries:
                ok, _ = _entry_match(entry, sub)
                if ok:
                    matched.append(int(sub.id))
                    break
        self.queued_sids = list(matched)
        return matched

    def _try_transfer_subscription(self, subscribe, force=False, refresh_channel=True):
        self.transfer_calls.append(int(getattr(subscribe, "id", 0) or 0))
        return {"success": True, "handled": True, "message": "mock transfer"}

    def _apply_cursor_event(self, rows: List[Dict[str, Any]], before_cursors: Dict[str, int]):
        strict_new = []
        for raw in rows:
            if not isinstance(raw, dict) or raw.get("stale") or raw.get("cached_index"):
                continue
            row = dict(raw)
            source = str(row.get("source_url") or "").strip()
            message_id = str(row.get("message_id") or "").strip()
            if message_id.isdigit():
                old_cursor = int(before_cursors.get(source, 0) or 0)
                if old_cursor > 0 and int(message_id) > old_cursor:
                    strict_new.append(row)
        self._channel_new_entries_v1115 = strict_new
        return strict_new

    def refresh_like_production(self, source_url: str, page_html: str, *, force: bool = True):
        before = dict((self.get_data("channel_cursors") or {}))
        before_cursors = {str(k): int(v or 0) for k, v in before.items()}
        # Simulate foundation ingest + legacy merge for inbox-only pages.
        ingest = self._ingest_raw_channel_page_v209(page_html, source_url=source_url)
        entries = list(ingest.get("entries") or [])
        # legacy parser returns []
        legacy_entries: List[Dict[str, Any]] = []
        # Merge like legacy.refresh_channels
        by_mid = {}
        for e in legacy_entries + entries:
            mid = str(e.get("message_id") or "")
            key = f"{source_url}|{mid}"
            e = dict(e)
            e["cached_index"] = False
            e["source_url"] = source_url
            by_mid[key] = e
        fetched = list(by_mid.values())
        max_id = int(ingest.get("max_message_id") or 0)
        cursors = dict(self.get_data("channel_cursors") or {})
        if max_id > 0 and not ingest.get("parse_suspect"):
            cursors[source_url] = max(int(cursors.get(source_url) or 0), max_id)
            self.save_data("channel_cursors", cursors)
        index = dict(self.get_data("channel_index") or {})
        index["items"] = fetched
        self.save_data("channel_index", index)
        self._apply_cursor_event(fetched, before_cursors)
        # Event → matcher → transfer
        sids = self._subscriptions_for_new_channel_entries_v1115()
        for sid in sids:
            sub = next(s for s in self._list_subscriptions() if int(s.id) == int(sid))
            self._try_transfer_subscription(sub)
        return {
            "inbox_rows": int((self.get_data("channel_resource_inbox_v1") or {}).get("count") or len(
                ((self.get_data("channel_resource_inbox_v1") or {}).get("items") or {})
            )),
            "legacy_entries": len(legacy_entries),
            "channel_new_entries": len(self._channel_new_entries_v1115),
            "matcher_calls": self.matcher_calls,
            "queued_sids": list(self.queued_sids),
            "transfer_calls": list(self.transfer_calls),
            "cursor": int((self.get_data("channel_cursors") or {}).get(source_url) or 0),
            "entries": fetched,
            "ingest": ingest,
        }


def _entry_match(entry: Dict[str, Any], subscribe: Any):
    """Exact title match including title_candidates (mirrors legacy semantics)."""
    name = str(getattr(subscribe, "name", "") or "").strip()
    year = str(getattr(subscribe, "year", "") or "").strip()
    titles = [str(entry.get("title") or "").strip(), str(entry.get("match_title") or "").strip()]
    titles.extend(str(x).strip() for x in (entry.get("title_candidates") or []) if str(x).strip())
    for title in titles:
        if not title:
            continue
        # exact normalized: strip year suffix
        base = title
        if year and base.endswith(f"({year})"):
            base = base[: -(len(year) + 2)].strip()
        if base == name or title == name:
            return True, "exact_title"
        if year and f"{name} ({year})" == title:
            return True, "exact_title_year"
    return False, ""


def test_a_hidden_inbox_only_same_cycle_transfer():
    h = _Harness()
    source = "https://tgm.li668.asia/vip115hot"
    h.save_data("channel_cursors", {source: 5999})
    body = (
        '名称：目击 (2026)<br/>'
        '<div data-clipboard-text="https://www.guangyapan.com/s/TEST">复制</div>'
    )
    page = _msg("vip115hot/6000", body)
    out = h.refresh_like_production(source, page)
    assert out["legacy_entries"] == 0
    assert out["inbox_rows"] >= 1
    assert out["channel_new_entries"] == 1
    assert out["matcher_calls"] == 1
    assert out["queued_sids"] == [200]
    assert out["transfer_calls"] == [200]
    assert out["cursor"] == 6000
    assert out["entries"][0].get("cached_index") is False
    assert out["entries"][0].get("resource_trace_id")


def test_b_bootstrap_no_transfer_then_live():
    h = _Harness()
    source = "https://tgm.li668.asia/vip115hot"
    h.save_data("channel_cursors", {source: 0})
    # history 5900-6000 simplified as single page max 6000
    bodies = []
    for mid in range(5998, 6001):
        bodies.append(_msg(
            f"vip115hot/{mid}",
            f'名称：目击 (2026)<br/><div data-clipboard-text="https://www.guangyapan.com/s/H{mid}">x</div>',
        ))
    page = "".join(bodies)
    out1 = h.refresh_like_production(source, page)
    assert out1["inbox_rows"] >= 1
    assert out1["transfer_calls"] == []
    assert out1["cursor"] == 6000
    # second cycle: message 6001
    h.matcher_calls = 0
    page2 = _msg(
        "vip115hot/6001",
        '名称：目击 (2026)<br/><div data-clipboard-text="https://www.guangyapan.com/s/H6001">x</div>',
    )
    out2 = h.refresh_like_production(source, page2)
    assert out2["transfer_calls"] == [200]
    assert out2["cursor"] == 6001


def test_c_dual_parser_dedup_one_transfer():
    h = _Harness()
    source = "https://tgm.li668.asia/vip115hot"
    h.save_data("channel_cursors", {source: 5999})
    body = (
        '名称：目击 (2026)<br/>'
        '<a href="https://www.guangyapan.com/s/DUAL">可见</a>'
        '<div data-clipboard-text="https://www.guangyapan.com/s/DUAL">隐</div>'
    )
    page = _msg("vip115hot/6000", body)
    # Pretend legacy also saw the same message
    ingest = h._ingest_raw_channel_page_v209(page, source_url=source)
    inbox_entries = list(ingest.get("entries") or [])
    legacy_entry = dict(inbox_entries[0])
    legacy_entry["origin"] = "legacy"
    by_mid = {}
    for e in [legacy_entry] + inbox_entries:
        key = f"{source}|{e.get('message_id')}"
        existing = by_mid.get(key)
        if existing:
            existing["origin"] = "both"
            if e.get("resource_trace_id") and not existing.get("resource_trace_id"):
                existing["resource_trace_id"] = e.get("resource_trace_id")
        else:
            row = dict(e)
            row["cached_index"] = False
            row["source_url"] = source
            by_mid[key] = row
    fetched = list(by_mid.values())
    assert len(fetched) == 1
    h.save_data("channel_cursors", {source: 6000})
    h._apply_cursor_event(fetched, {source: 5999})
    # Force cursor event with before=5999
    h._channel_new_entries_v1115 = fetched  # already new
    sids = h._subscriptions_for_new_channel_entries_v1115()
    for sid in sids:
        h._try_transfer_subscription(SimpleNamespace(id=sid, name="目击", year=2026))
    assert len(fetched) == 1
    assert h.matcher_calls == 1
    assert h.transfer_calls == [200]


# ---------------------------------------------------------------------------
# TEST D-K — diagnostics / aggregation / idempotency / trace
# ---------------------------------------------------------------------------

def test_d_tmdb_match_then_share_expired_keeps_codes():
    diag = _load("transfer_diag_v209")
    identity = diag.identity_diag_from_assessment({
        "ok": True,
        "reason_code": "TMDB_MATCH",
        "stage": "IDENTITY",
        "evidence": {"expected_tmdb": "324580", "actual_tmdb": "324580"},
    }, resource_trace_id="TRACE-A", candidate_trace_id="guangya:TEST", sid=90)
    assert identity["reason_code"] == "TMDB_MATCH"
    assert identity["state"] == "CONTINUE"
    assert identity["terminal"] is False
    expired = diag.classify_share_inspect_failure("分享不存在或已失效", source="guangya")
    expired = diag.enrich_diag(expired, resource_trace_id="TRACE-A", candidate_trace_id="guangya:TEST", sid=90)
    assert expired["reason_code"] == "SHARE_EXPIRED"
    final = diag.aggregate_subscription_diag([identity, expired])
    assert final["reason_code"] == "SHARE_EXPIRED"
    assert final["reason_code"] not in {"MEDIA_IDENTITY_UNCONFIRMED", "TRANSFER_FAILED"}
    assert final["resource_trace_id"] == "TRACE-A"


def test_e_tmdb_mismatch_identity_stage():
    diag = _load("transfer_diag_v209")
    row = diag.identity_diag_from_assessment({
        "ok": False,
        "reason_code": "TMDB_ID_MISMATCH",
        "stage": "IDENTITY",
        "state": "FAILED_FINAL",
        "evidence": {"expected_tmdb": "324580", "actual_tmdb": ["999999"]},
    }, resource_trace_id="TRACE-E", sid=1)
    assert row["reason_code"] == "TMDB_ID_MISMATCH"
    assert row["stage"] == "IDENTITY"
    assert row["terminal"] is True


def test_f_season_mismatch():
    diag = _load("transfer_diag_v209")
    row = diag.identity_diag_from_assessment({
        "ok": False,
        "reason_code": "SEASON_MISMATCH",
        "stage": "IDENTITY",
        "evidence": {"expected_season": 1, "actual_seasons": [2]},
    })
    assert row["reason_code"] == "SEASON_MISMATCH"


def test_g_existing_episodes_skipped_not_failed():
    diag = _load("transfer_diag_v209")
    row = diag.make_diag(
        state="SKIPPED",
        reason_code="RESOURCE_CONTAINS_ONLY_EXISTING_EPISODES",
        stage="EPISODE_FENCE",
        source="guangya",
    )
    buckets = diag.batch_summary_buckets([row])
    assert buckets["failed"] == 0
    assert buckets["no_need"] == 1


def test_h_guangya_expired_magnet_pending_final_pending():
    diag = _load("transfer_diag_v209")
    rows = [
        diag.make_diag(state="FAILED_RETRYABLE", reason_code="SHARE_EXPIRED", stage="SHARE_INSPECT", source="guangya"),
        diag.make_diag(state="PENDING", reason_code="REMOTE_TASK_PENDING", stage="SUBMIT", source="magnet"),
    ]
    final = diag.aggregate_subscription_diag(rows)
    assert final["final_state"] == "PENDING"
    assert final["final_reason"] == "REMOTE_TASK_PENDING"
    buckets = diag.batch_summary_buckets([final])
    assert buckets["failed"] == 0
    assert buckets["pending"] == 1


def test_i_magnet_failed_ed2k_success_final_success():
    diag = _load("transfer_diag_v209")
    rows = [
        diag.make_diag(state="FAILED_RETRYABLE", reason_code="CLOUD_TASK_SUBMIT_FAILED", stage="SUBMIT", source="magnet"),
        diag.make_diag(state="SUCCESS", reason_code="REMOTE_VERIFY_CONFIRMED", stage="REMOTE_VERIFY", source="ed2k"),
    ]
    final = diag.aggregate_subscription_diag(rows)
    assert final["final_state"] == "SUCCESS"
    assert final["reason_code"] == "REMOTE_VERIFY_CONFIRMED"


def test_j_remote_running_is_pending():
    diag = _load("transfer_diag_v209")
    row = diag.make_diag(
        state="PENDING",
        reason_code="REMOTE_TASK_PENDING",
        stage="REMOTE_VERIFY",
        source="guangya",
        message="task running",
    )
    assert row["state"] == "PENDING"
    assert row["reason_code"] != "TRANSFER_OK"
    # classifier must prefer pending over success=True
    classified = diag.classify_transfer_message_v209({
        "success": True,
        "pending": True,
        "message": "转存任务已提交，等待目标文件落盘确认",
    })
    assert classified["reason_code"] == "REMOTE_TASK_PENDING"


def test_k_resource_trace_continuity_not_regenerated():
    diag = _load("transfer_diag_v209")
    foundation = _load("foundation_ops_v209")
    TRACE = "TRACE-A"

    class Obj(foundation.GuangYaFoundationOpsV209Mixin):
        def __init__(self):
            self._logs = []
            self._recorded = []
            self._current_subscription_run_id_v209 = "run:#90:t:1"
            self._current_subscription_candidate_diags_v209 = []

        def _plugin_log(self, *a, **k):
            self._logs.append(a)

        def _resource_trace_v209(self, **kwargs):
            return None

        def _record_transfer_diag_v209(self, subscribe, diag_row, final=True):
            self._recorded.append(diag_row)

    obj = Obj()
    # Skip init_plugin MRO
    result = {
        "success": False,
        "handled": True,
        "message": "分享不存在",
        "resource_trace_id": TRACE,
        "subscription_run_id": "run:#90:t:1",
        "candidate_diags": [
            diag.make_diag(
                state="CONTINUE",
                reason_code="TMDB_MATCH",
                stage="IDENTITY",
                resource_trace_id=TRACE,
                candidate_trace_id="guangya:X",
            ),
            diag.classify_share_inspect_failure("分享不存在"),
        ],
    }
    # enrich inspect with same resource id
    result["candidate_diags"][1] = diag.enrich_diag(
        result["candidate_diags"][1], resource_trace_id=TRACE, candidate_trace_id="guangya:X"
    )
    obj._trace_transfer_result_v209(SimpleNamespace(id=90, name="第一声啼哭"), result)
    assert result["resource_trace_id"] == TRACE
    assert result["diag"]["resource_trace_id"] == TRACE
    assert result["diag"]["reason_code"] == "SHARE_EXPIRED"
    # Must not invent sub|sid|reason hash when TRACE-A present
    invented = diag.stable_trace_id("sub", 90, "SHARE_EXPIRED")
    assert result["resource_trace_id"] != invented


def test_batch_idempotency_same_run_counted_once():
    Safety = _bind_safety()

    class Obj(Safety):
        def __init__(self):
            self._failure_batch_lock_v208 = __import__("threading").RLock()
            self._failure_batch_active_v208 = 0
            self._failure_batch_v208 = []
            self._diag_batch_v209 = []
            self._notify = False
            self.messages = []

        def _plugin_log(self, *a, **k):
            return None

        def post_message(self, **kwargs):
            self.messages.append(kwargs)

    obj = Obj()
    diag = _load("transfer_diag_v209")
    sub = SimpleNamespace(id=90, name="demo")
    row = diag.make_diag(
        state="FAILED_RETRYABLE",
        reason_code="SHARE_EXPIRED",
        stage="SHARE_INSPECT",
        subscription_run_id="run:#90:batch:1",
        sid=90,
    )
    obj._begin_failure_batch_v208()
    obj._record_transfer_diag_v209(sub, row, final=True)
    obj._record_transfer_diag_v209(sub, row, final=True)
    assert len(obj._diag_batch_v209) == 1
    buckets = diag.batch_summary_buckets(obj._diag_batch_v209)
    assert buckets["checked"] == 1


def test_classifier_already_success_not_transfer_ok():
    diag = _load("transfer_diag_v209")
    row = diag.classify_transfer_message_v209({
        "success": True,
        "already": True,
        "message": "已同步，无新增资源；进度 10/10，剩余 0",
    })
    assert row["reason_code"] in {
        "NO_NEW_ACTION",
        "CURRENT_TARGET_ALREADY_SATISFIED",
        "TRANSFER_ALREADY_RESERVED",
        "RESOURCE_CONTAINS_ONLY_EXISTING_EPISODES",
    }
    assert row["reason_code"] != "TRANSFER_OK"


def test_classifier_respects_existing_diag():
    diag = _load("transfer_diag_v209")
    existing = diag.make_diag(
        state="FAILED_FINAL",
        reason_code="TMDB_ID_MISMATCH",
        stage="IDENTITY",
        message="mismatch",
    )
    row = diag.classify_transfer_message_v209({
        "success": False,
        "message": "匹配分享均不可用",
        "diag": existing,
    })
    assert row["reason_code"] == "TMDB_ID_MISMATCH"


def test_title_candidates_exact_no_fuzzy():
    inbox = _load("resource_inbox_v209")
    meta = inbox.parse_message_title_metadata_v209("名称：赴汤蹈火/亡命闺蜜(2026)")
    assert "亡命闺蜜" in meta["title_candidates"]
    entry = {
        "title": meta.get("match_title"),
        "match_title": meta.get("match_title"),
        "title_candidates": meta.get("title_candidates"),
    }
    ok, _ = _entry_match(entry, SimpleNamespace(name="亡命闺蜜", year=2026))
    assert ok is True
    # no fuzzy: unrelated title must fail
    bad, _ = _entry_match(entry, SimpleNamespace(name="亡命天涯", year=2026))
    assert bad is False


def test_version_frozen():
    text = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
    assert 'plugin_version = "2.0.13"' in text
    assert 'build_id = "20260911-r97"' in text


def test_share_inspect_network_not_expired():
    diag = _load("transfer_diag_v209")
    assert diag.classify_share_inspect_failure("connection reset by peer")["reason_code"] == "NETWORK_ERROR"
    assert diag.classify_share_inspect_failure("timeout waiting")["reason_code"] == "HTTP_TIMEOUT"
    assert diag.classify_share_inspect_failure("分享已过期")["reason_code"] == "SHARE_EXPIRED"


def test_official_alias_continue():
    diag = _load("transfer_diag_v209")
    row = diag.identity_diag_from_assessment({
        "ok": True,
        "reason_code": "OFFICIAL_ALIAS_MATCH",
        "stage": "IDENTITY",
    })
    assert row["state"] == "CONTINUE"
    assert row["terminal"] is False
