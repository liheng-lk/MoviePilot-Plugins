from __future__ import annotations

import ast
import importlib.util
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
POLICY = PLUGIN / "dispatch_policy_v1125.py"
FINAL_POLICY = PLUGIN / "dispatch_policy_final_v1125.py"
ENTRY = PLUGIN / "__init__.py"

policy_text = POLICY.read_text(encoding="utf-8")
final_policy_text = FINAL_POLICY.read_text(encoding="utf-8")
entry_text = ENTRY.read_text(encoding="utf-8")

spec = importlib.util.spec_from_file_location("guangya_dispatch_policy_v1125_test", POLICY)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)
PolicyMixin = module.GuangYaDispatchPolicyV1125Mixin


class _Sub:
    def __init__(self, sid: int, *, movie: bool = False, missing=None, state: str = "R"):
        self.id = sid
        self.name = f"Demo {sid}"
        self.movie = movie
        self.missing = list(missing or [])
        self.state = state


class _Base:
    _external_search_cooldown_minutes_v1114 = 180

    def __init__(self):
        self._selected_subscriptions = [1, 2, 3, 4, 5]
        self.subs = {
            1: _Sub(1, missing=[1]),
            2: _Sub(2, missing=[2]),
            3: _Sub(3, missing=[3]),
            4: _Sub(4, movie=True),
            5: _Sub(5, missing=[5]),
        }
        self.mode = ""
        self.gates = {
            1: {"calendar_available": True, "raw_missing": [1], "due_uncovered": [1], "reserved": [], "claimed": []},
            2: {"calendar_available": True, "raw_missing": [2], "due_uncovered": [], "future_missing": [2], "reserved": [], "claimed": []},
            3: {"calendar_available": False, "raw_missing": [3], "due_uncovered": [], "reserved": [], "claimed": []},
            5: {"calendar_available": True, "raw_missing": [5], "due_uncovered": [5], "reserved": [], "claimed": []},
        }
        self.reservations = {}
        self.claims = {}
        self.external_state = {"5": {"last_at": time.time()}}
        self.saved = {}
        self.mode_batches = []
        self.base_batches = []
        self.tick_due = None
        self.gate_calls = 0

    def init_plugin(self, config=None):
        return None

    def _list_subscriptions(self, state="N,R"):
        return list(self.subs.values())

    def _is_guangya_route(self, subscribe):
        return True

    def _is_movie_subscription(self, subscribe):
        return bool(subscribe.movie)

    def _subscription_missing_episodes(self, subscribe):
        return list(subscribe.missing)

    def _pending_reservations(self, subscribe):
        return {
            "episodes": set(self.reservations.get(int(subscribe.id), [])),
            "movie": False,
        }

    def _active_source_claims(self, sid):
        return list(self.claims.get(int(sid), []))

    def _movie_transfer_confirmed(self, subscribe):
        return False

    def _finish_subscription_if_complete(self, subscribe):
        return True

    def _external_search_state_v1114(self):
        return dict(self.external_state)

    def _refresh_airing_calendar_v1120(self, force=False):
        return {"subscriptions": []}

    def _airing_gate_v1120(self, subscribe, payload=None):
        self.gate_calls += 1
        return dict(self.gates.get(subscribe.id) or {})

    def _route_source_mode_value_v1115(self):
        return self.mode

    def _find_subscription(self, sid):
        return self.subs.get(int(sid or 0))

    def save_data(self, key, value):
        self.saved[key] = value

    def get_data(self, key):
        return self.saved.get(key)

    def _plugin_log(self, *args, **kwargs):
        return None

    def _run_v1115_mode_batch(self, batch, trigger, mode, force=False):
        self.mode_batches.append((list(batch), trigger, mode, bool(force)))

    def _run_reliability_route_batch(self, batch, trigger):
        self.base_batches.append((list(batch), trigger))

    def _tick(self, host_service=True):
        self.tick_due = self._viewing_due_subscription_ids_v1115()
        return None


class _Harness(PolicyMixin, _Base):
    pass


def _method(name: str, next_name: str | None = None) -> str:
    start = policy_text.index(f"    def {name}(")
    if next_name:
        return policy_text[start:policy_text.index(f"    def {next_name}(", start)]
    return policy_text[start:]


def test_v1125_policy_parses_and_sits_below_final_authority_above_weekly_scheduler():
    ast.parse(policy_text, filename=str(POLICY))
    ast.parse(final_policy_text, filename=str(FINAL_POLICY))
    ast.parse(entry_text, filename=str(ENTRY))
    assert "from .dispatch_policy_v1125 import GuangYaDispatchPolicyV1125Mixin" in entry_text
    assert "from .dispatch_policy_final_v1125 import GuangYaDispatchPolicyFinalV1125Mixin" in entry_text
    start = entry_text.index("class GuangYaTransferAssistant(")
    page = entry_text.index("GuangYaPagePerfV1123Mixin,", start)
    final_policy = entry_text.index("GuangYaDispatchPolicyFinalV1125Mixin,", start)
    policy = entry_text.index("GuangYaDispatchPolicyV1125Mixin,", start)
    weekly = entry_text.index("GuangYaAiringWeeklyV1121Mixin,", start)
    scheduler = entry_text.index("GuangYaAiringSchedulerV1120Mixin,", start)
    assert page < final_policy < policy < weekly < scheduler
    assert 'plugin_version = "1.12.12"' in entry_text
    assert 'build_id = "20260905-r58"' in entry_text
    assert 'build_id = "20260904-r51"' in policy_text


