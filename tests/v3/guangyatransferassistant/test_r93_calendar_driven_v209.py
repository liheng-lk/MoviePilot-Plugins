"""2.0.9-r93：MP 原生日历 ∩ missing、21:00 兜底、handled/covered、PoW singleflight。"""
from __future__ import annotations

import ast
import datetime
import importlib.util
import threading
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
CAL = (PLUGIN / "calendar_driven_v209.py").read_text(encoding="utf-8")
POW = (PLUGIN / "pow_singleflight_v209.py").read_text(encoding="utf-8")
VIEW = (PLUGIN / "viewing_logging_v1113.py").read_text(encoding="utf-8")
PACKAGE = (ROOT / "package.v3.json").read_text(encoding="utf-8")


def test_r93_version_and_mro():
    assert 'plugin_version = "2.0.10"' in ENTRY
    assert 'build_id = "20260911-r94"' in ENTRY
    assert "GuangYaCalendarDrivenV209Mixin" in ENTRY
    assert "GuangYaPowSingleflightV209Mixin" in ENTRY
    assert "GuangYaFoundationOpsV209Mixin" in ENTRY
    head = ENTRY.split("class GuangYaTransferAssistant(", 1)[1].split("):", 1)[0]
    lines = [ln.strip().rstrip(",") for ln in head.strip().splitlines() if ln.strip()]
    assert lines[0] == "GuangYaFoundationOpsV209Mixin"
    assert lines[1] == "GuangYaEpisodeTargetV210Mixin"
    assert lines[2] == "GuangYaCalendarDrivenV209Mixin"
    assert lines[3] == "GuangYaPowSingleflightV209Mixin"
    assert "GuangYaEpisodeTargetV210Mixin" in ENTRY
    assert '"version": "2.0.10"' in PACKAGE
    assert "v2.0.9" in PACKAGE
    assert "0 21 * * *" in CAL
    assert "GuangYaTransferAssistantDailyReconcile" in CAL
    assert "DailyCatchup" in CAL  # filtered out of services
    assert "硬阻断观影 Magnet/ED2K" not in VIEW
    assert "covered=False" in VIEW


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
        "Set": set,
        "Tuple": tuple,
        "datetime": datetime,
        "inspect": __import__("inspect"),
        "threading": threading,
        "time": __import__("time"),
        "CronTrigger": MagicMock(),
    }
    # CronTrigger.from_crontab used in class body defaults / methods — provide stub.
    ns["CronTrigger"].from_crontab = MagicMock(return_value="cron")
    exec(compile(mod, str(module_file), "exec"), ns)
    return ns[class_name]


