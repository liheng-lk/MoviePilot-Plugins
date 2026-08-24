from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ROUTING = ROOT / "plugins.v3" / "guangyatransferassistant" / "routing_v170.py"
LEGACY = ROOT / "plugins.v3" / "guangyatransferassistant" / "legacy.py"


def test_all_page_actions_share_one_v3_auth_normalizer():
    routing = ROUTING.read_text(encoding="utf-8")
    legacy = LEGACY.read_text(encoding="utf-8")

    # 当前页面的这些操作都曾使用 token 参数；v1.7 必须在渲染前统一删除 token，
    # 改为 MoviePilot V3 插件 API 的 apikey，避免前端把请求判成登录失效并跳登录页。
    for endpoint in (
        "check_missing",
        "recheck_pending",
        "cancel_pending",
        "reset_state",
        "release_native",
        "clear_plugin_logs",
    ):
        assert f"plugin/GuangYaTransferAssistant/{endpoint}" in legacy

    normalize = routing.split("    def _normalize_page_api_auth(", 1)[1].split("    def get_form(", 1)[0]
    assert 'str(click.get("api") or "").startswith("plugin/GuangYaTransferAssistant/")' in normalize
    assert 'params.pop("token", None)' in normalize
    assert 'params.setdefault("apikey", settings.API_TOKEN)' in normalize
    assert "elif isinstance(node, list):" in normalize


def test_reset_state_endpoint_does_not_reload_plugin_or_rewrite_config():
    legacy = LEGACY.read_text(encoding="utf-8")
    api = legacy.split("    def api_reset_state(", 1)[1].split("    def api_cancel_pending(", 1)[0]
    assert "_reset_subscription_check_state" in api
    assert "update_config" not in api
    assert "_save_config" not in api
    assert "PluginManager" not in api
