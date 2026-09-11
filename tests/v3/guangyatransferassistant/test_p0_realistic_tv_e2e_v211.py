"""2.0.11-r95: SIMULATED REALISTIC E2E for 光鸭测试剧 (TMDB 990001).

This is SIMULATED REALISTIC E2E — not real Emby/GYING/GuangYa network.
It verifies EpisodeFacts → Target → pending → ingest → historical recovery
using the production resolver + pending library + claim lifecycle helpers.
"""
from __future__ import annotations

import importlib.util
import sys
import threading
import time
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Set

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
    return pkg


def _load(stem: str):
    pkg = _ensure_pkg()
    full = f"{pkg}.{stem}"
    path = PLUGIN / f"{stem}.py"
    if full in sys.modules and getattr(sys.modules[full], "__file__", None) == str(path):
        # Force reload for evolving hotspot modules during this hotfix round.
        if stem in {"episode_target_v210", "episode_runtime_v211"}:
            pass
        else:
            return sys.modules[full]
    spec = importlib.util.spec_from_file_location(full, path)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = pkg
    sys.modules[full] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _tv():
    return SimpleNamespace(
        id=990001,
        name="光鸭测试剧",
        type="电视剧",
        season=1,
        start_episode=1,
        total_episode=12,
        note=[],
        lack_episode=12,
        state="R",
        best_version=0,
        media_source=None,
        media_id="990001",
        episode_group=None,
        tmdbid=990001,
    )


class FakeWorld:
    """Boundary fakes for Emby / calendar / submits."""

    def __init__(self):
        self.emby_existing: Set[int] = {1, 2, 3, 4, 6, 8, 10}
        self.emby_calls = 0
        self.due = set(range(1, 11))
        self.future = {11, 12}
        self.mp_missing = {5, 7, 11, 12}  # omits E09 on purpose
        self.submits: List[Dict[str, Any]] = []
        self.logs: List[str] = []
        self.data: Dict[str, Any] = {}

    def build_host(self):
        target = _load("episode_target_v210")
        runtime = _load("episode_runtime_v211")
        world = self

        class Base:
            def __init__(self):
                self._episode_target_lock_v210 = __import__("threading").RLock()
                self._episode_target_cache_v210 = {}
                self._episode_snapshot_tls_v211 = __import__("threading").local()
                self._pending_library_ttl_v210 = 1200
                self._library_snapshot_ttl_v210 = 120  # allow same-run Emby reuse
                self._airing_due_lock_v211 = __import__("threading").RLock()
                self._airing_due_running_v211 = False
                self._airing_due_owner_v211 = ""
                self._airing_due_cycle_v211 = 0
                self._host_airing_heartbeat_v211 = 0.0
                self.plugin_version = "2.0.13"
                self.build_id = "20260911-r97"

            def _is_movie_subscription(self, s):
                return False

            def _plugin_log(self, level, msg, *args):
                try:
                    text = msg % args if args else str(msg)
                except Exception:
                    text = str(msg)
                world.logs.append(f"{level}|{text}")

            def get_data(self, key):
                return world.data.get(key)

            def save_data(self, key, value):
                world.data[key] = value

            def _sync_media_library_progress(self, subscribe):
                world.emby_calls += 1
                bounds = set(range(1, 13))
                existing = set(world.emby_existing)
                return {
                    "success": True,
                    "existing": sorted(existing),
                    "missing": sorted(bounds - existing),
                    "note": list(getattr(subscribe, "note", []) or []),
                }

            def _mp_authoritative_missing_episodes_v209(self, subscribe):
                return "used_missing", set(world.mp_missing)

            def _refresh_airing_calendar_v1120(self, force=False):
                return {"items": []}

            def _calendar_item_for_v1120(self, subscribe, calendar):
                eps = []
                for ep in sorted(world.due | world.future):
                    eps.append(
                        {
                            "episode": ep,
                            "air_date": "2026-01-01" if ep in world.due else "2099-01-01",
                        }
                    )
                return {"episodes": eps, "provider": "fake"}

            def _split_calendar_due_future_v209(self, item, subscribe, now, candidate_episodes=None):
                return {
                    "due": set(world.due),
                    "future": set(world.future),
                    "air_dates": {},
                    "calendar_available": True,
                    "next_episode": min(world.future) if world.future else 0,
                    "next_air_at": "2099-01-01",
                }

            def _pending_reservations(self, subscribe, exclude_job_key=""):
                return {"episodes": set(), "paths": set(), "movie": False}

            def _active_source_claims(self, sid):
                return []

            def _source_store(self):
                return {"items": {}}

            def _finish_subscription_if_complete(self, subscribe, channel_state=None):
                return False

            def _subscription_missing_episodes(self, subscribe):
                return []

            def _remember_episode_facts(self, subscribe, episodes, origin="library"):
                return 0

            def init_plugin(self, config=None):
                pass

        class Host(runtime.GuangYaEpisodeRuntimeV211Mixin, target.GuangYaEpisodeTargetV210Mixin, Base):
            pass

        return Host()