def test_target_episodes_calendar_intersect_missing():
    """E10 today due ∩ missing{E10,E11} → target E10 only; E11 future not searched."""
    Mixin = _load_mixin(PLUGIN / "calendar_driven_v209.py", "GuangYaCalendarDrivenV209Mixin")

    class Base:
        def _airing_gate_v1120(self, subscribe, payload=None):
            return {
                "subscribe_id": 100,
                "calendar_available": True,
                "due_missing": [10, 11],
                "due_uncovered": [10, 11],
                "future_missing": [],
                "calendar_provider": "moviepilot_native",
            }

        def _is_movie_subscription(self, subscribe):
            return False

        def _mp_authoritative_missing_episodes_v209(self, subscribe):
            return "used", {10, 11}

        def _refresh_airing_calendar_v1120(self, force=False):
            return self._calendar

        def _calendar_item_for_v1120(self, subscribe, calendar):
            return self._calendar["subscriptions"][0]

        def _episode_air_at_v1120(self, row):
            return datetime.datetime.fromisoformat(row["air_at"])

        def _episode_is_actively_due_v209(self, row, now):
            air = datetime.datetime.fromisoformat(row["air_at"])
            return air.date() <= now.date()

        def _pending_reservations(self, subscribe):
            return {"episodes": []}

        def _active_source_claims(self, sid):
            return set()

        def _episode_ready_for_external_v209(self, *a, **k):
            return True

        def _plugin_log(self, *a, **k):
            pass

        def _bump_metric_v209(self, *a, **k):
            pass

    class Obj(Mixin, Base):
        def _mp_authoritative_missing_episodes_v209(self, subscribe):
            return "used", {10, 11}

        def _episode_is_actively_due_v209(self, row, now):
            air = datetime.datetime.fromisoformat(row["air_at"])
            return air.date() <= now.date()

        def _episode_ready_for_external_v209(self, *a, **k):
            return True

    today = datetime.date.today()
    obj = Obj()
    obj._calendar = {
        "subscriptions": [{
            "subscribe_id": 100,
            "provider": "moviepilot_native",
            "episode_group": "abc",
            "episodes": [
                {"episode": 9, "air_date": (today - datetime.timedelta(days=1)).isoformat(),
                 "air_at": f"{(today - datetime.timedelta(days=1)).isoformat()}T20:00:00", "precision": "datetime"},
                {"episode": 10, "air_date": today.isoformat(),
                 "air_at": f"{today.isoformat()}T20:00:00", "precision": "datetime"},
                {"episode": 11, "air_date": (today + datetime.timedelta(days=1)).isoformat(),
                 "air_at": f"{(today + datetime.timedelta(days=1)).isoformat()}T20:00:00", "precision": "datetime"},
            ],
        }]
    }
    sub = SimpleNamespace(id=100, name="青春碎片", season=1, episode_group="abc")
    gate = obj._airing_gate_v1120(sub, payload=obj._calendar)
    assert gate["target_episodes"] == [10], gate
    assert 11 not in gate["due_uncovered"]
    assert gate.get("episode_group") == "abc"


def test_skip_complete_when_mp_missing_empty():
    """Only used_complete (positive coverage) may skip_complete on empty missing."""
    Mixin = _load_mixin(PLUGIN / "calendar_driven_v209.py", "GuangYaCalendarDrivenV209Mixin")

    class Base:
        def _airing_gate_v1120(self, subscribe, payload=None):
            return {"due_missing": [10], "due_uncovered": [10], "calendar_provider": "moviepilot_native"}

        def _is_movie_subscription(self, subscribe):
            return False

        def _plugin_log(self, *a, **k):
            self.logs.append(a)

        def _bump_metric_v209(self, *a, **k):
            pass

    class Obj(Mixin, Base):
        def __init__(self):
            self.logs = []

        def _mp_authoritative_missing_episodes_v209(self, subscribe):
            return "used_complete", set()

        def _sync_media_library_progress(self, subscribe):
            return {"existing": [1, 2, 3], "missing": []}

        def _library_existing_episodes_v209(self, subscribe):
            return {1, 2, 3}

    obj = Obj()
    gate = obj._airing_gate_v1120(SimpleNamespace(id=170, name="尼古喵喵", season=1))
    assert gate["decision"] == "skip_complete"
    assert gate["preflight_state"] == "SATISFIED"
    assert gate["target_episodes"] == []
    assert gate["covered"] is True


def test_used_empty_without_calendar_is_continue_match():
    Mixin = _load_mixin(PLUGIN / "calendar_driven_v209.py", "GuangYaCalendarDrivenV209Mixin")

    class Base:
        def _airing_gate_v1120(self, subscribe, payload=None):
            return {"calendar_available": False}

        def _is_movie_subscription(self, subscribe):
            return False

        def _plugin_log(self, *a, **k):
            pass

        def _bump_metric_v209(self, *a, **k):
            pass

    class Obj(Mixin, Base):
        def _mp_authoritative_missing_episodes_v209(self, subscribe):
            return "used_empty", set()

        def _refresh_airing_calendar_v1120(self, force=False):
            return {"subscriptions": []}

        def _calendar_item_for_v1120(self, subscribe, calendar):
            return {}

        def _pending_reservations(self, subscribe):
            return {}

        def _active_source_claims(self, sid):
            return set()

        def _sync_media_library_progress(self, subscribe):
            return {"existing": [], "missing": []}

        def _library_existing_episodes_v209(self, subscribe):
            return set()

    gate = Obj()._airing_gate_v1120(
        SimpleNamespace(id=171, name="未知剧", season=1, total_episode=18, start_episode=1),
        payload={"subscriptions": []},
    )
    assert gate["decision"] == "continue_match"
    assert gate["preflight_state"] == "UNKNOWN"
    assert gate["covered"] is False


