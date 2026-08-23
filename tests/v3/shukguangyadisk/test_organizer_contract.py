from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
INIT = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
ORGANIZER = (PLUGIN / "organizer.py").read_text(encoding="utf-8")
MODELS = (PLUGIN / "models.py").read_text(encoding="utf-8")
REMOTE = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")
PAGE = (PLUGIN / "dist" / "assets" / "__federation_expose_AssistantPage-v310.js").read_text(encoding="utf-8")


def test_v310_version_and_federation_entry():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["ShukGuangYaDisk"]
    local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    assert package["version"] == "3.1.0"
    assert local["version"] == "3.1.0"
    assert 'plugin_version = "3.1.0"' in INIT
    assert "__federation_expose_AssistantPage-v310.js?v=3.1.0" in REMOTE
    assert "网盘整理" in PAGE


def test_organizer_uses_moviepilot_directory_and_recognition_sources():
    assert "DirectoryHelper().get_library_dirs()" in ORGANIZER
    assert "MediaChain().recognize_by_meta" in ORGANIZER
    assert "MetaInfoPath" in ORGANIZER
    for field in (
        "media_type", "media_category", "library_type_folder",
        "library_category_folder", "transfer_type", "overwrite_mode",
        "library_path", "library_storage", "renaming", "scraping",
    ):
        assert f'"{field}"' in ORGANIZER
    assert "自动按 MoviePilot 优先级匹配" in ORGANIZER


def test_organizer_is_preview_first_and_execute_requires_confirmation():
    assert "/organize/preview" in ORGANIZER
    assert "/organize/execute" in ORGANIZER
    execute = ORGANIZER.split("def api_organize_execute", 1)[1].split("def api_organize_history", 1)[0]
    assert 'payload.get("confirm")' in execute
    assert "plan_id" in execute
    assert "整理计划不存在或已失效" in execute
    assert "15 分钟" in execute
    assert "globalThis.confirm" in PAGE


def test_organizer_path_and_overwrite_safety_guards_exist():
    validate = ORGANIZER.split("def _validate_organize_roots", 1)[1].split("def _build_organize_plan", 1)[0]
    assert 'source == "/"' in validate
    assert "源目录和目标目录不能相同" in validate
    assert "目标目录不能位于源目录内部" in validate
    assert "allow_overwrite" in ORGANIZER
    assert "目标已存在且未允许覆盖" in ORGANIZER
    assert "overwrite_mode" in ORGANIZER
    assert "允许按 MP 覆盖策略处理同名目标" in PAGE


def test_organizer_keeps_cloud_items_and_sidecars_together():
    assert "_same_stem_sidecars" in ORGANIZER
    assert "_SIDECAR_EXTENSIONS" in ORGANIZER
    assert "companions" in ORGANIZER
    assert "get_folder(Path(target_parent))" in ORGANIZER
    assert "self._guangya_api.copy" in ORGANIZER
    assert "self._guangya_api.move" in ORGANIZER
    assert "保持光鸭原文件/目录名称" in ORGANIZER


def test_organizer_v3_json_endpoints_have_response_model():
    assert "class GuangYaOrganizerResponse" in MODELS
    block = ORGANIZER.split("def get_organizer_api", 1)[1]
    for endpoint in ("policies", "folders", "preview", "execute", "history"):
        assert f'"/organize/{endpoint}"' in block
    assert block.count('"response_model": GuangYaOrganizerResponse') == 5
    assert "apis.extend(self.get_organizer_api())" in INIT
