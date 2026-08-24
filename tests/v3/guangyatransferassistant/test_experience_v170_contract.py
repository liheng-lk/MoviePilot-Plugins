import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENTRY = ROOT / "plugins.v3" / "guangyatransferassistant" / "__init__.py"
EXPERIENCE = ROOT / "plugins.v3" / "guangyatransferassistant" / "experience_v170.py"
ROUTING = ROOT / "plugins.v3" / "guangyatransferassistant" / "routing_v170.py"

entry_text = ENTRY.read_text(encoding="utf-8")
experience_text = EXPERIENCE.read_text(encoding="utf-8")
routing_text = ROUTING.read_text(encoding="utf-8")


def _method_text(source: str, name: str, next_name: str | None = None) -> str:
    marker = f"    def {name}("
    assert marker in source, name
    body = source.split(marker, 1)[1]
    if next_name:
        next_marker = f"    def {next_name}("
        if next_marker in body:
            body = body.split(next_marker, 1)[0]
    return body


def test_experience_layer_is_wired_into_runtime():
    ast.parse(experience_text)
    ast.parse(entry_text)
    assert "from .experience_v170 import GuangYaExperienceMixin" in entry_text
    assert "class GuangYaTransferAssistant(GuangYaExperienceMixin, _RoutingV170Assistant):" in entry_text
    assert 'build_id = "20260824-r4"' in experience_text


def test_native_search_guard_is_non_blocking():
    guard = _method_text(experience_text, "_guard_one_subscription", "_queue_async_route_check")
    assert "_queue_async_route_check" in guard
    assert "refresh_channels" not in guard
    assert "_try_transfer_subscription" not in guard
    assert "搜索线程立即返回" in guard


def test_background_route_checks_are_coalesced():
    worker = _method_text(experience_text, "_queue_async_route_check", "_resolve_any_subscription")
    assert "_async_route_pending" in worker
    assert "_async_route_worker_running" in worker
    assert "time.sleep(self._async_route_debounce)" in worker
    assert "need_refresh" in worker
    assert "self.refresh_channels(force=True)" in worker
    assert "self._try_transfer_subscription(subscribe, refresh_channel=False)" in worker


def test_message_management_commands_cover_existing_subscriptions_and_diagnostics():
    for token in (
        '"cmd": "/gysub"',
        '"cmd": "/gyroute"',
        '"cmd": "/gycheck"',
        '"cmd": "/gywhy"',
        '"cmd": "/gystatus"',
        '"cmd": "/gynative"',
        '"cmd": "/gyselfcheck"',
        "guangya_takeover_existing",
        "guangya_check_existing",
        "guangya_explain_existing",
        "guangya_selfcheck",
    ):
        assert token in experience_text, token
    assert "_resolve_any_subscription" in experience_text
    assert "_handle_takeover_existing_command" in experience_text
    assert "_handle_check_existing_command" in experience_text
    assert "_handle_explain_existing_command" in experience_text


def test_crash_recovery_treats_pending_route_as_durable_intent():
    init = _method_text(experience_text, "init_plugin", "get_command")
    assert 'config["selected_subscriptions"] = pending_ids' in init
    assert "_schedule_pending_route_recovery" in init
    recovery = _method_text(experience_text, "_schedule_pending_route_recovery", "_guard_one_subscription")
    assert 'self._save_config()' in recovery
    assert 'self.save_data("route_membership_pending", {})' in recovery
    assert "route_recovery_marker" in recovery


def test_selfcheck_covers_runtime_channel_and_all_native_guards():
    report = _method_text(experience_text, "_build_selfcheck", "_format_selfcheck")
    for token in (
        "_is_search_guard_active",
        "_guangya_match_guard",
        "_guangya_download_guard",
        "_get_guangya_runtime",
        "_source_urls",
        'get_data("channel_index")',
        'get_data("transfer_jobs")',
        'get_data("route_membership_pending")',
        "_save_path",
    ):
        assert token in report, token
    assert '"path": "/selfcheck"' in experience_text
    assert "api_selfcheck" in experience_text


def test_page_explains_why_not_transferred_and_uses_v3_apikey():
    page = _method_text(experience_text, "get_page")
    assert "为什么还没转存" in page
    assert "运行转存自检" in page
    assert '"apikey": settings.API_TOKEN' in page
    assert "_diagnose_subscription" in page
    assert "build" in page


def test_diagnosis_exposes_actionable_states():
    diagnosis = _method_text(experience_text, "_diagnose_subscription", "_format_subscription_diagnosis")
    for token in (
        "正在等待光鸭落盘确认",
        "最近转存任务失败",
        "频道索引为空",
        "当前频道索引没有命中该媒体",
        "不会回退到 MoviePilot 本地下载",
        "连载保护",
    ):
        assert token in diagnosis, token


def test_existing_login_fix_remains_intact():
    normalize = routing_text.split("    def _normalize_page_api_auth(", 1)[1].split("    def get_form(", 1)[0]
    assert 'params.pop("token", None)' in normalize
    assert 'params.setdefault("apikey", settings.API_TOKEN)' in normalize
