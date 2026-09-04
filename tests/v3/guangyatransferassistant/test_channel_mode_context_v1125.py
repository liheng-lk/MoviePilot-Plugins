from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
CHANNEL = (PLUGIN / "channel_event_v1115.py").read_text(encoding="utf-8")
GUARD = (PLUGIN / "channel_event_guard_v1115.py").read_text(encoding="utf-8")
CURSOR = (PLUGIN / "channel_cursor_event_v1115.py").read_text(encoding="utf-8")


def test_route_source_mode_is_thread_local_truth_not_shared_string():
    ast.parse(CHANNEL)
    ast.parse(GUARD)
    ast.parse(CURSOR)
    assert "import threading" in CHANNEL
    assert "self._route_source_local_v1115 = threading.local()" in CHANNEL
    assert "def _route_source_mode_value_v1115" in CHANNEL
    helper = CHANNEL.split("    def _route_source_mode_value_v1115(", 1)[1].split("    # ------------------------------------------------------------------", 1)[0]
    assert 'hasattr(local, "mode")' in helper
    assert 'getattr(self, "_route_source_mode_v1115"' in helper


def test_mode_batch_sets_and_restores_thread_local_context():
    method = CHANNEL.split("    def _run_v1115_mode_batch(", 1)[1].split("    def _run_reliability_route_batch(", 1)[0]
    assert "local.mode = mode" in method
    assert "had_local = hasattr(local, \"mode\")" in method
    assert "local.mode = previous_local" in method
    assert 'delattr(local, "mode")' in method
    assert "self._route_source_mode_v1115 = previous" in method


def test_all_channel_mode_decisions_read_thread_local_helper():
    refresh = CHANNEL.split("    def refresh_channels(", 1)[1].split("    # ------------------------------------------------------------------\n    # 新频道消息", 1)[0]
    claim = CHANNEL.split("    def _claim_external_search_round_v1114(", 1)[1].split("    def _viewing_due_subscription_ids_v1115(", 1)[0]
    assert "_route_source_mode_value_v1115()" in refresh
    assert "_route_source_mode_value_v1115()" in claim
    assert "_route_source_mode_value_v1115()" in GUARD
    assert "_route_source_mode_value_v1115()" in CURSOR
    assert '{"viewing_poll", "airing_pull", "daily_repair_pull"}' in refresh
    assert '{"viewing_poll", "airing_pull", "daily_repair_pull"}' in CURSOR
