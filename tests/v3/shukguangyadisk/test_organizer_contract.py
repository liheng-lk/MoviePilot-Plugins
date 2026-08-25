from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
INIT = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
ORGANIZER = (PLUGIN / "organizer.py").read_text(encoding="utf-8")
FOLDER_STREAM = (PLUGIN / "organizer_folder_stream.py").read_text(encoding="utf-8")
FOLDER_HISTORY = (PLUGIN / "organizer_folder_history.py").read_text(encoding="utf-8")
RECOGNITION = (PLUGIN / "organizer_recognition.py").read_text(encoding="utf-8")
RUNTIME = (PLUGIN / "organizer_runtime.py").read_text(encoding="utf-8")
STATE = (PLUGIN / "organizer_state.py").read_text(encoding="utf-8")
HISTORY = (PLUGIN / "organizer_history.py").read_text(encoding="utf-8")
STORAGE = (PLUGIN / "storage_contract.py").read_text(encoding="utf-8")
MODELS = (PLUGIN / "models.py").read_text(encoding="utf-8")
REMOTE = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")
PAGE = (PLUGIN / "dist" / "assets" / "__federation_expose_AssistantPage-v330.js").read_text(encoding="utf-8")


def test_v331_version_and_federation_entry():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["ShukGuangYaDisk"]
    local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    assert package["version"] == "3.3.1"
    assert local["version"] == "3.3.1"
    assert 'plugin_version = "3.3.1"' in INIT
    assert "__federation_expose_AssistantPage-v330.js?v=3.3.1" in REMOTE
    assert "自动整理监控" in PAGE
    assert "v3.3.1" in package["history"]


def test_architecture_separates_monitor_state_history_recognition_and_runtime():
    assert "from .organizer_state import OrganizerStateStore" in ORGANIZER
    assert "from .organizer_history import inspect_moviepilot_history" in ORGANIZER
    assert "from .organizer_runtime import bind_organizer_runtime" in RECOGNITION
    assert "class OrganizerStateStore" in STATE
    assert "def inspect_moviepilot_history" in HISTORY
    assert "def bind_organizer_runtime" in RUNTIME
    assert "eventmanager.register" not in RECOGNITION
    assert "DirectoryHelper" not in STATE
    assert "TransferChain" not in STATE
    assert "TransferDispatcher" not in STATE


def test_folder_stream_and_history_layers_are_explicitly_composed():
    assert "from .organizer_folder_stream import GuangYaFolderStreamMixin" in INIT
    assert "from .organizer_folder_history import GuangYaFolderHistoryMixin" in INIT
    class_block = INIT.split("class ShukGuangYaDisk(", 1)[1].split("):", 1)[0]
    assert class_block.index("GuangYaFolderHistoryMixin") < class_block.index("GuangYaFolderStreamMixin")
    assert "_organize_scan_mode = \"folder_stream\"" in FOLDER_STREAM
    assert "group_path" in FOLDER_STREAM
    assert "batch_id" in FOLDER_STREAM
    assert "folder_batch" in FOLDER_STREAM


def test_grouped_history_retains_folder_context_without_changing_moviepilot_rules():
    assert "class GuangYaFolderHistoryMixin" in FOLDER_HISTORY
    assert "_monitor_history_limit = 1000" in FOLDER_HISTORY
    assert "folder_history" in FOLDER_HISTORY
    assert "history_retained" in FOLDER_HISTORY
    assert "_seen_paths" in FOLDER_HISTORY
    assert '"completed": "completed"' in FOLDER_HISTORY
    assert '"queued": "inflight"' in FOLDER_HISTORY
    assert '"failed": "retry"' in FOLDER_HISTORY
    assert "api_organize_monitor_status" in FOLDER_HISTORY
    for forbidden in ("TransferChain", "DirectoryHelper", "MediaType", "TMDB"):
        assert forbidden not in FOLDER_HISTORY


