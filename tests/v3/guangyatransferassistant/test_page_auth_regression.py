import importlib.util
import inspect
from pathlib import Path
from types import SimpleNamespace

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


class _FakePlugin:
    def __init__(self):
        self._selected_subscriptions = [7]
        self.queued = []
        self.logs = []
        self.original_checks = 0

    def _find_subscription(self, sid):
        if int(sid or 0) != 7:
            return None
        return SimpleNamespace(id=7, name="藏锋", state="R")

    def _runtime_is_current(self):
        return True

    def _manual_transfer_guard(self, subscribe):
        return None

    def _queue_async_route_check(self, sids, trigger=""):
        self.queued.append((list(sids), trigger))

    def _record_route_health(self, **kwargs):
        self.health = kwargs

    @staticmethod
    def _now_text():
        return "2026-08-25 12:00:00"

    def _plugin_log(self, level, message, *args):
        self.logs.append((level, message, args))

    def legacy_check_missing(self, subscribe_id: int = 0):
        self.original_checks += 1
        return {"success": True, "message": "不应在 HTTP 请求中同步执行"}

    def clear_logs(self):
        return {"success": True, "message": "已清空", "count": 3}


def test_check_missing_returns_immediately_and_queues_existing_reliable_worker():
    plugin = _FakePlugin()
    original = plugin.legacy_check_missing
    routes = auth.force_bear_auth([
        {
            "path": "/check_missing",
            "endpoint": original,
            "methods": ["POST"],
        }
    ])
    endpoint = routes[0]["endpoint"]

    # functools.wraps 必须保留旧 endpoint 的签名，否则 FastAPI 会丢失 subscribe_id Query 参数。
    assert inspect.signature(endpoint) == inspect.signature(original)

    result = endpoint(subscribe_id=7)
    assert set(result) == {"success", "message", "data"}
    assert result["success"] is True
    assert result["data"] == {
        "subscribe_id": 7,
        "queued": True,
        "action": "check_missing",
    }
    assert plugin.original_checks == 0
    assert plugin.queued == [([7], "状态页立即检查缺集")]


def test_fast_status_action_is_normalized_to_strict_v3_envelope():
    plugin = _FakePlugin()
    routes = auth.force_bear_auth([
        {
            "path": "/clear_plugin_logs",
            "endpoint": plugin.clear_logs,
            "methods": ["POST"],
        }
    ])
    result = routes[0]["endpoint"]()
    assert result == {
        "success": True,
        "message": "已清空",
        "data": {"count": 3},
    }


def test_reset_state_endpoint_does_not_reload_plugin_or_rewrite_config():
    legacy = LEGACY.read_text(encoding="utf-8")
    api = legacy.split("    def api_reset_state(", 1)[1].split("    def api_cancel_pending(", 1)[0]
    assert "_reset_subscription_check_state" in api
    assert "update_config" not in api
    assert "_save_config" not in api
    assert "PluginManager" not in api
