from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
NETWORK = (PLUGIN / "guangya_network_resilience_v347.py").read_text(encoding="utf-8")
FILTER = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")
CLIENT = (PLUGIN / "guangya_client.py").read_text(encoding="utf-8")
LEGACY = (PLUGIN / "guangya_client_legacy.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
REMOTE = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")


def test_v347_is_installed_after_existing_organizer_patches():
    for token in (
        "from .guangya_network_resilience_v347 import install_network_resilience_v347",
        "install_mp_folder_context_v346()",
        "install_network_resilience_v347()",
    ):
        assert token in FILTER, token
    assert FILTER.index("install_mp_folder_context_v346()") < FILTER.index("install_network_resilience_v347()")


def test_transient_network_requests_bypass_legacy_error_spam():
    assert "GuangYaClient._request = _request" in NETWORK
    assert "super()._request" not in NETWORK
    assert "requests.exceptions.ConnectionError" in NETWORK
    assert "requests.exceptions.Timeout" in NETWORK
    assert "_TRANSIENT_HTTP_STATUS = {408, 425, 429, 500, 502, 503, 504}" in NETWORK
    assert 'logger.error(f"【光鸭云盘助手】请求失败:' in LEGACY


def test_dns_retry_is_bounded_and_host_circuit_breaker_prevents_request_storms():
    for token in (
        "_RETRY_DELAYS = (1.0, 2.0)",
        "_MAX_CIRCUIT_SECONDS = 30.0",
        "_WARN_INTERVAL = 30.0",
        '"network_circuit_open"',
        '"retry_after"',
        "暂停该主机请求",
        "已恢复，继续处理挂起任务",
    ):
        assert token in NETWORK, token


def test_account_control_plane_uses_recent_success_cache_during_dns_outage():
    for token in (
        "_CONTROL_CACHE_TTL = 60.0",
        "_cached_control_call",
        '"user_info"',
        '"assets"',
        '"_guangya_stale_cache"',
        '"_guangya_network_unavailable"',
    ):
        assert token in NETWORK, token
    assert "GuangYaClient.get_user_info = get_user_info" in NETWORK
    assert "GuangYaClient.get_assets = get_assets" in NETWORK


def test_auto_scan_marks_incomplete_inventory_truncated_on_network_failure():
    for token in (
        'scan_meta["truncated"] = True',
        'scan_meta["network_deferred"] = True',
        "当前 group 可能只扫描了一部分",
        "本轮 inventory 已按截断处理，不清理旧状态",
        "本轮扫描已安全延后",
    ):
        assert token in NETWORK, token
    assert "GuangYaFolderStreamMixin._iter_folder_groups = iter_groups" in NETWORK
    assert "GuangYaFolderStreamMixin.run_organize_monitor_scan = run_scan" in NETWORK


def test_v347_network_history_remains_in_current_release():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["ShukGuangYaDisk"]
    local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    current = package["version"]
    assert local["version"] == current
    assert f'plugin_version = "{current}"' in ENTRY
    assert f"__federation_expose_AssistantPage-v330.js?v={current}" in REMOTE
    assert package["history"]["v3.4.7"] == "降低光鸭 DNS/网络异常日志噪音，增加自动退避和扫描保护，网络恢复后自动继续。"


def test_existing_client_transient_markers_remain_for_compatibility():
    for marker in (
        "NameResolutionError",
        "Temporary failure in name resolution",
        "Failed to resolve",
        "Max retries exceeded",
    ):
        assert marker in CLIENT, marker
