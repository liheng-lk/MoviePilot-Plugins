"""2.0.10-r94: Episode Integrity — Emby actual library truth + target snapshot.

Covers stale note masking, MP vs Emby, calendar due/future, pending library,
completion gate, and structured observability markers.
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


def _tv(sid: int = 901, *, note=None, start=1, total=10, season=1, name="冬城猎凶"):
    return SimpleNamespace(
        id=sid,
        name=name,
        type="电视剧",
        season=season,
        start_episode=start,
        total_episode=total,
        note=list(note or []),
        lack_episode=total,
        state="R",
        best_version=0,
        media_source=None,
        media_id=None,
        episode_group=None,
        tmdbid=290863,
    )


def _host(
    *,
    emby_existing: Set[int],
    library_ok: bool = True,
    mp_state: str = "used_missing",
    mp_missing: Set[int] | None = None,
    due: Set[int] | None = None,
    future: Set[int] | None = None,
    reserved: Set[int] | None = None,
    claimed: Set[int] | None = None,
):
    mod = _load("episode_target_v210")

    class Base:
        def __init__(self):
            self._logs: List[str] = []
            self._data: Dict[str, Any] = {}
            self._episode_target_lock_v210 = __import__("threading").RLock()
            self._episode_target_cache_v210 = {}
            self._emby_existing = set(emby_existing)
            self._library_ok = library_ok
            self._mp_state = mp_state
            self._mp_missing = set(mp_missing if mp_missing is not None else set())
            self._due = set(due if due is not None else set())
            self._future = set(future if future is not None else set())
            self._reserved = set(reserved or [])
            self._claimed = set(claimed or [])
            self._finished = False

        def init_plugin(self, config=None):
            pass

        def _plugin_log(self, level, msg, *args):
            try:
                text = msg % args if args else str(msg)
            except Exception:
                text = str(msg)
            self._logs.append(f"{level}|{text}")

        def get_data(self, key):
            return self._data.get(key)

        def save_data(self, key, value):
            self._data[key] = value

        def _is_movie_subscription(self, subscribe):
            return "movie" in str(getattr(subscribe, "type", "") or "").lower()

        def _sync_media_library_progress(self, subscribe):
            start = max(1, int(getattr(subscribe, "start_episode", 1) or 1))
            total = int(getattr(subscribe, "total_episode", 0) or 0)
            bounds = set(range(start, total + 1)) if total >= start else set()
            if not self._library_ok:
                return {
                    "success": False,
                    "existing": [],
                    "missing": [],
                    "note": list(getattr(subscribe, "note", []) or []),
                }
            existing = set(self._emby_existing).intersection(bounds)
            return {
                "success": True,
                "existing": sorted(existing),
                "missing": sorted(bounds - existing),
                "note": list(getattr(subscribe, "note", []) or []),
            }

        def _mp_authoritative_missing_episodes_v209(self, subscribe):
            return self._mp_state, set(self._mp_missing)

        def _refresh_airing_calendar_v1120(self, force=False):
            return {"items": []}

        def _calendar_item_for_v1120(self, subscribe, calendar):
            eps = []
            for ep in sorted(self._due | self._future):
                eps.append(
                    {
                        "episode": ep,
                        "air_date": "2026-01-01" if ep in self._due else "2099-01-01",
                    }
                )
            return {"episodes": eps, "provider": "test"}

        def _split_calendar_due_future_v209(self, item, subscribe, now, candidate_episodes=None):
            due = set(self._due)
            future = set(self._future)
            if candidate_episodes is not None:
                due &= set(candidate_episodes)
                future &= set(candidate_episodes)
            nxt = min(future) if future else 0
            return {
                "due": due,
                "future": future,
                "air_dates": {},
                "calendar_available": bool(due or future or (item or {}).get("episodes")),
                "next_episode": nxt,
                "next_air_at": "2099-01-01" if nxt else "",
            }

        def _episode_air_at_v1120(self, row):
            return None

        def _pending_reservations(self, subscribe, exclude_job_key=""):
            return {"episodes": set(self._reserved), "paths": set(), "movie": False}

        def _active_source_claims(self, sid):
            return list(self._claimed)

        def _finish_subscription_if_complete(self, subscribe, channel_state=None):
            self._finished = True
            return True

        def _subscription_missing_episodes(self, subscribe):
            return []

        def _subscription_episode_progress(self, subscribe):
            return (0, 0, 0)

        def _remember_episode_facts(self, subscribe, episodes, origin="library"):
            return 1

    class Host(mod.GuangYaEpisodeTargetV210Mixin, Base):
        pass

    return Host()


def test_a_stale_note_does_not_mask_emby_gap():
    h = _host(
        emby_existing={1, 2, 3},
        mp_state="used_complete",
        mp_missing=set(),
        due={1, 2, 3, 4, 5},
        future={6, 7},
    )
    sub = _tv(note=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    snap = h._episode_target_snapshot_v210(sub, log=False)
    assert snap["library_state"] == "OK"
    assert set(snap["emby_gap"]) == {4, 5, 6, 7, 8, 9, 10}
    assert set(snap["final_target"]) == {4, 5}
    assert set(snap["note_only"]) == {4, 5, 6, 7, 8, 9, 10}


def test_b_mp_empty_emby_gap_due_still_targets():
    h = _host(
        emby_existing={1},
        mp_state="used_empty",
        mp_missing=set(),
        due={1, 2, 3},
        future=set(),
    )
    snap = h._episode_target_snapshot_v210(_tv(total=3), log=False)
    assert set(snap["final_target"]) == {2, 3}
    assert snap["decision"] == "search_missing"


def test_c_historical_due_kept_future_excluded():
    h = _host(
        emby_existing={1},
        mp_missing={2, 3, 4, 5},
        due={2, 3},
        future={4, 5},
    )
    snap = h._episode_target_snapshot_v210(_tv(total=5), log=False)
    assert set(snap["final_target"]) == {2, 3}
    assert 4 not in snap["final_target"] and 5 not in snap["final_target"]


def test_d_future_only_skip_future():
    h = _host(
        emby_existing={1, 2, 3},
        mp_missing={4, 5},
        due=set(),
        future={4, 5},
    )
    snap = h._episode_target_snapshot_v210(_tv(total=5), log=False)
    assert snap["final_target"] == []
    assert snap["decision"] == "skip_future"


def test_e_reserved_claimed_pending_subtracted():
    h = _host(
        emby_existing={1},
        mp_missing={2, 3, 4},
        due={2, 3, 4},
        reserved={2},
        claimed={3},
    )
    sub = _tv(total=4)
    h._mark_pending_library_confirmation_v210(sub, [4], source="magnet")
    snap = h._episode_target_snapshot_v210(sub, log=False)
    assert snap["final_target"] == []
    assert set(snap["pending_library"]) == {4}
    assert snap["decision"] == "skip_reserved_or_pending"


def test_f_library_unknown_blocks_completion():
    h = _host(emby_existing=set(), library_ok=False, due={1}, mp_missing={1})
    assert h._finish_subscription_if_complete(_tv(total=1)) is False
    assert h._finished is False
    assert any("LIBRARY_UNKNOWN" in x for x in h._logs)


def test_g_emby_gap_blocks_completion_despite_note():
    h = _host(
        emby_existing={1, 2},
        due={1, 2, 3},
        future=set(),
        mp_missing=set(),
        mp_state="used_complete",
    )
    sub = _tv(total=3, note=[1, 2, 3])
    assert h._finish_subscription_if_complete(sub) is False
    assert any("emby_actual_incomplete" in x for x in h._logs)


def test_h_emby_complete_allows_finish():
    h = _host(
        emby_existing={1, 2, 3},
        due={1, 2, 3},
        future=set(),
        mp_missing=set(),
        mp_state="used_complete",
    )
    assert h._finish_subscription_if_complete(_tv(total=3, note=[1, 2, 3])) is True
    assert h._finished is True


def test_i_pending_cleared_when_emby_has_episode():
    h = _host(emby_existing={1, 2}, due={1, 2, 3}, mp_missing={3})
    sub = _tv(total=3)
    h._mark_pending_library_confirmation_v210(sub, [2, 3], source="xunlei")
    still = h._clear_pending_library_confirmed_v210(sub, {1, 2})
    assert still == {3}
    snap = h._episode_target_snapshot_v210(sub, log=False)
    assert set(snap["pending_library"]) == {3}
    assert set(snap["final_target"]) == set()


def test_j_structured_observability_markers():
    h = _host(emby_existing={1}, due={1, 2}, future={3}, mp_missing={2, 3})
    h._episode_target_snapshot_v210(_tv(total=3), log=True)
    joined = "\n".join(h._logs)
    assert "【Emby剧集事实】" in joined
    assert "【MP剧集事实】" in joined
    assert "【播出日历事实】" in joined
    assert "【剧集目标计算】" in joined
    assert "final_target=" in joined


def test_k_legacy_sync_missing_not_from_merged_note():
    legacy = (PLUGIN / "legacy.py").read_text(encoding="utf-8")
    body = legacy.split("def _sync_media_library_progress")[1].split("def _install_takeover")[0]
    assert "target.difference(library_existing)" in body
    assert "target.difference(merged)" not in body


def test_l_calendar_fallback_prefers_library_missing():
    cal = (PLUGIN / "calendar_driven_v209.py").read_text(encoding="utf-8")
    assert "library_missing).intersection(logical)" not in cal


def test_m_core_xunlei_no_hard_intersection():
    core = (PLUGIN / "core_pipeline_v11214.py").read_text(encoding="utf-8")
    xunlei = (PLUGIN / "xunlei_existing_fence_v11213.py").read_text(encoding="utf-8")
    assert "library_missing.intersection" not in core
    assert "library_missing.intersection(logical_missing)" not in xunlei
    assert "stale-complete note" in core or "stale-complete" in xunlei


def test_n_library_existing_empty_success_no_note_fallback():
    cal = (PLUGIN / "calendar_driven_v209.py").read_text(encoding="utf-8")
    block = cal.split("def _library_existing_episodes_v209")[1].split("def _split_calendar_due_future_v209")[0]
    assert 'if bool(sync.get("success"))' in block
    assert "if existing:" not in block


def test_o_mro_wires_episode_target():
    entry = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
    assert "GuangYaEpisodeTargetV210Mixin" in entry
    assert "GuangYaEpisodeRuntimeV211Mixin" in entry
    class_block = entry.split("class GuangYaTransferAssistant(")[1].split("):")[0]
    assert class_block.index("GuangYaFoundationOpsV209Mixin") < class_block.index(
        "GuangYaEpisodeRuntimeV211Mixin"
    )
    assert class_block.index("GuangYaEpisodeRuntimeV211Mixin") < class_block.index(
        "GuangYaEpisodeTargetV210Mixin"
    )
    assert class_block.index("GuangYaEpisodeTargetV210Mixin") < class_block.index(
        "GuangYaCalendarDrivenV209Mixin"
    )


def test_p_version_freeze_r94():
    entry = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
    assert 'plugin_version = "2.0.13"' in entry
    assert 'build_id = "20260911-r97"' in entry


def test_q_remember_marks_pending_library():
    h = _host(emby_existing={1}, due={2}, mp_missing={2})
    sub = _tv(total=2)
    h._mark_pending_library_confirmation_v210(sub, [2], source="guangya_offline")
    assert h._pending_library_episodes_v210(sub) == {2}


def test_r_emby_gap_override_when_mp_omits_due_gap():
    h = _host(
        emby_existing={1},
        mp_state="used_missing",
        mp_missing={2},
        due={2, 3},
        future=set(),
    )
    snap = h._episode_target_snapshot_v210(_tv(total=3), log=False)
    assert set(snap["final_target"]) == {2, 3}
    assert set(snap["emby_gap_override"]) == {3}


def test_s_subscription_missing_uses_final_target():
    h = _host(
        emby_existing={1},
        due={2, 3},
        future={4},
        mp_missing={2, 3, 4},
        reserved={3},
    )
    missing = h._subscription_missing_episodes(_tv(total=4))
    assert missing == [2]


def test_t_progress_uses_emby_not_note():
    h = _host(
        emby_existing={1, 2},
        due={1, 2, 3},
        mp_missing=set(),
        mp_state="used_complete",
    )
    sub = _tv(total=3, note=[1, 2, 3])
    # UI progress is zero-I/O: warm cache via one transfer-path snapshot first.
    h._episode_target_snapshot_v210(sub, force_library=True, log=False)
    done, total, lack = h._subscription_episode_progress(sub)
    assert (done, total, lack) == (2, 3, 1)
