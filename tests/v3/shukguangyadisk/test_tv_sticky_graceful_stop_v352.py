from __future__ import annotations

from source_helper import single_init_plugin_path

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = single_init_plugin_path(ROOT / "plugins.v3" / "shukguangyadisk")
V352 = (PLUGIN / "organizer_tv_sticky_graceful_stop_v352.py").read_text(encoding="utf-8")
FILTER = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
REMOTE = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")
PAGE = (PLUGIN / "dist" / "assets" / "__federation_expose_AssistantPage-v352.js").read_text(encoding="utf-8")


def test_tv_folder_stays_sticky_until_current_transaction_closes():
    for token in (
        "sticky_tv_group_path",
        "_is_tv_resource",
        "_group_has_pending",
        "_orch._is_loose_container_v351",
        "【剧集粘性】锁定当前剧集目录",
        "未完成前不切换其它剧集",
        'for state_name in ("inflight", "retry", "stabilizing")',
    ):
        assert token in V352, token


def test_generic_tv_container_is_not_mistaken_for_one_sticky_series():
    assert "if _orch._is_loose_container_v351(plugin, group_path, files):" in V352
    assert "return False" in V352


def test_graceful_stop_finishes_current_without_force_killing_transfer():
    for token in (
        "_disable_monitor_persistently",
        "_drain_private_waiting_after_boundary",
        "preserve_one",
        "stop.set()",
        "q.get_nowait()",
        "q.put_nowait(None)",
        "_return_items_to_retry_now",
        "当前资源将自然整理完成后停止",
        "不会强制中断 move/rename",
    ):
        assert token in V352, token
    for forbidden in (
        "global_vars.stop_transfer",
        "stop_service()",
        "_isolated_deferred_shutdown = True",
    ):
        assert forbidden not in V352, forbidden


def test_v3100_safe_stop_only_manages_private_worker_ownership():
    safe_stop = V352[V352.index("def _safe_stop"):V352.index("def _graceful_runtime_state")]
    assert "preserve_one=True" in safe_stop
    assert "graceful_stop_removed_legacy_waiting=0" in safe_stop
    assert "graceful_stop_host_queue_observer_only=True" in safe_stop
    assert "observed_host_queue" in safe_stop
    assert "_cleanup_legacy_global_tasks(plugin)" not in safe_stop
    assert "legacy_running =" not in safe_stop


def test_graceful_stop_api_and_ui_are_exposed():
    for token in (
        '"/organize/monitor/graceful-stop"',
        "api_organize_monitor_graceful_stop",
        "安全停止自动整理并清理未开始任务",
    ):
        assert token in V352, token
    for token in (
        "/organize/monitor/graceful-stop",
        "安全停止并清理待执行",
        "当前完成后停止中",
        "当前剧集目录",
        "不会中断当前 move/rename",
    ):
        assert token in PAGE, token


def test_v352_installs_last_after_v351_orchestrator():
    assert "install_tv_sticky_graceful_stop_v352" in FILTER
    assert "install_tv_sticky_graceful_stop_v352()" in FILTER
    assert FILTER.index("install_orchestrator_v351()") < FILTER.index("install_tv_sticky_graceful_stop_v352()")


def test_v352_release_metadata_is_consistent():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["ShukGuangYaDisk"]
    local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    note = "增加剧集目录粘性整理和安全停止，并优化超大分类目录主视频流式发现。"
    current = package["version"]
    assert local["version"] == current
    assert package["history"]["v3.5.2"] == note
    assert local["history"]["v3.5.2"] == note
    assert f'plugin_version = "{current}"' in ENTRY
    assert f"__federation_expose_AssistantPage-v352.js?v={current}" in REMOTE
