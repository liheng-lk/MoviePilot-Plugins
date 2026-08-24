import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENTRY = ROOT / "plugins.v3" / "guangyatransferassistant" / "__init__.py"
LEGACY = ROOT / "plugins.v3" / "guangyatransferassistant" / "legacy.py"
AUTH = ROOT / "plugins.v3" / "guangyatransferassistant" / "page_auth_v172.py"

spec = importlib.util.spec_from_file_location("guangya_page_auth_v172", AUTH)
auth = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(auth)


def test_all_status_page_actions_use_session_bearer_without_secret_params():
    entry = ENTRY.read_text(encoding="utf-8")
    legacy = LEGACY.read_text(encoding="utf-8")

    for endpoint in (
        "check_missing",
        "recheck_pending",
        "cancel_pending",
        "reset_state",
        "release_native",
        "clear_plugin_logs",
    ):
        assert f"plugin/GuangYaTransferAssistant/{endpoint}" in legacy

    page = [{
        "component": "VBtn",
        "events": {
            "click": {
                "api": "plugin/GuangYaTransferAssistant/check_missing",
                "method": "post",
                "params": {"subscribe_id": 7, "token": "secret", "apikey": "secret2"},
            }
        },
    }]
    auth.strip_page_api_secrets(page)
    params = page[0]["events"]["click"]["params"]
    assert params == {"subscribe_id": 7}

    routes = auth.force_bear_auth([
        {"path": "/check_missing", "methods": ["POST"]},
        {"path": "/clear_plugin_logs", "methods": ["POST"], "auth": "apikey"},
    ])
    assert routes and all(route["auth"] == "bear" for route in routes)
    assert "return force_bear_auth(super().get_api())" in entry
    assert "strip_page_api_secrets(pages)" in entry


def test_reset_state_endpoint_does_not_reload_plugin_or_rewrite_config():
    legacy = LEGACY.read_text(encoding="utf-8")
    api = legacy.split("    def api_reset_state(", 1)[1].split("    def api_cancel_pending(", 1)[0]
    assert "_reset_subscription_check_state" in api
    assert "update_config" not in api
    assert "_save_config" not in api
    assert "PluginManager" not in api
