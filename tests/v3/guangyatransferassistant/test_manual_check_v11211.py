from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
SOURCE = (PLUGIN / "manual_check_v11211.py").read_text(encoding="utf-8")
MOVIE = (PLUGIN / "movie_identity_v1129.py").read_text(encoding="utf-8")
SEASON = (PLUGIN / "xunlei_season_fence_v11210.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")


class _Base:
    def __init__(self):
        self.logs = []
        self.refreshes = []
        self.mode_batches = []
        self.delegated = []
        self.queued = []
        self.posts = []
        self.health = []
        self.movie_needed = True
        self.tv_uncovered = {1}
        self.subscriptions = {
            209: SimpleNamespace(id=209, name="失控陪审团", year="2003", type="MOVIE", state="N"),
            210: SimpleNamespace(id=210, name="测试剧", year="2026", type="TV", state="N"),
        }

    @staticmethod
    def _positive_ids_v1125(values):
        return {int(v) for v in values if str(v).isdigit() and int(v) > 0}

    def _plugin_log(self, level, message, *args):
        self.logs.append((level, message % args if args else message))

    def refresh_channels(self, force=False):
        self.refreshes.append(bool(force))
        return []

    def _run_v1115_mode_batch(self, batch, trigger, mode, force=False):
        self.mode_batches.append((list(batch), trigger, mode, bool(force)))

    def _find_subscription(self, sid):
        return self.subscriptions.get(int(sid))

    @staticmethod
    def _is_guangya_route(subscribe):
        return bool(subscribe)

    @staticmethod
    def _is_movie_subscription(subscribe):
        return str(getattr(subscribe, "type", "")) == "MOVIE"

    def _movie_needs_pull_v1125(self, subscribe):
        return bool(self.movie_needed)

    def _uncovered_missing_v1125(self, subscribe):
        return set(self.tv_uncovered)

    def _record_route_health(self, **kwargs):
        self.health.append(kwargs)

    @staticmethod
    def _now_text():
        return "2026-09-05 10:00:00"

    def _run_dispatch_trigger_v1125(self, ids, trigger):
        self.delegated.append((list(ids), trigger))

    def _command_subscription_or_reply(self, event_data, selected_only=False):
        return self.subscriptions[209]

    def _queue_async_route_check(self, sids, trigger=""):
        self.queued.append((list(sids), trigger))

    @staticmethod
    def _diagnose_subscription(subscribe):
        return {"matches": 0, "pending_jobs": 0, "failed_jobs": 0}

    def _post_command(self, event_data, title, text):
        self.posts.append((title, text))


def _mixin_class():
    tree = ast.parse(SOURCE, filename=str(PLUGIN / "manual_check_v11211.py"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "GuangYaManualCheckV11211Mixin")
    module = ast.Module(body=[cls], type_ignores=[])
    ast.fix_missing_locations(module)
    ns = {
        "Any": Any,
        "Dict": Dict,
        "Iterable": Iterable,
        "List": List,
        "GuangYaGyingAliasQueryV11212Mixin": _Base,
    }
    exec(compile(module, str(PLUGIN / "manual_check_v11211.py"), "exec"), ns)
    return ns["GuangYaManualCheckV11211Mixin"]


Mixin = _mixin_class()


class _Probe(Mixin):
    pass


def test_v11211_layer_parses_and_is_nested_before_resource_gate_without_dropping_v11210():
    ast.parse(SOURCE)
    ast.parse(MOVIE)
    ast.parse(SEASON)
    alias = (PLUGIN / "gying_alias_query_v11212.py").read_text(encoding="utf-8")
    assert "from .gying_alias_query_v11212 import GuangYaGyingAliasQueryV11212Mixin" in SOURCE
    assert "class GuangYaManualCheckV11211Mixin(GuangYaGyingAliasQueryV11212Mixin):" in SOURCE
    assert "from .xunlei_season_fence_v11210 import GuangYaXunleiSeasonFenceV11210Mixin" in alias
    assert "class GuangYaGyingAliasQueryV11212Mixin(GuangYaXunleiSeasonFenceV11210Mixin):" in alias
    assert "from .manual_check_v11211 import GuangYaManualCheckV11211Mixin" in MOVIE
    assert "class GuangYaMovieIdentityV1129Mixin(GuangYaManualCheckV11211Mixin):" in MOVIE
    head = ENTRY.split("class GuangYaTransferAssistant(", 1)[1].split("):", 1)[0]
    assert head.index("GuangYaMovieIdentityV1129Mixin") < head.index("GuangYaResourceGateV1127Mixin")
    assert 'plugin_version = "1.12.10"' in SEASON


def test_gycheck_movie_runs_channel_then_forced_full_chain():
    probe = _Probe()
    probe._run_dispatch_trigger_v1125([209], "消息立即检查·完整资源链")
    assert probe.refreshes == [True]
    assert probe.mode_batches == [
        ([209], "人工立即检查·频道阶段", "channel_event", False),
        ([209], "人工立即检查·完整资源链", "airing_pull", True),
    ]
    assert any("观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K" in row[1] for row in probe.logs)


def test_gycheck_stops_external_chain_when_channel_already_covers_movie():
    probe = _Probe()

    def cover(batch, trigger, mode, force=False):
        probe.mode_batches.append((list(batch), trigger, mode, bool(force)))
        if mode == "channel_event":
            probe.movie_needed = False

    probe._run_v1115_mode_batch = cover
    probe._run_dispatch_trigger_v1125([209], "消息立即检查·完整资源链")
    assert probe.mode_batches == [([209], "人工立即检查·频道阶段", "channel_event", False)]


def test_gycheck_tv_uses_real_uncovered_after_channel():
    probe = _Probe()
    probe._run_dispatch_trigger_v1125([210], "消息立即检查·完整资源链")
    assert probe.mode_batches[-1] == ([210], "人工立即检查·完整资源链", "airing_pull", True)
    probe.mode_batches.clear()
    probe.tv_uncovered = set()
    probe._run_dispatch_trigger_v1125([210], "消息立即检查·完整资源链")
    assert probe.mode_batches == [([210], "人工立即检查·频道阶段", "channel_event", False)]


def test_non_gycheck_trigger_delegates_without_changing_scheduler_semantics():
    probe = _Probe()
    probe._run_dispatch_trigger_v1125([209], "更新日历主动拉取")
    assert probe.delegated == [([209], "更新日历主动拉取")]
    assert probe.refreshes == []
    assert probe.mode_batches == []


def test_gycheck_command_ack_explains_channel_zero_does_not_stop_viewing():
    probe = _Probe()
    probe._handle_check_existing_command({"arg_str": "失控陪审团"})
    assert probe.queued == [([209], "消息立即检查·完整资源链")]
    assert probe.posts
    title, text = probe.posts[-1]
    assert "人工完整资源检查" in title
    assert "频道为 0 不会停止后续观影检索" in text
    assert "观影迅雷秒传 → 光鸭直接转存 → Magnet → ED2K" in text
    assert "绕过自动外部检索冷却" in text
