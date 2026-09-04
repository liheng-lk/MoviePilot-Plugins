from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
FINAL = PLUGIN / "dispatch_policy_final_v1125.py"
ENTRY = PLUGIN / "__init__.py"

final_text = FINAL.read_text(encoding="utf-8")
entry_text = ENTRY.read_text(encoding="utf-8")


def _method(name: str, next_name: str | None = None) -> str:
    start = final_text.index(f"    def {name}(")
    if next_name:
        return final_text[start:final_text.index(f"    def {next_name}(", start)]
    return final_text[start:]


def test_final_dispatch_parses_and_is_cooperative_runtime_authority():
    ast.parse(final_text, filename=str(FINAL))
    ast.parse(entry_text, filename=str(ENTRY))
    assert "class GuangYaDispatchPolicyFinalV1125Mixin:" in final_text
    assert "_DispatchPolicyPreviewV1125" not in final_text
    assert 'build_id = "20260904-r51-preview"' in final_text
    start = entry_text.index("class GuangYaTransferAssistant(")
    final_pos = entry_text.index("GuangYaDispatchPolicyFinalV1125Mixin,", start)
    preview_pos = entry_text.index("GuangYaDispatchPolicyV1125Mixin,", start)
    weekly_pos = entry_text.index("GuangYaAiringWeeklyV1121Mixin,", start)
    assert final_pos < preview_pos < weekly_pos


def test_stable_weekday_is_schedule_fact_not_calendar_failure_fallback():
    gate = _method("_airing_gate_v1120", "_record_auto_external_cooldown_v1125")
    assert 'not bool(result.get("calendar_available"))' in gate
    assert 'result.get("weekday") is not None' in gate
    assert 'result["calendar_available"] = True' in gate
    assert 'result["calendar_available_basis_v1125"] = "stable_weekday"' in gate
    assert 'bool(result.get("passive_channel_bypass_v1125"))' in gate


def test_daily_automatic_force_records_cooldown_but_manual_force_does_not():
    claim = _method("_claim_external_search_round_v1114", "_spawn_route_prime")
    record = _method("_record_auto_external_cooldown_v1125", "_claim_external_search_round_v1114")
    assert 'mode == "daily_repair_pull"' in claim
    assert "if not allowed or not force:" in claim
    assert '_record_auto_external_cooldown_v1125(subscribe, "daily_repair_pull")' in claim
    assert 'self.save_data("external_search_guard", state)' in record
    for manual in ("手动", "人工", "立即", "控制台"):
        assert manual not in claim


def test_new_subscription_prime_refreshes_channel_once_without_direct_gying_force():
    prime = _method("_spawn_route_prime", "_queue_async_route_check")
    assert "_cached_matches_for_subscription(subscribe)" in prime
    assert "self.refresh_channels(force=True)" in prime
    assert 'trigger="新订阅资源匹配"' in prime
    assert "仅按更新日历判断是否主动搜索" in prime
    assert "观影立即搜索" not in prime
    assert "_run_v1115_mode_batch" not in prime


def test_async_queue_keeps_real_trigger_per_subscription_after_governance_filter_prediction():
    queue = _method("_queue_async_route_check", "_ordered_async_triggers_v1125")
    assert "accepted = set(ids)" in queue
    assert 'getattr(self, "_automatic_trigger_v1114", None)' in queue
    assert 'getattr(self, "_manual_trigger_v1114", None)' in queue
    assert "accepted -= active" in queue
    assert "_dispatch_triggers_v1125" in queue
    assert 'if text == "后台合并补偿" and bucket:' in queue
    assert "return super()._queue_async_route_check(ids, trigger=trigger)" in queue


def test_async_trigger_record_and_governance_enqueue_share_one_reentrant_route_lock():
    queue = _method("_queue_async_route_check", "_ordered_async_triggers_v1125")
    assert 'route_lock = getattr(self, "_async_route_lock", None)' in queue
    assert "route_lock = threading.RLock()" in queue
    assert "self._async_route_lock = route_lock" in queue
    lock_pos = queue.index("with route_lock:")
    active_pos = queue.index("accepted -= active", lock_pos)
    record_pos = queue.index("store[sid] = bucket[-limit:]", active_pos)
    super_pos = queue.index("return super()._queue_async_route_check(ids, trigger=trigger)", record_pos)
    # 这四个动作保持同一级 with 缩进；super 内 Governance/Reliability 对同一 RLock 可重入。
    locked_tail = queue[lock_pos:]
    assert active_pos < record_pos < super_pos
    assert "with route_lock:" in locked_tail
    assert "return super()._queue_async_route_check(ids, trigger=trigger)" in locked_tail
    assert "预测与真正入队之间被 worker 改写 active" not in queue


