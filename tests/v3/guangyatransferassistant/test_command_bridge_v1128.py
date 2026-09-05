from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
ROUTING = (PLUGIN / "routing_v170.py").read_text(encoding="utf-8")


def test_final_runtime_explicitly_binds_routing_plugin_action_handler():
    class_body = ENTRY.split("class GuangYaTransferAssistant(", 1)[1]
    assert "def action_event_handler(self, event: Event) -> None:" in class_body
    assert "return super().action_event_handler(event)" in class_body
    assert class_body.count("@eventmanager.register(EventType.PluginAction)") >= 2


def test_gysub_still_routes_to_direct_subscribe_handler():
    assert 'if action == "guangya_direct_subscribe":' in ROUTING
    assert "self._handle_direct_subscribe_command(event_data)" in ROUTING


def test_gysub_ack_is_sent_before_tmdb_lookup():
    handler = ROUTING.split("def _handle_direct_subscribe_command", 1)[1].split("def _spawn_command_transfer", 1)[0]
    ack = handler.index("⏳ 已收到光鸭直订请求")
    lookup = handler.index("self._search_direct_candidates(request)")
    assert ack < lookup
    assert "识别完成后会继续回传结果" in handler


def test_v1128_metadata_and_previous_resource_gate_remain_active():
    assert 'plugin_version = "1.12.16"' in ENTRY
    assert 'build_id = "20260906-r63"' in ENTRY
    assert "GuangYaResourceGateV1127Mixin" in ENTRY
