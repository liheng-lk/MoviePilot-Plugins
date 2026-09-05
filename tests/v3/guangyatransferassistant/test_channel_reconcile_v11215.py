from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Set, Tuple


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
SOURCE = (PLUGIN / "channel_reconcile_v11215.py").read_text(encoding="utf-8")
MANUAL = (PLUGIN / "manual_check_v11211.py").read_text(encoding="utf-8")
CORE_FINAL = (PLUGIN / "core_pipeline_final_v11214.py").read_text(encoding="utf-8")
CORE = (PLUGIN / "core_pipeline_v11214.py").read_text(encoding="utf-8")
DISPATCH = (PLUGIN / "dispatch_policy_v1125.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
PLUGIN_JSON = (PLUGIN / "plugin.json").read_text(encoding="utf-8")


class _CoreBase:
    def __init__(self):
        self.immediate = []
        self.subscriptions = []
        self.gaps = {}
        self.cache = {}
        self.cover = {}
        self.movies = set()
        self.movie_due = set()
        self.logs = []

    def _subscriptions_for_new_channel_entries_v1115(self):
        return list(self.immediate)

    def _active_selected_subscriptions_v1125(self):
        return list(self.subscriptions)

    def _is_movie_subscription(self, subscribe):
        return int(getattr(subscribe, "id", 0) or 0) in self.movies

    def _movie_needs_pull_v1125(self, subscribe):
        return int(getattr(subscribe, "id", 0) or 0) in self.movie_due

    def _uncovered_missing_v1125(self, subscribe):
        value = self.gaps.get(int(getattr(subscribe, "id", 0) or 0), set())
        if isinstance(value, Exception):
            raise value
        return set(value)

    def _cached_matches_for_subscription(self, subscribe):
        value = self.cache.get(int(getattr(subscribe, "id", 0) or 0), [])
        if isinstance(value, Exception):
            raise value
        return list(value)

    def _entry_can_cover_missing_v1115(self, entry, subscribe):
        key = str(entry.get("resource_group_id") or entry.get("message_id") or entry.get("share_url") or "")
        return self.cover.get(key, True)

    def _plugin_log(self, *args):
        self.logs.append(args)


def _entry_key(row: Dict[str, Any]) -> str:
    return str(row.get("resource_group_id") or row.get("message_id") or row.get("share_url") or "")


def _load_mixin():
    tree = ast.parse(SOURCE, filename=str(PLUGIN / "channel_reconcile_v11215.py"))
    nodes = [
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "GuangYaChannelReconcileV11215Mixin"
    ]
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "Any": Any,
        "Dict": Dict,
        "Iterable": Iterable,
        "List": List,
        "Set": Set,
        "Tuple": Tuple,
        "GuangYaCorePipelineFinalV11214Mixin": _CoreBase,
        "_entry_key_v1115": _entry_key,
    }
    exec(compile(module, str(PLUGIN / "channel_reconcile_v11215.py"), "exec"), namespace)
    return namespace["GuangYaChannelReconcileV11215Mixin"]


def _sub(sid: int, name: str = "测试剧"):
    return SimpleNamespace(id=sid, name=name)


def _pair(row: Dict[str, Any]):
    return (row, "matched")


def test_candidate_parses_and_is_inserted_without_moving_top_level_mro():
    ast.parse(SOURCE, filename=str(PLUGIN / "channel_reconcile_v11215.py"))
    ast.parse(MANUAL, filename=str(PLUGIN / "manual_check_v11211.py"))
    head = ENTRY.split("class GuangYaTransferAssistant(", 1)[1].split("):", 1)[0]
    assert "GuangYaChannelReconcileV11215Mixin" not in head
    assert "class GuangYaManualCheckV11211Mixin(GuangYaChannelReconcileV11215Mixin):" in MANUAL
    assert "class GuangYaChannelReconcileV11215Mixin(GuangYaCorePipelineFinalV11214Mixin):" in SOURCE
    assert "class GuangYaCorePipelineFinalV11214Mixin(GuangYaCorePipelineV11214Mixin):" in CORE_FINAL
    assert "class GuangYaCorePipelineV11214Mixin(GuangYaXunleiExistingEpisodeFenceV11213Mixin):" in CORE


def test_cached_guangya_share_reconciles_when_strict_event_is_missing():
    cls = _load_mixin()
    probe = cls()
    probe.subscriptions = [_sub(501)]
    probe.gaps[501] = {11}
    probe.cache[501] = [_pair({
        "resource_group_id": "rg-guangya",
        "share_url": "https://pan.guangyapan.com/s/test",
        "episode_hint": "S01E11",
    })]
    assert probe._subscriptions_for_new_channel_entries_v1115() == [501]
    assert any("频道补偿v1.12.15" in str(row) for row in probe.logs)