def test_passive_channel_uses_real_missing_and_never_calls_calendar_gate():
    harness = _Harness()
    harness.mode = "channel_event"
    harness.subs[1].missing = [1, 2, 3]
    harness.reservations[1] = [2]
    harness.claims[1] = [3]
    harness.saved["airing_gate_state_v1120"] = {
        "1": {
            "due_uncovered": [],
            "future_missing": [1, 2],
            "off_day_missing": [3],
            "next_episode": 4,
            "next_air_at": "2026-09-10T20:00",
        }
    }
    result = harness._airing_gate_v1120(harness.subs[1])
    assert harness.gate_calls == 0
    assert result["passive_channel_bypass_v1125"] is True
    assert result["calendar_available"] is True
    assert result["due_missing"] == [1, 2, 3]
    assert result["due_uncovered"] == [1]
    assert result["reserved"] == [2]
    assert result["claimed"] == [3]
    assert result["strict_due_uncovered_v1125"] == []
    assert result["strict_future_missing_v1125"] == [1, 2]
    assert result["future_missing"] == []
    assert result["off_day_missing"] == []

    harness.mode = "airing_pull"
    strict = harness._airing_gate_v1120(harness.subs[1])
    assert harness.gate_calls == 1
    assert "passive_channel_bypass_v1125" not in strict
    assert strict["due_uncovered"] == [1]


def test_passive_channel_survives_even_if_strict_calendar_gate_would_raise():
    class _BrokenCalendarBase(_Base):
        def _airing_gate_v1120(self, subscribe, payload=None):
            raise RuntimeError("calendar unavailable")

    class _BrokenHarness(PolicyMixin, _BrokenCalendarBase):
        pass

    harness = _BrokenHarness()
    harness.mode = "channel_event"
    result = harness._airing_gate_v1120(harness.subs[1])
    assert result["passive_channel_bypass_v1125"] is True
    assert result["due_uncovered"] == [1]

    harness.mode = "airing_pull"
    try:
        harness._airing_gate_v1120(harness.subs[1])
    except RuntimeError as err:
        assert "calendar unavailable" in str(err)
    else:
        raise AssertionError("主动日历模式必须继续尊重严格日历 gate")


def test_due_scope_is_thread_local_between_concurrent_subscriptions():
    harness = _Harness()
    harness.subs[1].missing = [1, 9]
    harness.subs[2].missing = [2, 8]
    barrier = threading.Barrier(2)
    results = {}

    def worker(sid: int, episode: int):
        subscribe = harness.subs[sid]
        with harness._due_scope_v1120(subscribe, [episode]):
            barrier.wait(timeout=2)
            results[sid] = harness._subscription_missing_episodes(subscribe)
            barrier.wait(timeout=2)

    first = threading.Thread(target=worker, args=(1, 1))
    second = threading.Thread(target=worker, args=(2, 2))
    first.start()
    second.start()
    first.join(timeout=3)
    second.join(timeout=3)
    assert not first.is_alive() and not second.is_alive()
    assert results == {1: [1], 2: [2]}
    assert harness._subscription_missing_episodes(harness.subs[1]) == [1, 9]
    assert harness._subscription_missing_episodes(harness.subs[2]) == [2, 8]


def test_smart_pull_filters_off_day_before_execution_and_falls_back_only_when_calendar_unavailable():
    harness = _Harness()
    due = harness._smart_pull_due_ids_v1125()
    # #1 今天 due；#2 有日历但今天不更新；#3 日历不可用按旧真实缺集兜底；
    # #4 电影按冷却参与；#5 虽然 due 但仍在外部检索冷却。
    assert due == [1, 3, 4]
    snapshot = harness.saved["dispatch_policy_v1125"]
    assert snapshot["off_day"] == 1
    assert snapshot["calendar_fallback"] == 1


def test_five_minute_tick_is_channel_only_without_disabling_other_threads_selector():
    harness = _Harness()
    harness._tick(host_service=False)
    assert harness.tick_due == []
    # tick finally 后同一实例的正常 selector 仍恢复。
    assert harness._viewing_due_subscription_ids_v1115() == [1, 3, 4]


def test_channel_worker_never_appends_post_channel_viewing_pull():
    harness = _Harness()
    harness._run_reliability_route_batch([1, 2], "频道新增资源")
    assert harness.mode_batches == [([1, 2], "频道新增资源", "channel_event", False)]
    assert harness.base_batches == []


def test_legacy_viewing_trigger_is_revalidated_by_smart_selector():
    harness = _Harness()
    harness._run_reliability_route_batch([1, 2, 3, 4, 5], "观影定时轮询")
    assert harness.mode_batches == [([1, 3, 4], "更新日历主动拉取", "airing_pull", False)]


def test_hourly_airing_service_is_the_only_routine_pull_and_never_force_bypasses_cooldown():
    method = _method("_calendar_due_check_v1110", "_repair_signature_v1125")
    assert "_smart_pull_due_ids_v1125()" in method
    assert '"airing_pull"' in method
    assert "force=False" in method
    assert "_airing_due_force_v1120" not in method
    tick = _method("_tick", "_external_cooldown_due_v1125")
    assert "channel_only = True" in tick
    assert "super()._tick(host_service=host_service)" in tick


def test_daily_repair_is_strictly_channel_first_then_remaining_gying():
    method = _method("_daily_full_catchup_v1110")
    refresh = method.index("self.refresh_channels(force=True)")
    channel = method.index('"每日全员复核·频道阶段"')
    recompute = method.index("remaining: List[int]")
    gying = method.index('"每日全员复核·GYING阶段"')
    assert refresh < channel < recompute < gying
    assert '"channel_event"' in method
    assert '"daily_repair_pull"' in method
    assert "force=True" in method
    assert "_uncovered_missing_v1125" in method
    assert '"strategy": "channel_first_then_gying"' in method
