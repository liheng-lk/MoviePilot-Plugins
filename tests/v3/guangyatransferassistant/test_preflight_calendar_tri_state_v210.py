"""2.0.10-r94 Beta: Preflight/Calendar MISSING|SATISFIED|UNKNOWN + due/future unify.

Regression focus: 冬城猎凶 (TMDB 290863) episodes=[] must not skip_complete.
"""
from __future__ import annotations

import ast
import datetime
import threading
import types
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Set, Tuple
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"

NOW = datetime.datetime(2026, 9, 11, 13, 34, 0)


@contextmanager
def _freeze_datetime_now(ns: Dict[str, Any], when: datetime.datetime):
    """Replace ns['datetime'] module so mixin globals see a frozen now()."""
    real = ns["datetime"]
    fake = types.ModuleType("datetime")
    fake.date = real.date
    fake.time = real.time
    fake.timedelta = real.timedelta
    fake.timezone = getattr(real, "timezone", None)

    class _DT(real.datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return when
            return when.replace(tzinfo=tz)

        @classmethod
        def fromisoformat(cls, date_string):
            return real.datetime.fromisoformat(date_string)

    fake.datetime = _DT
    previous = ns["datetime"]
    ns["datetime"] = fake
    try:
        yield
    finally:
        ns["datetime"] = previous


def _load_mixin(module_file: Path, class_name: str):
    tree = ast.parse(module_file.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    mod = ast.Module(body=[cls], type_ignores=[])
    ast.fix_missing_locations(mod)
    ns: Dict[str, Any] = {
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "Optional": Optional,
        "Set": Set,
        "Tuple": Tuple,
        "datetime": datetime,
        "inspect": __import__("inspect"),
        "threading": threading,
        "time": __import__("time"),
        "CronTrigger": MagicMock(),
        "nullcontext": __import__("contextlib").nullcontext,
    }
    ns["CronTrigger"].from_crontab = MagicMock(return_value="cron")
    exec(compile(mod, str(module_file), "exec"), ns)
    return ns[class_name], ns


def _gate_base(
    *,
    missing_source: str,
    missing: Set[int],
    existing: Set[int],
    episodes: List[Dict[str, Any]],
    reserved: Optional[List[int]] = None,
    claimed: Optional[Set[int]] = None,
):
    Mixin, ns = _load_mixin(PLUGIN / "calendar_driven_v209.py", "GuangYaCalendarDrivenV209Mixin")
    cal = {
        "subscriptions": [{
            "subscribe_id": 290863,
            "provider": "moviepilot_native",
            "episodes": episodes,
        }]
    }

    class Base:
        def _airing_gate_v1120(self, subscribe, payload=None):
            return {"calendar_available": bool(episodes), "calendar_provider": "moviepilot_native"}

        def _is_movie_subscription(self, subscribe):
            return False

        def _plugin_log(self, *a, **k):
            pass

        def _bump_metric_v209(self, *a, **k):
            pass

    class Obj(Mixin, Base):
        # Overrides must live on Obj so they win over Mixin MRO.
        def _mp_authoritative_missing_episodes_v209(self, subscribe):
            return missing_source, set(missing)

        def _refresh_airing_calendar_v1120(self, force=False):
            return cal

        def _calendar_item_for_v1120(self, subscribe, calendar):
            return cal["subscriptions"][0] if episodes else {}

        def _episode_air_at_v1120(self, row):
            raw = str(row.get("air_at") or "").strip()
            if raw:
                return datetime.datetime.fromisoformat(raw)
            day = str(row.get("air_date") or "")[:10]
            return datetime.datetime.fromisoformat(f"{day}T20:00:00") if day else None

        def _episode_is_actively_due_v209(self, row, now):
            air = self._episode_air_at_v1120(row)
            return bool(air and air <= now)

        def _pending_reservations(self, subscribe):
            return {"episodes": list(reserved or [])}

        def _active_source_claims(self, sid):
            return set(claimed or set())

        def _episode_ready_for_external_v209(self, *a, **k):
            return True

        def _sync_media_library_progress(self, subscribe):
            return {"existing": sorted(existing), "missing": []}

        def _library_existing_episodes_v209(self, subscribe):
            return set(existing)

    return Obj(), ns, cal


def _sub(**kwargs):
    base = dict(
        id=290863,
        name="冬城猎凶",
        season=1,
        tmdbid=290863,
        total_episode=18,
        start_episode=1,
        note=[],
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_a_winter_city_used_empty_yesterday_e01_is_due():
    episodes = [
        {"episode": 1, "air_date": "2026-09-10", "air_at": "2026-09-10T20:00:00", "precision": "datetime"},
        {"episode": 7, "air_date": "2026-09-17", "air_at": "2026-09-17T20:00:00", "precision": "datetime"},
        {"episode": 8, "air_date": "2026-09-18", "air_at": "2026-09-18T20:00:00", "precision": "datetime"},
        {"episode": 9, "air_date": "2026-09-19", "air_at": "2026-09-19T20:00:00", "precision": "datetime"},
    ]
    obj, ns, cal = _gate_base(
        missing_source="used_empty", missing=set(), existing=set(), episodes=episodes,
    )
    with _freeze_datetime_now(ns, NOW):
        gate = obj._airing_gate_v1120(_sub(), payload=cal)
    assert gate["preflight_state"] == "MISSING"
    assert gate["decision"] in {"search_due", "continue_match"}
    assert gate["decision"] != "skip_complete"
    assert 1 in (gate.get("due_calendar") or [])
    assert 1 in (gate.get("target_episodes") or gate.get("due_uncovered") or [])
    assert int(gate.get("next_episode") or 0) == 7
    assert int(gate.get("next_episode") or 0) != 1


def test_b_not_yet_aired_skip_future():
    episodes = [
        {"episode": 1, "air_date": "2026-09-12", "air_at": "2026-09-12T20:00:00", "precision": "datetime"},
    ]
    obj, ns, cal = _gate_base(
        missing_source="used_empty", missing=set(), existing=set(), episodes=episodes,
    )
    with _freeze_datetime_now(ns, NOW):
        gate = obj._airing_gate_v1120(_sub(), payload=cal)
    assert gate["decision"] == "skip_future"
    assert gate["decision"] != "skip_complete"
    assert (gate.get("due_uncovered") or gate.get("target_episodes") or []) == []
    assert 1 in (gate.get("future_missing") or [])
    assert int(gate.get("next_episode") or 0) == 1


def test_c_caught_up_skip_future():
    episodes = [
        {"episode": i, "air_date": f"2026-09-{i:02d}", "air_at": f"2026-09-{i:02d}T20:00:00", "precision": "datetime"}
        for i in range(1, 7)
    ] + [
        {"episode": 7, "air_date": "2026-09-12", "air_at": "2026-09-12T20:00:00", "precision": "datetime"},
    ]
    obj, ns, cal = _gate_base(
        missing_source="used_empty", missing=set(), existing={1, 2, 3, 4, 5, 6}, episodes=episodes,
    )
    with _freeze_datetime_now(ns, NOW):
        gate = obj._airing_gate_v1120(_sub(), payload=cal)
    assert gate["decision"] == "skip_future"
    assert gate["preflight_state"] == "SATISFIED"
    assert (gate.get("target_episodes") or []) == []
    assert int(gate.get("next_episode") or 0) == 7


def test_d_unknown_without_calendar():
    obj, ns, cal = _gate_base(
        missing_source="used_empty", missing=set(), existing=set(), episodes=[],
    )
    with _freeze_datetime_now(ns, NOW):
        gate = obj._airing_gate_v1120(_sub(), payload={"subscriptions": []})
    assert gate["preflight_state"] == "UNKNOWN"
    assert gate["decision"] == "continue_match"
    assert gate["decision"] not in {"skip_complete", "skip_future"}
    assert gate["covered"] is False


def test_e_explicit_mp_missing_due():
    episodes = [
        {"episode": 5, "air_date": "2026-09-10", "air_at": "2026-09-10T20:00:00", "precision": "datetime"},
        {"episode": 6, "air_date": "2026-09-11", "air_at": "2026-09-11T12:00:00", "precision": "datetime"},
    ]
    obj, ns, cal = _gate_base(
        missing_source="used_missing", missing={5, 6}, existing={1, 2, 3, 4}, episodes=episodes,
    )
    with _freeze_datetime_now(ns, NOW):
        gate = obj._airing_gate_v1120(_sub(), payload=cal)
    assert gate["decision"] == "search_due"
    assert gate["preflight_state"] == "MISSING"
    assert gate["target_episodes"] == [5, 6]


def test_f_mp_missing_all_future_skip_future():
    episodes = [
        {"episode": i, "air_date": f"2026-09-{10+i:02d}", "air_at": f"2026-09-{10+i:02d}T20:00:00", "precision": "datetime"}
        for i in range(5, 9)
    ]
    # E05=09-15, E06=09-16, E07=09-17, E08=09-18 — all after NOW 09-11
    obj, ns, cal = _gate_base(
        missing_source="used_missing", missing={5, 6, 7, 8}, existing={1, 2, 3, 4}, episodes=episodes,
    )
    with _freeze_datetime_now(ns, NOW):
        gate = obj._airing_gate_v1120(_sub(), payload=cal)
    assert gate["decision"] == "skip_future"
    assert (gate.get("target_episodes") or []) == []


def test_g_yesterday_miss_still_due_across_day():
    episodes = [
        {"episode": 1, "air_date": "2026-09-10", "air_at": "2026-09-10T20:00:00", "precision": "datetime"},
    ]
    obj, ns, cal = _gate_base(
        missing_source="used_empty", missing=set(), existing=set(), episodes=episodes,
    )
    with _freeze_datetime_now(ns, NOW):
        gate = obj._airing_gate_v1120(_sub(), payload=cal)
    assert 1 in (gate.get("due_calendar") or [])
    assert 1 in (gate.get("target_episodes") or gate.get("due_uncovered") or [])
    assert gate["decision"] != "skip_complete"


def test_h_next_future_never_past():
    episodes = [
        {"episode": 1, "air_date": "2026-09-10", "air_at": "2026-09-10T20:00:00", "precision": "datetime"},
        {"episode": 7, "air_date": "2026-09-12", "air_at": "2026-09-12T20:00:00", "precision": "datetime"},
        {"episode": 8, "air_date": "2026-09-19", "air_at": "2026-09-19T20:00:00", "precision": "datetime"},
    ]
    obj, ns, cal = _gate_base(
        missing_source="used_empty", missing=set(), existing=set(), episodes=episodes,
    )
    with _freeze_datetime_now(ns, NOW):
        gate = obj._airing_gate_v1120(_sub(), payload=cal)
    assert int(gate.get("next_episode") or 0) == 7
    assert int(gate.get("next_episode") or 0) != 1


def test_green_lantern_skip_future_preserved():
    """绿灯军团：existing E01-E04, E05+ future → skip_future."""
    episodes = [
        {"episode": i, "air_date": f"2026-08-{20+i:02d}", "air_at": f"2026-08-{20+i:02d}T20:00:00", "precision": "datetime"}
        for i in range(1, 5)
    ] + [
        {"episode": 5, "air_date": "2026-09-13", "air_at": "2026-09-13T20:00:00", "precision": "datetime"},
        {"episode": 6, "air_date": "2026-09-20", "air_at": "2026-09-20T20:00:00", "precision": "datetime"},
        {"episode": 7, "air_date": "2026-09-27", "air_at": "2026-09-27T20:00:00", "precision": "datetime"},
        {"episode": 8, "air_date": "2026-10-04", "air_at": "2026-10-04T20:00:00", "precision": "datetime"},
    ]
    obj, ns, cal = _gate_base(
        missing_source="used_empty", missing=set(), existing={1, 2, 3, 4}, episodes=episodes,
    )
    with _freeze_datetime_now(ns, NOW):
        gate = obj._airing_gate_v1120(
            _sub(id=501, name="绿灯军团", tmdbid=501), payload=cal,
        )
    assert gate["decision"] == "skip_future"
    assert (gate.get("target_episodes") or []) == []
    assert int(gate.get("next_episode") or 0) == 5


def test_yizhan_cangqiong_skip_future_preserved():
    episodes = [
        {"episode": i, "air_date": f"2026-08-{10+i:02d}", "air_at": f"2026-08-{10+i:02d}T20:00:00", "precision": "datetime"}
        for i in range(1, 9)
    ] + [
        {"episode": 9, "air_date": "2026-09-15", "air_at": "2026-09-15T20:00:00", "precision": "datetime"},
    ]
    obj, ns, cal = _gate_base(
        missing_source="used_empty", missing=set(), existing=set(range(1, 9)), episodes=episodes,
    )
    with _freeze_datetime_now(ns, NOW):
        gate = obj._airing_gate_v1120(
            _sub(id=502, name="一斩苍穹", tmdbid=502), payload=cal,
        )
    assert gate["decision"] == "skip_future"
    assert (gate.get("target_episodes") or []) == []
    assert int(gate.get("next_episode") or 0) == 9


def test_split_due_future_and_next_from_future_only():
    Cal, _ = _load_mixin(PLUGIN / "calendar_driven_v209.py", "GuangYaCalendarDrivenV209Mixin")

    class Base:
        def _airing_gate_v1120(self, subscribe, payload=None):
            return {}

        def _is_movie_subscription(self, subscribe):
            return False

        def _episode_air_at_v1120(self, row):
            return datetime.datetime.fromisoformat(row["air_at"])

        def _episode_is_actively_due_v209(self, row, now):
            air = self._episode_air_at_v1120(row)
            return bool(air and air <= now)

    class Obj(Cal, Base):
        pass

    item = {
        "episodes": [
            {"episode": 1, "air_at": "2026-09-10T20:00:00", "air_date": "2026-09-10", "precision": "datetime"},
            {"episode": 7, "air_at": "2026-09-12T20:00:00", "air_date": "2026-09-12", "precision": "datetime"},
        ]
    }
    split = Obj()._split_calendar_due_future_v209(item, _sub(), NOW)
    assert 1 in split["due"]
    assert 7 in split["future"]
    assert split["next_episode"] == 7