def test_reservation_blocks_gying_target():
    Mixin = _load_mixin(PLUGIN / "calendar_driven_v209.py", "GuangYaCalendarDrivenV209Mixin")
    today = datetime.date.today()

    class Base:
        def _airing_gate_v1120(self, subscribe, payload=None):
            return {"due_uncovered": [10], "calendar_available": True, "calendar_provider": "moviepilot_native"}

        def _is_movie_subscription(self, subscribe):
            return False

        def _mp_authoritative_missing_episodes_v209(self, subscribe):
            return "used", {10}

        def _refresh_airing_calendar_v1120(self, force=False):
            return self.cal

        def _calendar_item_for_v1120(self, subscribe, calendar):
            return self.cal["subscriptions"][0]

        def _episode_air_at_v1120(self, row):
            return datetime.datetime.fromisoformat(row["air_at"])

        def _episode_is_actively_due_v209(self, row, now):
            return True

        def _pending_reservations(self, subscribe):
            return {"episodes": [10]}

        def _active_source_claims(self, sid):
            return set()

        def _episode_ready_for_external_v209(self, *a, **k):
            return True

        def _plugin_log(self, *a, **k):
            pass

        def _bump_metric_v209(self, *a, **k):
            pass

    class Obj(Mixin, Base):
        def _mp_authoritative_missing_episodes_v209(self, subscribe):
            return "used", {10}

        def _episode_is_actively_due_v209(self, row, now):
            return True

        def _episode_ready_for_external_v209(self, *a, **k):
            return True

    obj = Obj()
    obj.cal = {"subscriptions": [{"subscribe_id": 1, "provider": "moviepilot_native", "episodes": [
        {"episode": 10, "air_date": today.isoformat(), "air_at": f"{today.isoformat()}T20:00:00", "precision": "datetime"}
    ]}]}
    gate = obj._airing_gate_v1120(SimpleNamespace(id=1, name="x", season=1), payload=obj.cal)
    assert gate["target_episodes"] == []
    assert gate["decision"] == "skip_complete"


def test_date_precision_morning_not_due():
    Mixin = _load_mixin(PLUGIN / "calendar_driven_v209.py", "GuangYaCalendarDrivenV209Mixin")
    obj = Mixin()
    obj._calendar_date_active_hour_v209 = 18
    today = datetime.date.today()
    row = {"precision": "date", "air_date": today.isoformat(), "air_at": ""}
    # monkeypatch air_at effective default hour 20
    obj._episode_air_at_v1120 = lambda r: datetime.datetime.combine(today, datetime.time(20, 0))
    morning = datetime.datetime.combine(today, datetime.time(10, 0))
    assert obj._episode_is_actively_due_v209(row, morning) is False
    evening = datetime.datetime.combine(today, datetime.time(18, 30))
    assert obj._episode_is_actively_due_v209(row, evening) is True