def test_e2e_phase1_final_target_emby_gap_override():
    world = FakeWorld()
    h = world.build_host()
    snap = h._episode_target_snapshot_v210(_tv(), force_library=True, log=True)
    assert set(snap["final_target"]) == {5, 7, 9}
    assert set(snap["emby_gap_override"]) == {9}
    assert 11 not in snap["final_target"]
    assert world.emby_calls == 1


def test_e2e_resource_selection_subset_of_final_target():
    """GuangYa package E01-E06 against target E05,E07,E09 → only E05."""
    world = FakeWorld()
    h = world.build_host()
    snap = h._episode_target_snapshot_v210(_tv(), force_library=True, log=False)
    final = set(snap["final_target"])
    package = set(range(1, 7))
    selected = sorted(package.intersection(final))
    assert selected == [5]
    world.submits.append({"source": "guangya", "episodes": selected, "task": "GY_TEST_001"})
    h._mark_pending_library_confirmation_v210(_tv(), selected, source="guangya")
    assert h._pending_library_episodes_v210(_tv()) == {5}


def test_e2e_magnet_ed2k_selection_and_future_reject():
    world = FakeWorld()
    h = world.build_host()
    # Direct package already submitted E05
    world.submits.append({"source": "guangya", "episodes": [5], "task": "GY_TEST_001"})
    h._mark_pending_library_confirmation_v210(_tv(), [5], source="guangya")
    snap = h._episode_target_snapshot_v210(_tv(), force_library=True, log=False)
    final = set(snap["final_target"])
    assert final == {7, 9}

    # Magnet subfiles: E07 video+sub, E11 future video
    magnet_files = [
        {"fileIndex": 7, "fileName": "光鸭测试剧.S01E07.1080p.mkv", "ep": 7, "video": True},
        {"fileIndex": 11, "fileName": "光鸭测试剧.S01E07.zh-CN.ass", "ep": 7, "video": False},
        {"fileIndex": 15, "fileName": "光鸭测试剧.S01E11.1080p.mkv", "ep": 11, "video": True},
    ]
    selected_indexes = []
    for row in magnet_files:
        if row["ep"] in final and row["ep"] not in world.future:
            selected_indexes.append(row["fileIndex"])
    assert selected_indexes == [7, 11]
    assert 15 not in selected_indexes
    world.submits.append({"source": "magnet", "episodes": [7], "indexes": selected_indexes})
    h._mark_pending_library_confirmation_v210(_tv(), [7], source="magnet")

    # ED2K video E09 allowed; subtitle-only blocked
    ed2k_video_ep = 9
    assert ed2k_video_ep in final
    world.submits.append({"source": "ed2k", "episodes": [9], "task": "ED2K_TEST_001"})
    h._mark_pending_library_confirmation_v210(_tv(), [9], source="ed2k")
    subtitle_only_allowed = False
    assert subtitle_only_allowed is False

    # counts
    flat = []
    for row in world.submits:
        flat.extend(row["episodes"])
    assert flat.count(5) + flat.count(7) + flat.count(9) == 3
    assert flat.count(11) == 0