def test_auto_monitor_delegates_business_rules_to_moviepilot():
    assert "from app.monitor.dispatcher import TransferDispatcher" in ORGANIZER
    assert "TransferDispatcher()" in ORGANIZER
    assert ".handle_file(" in ORGANIZER
    assert "DirectoryHelper().get_dirs()" in ORGANIZER
    assert "插件不维护第二套媒体库规则" in ORGANIZER
    for legacy_symbol in (
        "_build_organize_plan",
        "_build_target_parent",
        "_auto_policy_for_media",
        "_resolve_operation",
        "_conflict_decision",
        "self._guangya_api.move",
        "self._guangya_api.copy",
    ):
        assert legacy_symbol not in ORGANIZER


def test_runtime_bridge_is_install_safe_across_v3_event_surfaces():
    for token in (
        'getattr(ChainEventType, "StorageOperSelection", None)',
        'getattr(EventType, "TransferComplete", None)',
        'getattr(EventType, "TransferFailed", None)',
        'getattr(EventType, "SubtitleTransferComplete", None)',
        'getattr(EventType, "SubtitleTransferFailed", None)',
        'getattr(EventType, "AudioTransferComplete", None)',
        'getattr(EventType, "AudioTransferFailed", None)',
        "organizer_transfer_complete",
        "organizer_transfer_failed",
    ):
        assert token in RUNTIME, token
    assert "def _register_optional" in RUNTIME
    assert "except ImportError" in RUNTIME
    assert "weakref.ref(plugin)" in RUNTIME
    assert "active_organizer_plugin() is plugin" in RUNTIME


def test_state_machine_only_marks_terminal_success_completed():
    for token in ('"completed"', '"stabilizing"', '"inflight"', '"retry"', '"blocked"'):
        assert token in STATE
    assert "mark_submitting" in STATE
    assert "mark_completed" in STATE
    assert "mark_failed" in STATE
    assert "mark_blocked" in STATE
    assert "clear_blocked" in STATE
    assert "inflight_lease_seconds" in STATE
    assert "retry_delay" in STATE
    assert "blocked_recheck_seconds" in STATE
    assert "v3.3.0-reconfirm-v32-seen" in STATE
    migration = STATE.split("def migrate_from_v322", 1)[1]
    assert '"completed": {}' in migration
    assert 'normalized["retry"][path]' in migration


def test_moviepilot_history_gate_is_reused_but_not_an_install_time_dependency():
    for token in (
        "HistoryGateAction",
        "resolve_history",
        "evaluate_history_gate",
        "describe_history_gate",
        "HistoryGateAction.SKIP",
        "HistoryGateAction.SKIP_RETRY_EXHAUSTED",
    ):
        assert token in HISTORY, token
    assert "def _load_history_api" in HISTORY
    assert "from app.application.history import" in HISTORY
    assert '"action": "delegate_to_dispatcher"' in HISTORY
    assert '"decision": "completed"' in HISTORY
    assert '"decision": "blocked"' in HISTORY
    assert '"decision": "unknown"' in HISTORY
    assert "inspect_moviepilot_history(" in ORGANIZER


def test_snapshot_contract_tracks_current_moviepilot_previous_snapshot_parameter():
    assert "def snapshot_storage(" in STORAGE
    assert "previous_snapshot: Optional[Dict[str, Dict]] = None" in STORAGE
    assert "PurePosixPath" in STORAGE
    assert '"fileid": getattr(fileitem, "fileid", None)' in STORAGE
    assert "remove_deleted_children" in STORAGE


def test_scan_marks_inflight_before_dispatch_and_waits_for_terminal_receipt():
    preflight = ORGANIZER.index("preflight = self._preflight_history(item, path)")
    mark = ORGANIZER.index("state.mark_submitting(")
    dispatch = ORGANIZER.index("accepted = self._dispatch_to_moviepilot(item)")
    assert preflight < mark < dispatch
    assert 'result="queued"' in ORGANIZER
    assert "等待最终回执" in ORGANIZER
    assert "state.mark_deferred" in ORGANIZER
    assert "state.mark_ignored" in ORGANIZER
    assert "state.mark_blocked" in ORGANIZER
    assert "state_schema=OrganizerStateStore.schema_version" in ORGANIZER