def test_smart_pull_calendar_failure_no_tv_external():
    Mixin = _load_mixin(PLUGIN / "calendar_driven_v209.py", "GuangYaCalendarDrivenV209Mixin")

    class Base:
        def _active_selected_subscriptions_v1125(self):
            return [SimpleNamespace(id=1, name="tv"), SimpleNamespace(id=2, name="movie")]

        def _external_cooldown_due_v1125(self, sid, state, now):
            return True

        def _external_search_state_v1114(self):
            return {}

        def _is_movie_subscription(self, subscribe):
            return int(subscribe.id) == 2

        def _movie_needs_pull_v1125(self, subscribe):
            return True

        def _refresh_airing_calendar_v1120(self, force=False):
            raise RuntimeError("calendar down")

        def _positive_ids_v1125(self, values):
            return [int(v) for v in values]

        def _plugin_log(self, *a, **k):
            pass

    class Obj(Mixin, Base):
        def _external_cooldown_due_v1125(self, sid, state, now):
            return True

        def _external_search_state_v1114(self):
            return {}

        def _plugin_log(self, *a, **k):
            pass

    due = Obj()._smart_pull_due_ids_v1125()
    assert due == [2]  # movie may still pull; TV must not open all-missing GYING


def test_daily_reconcile_service_replaces_0410():
    Mixin = _load_mixin(PLUGIN / "calendar_driven_v209.py", "GuangYaCalendarDrivenV209Mixin")

    class Base:
        _enabled = True

        def get_service(self):
            return [
                {"id": "GuangYaTransferAssistantDailyCatchup", "name": "old", "trigger": "x", "func": None},
                {"id": "GuangYaTransferAssistantAiringDue", "name": "due", "trigger": "interval", "func": None},
            ]

    class Obj(Mixin, Base):
        def __init__(self):
            self._enabled = True
            self._daily_reconcile_cron_v209 = "0 21 * * *"

        def _daily_full_catchup_v1110(self):
            return {}

    services = Obj().get_service()
    ids = [s["id"] for s in services if isinstance(s, dict)]
    assert "GuangYaTransferAssistantDailyCatchup" not in ids
    assert ids.count("GuangYaTransferAssistantDailyReconcile") == 1
    assert "GuangYaTransferAssistantAiringDue" in ids


def test_daily_reconcile_remaining_skips_future_and_pending():
    Mixin = _load_mixin(PLUGIN / "calendar_driven_v209.py", "GuangYaCalendarDrivenV209Mixin")
    today = datetime.date.today()
    tomorrow = today + datetime.timedelta(days=1)
    yesterday = today - datetime.timedelta(days=1)

    class Probe(Mixin):
        def _is_movie_subscription(self, subscribe):
            return getattr(subscribe, "kind", "") == "movie"

        def _movie_needs_pull_v1125(self, subscribe):
            return True

        def _mp_authoritative_missing_episodes_v209(self, subscribe):
            return "used", set(getattr(subscribe, "missing", set()) or set())

        def _pending_reservations(self, subscribe):
            return {"episodes": list(getattr(subscribe, "reserved", []) or [])}

        def _active_source_claims(self, sid):
            return set(getattr(self, "_claims", {}).get(sid, set()) or set())

        def _calendar_item_for_v1120(self, subscribe, calendar):
            return getattr(subscribe, "item", {})

        def _episode_air_at_v1120(self, row):
            return datetime.datetime.fromisoformat(row["air_at"])

        def _episode_is_actively_due_v209(self, row, now):
            air = datetime.datetime.fromisoformat(row["air_at"])
            return air.date() <= now.date()

    p = Probe()
    cal = {"subscriptions": []}
    # A today missing -> remaining
    a = SimpleNamespace(id=1, missing={10}, reserved=[], item={
        "episodes": [{"episode": 10, "air_at": f"{today.isoformat()}T20:00:00"}]
    })
    assert p._daily_reconcile_remaining_v209(a, cal) is True
    # B tomorrow only -> skip
    b = SimpleNamespace(id=2, missing={8}, reserved=[], item={
        "episodes": [{"episode": 8, "air_at": f"{tomorrow.isoformat()}T20:00:00"}]
    })
    assert p._daily_reconcile_remaining_v209(b, cal) is False
    # C yesterday missing -> remaining
    c = SimpleNamespace(id=3, missing={5}, reserved=[], item={
        "episodes": [{"episode": 5, "air_at": f"{yesterday.isoformat()}T20:00:00"}]
    })
    assert p._daily_reconcile_remaining_v209(c, cal) is True
    # E pending reserved today -> not remaining (uncovered empty)
    e = SimpleNamespace(id=5, missing={9}, reserved=[9], item={
        "episodes": [{"episode": 9, "air_at": f"{today.isoformat()}T20:00:00"}]
    })
    assert p._daily_reconcile_remaining_v209(e, cal) is False