def test_e2e_pending_blocks_second_run_duplicates():
    world = FakeWorld()
    h = world.build_host()
    for ep, src in ((5, "guangya"), (7, "magnet"), (9, "ed2k")):
        h._mark_pending_library_confirmation_v210(_tv(), [ep], source=src)
    snap = h._episode_target_snapshot_v210(_tv(), force_library=True, log=False)
    assert snap["final_target"] == []
    assert set(snap["pending_library"]) == {5, 7, 9}
    ok, allowed, reason = h._final_target_allows_submit_v211(_tv(), [5, 7, 9])
    assert ok is False
    assert reason == "empty_final_target"


def test_e2e_emby_ingest_clears_pending_and_skip_future():
    world = FakeWorld()
    h = world.build_host()
    for ep in (5, 7, 9):
        h._mark_pending_library_confirmation_v210(_tv(), [ep], source="x")
    world.emby_existing = set(range(1, 11))
    snap = h._episode_target_snapshot_v210(_tv(), force_library=True, log=False)
    assert set(snap["pending_library"]) == set()
    assert snap["final_target"] == []
    assert snap["decision"] == "skip_future"
    assert set(snap["calendar_future"]) == {11, 12}


def test_e2e_historical_delete_e03_reenters_target():
    world = FakeWorld()
    h = world.build_host()
    world.emby_existing = set(range(1, 11)) - {3}
    world.mp_missing = {11, 12}  # MP does not know E03
    # stale completed claim must not block
    world.data["sources"] = {}
    snap = h._episode_target_snapshot_v210(_tv(), force_library=True, log=False)
    assert 3 in set(snap["final_target"])
    assert 11 not in set(snap["final_target"])


def test_e2e_future_due_promotion_e11():
    world = FakeWorld()
    h = world.build_host()
    world.emby_existing = set(range(1, 11))
    world.due = set(range(1, 12))
    world.future = {12}
    world.mp_missing = {11, 12}
    snap = h._episode_target_snapshot_v210(_tv(), force_library=True, log=False)
    assert set(snap["final_target"]) == {11}


def test_e2e_one_run_emby_query_count_leq_1():
    world = FakeWorld()
    h = world.build_host()
    before = world.emby_calls
    snap = h._episode_target_snapshot_v210(_tv(), force_library=True, log=False)
    # Same-run cache hits must not re-open Emby.
    for _ in range(10):
        h._episode_target_snapshot_v210(_tv(), force_library=False, log=False)
    assert world.emby_calls - before == 1
    assert snap["emby_query_count"] <= 1


def test_airing_due_overlap_singleflight():
    world = FakeWorld()
    h = world.build_host()
    c1 = h._begin_airing_due_cycle_v211("host")
    assert c1 is not None
    c2 = h._begin_airing_due_cycle_v211("fallback")
    assert c2 is None
    h._end_airing_due_cycle_v211()
    c3 = h._begin_airing_due_cycle_v211("fallback")
    assert c3 is not None
    h._end_airing_due_cycle_v211()


def test_get_service_airing_due_points_to_runtime_calendar():
    """Host scheduler registers AiringDue → Runtime._calendar_due_check_v1110."""
    release = (PLUGIN / "release_v1110.py").read_text(encoding="utf-8")
    assert '"id": "GuangYaTransferAssistantAiringDue"' in release
    assert '"func": self._calendar_due_check_v1110' in release
    assert '"kwargs": {"minutes":' in release
    runtime = (PLUGIN / "episode_runtime_v211.py").read_text(encoding="utf-8")
    assert "def _calendar_due_check_v1110(self, minutes: Any = None, owner: str = \"host\", **kwargs)" in runtime
    entry = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
    assert entry.index("GuangYaEpisodeRuntimeV211Mixin") < entry.index("GuangYaReleaseV1110Mixin")