def test_cached_xunlei_magnet_and_ed2k_are_actionable_channel_payloads():
    cls = _load_mixin()
    cases = [
        {"resource_group_id": "rg-x", "xunlei_sources": [{"share_id": "VP-test"}]},
        {"resource_group_id": "rg-m", "external_sources": [{"type": "magnet", "uri": "magnet:?xt=urn:btih:abc"}]},
        {"resource_group_id": "rg-e", "external_sources": [{"type": "ed2k", "uri": "ed2k://|file|a.mkv|1|ABC|/"}]},
    ]
    for index, row in enumerate(cases, start=1):
        sid = 600 + index
        probe = cls()
        probe.subscriptions = [_sub(sid)]
        probe.gaps[sid] = {11}
        probe.cache[sid] = [_pair(row)]
        assert probe._subscriptions_for_new_channel_entries_v1115() == [sid]


def test_reconcile_never_triggers_without_real_uncovered_gap():
    cls = _load_mixin()
    probe = cls()
    probe.subscriptions = [_sub(701)]
    probe.gaps[701] = set()
    probe.cache[701] = [_pair({"resource_group_id": "rg", "share_url": "https://pan.guangyapan.com/s/test"})]
    assert probe._subscriptions_for_new_channel_entries_v1115() == []


def test_title_only_stale_or_noncovering_cache_does_not_reconcile():
    cls = _load_mixin()
    probe = cls()
    probe.subscriptions = [_sub(801), _sub(802), _sub(803)]
    probe.gaps = {801: {11}, 802: {11}, 803: {11}}
    probe.cache[801] = [_pair({"resource_group_id": "title-only", "display_title": "测试剧"})]
    probe.cache[802] = [_pair({"resource_group_id": "stale", "stale": True, "share_url": "https://pan.guangyapan.com/s/a"})]
    probe.cache[803] = [_pair({"resource_group_id": "wrong-ep", "share_url": "https://pan.guangyapan.com/s/b", "episode_hint": "S01E10"})]
    probe.cover["wrong-ep"] = False
    assert probe._subscriptions_for_new_channel_entries_v1115() == []


def test_gap_or_cache_read_failure_fails_closed_for_reconcile_trigger():
    cls = _load_mixin()
    probe = cls()
    probe.subscriptions = [_sub(901), _sub(902)]
    probe.gaps[901] = RuntimeError("gap unavailable")
    probe.gaps[902] = {11}
    probe.cache[901] = [_pair({"resource_group_id": "a", "share_url": "https://pan.guangyapan.com/s/a"})]
    probe.cache[902] = RuntimeError("cache unavailable")
    assert probe._subscriptions_for_new_channel_entries_v1115() == []


def test_strict_new_and_reconciled_ids_are_unioned_without_duplicates():
    cls = _load_mixin()
    probe = cls()
    probe.immediate = [1001]
    probe.subscriptions = [_sub(1001), _sub(1002)]
    probe.gaps = {1001: {11}, 1002: {12}}
    probe.cache[1001] = [_pair({"resource_group_id": "same", "share_url": "https://pan.guangyapan.com/s/a"})]
    probe.cache[1002] = [_pair({"resource_group_id": "extra", "share_url": "https://pan.guangyapan.com/s/b"})]
    assert probe._subscriptions_for_new_channel_entries_v1115() == [1001, 1002]


def test_movie_cache_reconciles_only_while_movie_still_needs_pull():
    cls = _load_mixin()
    probe = cls()
    probe.subscriptions = [_sub(1101, "电影A"), _sub(1102, "电影B")]
    probe.movies = {1101, 1102}
    probe.movie_due = {1101}
    probe.cache[1101] = [_pair({"resource_group_id": "movie-a", "share_url": "https://pan.guangyapan.com/s/a"})]
    probe.cache[1102] = [_pair({"resource_group_id": "movie-b", "share_url": "https://pan.guangyapan.com/s/b"})]
    assert probe._subscriptions_for_new_channel_entries_v1115() == [1101]


def test_reconcile_path_remains_passive_channel_event_and_never_adds_gying_calls():
    assert "_gying_" not in SOURCE
    assert "_search_viewing" not in SOURCE
    dispatch = DISPATCH.split("    def _run_reliability_route_batch(", 1)[1].split("    # ------------------------------------------------------------------", 1)[0]
    assert 'if "频道新增资源" in text:' in dispatch
    assert '"channel_event", force=False' in dispatch
    xunlei = CORE.split("    def _search_viewing_xunlei(", 1)[1].split("    # ------------------------------------------------------------------", 1)[0]
    assert '== "channel_event"' in xunlei
    assert "不主动访问 GYING" in xunlei


def test_candidate_keeps_public_release_at_v11214_until_full_ci_is_green():
    assert 'plugin_version = "1.12.14"' in ENTRY
    assert 'build_id = "20260905-r60"' in ENTRY
    assert '"version": "1.12.14"' in PLUGIN_JSON
    assert 'plugin_version = "1.12.15"' not in SOURCE
