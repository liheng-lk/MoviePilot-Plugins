"""Run the real candidate dispatch methods with deterministic queue/source doubles."""
from __future__ import annotations

import ast
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional


PLUGIN = Path(__file__).resolve().parents[3] / "plugins.v3" / "guangyatransferassistant"
ACTIVE = {"new", "retry", "dispatching", "submitted", "queued", "waiting", "completed"}


def _method(filename, name):
    path = PLUGIN / filename
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(n for cls in tree.body if isinstance(cls, ast.ClassDef)
                for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    module = ast.Module(body=[node], type_ignores=[])
    ns = dict(Any=Any, Dict=Dict, List=List, Optional=Optional, time=time,
              _ACTIVE_SOURCE_STATES=ACTIVE, _ACTIVE_CLAIM_STATES=ACTIVE,
              _ACTIVE_VIEWING_SOURCE_STATES_V1113=ACTIVE,
              _entry_match_reason=lambda entry, sub: (entry.get("matches", True), "exact identity"))
    exec(compile(module, str(path), "exec"), ns)
    return ns[name]


class Harness:
    provider = _method("provider_sources_v192.py", "_dispatch_provider_candidate")
    channel = _method("resource_planner_v190.py", "_dispatch_channel_external_candidates")
    viewing = _method("viewing_dispatch_v1113.py", "_dispatch_viewing_external_v1113")
    _channel_external_auto_dispatch = True
    _provider_auto_search = True
    _external_auto_dispatch = True

    def __init__(self, *, movie=True):
        # User-reported names are labels here, not fabricated live resource evidence.
        self.sub = SimpleNamespace(id=1, name="朱丽叶与朱丽叶", year="2026", movie=movie)
        self.rows = [dict(type="magnet", identity="first", uri="first", name="first"),
                     dict(type="ed2k", identity="second", uri="second", name="second")]
        self.history = {}
        self.store = {}
        self.spawned = []
        self.upserts = []
        self.logs = []
        self.queue_results = {}
        self.plans = []

    def _is_movie_subscription(self, sub): return sub.movie
    def _provider_keyword(self, sub): return sub.name
    def _search_external_providers(self, keyword): return {"data": self.rows}
    def _provider_candidate_matches(self, sub, row): return row.get("matches", True)
    def _existing_source(self, sid, kind, identity): return self.history.get(identity, {})
    def _subscription_missing_episodes(self, sub): return [] if sub.movie else [1, 2]
    def _pending_reservations(self, sub): return {"movie": False, "episodes": []}
    def _active_source_claims(self, sid): return set()
    def _source_store(self): return {"items": self.store}
    def _external_resource_allowed(self, sub, entry, row): return row.get("allowed", True), "rule"
    def _candidate_target_episodes(self, sub, entry, row, uncovered): return {1}.intersection(uncovered)
    def _save_resource_plan(self, sub, plan): self.plans.append(plan)
    def _viewing_external_candidates_v1113(self, sub): return self.rows, {"counts": {}, "keyword": sub.name}
    def _plugin_log(self, level, message, *args): self.logs.append(message % args)

    def get_data(self, key):
        return {"items": [{"resource_group_id": str(i), "external_sources": [row]}
                          for i, row in enumerate(self.rows)]}

    def _upsert_source(self, sid, uri, **fields):
        self.upserts.append(uri)
        row = {"id": uri, "subscribe_id": sid, "state": "new", **fields}
        self.store[uri] = row
        return row

    def _update_source(self, sid, **fields):
        self.store[sid].update(fields)
        return self.store[sid]

    def _spawn_source_dispatch(self, sid):
        self.spawned.append(sid)
        return self.queue_results.get(sid, {"success": True, "reason": "queued"})


def test_provider_terminal_first_candidate_does_not_starve_later_movie_resource():
    for state in ("failed", "needs_review", "disabled"):
        h = Harness()
        h.history["first"] = {"id": "first", "state": state}
        action = h.provider(h.sub, set())
        assert action["source_id"] == "second", state
        assert h.upserts == ["second"]


def test_provider_cooldown_reopened_candidate_is_executed():
    for state in ("failed_reopen", "review_reopen"):
        h = Harness()
        h.history["first"] = {"id": "first", "state": state, "enabled": True}
        assert h.provider(h.sub, set())["source_id"] == "first"


def test_channel_movie_continues_to_next_matching_post_after_failed_or_rejected_candidate():
    for state in ("failed", "needs_review", "disabled"):
        h = Harness()
        h.history["first"] = {"id": "first", "state": state}
        result = h.channel(h.sub)
        assert result["success"] is True
        assert [a["source_id"] for a in result["actions"]] == ["second"], state
    h = Harness()
    h.rows[0]["allowed"] = False
    assert h.channel(h.sub)["actions"][0]["source_id"] == "second"


def test_all_automatic_dispatch_paths_report_queue_failure_without_success_actions():
    for route in ("provider", "channel", "viewing"):
        h = Harness()
        h.queue_results = {key: {"success": False, "reason": "thread_start_failed", "message": "cannot start"}
                           for key in ("first", "second")}
        result = h.provider(h.sub, set()) if route == "provider" else getattr(h, route)(h.sub)
        assert result is None if route == "provider" else not result["actions"], route
        assert h.spawned == ["first", "second"], route


def test_busy_source_does_not_spawn_alternative_movie_task():
    for route in ("provider", "channel", "viewing"):
        h = Harness()
        h.queue_results["first"] = {"success": False, "reason": "already_running", "message": "busy"}
        result = h.provider(h.sub, set()) if route == "provider" else getattr(h, route)(h.sub)
        assert result is None if route == "provider" else not result["actions"], route
        assert h.spawned == ["first"], route


def test_tv_queue_failure_keeps_missing_episodes_in_plan():
    for route in ("channel", "viewing"):
        h = Harness(movie=False)
        h.rows = h.rows[:1]
        h.queue_results["first"] = {"success": False, "reason": "thread_start_failed"}
        result = getattr(h, route)(h.sub)
        assert not result["actions"]
        remaining = h.plans[-1]["uncovered"] if route == "channel" else result["remaining"]
        assert remaining == [1, 2]


def test_accepted_movie_queue_stops_after_one_candidate():
    for route in ("provider", "channel", "viewing"):
        h = Harness()
        result = h.provider(h.sub, set()) if route == "provider" else getattr(h, route)(h.sub)
        assert result["source_id"] == "first" if route == "provider" else len(result["actions"]) == 1
        assert h.spawned == ["first"]