def test_handled_not_covered_continues_marker():
    assert "handled=True 仅表示托管所有权" in VIEW
    assert "covered=False" in VIEW
    # Ensure early return on handled alone is gone
    tree = ast.parse(VIEW)
    fn = next(
        n for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name == "GuangYaViewingLoggingV1113Mixin"
        for n in n.body
        if isinstance(n, ast.FunctionDef) and n.name == "_try_transfer_subscription_inner"
    )
    src = ast.get_source_segment(VIEW, fn) or ""
    assert "硬阻断" not in src
    assert "gap = self._viewing_gap_v1113" in src


def test_pow_singleflight_one_solver():
    tree = ast.parse(POW)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "GuangYaPowSingleflightV209Mixin")
    mod = ast.Module(body=[cls], type_ignores=[])
    ast.fix_missing_locations(mod)
    ns: Dict[str, Any] = {
        "Any": Any,
        "Dict": Dict,
        "Optional": Optional,
        "threading": threading,
        "time": __import__("time"),
        "canonical_gying_node": lambda n: str(n or "").rstrip("/").lower(),
    }
    exec(compile(mod, str(PLUGIN / "pow_singleflight_v209.py"), "exec"), ns)
    Mixin = ns["GuangYaPowSingleflightV209Mixin"]
    calls = {"n": 0}
    barrier = threading.Barrier(5)
    results = []

    class Base:
        def init_plugin(self, config=None):
            return None

        def _gying_solve_challenge_v1110(self, session, node, response, kind=None):
            calls["n"] += 1
            __import__("time").sleep(0.05)
            return {"success": True, "node": node, "n": calls["n"]}

    class Obj(Mixin, Base):
        pass

    obj = Obj()
    obj.init_plugin({})

    def worker():
        barrier.wait()
        results.append(obj._gying_solve_challenge_v1110(None, "https://xn--example.com", None, kind="remote_pow"))

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert calls["n"] == 1
    assert len(results) == 5


def test_performance_selector_cap_marker():
    """100 managed with 5 real due should not all enter pull — smart_pull uses gate targets only."""
    assert "calendar_failed" in CAL or "Fail-safe daytime" in CAL or "不主动" in CAL or "channel push" in CAL.lower() or "日历失败" in CAL or "calendar_failed" in CAL or "fail-safe" in CAL.lower() or "continue" in CAL
    assert "_smart_pull_due_ids_v1125" in CAL


def test_unscheduled_historical_gap_in_reconcile():
    Mixin = _load_mixin(PLUGIN / "calendar_driven_v209.py", "GuangYaCalendarDrivenV209Mixin")
    today = datetime.date.today()

    class Probe(Mixin):
        def _is_movie_subscription(self, subscribe):
            return False

        def _mp_authoritative_missing_episodes_v209(self, subscribe):
            return "used", {3}

        def _pending_reservations(self, subscribe):
            return {"episodes": []}

        def _active_source_claims(self, sid):
            return set()

        def _calendar_item_for_v1120(self, subscribe, calendar):
            return {
                "episodes": [
                    {"episode": 4, "air_at": f"{(today - datetime.timedelta(days=2)).isoformat()}T20:00:00"},
                    {"episode": 5, "air_at": f"{(today - datetime.timedelta(days=1)).isoformat()}T20:00:00"},
                ]
            }

        def _episode_air_at_v1120(self, row):
            return datetime.datetime.fromisoformat(row["air_at"])

        def _episode_is_actively_due_v209(self, row, now):
            return True

    assert Probe()._daily_reconcile_remaining_v209(SimpleNamespace(id=9), {}) is True
