"""2.0.11-r95 P0: Episode runtime architecture — observation ≠ receipt ≠ reservation.

Covers recursion break, reentrancy, library-origin migration, UNKNOWN empty-target,
and pure resolver invariants. SIMULATED / UNIT level (not real Emby/GYING).
"""
from __future__ import annotations

import importlib.util
import sys
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
        return sys.modules[full]
    spec = importlib.util.spec_from_file_location(full, path)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = pkg
    sys.modules[full] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _tv(**kwargs):
    base = dict(
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
        media_id=None,
        episode_group=None,
        tmdbid=990001,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_old_broken_call_graph_markers_removed_from_library_sync():
    legacy = (PLUGIN / "legacy.py").read_text(encoding="utf-8")
    body = legacy.split("def _sync_media_library_progress")[1].split("def _install_takeover")[0]
    assert '_remember_episode_facts(subscribe, library_existing, origin="library")' not in body
    assert "Library observation only" in body or "NEVER write transfer receipt" in body


def test_fence_library_origin_never_commits_receipt():
    fence_src = (PLUGIN / "episode_fence_v1124.py").read_text(encoding="utf-8")
    assert "_is_library_observation_origin_v1124" in fence_src
    assert "Library observation must never enter transfer receipt" in fence_src
    assert 'base["episodes"].update(self._acquired_episode_facts_v1124(subscribe))' not in fence_src


def test_mro_runtime_before_target():
    entry = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
    head = entry.split("class GuangYaTransferAssistant(", 1)[1].split("):", 1)[0]
    assert head.index("GuangYaEpisodeRuntimeV211Mixin") < head.index("GuangYaEpisodeTargetV210Mixin")
    assert 'plugin_version = "2.0.12"' in entry
    assert 'build_id = "20260911-r96"' in entry


def test_pure_resolver_emby_gap_override_and_future_safety():
    mod = _load("episode_target_v210")

    class H(mod.GuangYaEpisodeTargetV210Mixin):
        def _plugin_log(self, *a, **k):
            pass

    h = H()
    facts = {
        "subscription_bounds": list(range(1, 13)),
        "library_state": "OK",
        "calendar_state": "OK",
        "emby_existing": [1, 2, 3, 4, 6, 8, 10],
        "emby_gap": [5, 7, 9, 11, 12],
        "mp_missing": [5, 7, 11, 12],  # deliberately omits E09
        "calendar_due": list(range(1, 11)),
        "calendar_future": [11, 12],
        "reserved": [],
        "claimed": [],
        "pending_library": [],
    }
    snap = h._resolve_episode_target_v211(facts)
    assert set(snap["final_target"]) == {5, 7, 9}
    assert set(snap["emby_gap_override"]) == {9}
    assert 11 not in snap["final_target"] and 12 not in snap["final_target"]


def test_library_unknown_empty_due_intersection_does_not_search():
    mod = _load("episode_target_v210")

    class H(mod.GuangYaEpisodeTargetV210Mixin):
        def _plugin_log(self, *a, **k):
            pass

    h = H()
    facts = {
        "subscription_bounds": list(range(1, 13)),
        "library_state": "UNKNOWN",
        "calendar_state": "OK",
        "emby_existing": [],
        "emby_gap": [],
        "mp_missing": [10, 11, 12],
        "calendar_due": list(range(1, 10)),
        "calendar_future": [10, 11, 12],
        "reserved": [],
        "claimed": [],
        "pending_library": [],
    }
    snap = h._resolve_episode_target_v211(facts)
    assert snap["final_target"] == []
    assert snap["decision"] in {"skip_future", "continue_match"}
    assert snap["decision"] != "search_mp_calendar_failopen"


def test_reentrancy_blocks_second_emby_query():
    mod = _load("episode_target_v210")
    calls = {"emby": 0}

    class Base:
        def _is_movie_subscription(self, s):
            return False

        def _sync_media_library_progress(self, subscribe):
            calls["emby"] += 1
            # Re-enter snapshot from inside Emby observation (old bug path).
            nested = self._episode_target_snapshot_v210(subscribe, force_library=True, log=False)
            assert nested.get("reason") in {
                "episode_snapshot_reentrant",
                "episode_snapshot_building",
            } or nested.get("final_target") is not None
            return {"success": True, "existing": [1, 2, 3], "missing": list(range(4, 13)), "note": []}

        def _mp_authoritative_missing_episodes_v209(self, subscribe):
            return "used_missing", {5, 7, 9}

        def _refresh_airing_calendar_v1120(self, force=False):
            return {"items": []}

        def _calendar_item_for_v1120(self, subscribe, calendar):
            return {
                "episodes": [
                    {"episode": i, "air_date": "2026-01-01" if i <= 10 else "2099-01-01"}
                    for i in range(1, 13)
                ],
                "provider": "test",
            }

        def _split_calendar_due_future_v209(self, item, subscribe, now, candidate_episodes=None):
            return {
                "due": set(range(1, 11)),
                "future": {11, 12},
                "air_dates": {},
                "calendar_available": True,
                "next_episode": 11,
                "next_air_at": "2099-01-01",
            }

        def _pending_reservations(self, subscribe, exclude_job_key=""):
            return {"episodes": set(), "paths": set(), "movie": False}

        def _active_source_claims(self, sid):
            return []

        def _plugin_log(self, *a, **k):
            pass

        def get_data(self, key):
            return {}

        def save_data(self, key, value):
            pass

    class Host(mod.GuangYaEpisodeTargetV210Mixin, Base):
        def __init__(self):
            self._episode_target_lock_v210 = __import__("threading").RLock()
            self._episode_target_cache_v210 = {}
            self._episode_snapshot_tls_v211 = __import__("threading").local()
            self._pending_library_ttl_v210 = 1200
            self._library_snapshot_ttl_v210 = 45

    h = Host()
    snap = h._episode_target_snapshot_v210(_tv(), force_library=True, log=False)
    assert calls["emby"] == 1
    assert set(snap["final_target"]) == {5, 7, 9} or snap["decision"] in {
        "search_missing",
        "continue_match",
        "skip_reserved_or_pending",
    }


def test_migration_removes_library_origin_only():
    mod = _load("episode_runtime_v211")
    store: Dict[str, Any] = {
        "media_facts": {
            "s:990001:1:e0005": {"origin": "library", "time": "t"},
            "s:990001:1:e0007": {"origin": "magnet", "time": "t"},
            "s:990001:1:e0009": {"origin": "emby", "time": "t"},
            "s:990001:1:e0006": {"origin": "guangya_offline", "time": "t"},
        }
    }

    class Base:
        def init_plugin(self, config=None):
            pass

        def get_data(self, key):
            return store.get(key)

        def save_data(self, key, value):
            store[key] = value

        def _plugin_log(self, *a, **k):
            pass

        plugin_version = "2.0.12"
        build_id = "20260911-r96"

    class Host(mod.GuangYaEpisodeRuntimeV211Mixin, Base):
        pass

    h = Host()
    h._migrate_library_observation_facts_v211_once()
    facts = store["media_facts"]
    assert "s:990001:1:e0005" not in facts
    assert "s:990001:1:e0009" not in facts
    assert "s:990001:1:e0007" in facts
    assert "s:990001:1:e0006" in facts
    # second call no-op
    h._migrate_library_observation_facts_v211_once()
    assert store["episode_facts_migration_v211"]["done"] is True


def test_completed_claim_not_permanent():
    mod = _load("episode_runtime_v211")
    now = __import__("time").time()

    class Base:
        def _source_store(self):
            return {
                "items": {
                    "s1": {
                        "id": "s1",
                        "subscribe_id": 990001,
                        "enabled": True,
                        "state": "completed",
                        "completed_ts": now - 60,
                        "target_episodes": [3],
                    },
                    "s2": {
                        "id": "s2",
                        "subscribe_id": 990001,
                        "enabled": True,
                        "state": "submitted",
                        "target_episodes": [5],
                    },
                }
            }

        def _plugin_log(self, *a, **k):
            pass

    class Host(mod.GuangYaEpisodeRuntimeV211Mixin, Base):
        pass

    h = Host()
    claims = h._active_inflight_claims_v211(990001)
    # completed must never occupy active claim — even within former grace window.
    assert 3 not in claims
    assert 5 in claims


def test_pending_ttl_expired_allows_gap_again():
    mod = _load("episode_target_v210")
    store: Dict[str, Any] = {}

    class Base:
        def _is_movie_subscription(self, s):
            return False

        def _plugin_log(self, *a, **k):
            pass

        def get_data(self, key):
            return store.get(key)

        def save_data(self, key, value):
            store[key] = value

    class Host(mod.GuangYaEpisodeTargetV210Mixin, Base):
        def __init__(self):
            self._pending_library_ttl_v210 = 1

    h = Host()
    sub = _tv()
    h._mark_pending_library_confirmation_v210(sub, [5], source="magnet")
    # Force expire
    items = store["pending_library_confirmation_v210"]["items"]
    for row in items.values():
        row["expires_at"] = 1.0
    pending = h._pending_library_episodes_v210(sub)
    assert pending == set()
