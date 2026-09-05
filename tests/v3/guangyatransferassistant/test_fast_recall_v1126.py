from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
FAST = (PLUGIN / "fast_recall_v1126.py").read_text(encoding="utf-8")
FINAL = (PLUGIN / "dispatch_policy_final_v1125.py").read_text(encoding="utf-8")
DISPATCH = (PLUGIN / "dispatch_policy_v1125.py").read_text(encoding="utf-8")


def test_fast_recall_is_outer_than_v1125_dispatch_layers():
    assert "from .fast_recall_v1126 import GuangYaFastRecallV1126Mixin" in ENTRY
    head = ENTRY.split("class GuangYaTransferAssistant(", 1)[1].split("):", 1)[0]
    assert head.index("GuangYaFastRecallV1126Mixin") < head.index("GuangYaDispatchPolicyFinalV1125Mixin")
    assert 'plugin_version = "1.12.14"' in ENTRY
    assert 'build_id = "20260905-r60"' in ENTRY


def test_airing_service_wakes_every_ten_minutes():
    assert '_fast_recall_minutes_v1126 = 10' in FAST
    assert '"GuangYaTransferAssistantAiringDue"' in FAST
    assert 'kwargs["minutes"] = int(self._fast_recall_minutes_v1126)' in FAST


def test_tv_claim_is_ten_minutes_but_movie_keeps_v1125_window():
    assert 'self._is_movie_subscription(subscribe)' in FAST
    assert 'return bool(super()._claim_external_search_round_v1114(subscribe, force=force))' in FAST
    assert 'cooldown = max(60, int(self._fast_recall_minutes_v1126) * 60)' in FAST
    assert '"origin": "airing_fast_recall_v1126"' in FAST
    assert '_hourly_due_cooldown_seconds_v1125 = 60 * 60' in FINAL


def test_five_minute_channel_tick_still_never_becomes_active_gying_poll():
    assert 'local.channel_only = True' in DISPATCH
    assert 'if bool(getattr(local, "channel_only", False)):' in DISPATCH
    assert 'return []' in DISPATCH
    assert '观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K' in FAST
