from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
INIT = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
ORGANIZER = (PLUGIN / "organizer.py").read_text(encoding="utf-8")
RECOGNITION = (PLUGIN / "organizer_recognition.py").read_text(encoding="utf-8")
SAFE_RECOGNITION = (PLUGIN / "organizer_safe_recognition_v344.py").read_text(encoding="utf-8")
RUNTIME = (PLUGIN / "organizer_runtime.py").read_text(encoding="utf-8")
STATE = (PLUGIN / "organizer_state.py").read_text(encoding="utf-8")
HISTORY = (PLUGIN / "organizer_history.py").read_text(encoding="utf-8")
STORAGE = (PLUGIN / "storage_contract.py").read_text(encoding="utf-8")
MODELS = (PLUGIN / "models.py").read_text(encoding="utf-8")
REMOTE = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")
PAGE = (PLUGIN / "dist" / "assets" / "__federation_expose_AssistantPage-v330.js").read_text(encoding="utf-8")


def test_v344_version_and_federation_entry():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["ShukGuangYaDisk"]
    local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    assert package["version"] == "3.4.4"
    assert local["version"] == "3.4.4"
    assert 'plugin_version = "3.4.4"' in INIT
    assert "__federation_expose_AssistantPage-v330.js?v=3.4.4" in REMOTE
    assert "v3.4.4" in package["history"]
    assert "安全识别提示" in package["history"]["v3.4.4"]


def test_builtin_organizer_page_has_no_internal_version_badge():
    assert "自动整理监控" in PAGE
    assert "MoviePilot 内置" in PAGE
    assert "gya-badge" not in PAGE
    assert "'v3.4.3'" not in PAGE
    assert "'v3.4.4'" not in PAGE
    assert "GuangyaCloudAssistantV343" not in PAGE


def test_architecture_separates_state_history_recognition_and_runtime():
    assert "from .organizer_state import OrganizerStateStore" in ORGANIZER
    assert "from .organizer_history import inspect_moviepilot_history" in ORGANIZER
    assert "from .organizer_runtime import bind_organizer_runtime" in RECOGNITION
    assert "class OrganizerStateStore" in STATE
    assert "def inspect_moviepilot_history" in HISTORY
    assert "def bind_organizer_runtime" in RUNTIME
    assert "eventmanager.register" not in RECOGNITION
    assert "TransferChain" not in STATE


def test_auto_monitor_still_delegates_business_rules_to_moviepilot():
    assert "DirectoryHelper().get_dirs()" in ORGANIZER
    assert "插件不维护第二套媒体库规则" in ORGANIZER
    for forbidden in (
        "_build_organize_plan",
        "_build_target_parent",
        "_auto_policy_for_media",
        "_resolve_operation",
        "_conflict_decision",
        "self._guangya_api.move",
        "self._guangya_api.copy",
    ):
        assert forbidden not in ORGANIZER


def test_runtime_bridge_is_install_safe_across_v3_event_surfaces():
    for token in (
        'getattr(ChainEventType, "StorageOperSelection", None)',
        'getattr(EventType, "TransferComplete", None)',
        'getattr(EventType, "TransferFailed", None)',
        "organizer_transfer_complete",
        "organizer_transfer_failed",
        "weakref.ref(plugin)",
    ):
        assert token in RUNTIME, token


def test_state_machine_only_marks_terminal_success_completed():
    for token in ('"completed"', '"stabilizing"', '"inflight"', '"retry"', '"blocked"'):
        assert token in STATE
    for token in (
        "mark_submitting",
        "mark_completed",
        "mark_failed",
        "mark_blocked",
        "clear_blocked",
        "inflight_lease_seconds",
    ):
        assert token in STATE


def test_moviepilot_history_gate_is_reused():
    for token in (
        "HistoryGateAction",
        "resolve_history",
        "evaluate_history_gate",
        "describe_history_gate",
        '"decision": "completed"',
        '"decision": "blocked"',
        '"decision": "unknown"',
    ):
        assert token in HISTORY, token


def test_snapshot_contract_tracks_current_moviepilot_parameter():
    assert "previous_snapshot: Optional[Dict[str, Dict]] = None" in STORAGE
    assert "remove_deleted_children" in STORAGE
    assert '"fileid": getattr(fileitem, "fileid", None)' in STORAGE


def test_explicit_episode_context_keeps_weak_name_support():
    for token in (
        "_release_parent_title",
        "_preferred_episode_title",
        "_sxe_re",
        "_x_episode_re",
        "_cn_episode_re",
        "_episode_only_re",
        "父目录有本地化中文标题时优先使用中文标题",
        'MetaInfo(f"{title} S{season:02d}E{episode:02d}")',
    ):
        assert token in RECOGNITION, token


def test_safe_recognition_uses_parent_chinese_title_only_as_mp_hint():
    for token in (
        "MediaChain().recognize_by_meta",
        "_release_parent_title",
        "未按英文文件名继续猜测",
        "无硬编码媒体ID",
        "分类/命名仍由 MoviePilot 决定",
    ):
        assert token in SAFE_RECOGNITION, token
    assert "tmdb_id=" not in SAFE_RECOGNITION
    assert "media_id=" not in SAFE_RECOGNITION


def test_safe_recognition_checks_localized_titles_and_aliases():
    for token in (
        '"hk_title"',
        '"tw_title"',
        '"sg_title"',
        '"names"',
        '"original_name"',
        "overlap >= 0.70",
    ):
        assert token in SAFE_RECOGNITION, token


def test_safe_recognition_stops_on_title_or_year_conflict():
    assert "_recognition_matches_hint" in SAFE_RECOGNITION
    assert "MoviePilot 返回" in SAFE_RECOGNITION
    assert "int(str(media_year)[:4]) != int(year)" in SAFE_RECOGNITION
    assert "return False, message" in SAFE_RECOGNITION


def test_monitor_uses_persistent_settings_and_bounded_inventory():
    for key in (
        "organize_monitor_config",
        "organize_monitor_state",
        "organize_monitor_history",
        "organize_monitor_status",
    ):
        assert key in ORGANIZER
    assert "_monitor_inventory_cap" in ORGANIZER
    assert "reconcile_inventory" in ORGANIZER


def test_backend_exposes_monitor_controls():
    assert "class GuangYaOrganizerResponse" in MODELS
    block = ORGANIZER.split("def get_organizer_api", 1)[1]
    for endpoint in (
        "/organize/monitor/config",
        "/organize/monitor/scan",
        "/organize/monitor/status",
        "/organize/monitor/selfcheck",
        "/organize/monitor/unblock",
    ):
        assert endpoint in block
    assert "apis.extend(self.get_organizer_api())" in INIT


def test_ui_remains_a_state_console_not_a_second_organizer():
    for token in (
        "监控目录",
        "启用自动监控整理",
        "保存设置",
        "立即扫描",
        "运行自检",
        "最近自动整理流水",
        "MoviePilot 内置",
    ):
        assert token in PAGE, token
    for forbidden in (
        "目标根目录",
        "目录策略",
        "强制移动",
        "强制复制",
        "预览整理计划",
    ):
        assert forbidden not in PAGE
