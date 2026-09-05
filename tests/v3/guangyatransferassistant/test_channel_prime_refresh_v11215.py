from __future__ import annotations

import ast
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Set, Tuple


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
SOURCE = (PLUGIN / "channel_reconcile_v11215.py").read_text(encoding="utf-8")
MANUAL = (PLUGIN / "manual_check_v11211.py").read_text(encoding="utf-8")
MOVIE = (PLUGIN / "movie_identity_v1129.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")


class _LegacyStub:
    @staticmethod
    def _entry_match_reason(row, subscribe):
        return True, "matched"


class _CoreBase:
    def __init__(self):
        self._enabled = True
        self.events: List[str] = []
        self.logs = []
        self.rows: Dict[int, List[Any]] = {}
        self.subscriptions = {1: SimpleNamespace(id=1, name="测试剧", season=1)}
        self.gaps = {1: {11}}
        self.refresh_populates = False
        self.backfill_populates = False
        self._channel_refresh_lock = threading.Lock()

    def _positive_ids_v1125(self, values):
        return {int(value) for value in values if int(value or 0) > 0}

    def _find_subscription(self, sid):
        return self.subscriptions.get(int(sid or 0))

    def _is_guangya_route(self, subscribe):
        return True

    def _is_movie_subscription(self, subscribe):
        return False

    def _uncovered_missing_v1125(self, subscribe):
        return set(self.gaps.get(int(subscribe.id), set()))

    def _cached_matches_for_subscription(self, subscribe):
        self.events.append("cache")
        return list(self.rows.get(int(subscribe.id), []))

    def _entry_can_cover_missing_v1115(self, entry, subscribe):
        return True

    def refresh_channels(self, force=False):
        self.events.append(f"refresh:{bool(force)}")
        if self.refresh_populates:
            self.rows[1] = [({
                "resource_group_id": "fresh",
                "share_url": "https://www.guangyapan.com/s/fresh",
                "episode_hint": "S01E11",
            }, "matched")]
        return []

    def _history_backfill_for_subscriptions_v11215(self, subscriptions):
        self.events.append("history")
        if self.backfill_populates:
            self.rows[1] = [({
                "resource_group_id": "history",
                "share_url": "https://www.guangyapan.com/s/history",
                "episode_hint": "S01E11",
            }, "matched")]
        return {"pages": 2, "rows": 10, "cached": 10, "matched_ids": [1] if self.backfill_populates else [], "errors": []}

    def _channel_refresh_healthy_v11215(self):
        return True

    def _wait_for_channel_refresh_v11215(self):
        self.events.append("wait")

    def _queue_async_route_check(self, sids, trigger="后台检查"):
        self.events.append(f"queue:{trigger}:{','.join(str(x) for x in sids)}")

    def _plugin_log(self, *args):
        self.logs.append(args)

    def _subscriptions_for_new_channel_entries_v1115(self):
        return []

    def _active_selected_subscriptions_v1125(self):
        return list(self.subscriptions.values())


def _entry_key(row: Dict[str, Any]) -> str:
    return str(row.get("resource_group_id") or row.get("message_id") or row.get("share_url") or "")


def _load_mixin():
    tree = ast.parse(SOURCE, filename=str(PLUGIN / "channel_reconcile_v11215.py"))
    node = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "GuangYaChannelReconcileV11215Mixin"
    )
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "Any": Any,
        "Dict": Dict,
        "Iterable": Iterable,
        "List": List,
        "Set": Set,
        "Tuple": Tuple,
        "threading": threading,
        "_legacy_module": _LegacyStub,
        "_entry_key_v1115": _entry_key,
        "GuangYaCorePipelineFinalV11214Mixin": _CoreBase,
    }
    exec(compile(module, str(PLUGIN / "channel_reconcile_v11215.py"), "exec"), namespace)
    return namespace["GuangYaChannelReconcileV11215Mixin"]


def test_new_subscription_prime_override_is_before_v1125_dispatch_final_in_runtime_chain():
    assert "class GuangYaManualCheckV11211Mixin(GuangYaChannelReconcileV11215Mixin):" in MANUAL
    assert "class GuangYaMovieIdentityV1129Mixin(GuangYaManualCheckV11211Mixin):" in MOVIE
    head = ENTRY.split("class GuangYaTransferAssistant(", 1)[1].split("):", 1)[0]
    assert head.index("GuangYaMovieIdentityV1129Mixin") < head.index("GuangYaDispatchPolicyFinalV1125Mixin")
    assert "def _spawn_route_prime(" in SOURCE


def test_new_subscription_force_refresh_happens_before_first_cache_match():
    cls = _load_mixin()
    probe = cls()
    probe.refresh_populates = True
    probe._spawn_route_prime([1])

    assert probe.events[0] == "refresh:True"
    assert probe.events.index("refresh:True") < probe.events.index("cache")
    assert "history" not in probe.events
    assert probe.events[-1] == "queue:新订阅资源匹配:1"


def test_history_backfill_runs_only_after_forced_refresh_still_misses():
    cls = _load_mixin()
    probe = cls()
    probe.backfill_populates = True
    probe._spawn_route_prime([1])

    assert probe.events[0] == "refresh:True"
    assert "history" in probe.events
    assert probe.events.index("refresh:True") < probe.events.index("history")
    history_pos = probe.events.index("history")
    assert any(value == "cache" for value in probe.events[:history_pos])
    assert any(value == "cache" for value in probe.events[history_pos + 1:])
    assert probe.events[-1] == "queue:新订阅资源匹配:1"


def test_history_backfill_is_cache_only_and_never_reclassifies_old_posts_as_new_events():
    method = SOURCE.split("    def _history_backfill_for_subscriptions_v11215", 1)[1].split("    def _spawn_route_prime", 1)[0]
    assert "_extract_channel_entries" in method
    assert "_extract_pagination_urls" in method
    assert "_refresh_channel_cache_v1115(discovered)" in method
    assert 'save_data("channel_cursors"' not in method
    assert "_channel_new_entries_v1115 =" not in method
    assert "refresh_channels(" not in method


def test_prime_always_refreshes_configured_channels_not_only_when_old_cache_is_empty():
    method = SOURCE.split("    def _spawn_route_prime", 1)[1].split("    def _subscriptions_for_new_channel_entries_v1115", 1)[0]
    refresh_pos = method.index("self.refresh_channels(force=True)")
    match_pos = method.index("missing_after_refresh =")
    assert refresh_pos < match_pos
    assert "先强刷全部配置频道，再读取 7 天本地缓存匹配" in method


def test_failed_channel_refresh_never_claims_that_channel_has_no_resource():
    assert "不能据此判定频道无资源" in SOURCE
    assert "本地缓存未命中”不等于“频道没有资源" in SOURCE


def test_prime_and_history_backfill_never_add_gying_or_moviepilot_downloader_paths():
    assert "_gying_" not in SOURCE
    assert "_search_viewing" not in SOURCE
    assert "DownloadChain" not in SOURCE
    assert "downloader" not in SOURCE.lower()