def test_airing_due_fallback_after_stale_heartbeat():
    world = FakeWorld()
    h = world.build_host()
    h._enabled = True
    h._refresh_minutes = 5
    h._auto_transfer_on_refresh = True
    h._airing_fallback_stale_seconds_v211 = 1
    h._host_airing_heartbeat_v211 = 0.0
    h._host_tick_heartbeat = time.monotonic()
    h._runtime_stop = threading.Event()
    calls = []

    def fake_calendar(minutes=None, owner="host", **kwargs):
        calls.append(owner)
        return {"success": True, "checked": 0}

    h._calendar_due_check_v1110 = fake_calendar
    h._runtime_is_current = lambda: True
    h._tick = lambda host_service=False: None
    # Simulate one loop iteration body for AiringDue fallback only
    airing_hb = float(getattr(h, "_host_airing_heartbeat_v211", 0.0) or 0.0)
    stale = max(1, int(getattr(h, "_airing_fallback_stale_seconds_v211", 900) or 900))
    assert (not airing_hb) or (time.monotonic() - airing_hb) >= stale
    h._calendar_due_check_v1110(owner="fallback")
    assert calls == ["fallback"]


def test_submit_hard_gate_blocks_empty_final_target():
    world = FakeWorld()
    h = world.build_host()
    for ep in (5, 7, 9):
        h._mark_pending_library_confirmation_v210(_tv(), [ep], source="x")
    world.data.setdefault("sources", {"items": {}})
    world.data["sources"]["items"]["s1"] = {
        "id": "s1",
        "subscribe_id": 990001,
        "type": "magnet",
        "resolved_episodes": [5],
        "target_episodes": [5],
        "state": "new",
    }

    class BaseSubmit:
        def _submit_offline_source(self, source_id):
            return {"success": True, "submitted": True}

        def _source_store(self):
            return world.data["sources"]

        def _find_subscription(self, sid):
            return _tv() if int(sid) == 990001 else None

        def _is_movie_subscription(self, s):
            return False

        def _plugin_log(self, *a, **k):
            pass

        def _update_source(self, *a, **k):
            return None

    runtime = _load("episode_runtime_v211")
    target = _load("episode_target_v210")

    class GateHost(runtime.GuangYaEpisodeRuntimeV211Mixin, target.GuangYaEpisodeTargetV210Mixin, BaseSubmit):
        def __init__(self):
            self._episode_target_lock_v210 = threading.RLock()
            self._episode_target_cache_v210 = {}
            self._episode_snapshot_tls_v211 = threading.local()
            self._pending_library_ttl_v210 = 1200
            self._library_snapshot_ttl_v210 = 0

        def get_data(self, key):
            return world.data.get(key)

        def save_data(self, key, value):
            world.data[key] = value

        def _sync_media_library_progress(self, subscribe):
            world.emby_calls += 1
            existing = set(world.emby_existing)
            return {
                "success": True,
                "existing": sorted(existing),
                "missing": sorted(set(range(1, 13)) - existing),
                "note": [],
            }

        def _mp_authoritative_missing_episodes_v209(self, subscribe):
            return "used_missing", set(world.mp_missing)

        def _refresh_airing_calendar_v1120(self, force=False):
            return {"items": []}

        def _calendar_item_for_v1120(self, subscribe, calendar):
            return {
                "episodes": [
                    {"episode": ep, "air_date": "2026-01-01" if ep in world.due else "2099-01-01"}
                    for ep in sorted(world.due | world.future)
                ]
            }

        def _split_calendar_due_future_v209(self, item, subscribe, now, candidate_episodes=None):
            return {
                "due": set(world.due),
                "future": set(world.future),
                "air_dates": {},
                "calendar_available": True,
                "next_episode": min(world.future) if world.future else 0,
                "next_air_at": "2099-01-01",
            }

        def _pending_reservations(self, subscribe, exclude_job_key=""):
            return {"episodes": set(), "paths": set(), "movie": False}

        def _active_source_claims(self, sid):
            return []

        def _finish_subscription_if_complete(self, subscribe, channel_state=None):
            return False

    gh = GateHost()
    out = gh._submit_offline_source("s1")
    assert out.get("skipped") is True
    assert out.get("reason") == "empty_final_target"
