from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
INIT = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
ORGANIZER = (PLUGIN / "organizer.py").read_text(encoding="utf-8")
RECOGNITION = (PLUGIN / "organizer_recognition.py").read_text(encoding="utf-8")
MODELS = (PLUGIN / "models.py").read_text(encoding="utf-8")
REMOTE = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")
PAGE = (PLUGIN / "dist" / "assets" / "__federation_expose_AssistantPage-v320.js").read_text(encoding="utf-8")


def test_v321_version_and_federation_entry():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["ShukGuangYaDisk"]
    local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    assert package["version"] == "3.2.1"
    assert local["version"] == "3.2.1"
    assert 'plugin_version = "3.2.1"' in INIT
    assert "__federation_expose_AssistantPage-v320.js?v=3.2.1" in REMOTE
    assert "自动整理监控" in PAGE


def test_auto_monitor_delegates_organization_to_moviepilot_native_chain():
    assert "from app.monitor.dispatcher import TransferDispatcher" in ORGANIZER
    assert "TransferDispatcher()" in ORGANIZER
    assert ".handle_file(" in ORGANIZER
    assert "DirectoryHelper().get_dirs()" in ORGANIZER
    assert "TransferChain" in ORGANIZER  # documented responsibility boundary
    assert "插件不维护第二套分类或命名规则" in ORGANIZER

    # v3.2+ must not rebuild the old custom planner / target naming path.
    for legacy_symbol in (
        "_build_organize_plan",
        "_build_target_parent",
        "_auto_policy_for_media",
        "_resolve_operation",
        "_conflict_decision",
        "MediaChain().recognize_by_meta",
        "self._guangya_api.move",
        "self._guangya_api.copy",
    ):
        assert legacy_symbol not in ORGANIZER


def test_numeric_episode_uses_parent_title_as_moviepilot_recognition_hint():
    assert "from .organizer_recognition import GuangYaOrganizerMixin" in INIT
    assert "from app.chain.transfer import TransferChain" in RECOGNITION
    assert "from app.domain.metainfo import MetaInfo" in RECOGNITION
    assert "_episode_parent_context" in RECOGNITION
    assert "22~[4K][HEVC.AAC][2026.08.19].mp4" in RECOGNITION
    assert 'MetaInfo(f"{title} S{season:02d}E{episode:02d}")' in RECOGNITION
    assert "meta=meta" in RECOGNITION
    assert "mtype=MediaType.TV" in RECOGNITION
    assert "super()._dispatch_to_moviepilot(item)" in RECOGNITION
    assert "弱文件名使用父目录剧名" in RECOGNITION

    # 识别桥只提供 meta hint，不接管 MoviePilot 的目录/移动/命名策略。
    for forbidden in (
        "target_directory=",
        "library_path",
        "_build_target_parent",
        "self._guangya_api.move",
        "self._guangya_api.copy",
    ):
        assert forbidden not in RECOGNITION

    # 误识别保护：裸数字只允许显式季目录，普通文字标题尾巴不接管，纯数字电影父目录不接管。
    assert "if not tail and not season_dir" in RECOGNITION
    assert "if tail_residue" in RECOGNITION
    assert "semantic_parent" in RECOGNITION
    assert "_generic_title_dirs" in RECOGNITION


def test_auto_monitor_has_persistent_settings_and_scheduler():
    for key in (
        "organize_monitor_config",
        "organize_monitor_state",
        "organize_monitor_history",
        "organize_monitor_status",
    ):
        assert key in ORGANIZER
    assert "self.save_data(self._monitor_config_key, config)" in ORGANIZER
    assert "self.get_data(self._monitor_config_key)" in ORGANIZER
    assert "IntervalTrigger(seconds=self._monitor_heartbeat)" in ORGANIZER
    assert '"enabled"' in ORGANIZER
    assert '"path"' in ORGANIZER
    assert '"interval"' in ORGANIZER
    assert '"stability"' in ORGANIZER
    assert '"batch_size"' in ORGANIZER
    assert '"recursive"' in ORGANIZER


def test_monitor_only_accepts_concrete_cloud_folder_and_waits_for_stability():
    assert 'self._organize_monitor_path == "/"' in ORGANIZER
    assert "禁止直接监控根目录" in ORGANIZER
    assert "监控目录不存在" in ORGANIZER
    assert "first_seen" in ORGANIZER
    assert "_organize_monitor_stability" in ORGANIZER
    assert "_fingerprint" in ORGANIZER
    assert "fileid" in ORGANIZER
    assert "modify_time" in ORGANIZER


def test_ui_focuses_on_monitoring_not_custom_classification():
    assert "监控目录" in PAGE
    assert "启用自动监控整理" in PAGE
    assert "保存设置" in PAGE
    assert "立即扫描" in PAGE
    assert "扫描间隔" in PAGE
    assert "文件稳定等待" in PAGE
    assert "MoviePilot 内置" in PAGE
    assert "目标根目录" not in PAGE
    assert "目录策略" not in PAGE
    assert "强制移动" not in PAGE
    assert "强制复制" not in PAGE
    assert "允许按 MP 覆盖策略" not in PAGE
    assert "预览整理计划" not in PAGE


def test_auto_monitor_v3_json_endpoints_have_response_model():
    assert "class GuangYaOrganizerResponse" in MODELS
    block = ORGANIZER.split("def get_organizer_api", 1)[1]
    for endpoint in (
        "/organize/policies",
        "/organize/folders",
        "/organize/monitor/config",
        "/organize/monitor/scan",
        "/organize/monitor/status",
    ):
        assert endpoint in block
    assert block.count('"response_model": GuangYaOrganizerResponse') == 6
    assert "apis.extend(self.get_organizer_api())" in INIT
