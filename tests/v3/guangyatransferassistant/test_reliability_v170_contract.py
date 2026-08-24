import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENTRY = ROOT / "plugins.v3" / "guangyatransferassistant" / "__init__.py"
RELIABILITY = ROOT / "plugins.v3" / "guangyatransferassistant" / "reliability_v170.py"

entry_text = ENTRY.read_text(encoding="utf-8")
reliability_text = RELIABILITY.read_text(encoding="utf-8")


def test_reliability_layer_is_wired_and_syntax_valid():
    ast.parse(entry_text)
    ast.parse(reliability_text)
    assert "from .reliability_v170 import GuangYaReliabilityMixin" in entry_text
    class_block = entry_text.split("class GuangYaTransferAssistant(", 1)[1].split("):", 1)[0]
    assert "GuangYaReliabilityMixin" in class_block
    assert "GuangYaExperienceMixin" in class_block
    assert class_block.index("GuangYaReliabilityMixin") < class_block.index("GuangYaExperienceMixin")
    assert 'build_id = "20260824-r5"' in reliability_text


def test_only_latest_hot_reload_instance_may_handle_actions():
    for token in (
        "SubscribeChain._guangya_runtime_owner_ref = weakref.ref(self)",
        "SubscribeChain._guangya_runtime_generation = self._runtime_generation",
        "def _runtime_is_current",
        "if not self._runtime_is_current():",
        "def action_event_handler",
        "def experience_action_event_handler",
    ):
        assert token in reliability_text, token


def test_async_queue_dedupes_active_subscription_and_never_restarts_with_empty_ids():
    assert "self._async_route_active" in reliability_text
    assert "self._async_route_recheck" in reliability_text
    assert "active_hits = ids.intersection(self._async_route_active)" in reliability_text
    assert "self._async_route_recheck.update(active_hits)" in reliability_text
    assert "relaunch = sorted(self._async_route_pending)" in reliability_text
    assert 'self._queue_async_route_check(relaunch, trigger="后台合并补偿")' in reliability_text
    assert 'self._queue_async_route_check([], trigger="后台合并补偿")' not in reliability_text


def test_channel_refresh_is_singleflight_and_uses_exponential_backoff_cache_degrade():
    for token in (
        "self._channel_refresh_lock.acquire(blocking=False)",
        "return self._cached_channel_items()",
        '"state": "degraded"',
        "_channel_retry_base_seconds",
        "2 ** min(failures - 1, 5)",
        "self._schedule_channel_recovery(delay)",
        "频道源连续失败",
        "不回退本地下载",
    ):
        assert token in reliability_text, token


def test_outage_auto_recovery_requeues_selected_routes():
    recovery = reliability_text.split("    def _schedule_channel_recovery", 1)[1].split("    def refresh_channels", 1)[0]
    assert "threading.Timer" in recovery
    assert "self._selected_subscriptions" in recovery
    assert 'trigger="频道故障自动恢复"' in recovery
    assert "self.refresh_channels(force=True)" in recovery


def test_diagnostics_and_selfcheck_surface_degraded_mode():
    assert "频道源暂时不可用，正在使用本地缓存降级" in reliability_text
    assert '"key": "runtime_owner"' in reliability_text
    assert '"key": "channel_circuit"' in reliability_text
    assert "channel_degraded" in reliability_text
    assert "频道源暂时不可用 · 已进入缓存降级" in reliability_text


def test_stop_service_cancels_recovery_and_releases_owner_only_for_current_instance():
    stop = reliability_text.split("    def stop_service", 1)[1]
    assert "timer.cancel()" in stop
    assert "current = self._runtime_is_current()" in stop
    assert "SubscribeChain._guangya_runtime_owner_ref = None" in stop
    assert "SubscribeChain._guangya_runtime_generation = \"\"" in stop
