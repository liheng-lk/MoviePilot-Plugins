"""Real-log development regressions without changing the public 2.1.5-r103 release marker."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENTRY_PATH = ROOT / "plugins.v3" / "guangyatransferassistant" / "__init__.py"
ENTRY = ENTRY_PATH.read_text(encoding="utf-8")


def _bundles() -> dict[str, str]:
    tree = ast.parse(ENTRY, filename=str(ENTRY_PATH))
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(target, ast.Name) and target.id == "_BUNDLED_SOURCES" for target in targets):
            value = ast.literal_eval(node.value)
            assert isinstance(value, dict)
            return {str(k): str(v) for k, v in value.items()}
    raise AssertionError("_BUNDLED_SOURCES missing")


def _bundle(name: str) -> str:
    return _bundles()[name]


def _bundle_with(marker: str) -> str:
    matches = [source for source in _bundles().values() if marker in source]
    assert len(matches) == 1, f"expected one bundle for {marker!r}, got {len(matches)}"
    return matches[0]


def _exec_identity():
    ns = {}
    exec(compile(_bundle("media_identity_v1111"), "<media_identity_v1111>", "exec"), ns)
    return ns


def test_numbered_sequel_can_bridge_publisher_base_title_plus_real_season():
    ns = _exec_identity()
    helper = ns["sequel_numbered_title_season_alias_v1111"]
    assess = ns["assess_media_identity_v1111"]

    assert helper(
        ["我们的少年时代2"],
        1,
        {2},
        ["我们的少年时代 (2026) S02", "我们的少年时代.S02E15.mkv"],
        expected_year=2026,
    )
    assert not helper(
        ["我们的少年时代"],
        1,
        {2},
        ["我们的少年时代 (2026) S02", "我们的少年时代.S02E15.mkv"],
        expected_year=2026,
    )

    allowed = assess(
        aliases=["我们的少年时代2"],
        expected_year=2026,
        expected_season=1,
        is_movie=False,
        primary_evidences=["我们的少年时代 (2026) S02"],
        file_evidences=["我们的少年时代.S02E15.mkv"],
        threshold=100,
    )
    assert allowed["ok"] is True
    assert allowed["hard_conflict"] is False
    assert allowed["score"] == 100

    blocked = assess(
        aliases=["我们的少年时代"],
        expected_year=2026,
        expected_season=1,
        is_movie=False,
        primary_evidences=["我们的少年时代 (2026) S02"],
        file_evidences=["我们的少年时代.S02E15.mkv"],
        threshold=50,
    )
    assert blocked["ok"] is False
    assert blocked["hard_conflict"] is True
    assert blocked["reason_code"] == "SEASON_MISMATCH"


def test_gying_hardening_keeps_public_build_r103_and_reuses_live_session():
    final = ENTRY[ENTRY.rindex("\nclass GuangYaTransferAssistant("):]
    assert 'plugin_version = "2.1.5"' in final
    assert 'build_id = "20260913-r103"' in final
    assert "v2.1.5-r104 实机热修" not in ENTRY[:1200]
    assert "_gying_transaction_lock_r104 = threading.RLock()" in final
    assert 'def _gying_new_session(self, node: str, saved_cookie: str = "")' in final
    assert "self._gying_live_sessions_r104" in final
    assert "PanSou PoW：复用当前活 Session" in final
    assert "self._gying_drop_live_session_r104(node, expected_session=session)" in final


def test_same_run_gying_hard_failure_is_not_retried_by_lower_priority_stage():
    final = ENTRY[ENTRY.rindex("\nclass GuangYaTransferAssistant("):]
    assert "self._gying_run_failures_dev = {}" in final
    assert "def _gying_run_failure_key_dev" in final
    assert "def _gying_get_run_failure_dev" in final
    assert "def _gying_store_run_failure_dev" in final
    assert 'state["transport"] = "run_failure_memo"' in final
    assert "同轮失败复用" in final
    assert final.count("self._gying_store_run_failure_dev(keyword, state)") >= 2


def test_expired_pending_library_rows_are_released_after_one_aggregated_warning():
    source = _bundle_with("action=expired_pending_released")
    assert "expired_missing: Set[int] = set()" in source
    assert "expired_missing |= remain" in source
    assert "items.pop(key, None)" in source
    assert source.count("action=expired_pending_released") == 1


def test_channel_statistics_use_canonical_slug_instead_of_blind_url_truncation():
    source = _bundle_with("【频道资源统计】channel=%s")
    assert 'raw_channel = str(row.get("channel") or row.get("source_url") or "-").strip()' in source
    assert "self._channel_slug_from_source_v209(raw_channel)" in source
    assert 'str(row.get("channel") or row.get("source_url") or "-")[-40:]' not in source


def test_xunlei_ambiguous_planner_keeps_hard_gate_but_logs_file_diagnostics():
    source = _bundle_with("【光鸭转存助手】【拆包v1.12.7】")
    assert 'result.get("diagnostics")' in source
    assert "diagnostics[:8]" in source
    assert "message=%s diag=%s" in source
    resolver = _bundle("episode_resolver_v190")
    assert "AUTO_SELECT_CONFIDENCE = 0.90" in resolver

def test_channel_discovery_and_source_execution_are_globally_phase_serialized():
    final = ENTRY[ENTRY.rindex("\nclass GuangYaTransferAssistant"):]
    assert "self._pipeline_phase_lock_dev = threading.RLock()" in final
    assert "def refresh_channels(self, force: bool = False)" in final
    assert "def _run_v1115_mode_batch(" in final
    assert "with self._pipeline_phase_lock_dev:" in final
    # AiringDue keeps EpisodeRuntime as the owner/ready/singleflight authority.
    runtime = _bundle("episode_runtime_v211")
    assert 'def _calendar_due_check_v1110(self, minutes: Any = None, owner: str = "host", **kwargs)' in runtime
    due = runtime[runtime.index("    def _calendar_due_check_v1110("):]
    due = due[:due.index("    def _runtime_worker_loop(", 1)]
    assert due.index("phase_lock.acquire()") < due.index("phase=DISCOVERY_CHANNEL")
    assert due.index("phase=DISCOVERY_CHANNEL") < due.index("self.refresh_channels(force=False)")
    assert due.index("self.refresh_channels(force=False)") < due.index("phase=EXECUTE_PRIORITY_CHAIN")
    assert due.index("phase=EXECUTE_PRIORITY_CHAIN") < due.index("super()._calendar_due_check_v1110()")
    assert due.index("super()._calendar_due_check_v1110()") < due.index("phase_lock.release()")
    assert "def _calendar_due_check_v1110(self)" not in final


def test_channel_event_is_discovery_trigger_not_higher_priority_transfer_stage():
    final = ENTRY[ENTRY.rindex("\nclass GuangYaTransferAssistant"):]
    method = final[final.index("    def _run_channel_then_due_gying_v103("):]
    method = method[:method.index("    def _run_reliability_route_batch(", 1)]
    assert '"channel_priority"' in method
    assert '"channel_event"' not in method
    assert "priority=观影迅雷>光鸭分享>Magnet>ED2K" in method

    # The actual full chain still implements Xunlei before the lower chain,
    # and Magnet/ED2K only after the lower/direct-share chain leaves a real gap.
    xunlei = _bundle("xunlei_flash_v193")
    xmethod = xunlei[xunlei.index("    def _try_transfer_subscription_inner("):]
    assert xmethod.index("flash = self._dispatch_xunlei_flash(subscribe)") < xmethod.index(
        "super()._try_transfer_subscription_inner"
    )
    viewing = _bundle("viewing_logging_v1113")
    vmethod = viewing[viewing.index("    def _try_transfer_subscription_inner("):]
    assert vmethod.index("super()._try_transfer_subscription_inner") < vmethod.index(
        "self._dispatch_viewing_external_v1113(subscribe)"
    )


def test_manual_and_daily_repair_use_one_priority_chain_after_channel_discovery():
    final = ENTRY[ENTRY.rindex("\nclass GuangYaTransferAssistant"):]
    manual = final[final.index("    def _run_dispatch_trigger_v1125("):]
    manual = manual[:manual.index("    def _daily_full_catchup_v1110(", 1)]
    assert "self.refresh_channels(force=True)" in manual
    assert '"manual_priority"' in manual
    assert '"channel_event"' not in manual
    assert "priority=观影迅雷>光鸭分享>Magnet>ED2K" in manual

    daily = final[final.index("    def _daily_full_catchup_v1110("):]
    daily = daily[:daily.index("    def _gying_node_order(", 1)]
    assert "self.refresh_channels(force=True)" in daily
    assert '"daily_repair_pull"' in daily
    assert '"channel_event"' not in daily
    assert '"strategy": "channel_discovery_then_priority_chain"' in daily


def test_gying_auto_switch_prefers_current_pansou_primary_and_keeps_manual_pin_semantics():
    final = ENTRY[ENTRY.rindex("\nclass GuangYaTransferAssistant"):]
    assert '_gying_primary_node_dev = "https://www.xn--wcv59z.com"' in final
    order = final[final.index("    def _gying_node_order("):]
    order = order[:order.index('    plugin_version = "2.1.5"', 1)]
    assert 'if not bool(getattr(self, "_viewing_auto_switch", True)):' in order
    assert "return rows" in order
    assert "return [primary] +" in order
    # Current PanSou primary is preferred; the old 星际穿越 mirror remains only in the bundled fallback pool.
    mirror_pool = "\n".join(_bundles().values())
    assert "https://www.教父.com" in mirror_pool
    assert "https://www.星际穿越.com" in mirror_pool


def test_gying_transport_can_upgrade_to_cloudscraper_without_making_it_a_dependency():
    final = ENTRY[ENTRY.rindex("\nclass GuangYaTransferAssistant"):]
    session = final[final.index('    def _gying_new_session(self, node: str, saved_cookie: str = "")'):]
    session = session[:session.index("    def _gying_request(", 1)]
    assert "import cloudscraper as _cloudscraper" in session
    assert 'transport = "requests"' in session
    assert "if callable(maker):" in session
    assert "maker(sess=session)" in session
    assert "except Exception:" in session
    assert "challenge/verify/retry 复用同一活会话" in session