def test_terminal_receipt_is_scoped_to_current_monitor_path():
    assert "not self._is_monitored_path(raw_path)" in RECOGNITION
    assert "self._state().mark_completed" in RECOGNITION
    assert "self._state().mark_failed" in RECOGNITION
    assert "MP最终结果" in RECOGNITION


def test_explicit_episode_recognition_prefers_clean_localized_release_title():
    for token in (
        "_title_before_match",
        "_release_parent_title",
        "_preferred_episode_title",
        "_release_cut_re",
        "_sxe_re",
        "_x_episode_re",
        "_cn_episode_re",
        "_episode_only_re",
    ):
        assert token in RECOGNITION, token
    assert "父目录有本地化中文标题时优先使用中文标题" in RECOGNITION
    assert "判定优先级：明确季集 > MP目录配置 > Season/剧集目录 > TV/Movie根目录" in RECOGNITION
    assert "configured_type or (MediaType.TV if series_folder else root_type)" in RECOGNITION
    assert 'MetaInfo(f"{title} S{season:02d}E{episode:02d}")' in RECOGNITION
    assert "mtype=media_type" in RECOGNITION
    assert "meta.year = file_meta.year" in RECOGNITION
    assert "result = TransferChain().do_transfer(" in RECOGNITION
    assert "return bool(result[0])" in RECOGNITION


def test_numeric_episode_retains_false_positive_guards():
    assert "_episode_parent_context" in RECOGNITION
    assert "if not tail and not season_dir" in RECOGNITION
    assert "if tail_residue" in RECOGNITION
    assert "semantic_parent" in RECOGNITION
    assert "_generic_title_dirs" in RECOGNITION


def test_monitor_uses_persistent_settings_scheduler_and_bounded_inventory():
    for key in (
        "organize_monitor_config",
        "organize_monitor_state",
        "organize_monitor_history",
        "organize_monitor_status",
    ):
        assert key in ORGANIZER
    assert "IntervalTrigger(seconds=self._monitor_heartbeat)" in ORGANIZER
    assert "deque([root])" in ORGANIZER
    assert "_monitor_inventory_cap" in ORGANIZER
    assert "truncated" in ORGANIZER
    assert "reconcile_inventory" in ORGANIZER


def test_monitor_only_accepts_concrete_cloud_folder_and_waits_for_stability():
    assert 'self._organize_monitor_path == "/"' in ORGANIZER
    assert "禁止直接监控根目录" in ORGANIZER
    assert "监控目录不存在" in ORGANIZER
    assert "stability_seconds=self._organize_monitor_stability" in ORGANIZER
    assert "_fingerprint" in ORGANIZER
    assert "fileid" in ORGANIZER
    assert "modify_time" in ORGANIZER


def test_backend_exposes_status_selfcheck_and_manual_unblock():
    assert "class GuangYaOrganizerResponse" in MODELS
    block = ORGANIZER.split("def get_organizer_api", 1)[1]
    for endpoint in (
        "/organize/policies",
        "/organize/folders",
        "/organize/monitor/config",
        "/organize/monitor/scan",
        "/organize/monitor/status",
        "/organize/monitor/selfcheck",
        "/organize/monitor/unblock",
    ):
        assert endpoint in block
    assert block.count('"response_model": GuangYaOrganizerResponse') == 8
    assert "_organizer_selfcheck" in ORGANIZER
    assert "runtime_bridge" in ORGANIZER
    assert "clear_blocked" in ORGANIZER
    assert "apis.extend(self.get_organizer_api())" in INIT


def test_ui_is_a_state_console_not_a_second_organizer():
    for token in (
        "监控目录",
        "启用自动监控整理",
        "保存设置",
        "立即扫描",
        "运行自检",
        "重新检查 MP 门控",
        "整理中",
        "重试等待",
        "按子目录整理历史",
        "MoviePilot 内置",
        "folderHistory",
        "toggleGroup",
        "groups_scanned",
        "queue_slots",
        "v3.4.0 preview",
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
