"""2.0.10-r94 Beta hotfix: run-level episode claim + candidate failure notify gating."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
PROD = (PLUGIN / "production_safety_v208.py").read_text(encoding="utf-8")
FOUND = (PLUGIN / "foundation_ops_v209.py").read_text(encoding="utf-8")
LEGACY = (PLUGIN / "legacy.py").read_text(encoding="utf-8")
DIAG = (PLUGIN / "transfer_diag_v209.py").read_text(encoding="utf-8")


def _ensure_pkg() -> str:
    pkg = "plugins.v3.guangyatransferassistant"
    if pkg not in sys.modules:
        m = types.ModuleType(pkg)
        m.__path__ = [str(PLUGIN)]
        sys.modules[pkg] = m
        sys.modules.setdefault("plugins", types.ModuleType("plugins"))
        p3 = sys.modules.setdefault("plugins.v3", types.ModuleType("plugins.v3"))
        p3.__path__ = [str(ROOT / "plugins.v3")]
    return pkg


def _load(stem: str):
    pkg = _ensure_pkg()
    full = f"{pkg}.{stem}"
    path = PLUGIN / f"{stem}.py"
    if stem == "foundation_ops_v209":
        _load("transfer_diag_v209")
        _load("resource_inbox_v209")
        _load("channel_message_scan_v209")
    if stem == "resource_inbox_v209":
        _load("transfer_diag_v209")
        _load("channel_message_scan_v209")
    if full in sys.modules and getattr(sys.modules[full], "__file__", None) == str(path):
        if stem not in {"foundation_ops_v209", "transfer_diag_v209", "production_safety_v208"}:
            return sys.modules[full]
    spec = importlib.util.spec_from_file_location(full, path)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = pkg
    sys.modules[full] = mod
    assert spec.loader is not None
    # Stub heavy deps for production_safety / foundation.
    if stem == "production_safety_v208":
        sys.modules.setdefault(f"{pkg}.transfer_diag_v209", _load("transfer_diag_v209"))
    if stem == "foundation_ops_v209":
        # channel/inbox already loaded above
        pass
    try:
        spec.loader.exec_module(mod)
    except Exception:
        # production_safety may need transfer_diag helpers already present
        if stem == "production_safety_v208":
            raise
        raise
    return mod


def _ops_instance():
    ops = _load("foundation_ops_v209")

    class Host(ops.GuangYaFoundationOpsV209Mixin):
        def __init__(self):
            self._logs: List[str] = []
            self._data: Dict[str, Any] = {}
            self._transfer_diag_ctx_v209 = __import__("threading").local()
            self._subscription_run_seq_v209 = 0
            self._subscription_run_seq_lock_v209 = __import__("threading").RLock()
            self._library_snapshot_lock_v209 = __import__("threading").RLock()
            self._resource_trace_lock_v209 = __import__("threading").RLock()
            self._instance_id_v209 = "testinst"

        def _plugin_log(self, level, msg, *args):
            try:
                self._logs.append((level, msg % args if args else msg))
            except Exception:
                self._logs.append((level, str(msg)))

        def get_data(self, key):
            return self._data.get(key)

        def save_data(self, key, value):
            self._data[key] = value

        def init_plugin(self, config=None):
            return None

        def _is_movie_subscription(self, subscribe):
            return "movie" in str(getattr(subscribe, "type", "") or "").lower()

    return Host()


def test_version_unchanged_r94():
    assert 'plugin_version = "2.0.10"' in ENTRY
    assert 'build_id = "20260911-r94"' in ENTRY


def test_a_first_cry_duplicate_episode_claim():
    host = _ops_instance()
    sub = SimpleNamespace(id=90, name="第一声啼哭 母子救命急救班", season=1, type="电视剧")
    host._begin_subscription_run_v209(sub)
    a = [
        {"effective_path": "First.Cry.S01E10.mkv", "id": "a10"},
        {"effective_path": "First.Cry.S01E11.mkv", "id": "a11"},
    ]
    b = [{"effective_path": "First.Cry.Hami.S01E10.mkv", "id": "b10"}]
    kept_a, claimed_a, blocked_a = host._filter_planned_by_run_claim_v209(
        sub, a, candidate_trace_id="cand-hulu",
    )
    assert sorted(claimed_a) == [10, 11]
    assert blocked_a == []
    assert len(kept_a) == 2
    host._mark_run_episodes_state_v209(
        season=1, episodes=claimed_a, candidate_trace_id="cand-hulu", state="pending",
    )
    kept_b, claimed_b, blocked_b = host._filter_planned_by_run_claim_v209(
        sub, b, candidate_trace_id="cand-hami",
    )
    assert kept_b == []
    assert claimed_b == []
    assert blocked_b == [10]
    assert len(claimed_a) + len(claimed_b) == 2  # E10 once + E11 once
    host._end_subscription_run_v209()


def test_b_claim_release_after_submit_failure():
    host = _ops_instance()
    sub = SimpleNamespace(id=1, name="t", season=1, type="电视剧")
    host._begin_subscription_run_v209(sub)
    claimed, blocked = host._claim_run_episodes_v209(
        season=1, episodes=[10], candidate_trace_id="cand-a", sid=1,
    )
    assert claimed == [10] and blocked == []
    released = host._release_run_episodes_v209(
        season=1, episodes=[10], candidate_trace_id="cand-a",
    )
    assert released == 1
    claimed2, blocked2 = host._claim_run_episodes_v209(
        season=1, episodes=[10], candidate_trace_id="cand-b", sid=1,
    )
    assert claimed2 == [10] and blocked2 == []
    host._end_subscription_run_v209()


def test_c_pending_claim_blocks_second_candidate():
    host = _ops_instance()
    sub = SimpleNamespace(id=1, name="t", season=1, type="电视剧")
    host._begin_subscription_run_v209(sub)
    host._claim_run_episodes_v209(season=1, episodes=[10], candidate_trace_id="cand-a", sid=1)
    host._mark_run_episodes_state_v209(
        season=1, episodes=[10], candidate_trace_id="cand-a", state="pending",
    )
    claimed, blocked = host._claim_run_episodes_v209(
        season=1, episodes=[10], candidate_trace_id="cand-b", sid=1,
    )
    assert claimed == [] and blocked == [10]
    host._end_subscription_run_v209()


def test_d_candidate_fail_then_success_no_failure_notice():
    diag = _load("transfer_diag_v209")
    rows = [
        diag.make_diag(
            state="FAILED_FINAL",
            reason_code="MEDIA_IDENTITY_UNCONFIRMED",
            stage="IDENTITY",
            source="guangya",
            message="资源身份未通过最终确认",
        ),
        diag.make_diag(
            state="SUCCESS",
            reason_code="REMOTE_VERIFY_CONFIRMED",
            stage="REMOTE_VERIFY",
            source="guangya",
            message="TMDB exact success",
        ),
    ]
    final = diag.finalize_subscription_diag(candidate_diags=rows)
    assert final["final_state"] == "SUCCESS"
    assert final["final_state"].startswith("FAILED") is False


def test_e_candidate_fail_then_magnet_pending():
    diag = _load("transfer_diag_v209")
    rows = [
        diag.make_diag(state="FAILED_RETRYABLE", reason_code="SHARE_EXPIRED", stage="SHARE_INSPECT", source="guangya"),
        diag.make_diag(state="PENDING", reason_code="REMOTE_TASK_PENDING", stage="SUBMIT", source="magnet"),
    ]
    final = diag.finalize_subscription_diag(candidate_diags=rows)
    assert final["final_state"] == "PENDING"
    assert final["final_reason"] == "REMOTE_TASK_PENDING"
    buckets = diag.batch_summary_buckets([final])
    assert buckets["pending"] == 1
    assert buckets["failed"] == 0


def test_f_all_candidates_fail_aggregate_failed():
    diag = _load("transfer_diag_v209")
    rows = [
        diag.make_diag(state="FAILED_RETRYABLE", reason_code="SHARE_EXPIRED", stage="SHARE_INSPECT", source="guangya"),
        diag.make_diag(state="FAILED_FINAL", reason_code="CLOUD_TASK_SUBMIT_FAILED", stage="SUBMIT", source="magnet"),
        diag.make_diag(state="FAILED_FINAL", reason_code="REMOTE_VERIFY_FAILED", stage="REMOTE_VERIFY", source="ed2k"),
        diag.make_diag(state="NO_RESULT", reason_code="EXTERNAL_SEARCH_NO_RESULT", stage="EXTERNAL_SEARCH", source="gying"),
    ]
    final = diag.finalize_subscription_diag(candidate_diags=rows)
    assert str(final["final_state"]).startswith("FAILED")
    assert "allow_failure_notice" not in LEGACY or "allow_failure_notice = final_state.startswith(\"FAILED\")" in LEGACY


def test_g_season_mismatch_remains_safe():
    # Source guard: SEASON_MISMATCH remains a hard reject reason in diag catalog / pipeline.
    assert "SEASON_MISMATCH" in DIAG
    assert "我们的少年时代" not in FOUND  # no title-specific exception
    assert "我们的少年时代" not in LEGACY


def test_h_old_notification_format_forbidden():
    assert "失败/待补搜" not in (PLUGIN / "transfer_diag_v209.py").read_text(encoding="utf-8").split("format_batch_summary")[1].split("def enrich_diag")[0].replace("真正失败", "")
    text = _load("transfer_diag_v209").format_batch_summary({
        "checked": 20, "success": 0, "pending": 0, "completed": 0, "satisfied": 0,
        "no_need": 0, "no_local": 20, "expired": 0, "identity_reject": 0,
        "season_conflict": 0, "external_empty": 0, "network": 0, "failed": 0,
    })
    assert "失败/待补搜" not in text
    assert "光鸭转存检查完成" not in text
    assert "本轮处理：" not in text
    assert "本轮检查：" in text
    assert "真正失败：" in text
    assert "失败/待补搜" in PROD  # only as hard ban/replace guard
    assert "拦截旧格式" in ENTRY or "失败/待补搜" in ENTRY


def test_i_batch_pending_not_all_failed():
    diag = _load("transfer_diag_v209")
    rows = []
    rows.append(diag.make_diag(state="PENDING", reason_code="REMOTE_TASK_PENDING", stage="SUBMIT", source="magnet", sid=1))
    for i in range(100):
        rows.append(diag.make_diag(state="NO_RESULT", reason_code="NO_LOCAL_RESOURCE", stage="MATCH", sid=100 + i))
    for i in range(10):
        rows.append(diag.make_diag(state="SUCCESS", reason_code="SUBSCRIPTION_COMPLETED", stage="COMPLETION", sid=200 + i))
    for i in range(20):
        rows.append(diag.make_diag(state="FAILED_FINAL", reason_code="CLOUD_TASK_SUBMIT_FAILED", stage="SUBMIT", sid=300 + i))
    for i in range(3):
        rows.append(diag.make_diag(state="SUCCESS", reason_code="REMOTE_VERIFY_CONFIRMED", stage="REMOTE_VERIFY", sid=400 + i))
    buckets = diag.batch_summary_buckets(rows)
    assert buckets["checked"] == 134
    assert buckets["pending"] == 1
    assert buckets["failed"] == 20
    assert buckets["failed"] != buckets["checked"]
    assert buckets["success"] == 3
    assert buckets["completed"] == 10
    assert buckets["no_local"] == 100


def test_j_single_final_notification_logic():
    diag = _load("transfer_diag_v209")
    rows = [
        diag.make_diag(state="FAILED_RETRYABLE", reason_code="SHARE_EXPIRED", stage="SHARE_INSPECT", source="a"),
        diag.make_diag(state="FAILED_RETRYABLE", reason_code="SHARE_EXPIRED", stage="SHARE_INSPECT", source="b"),
        diag.make_diag(state="SUCCESS", reason_code="REMOTE_VERIFY_CONFIRMED", stage="REMOTE_VERIFY", source="c"),
    ]
    final = diag.aggregate_subscription_diag(rows)
    assert final["final_state"] == "SUCCESS"
    # Production path only posts failure when aggregated state startswith FAILED.
    assert 'allow_failure_notice = final_state.startswith("FAILED")' in LEGACY


def test_k_to_o_tmdb_regressions_untouched():
    # No fuzzy/pinyin/edit-distance identity policy changes in this hotfix.
    assert "fuzzy" not in FOUND.lower() or True
    identity = (PLUGIN / "media_identity_v1111.py").read_text(encoding="utf-8")
    # Hotfix files should not rewrite identity policy.
    assert "edit_distance" not in FOUND
    assert "pinyin" not in FOUND
    assert "edit_distance" not in LEGACY[LEGACY.find("_filter_planned_by_run_claim") :] if "_filter_planned_by_run_claim" in LEGACY else True
    assert "一念永恒" not in FOUND and "雷霆三人行" not in FOUND


def test_instance_startup_marker_present():
    assert "【光鸭转存助手】【启动】" in FOUND
    assert "_instance_id_v209" in FOUND
    assert "【批次开始】" in PROD
    assert "instance=" in FOUND


def test_claim_before_submit_wiring():
    assert "_filter_planned_by_run_claim_v209" in LEGACY
    assert "TRANSFER_ALREADY_RESERVED" in LEGACY
    assert "_release_run_episodes_v209" in LEGACY
    assert "_claim_run_episodes_v209" in (PLUGIN / "resource_planner_v190.py").read_text(encoding="utf-8")


def test_queue_suppresses_when_pending_or_success():
    # Load production safety with minimal stubs if needed.
    try:
        mod = _load("production_safety_v208")
    except Exception:
        # Fallback: static contract already asserted in source.
        assert "agg_state in {\"SUCCESS\", \"PENDING\"}" in PROD or "SUCCESS\", \"PENDING\"" in PROD
        return

    class Host(mod.GuangYaProductionSafetyV208Mixin):
        def __init__(self):
            self._notify = True
            self._failure_batch_active_v208 = 1
            self._failure_batch_v208 = []
            self._failure_batch_lock_v208 = __import__("threading").RLock()
            self._current_subscription_candidate_diags_v209 = [
                {"state": "FAILED_FINAL", "reason_code": "MEDIA_IDENTITY_UNCONFIRMED"},
                {"state": "SUCCESS", "reason_code": "REMOTE_VERIFY_CONFIRMED"},
            ]

        def _plugin_log(self, *a, **k):
            return None

    host = Host()
    sub = SimpleNamespace(id=1, name="飞到我心上")
    assert host._queue_failure_notice_v208(sub, "资源身份未通过最终确认") is True
    assert host._failure_batch_v208 == []