def test_async_trigger_order_is_channel_before_active_pull_and_prime_collapses_duplicate_auto_events():
    order = _method("_ordered_async_triggers_v1125", "_take_async_route_triggers_v1125")
    assert '"新订阅资源匹配" in value' in order
    assert '"频道故障自动恢复" in value' in order
    assert '"频道新增资源" in value' in order
    assert '"观影定时轮询" in value' in order
    assert "ordered.extend(active)" in order
    assert order.index("ordered.append(recovery)") < order.index("ordered.extend(active)")
    assert order.index("ordered.extend(channel)") < order.index("ordered.extend(active)")


def test_worker_batch_is_regrouped_by_saved_trigger_instead_of_first_worker_trigger():
    run = _method("_run_reliability_route_batch", "_calendar_failure_payload_v1125")
    assert "trigger_map = self._take_async_route_triggers_v1125(ids, trigger)" in run
    assert "groups: Dict[str, List[int]] = {}" in run
    assert "groups.setdefault" in run
    assert "_async_trigger_priority_v1125" in run
    assert "self._run_dispatch_trigger_v1125(group_ids, value)" in run
    # worker 传入的 fallback trigger 只能补缺，不能直接覆盖所有 ID 的来源语义。
    assert "return super()._run_reliability_route_batch(batch, trigger)" not in run


def test_channel_recovery_is_channel_only_and_never_becomes_active_gying_pull():
    dispatch = _method("_run_dispatch_trigger_v1125", "_run_reliability_route_batch")
    recovery = dispatch.split('if "频道故障自动恢复" in text:', 1)[1].split('if "新订阅资源匹配" in text:', 1)[0]
    assert "self.refresh_channels(force=True)" in recovery
    assert '"channel_event"' in recovery
    assert "force=False" in recovery
    assert "_smart_pull_due_ids_v1125" not in recovery
    assert '"airing_pull"' not in recovery


def test_new_subscription_is_channel_first_then_date_gated_non_force_pull():
    dispatch = _method("_run_dispatch_trigger_v1125", "_run_reliability_route_batch")
    method = dispatch.split('if "新订阅资源匹配" in text:', 1)[1]
    channel = method.index('"新订阅资源匹配·频道阶段"')
    selector = method.index("_smart_pull_due_ids_v1125()")
    pull = method.index('"新订阅资源匹配·更新日历主动拉取"')
    assert channel < selector < pull
    assert '"channel_event"' in method
    assert '"airing_pull"' in method
    assert method.count("force=False") >= 2
    assert "pull_ids = [sid for sid in ids if sid in allowed]" in method
    assert '"subscription_prime"' not in method


def test_calendar_failure_returns_truthy_sentinel_and_enters_short_backoff():
    payload = _method("_calendar_failure_payload_v1125", "_refresh_airing_calendar_v1120")
    refresh = _method("_refresh_airing_calendar_v1120", "_daily_full_catchup_v1110")
    assert '"subscriptions": []' in payload
    assert '"calendar_refresh_failed_v1125": True' in payload
    assert "_calendar_refresh_failure_until_v1125" in refresh
    assert "if failure_until > now:" in refresh
    assert "return self._calendar_failure_payload_v1125()" in refresh
    assert "except Exception as err:" in refresh
    assert "now + max(" in refresh
    assert "短退避避免按订阅重复请求" in refresh
    assert "super()._refresh_airing_calendar_v1120(force=False)" in refresh


def test_forced_calendar_refresh_is_not_hidden_by_failure_backoff():
    refresh = _method("_refresh_airing_calendar_v1120", "_daily_full_catchup_v1110")
    force_branch = refresh.index("if force:")
    normal_backoff = refresh.index("failure_until = float", force_branch)
    assert 'return dict(super()._refresh_airing_calendar_v1120(force=True) or {})' in refresh[force_branch:normal_backoff]


def test_daily_calendar_network_refresh_is_deferred_until_channel_and_gying_finish():
    refresh = _method("_refresh_airing_calendar_v1120", "_daily_full_catchup_v1110")
    daily = _method("_daily_full_catchup_v1110")
    assert 'getattr(local, "defer_daily_calendar", False)' in refresh
    assert 'self.get_data("airing_calendar_v1120")' in refresh
    assert "local.defer_daily_calendar = True" in daily
    super_call = daily.index("super()._daily_full_catchup_v1110()")
    restore = daily.index("local.defer_daily_calendar = previous")
    trailing_refresh = daily.index("self._refresh_airing_calendar_v1120(force=True)")
    assert super_call < restore < trailing_refresh
    assert "两阶段补漏已完成" in daily


def test_final_dispatch_does_not_reimplement_download_or_transfer_business_chain():
    lowered = final_text.lower()
    for forbidden in (
        "downloadchain(",
        "from app.chain.download",
        "qbittorrent",
        "transmission",
        "aria2",
        "_xunlei_import_json_batch",
        "cloudcollection",
    ):
        assert forbidden not in lowered
