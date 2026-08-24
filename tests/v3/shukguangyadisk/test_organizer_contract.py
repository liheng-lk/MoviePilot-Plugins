from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
INIT = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
BASE_ORGANIZER = (PLUGIN / "organizer.py").read_text(encoding="utf-8")
ORGANIZER = (PLUGIN / "organizer_v320.py").read_text(encoding="utf-8")
MODELS = (PLUGIN / "models.py").read_text(encoding="utf-8")
REMOTE = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")
PAGE = (PLUGIN / "dist" / "assets" / "__federation_expose_AssistantPage-v320.js").read_text(encoding="utf-8")


def test_v320_version_and_federation_entry():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["ShukGuangYaDisk"]
    local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    assert package["version"] == "3.2.0"
    assert local["version"] == "3.2.0"
    assert 'plugin_version = "3.2.0"' in INIT
    assert "__federation_expose_AssistantPage-v320.js?v=3.2.0" in REMOTE
    assert "网盘整理" in PAGE


def test_organizer_uses_moviepilot_directory_and_recognition_sources():
    assert "DirectoryHelper().get_library_dirs()" in BASE_ORGANIZER
    assert "MediaChain().recognize_by_meta" in ORGANIZER
    assert "MetaInfoPath" in ORGANIZER
    for field in (
        "media_type", "media_category", "library_type_folder",
        "library_category_folder", "transfer_type", "overwrite_mode",
        "library_path", "library_storage", "renaming", "scraping",
    ):
        assert f'"{field}"' in BASE_ORGANIZER
    assert "自动按 MoviePilot 优先级匹配" in BASE_ORGANIZER


def test_organizer_is_preview_first_and_execute_requires_confirmation():
    assert "/organize/preview" in BASE_ORGANIZER
    assert "/organize/execute" in BASE_ORGANIZER
    execute = BASE_ORGANIZER.split("def api_organize_execute", 1)[1].split("def api_organize_history", 1)[0]
    assert 'payload.get("confirm")' in execute
    assert "plan_id" in execute
    assert "整理计划不存在或已失效" in execute
    assert "15 分钟" in execute
    assert "globalThis.confirm" in PAGE


def test_organizer_path_and_overwrite_safety_guards_exist():
    validate = BASE_ORGANIZER.split("def _validate_organize_roots", 1)[1].split("def _build_organize_plan", 1)[0]
    assert 'source == "/"' in validate
    assert "源目录和目标目录不能相同" in validate
    assert "目标目录不能位于源目录内部" in validate
    assert "allow_overwrite" in BASE_ORGANIZER
    assert "目标已存在且未允许覆盖" in BASE_ORGANIZER
    assert "overwrite_mode" in ORGANIZER
    assert "允许按 MP 覆盖策略处理同名目标" in PAGE


def test_organizer_keeps_cloud_items_and_sidecars_together():
    assert "_same_stem_sidecars" in BASE_ORGANIZER
    assert "_SIDECAR_EXTENSIONS" in BASE_ORGANIZER
    assert "companions" in ORGANIZER
    assert "get_folder(Path(target_parent))" in BASE_ORGANIZER
    assert "self._guangya_api.copy" in BASE_ORGANIZER
    assert "self._guangya_api.move" in BASE_ORGANIZER
    assert "TransHandler" in ORGANIZER
    assert "preview=True" in ORGANIZER
    assert "target_name" in ORGANIZER
    assert "伴随文件" in ORGANIZER


def test_organizer_v3_json_endpoints_have_response_model():
    assert "class GuangYaOrganizerResponse" in MODELS
    block = BASE_ORGANIZER.split("def get_organizer_api", 1)[1]
    for endpoint in ("policies", "folders", "preview", "execute", "history"):
        assert f'"/organize/{endpoint}"' in block
    assert block.count('"response_model": GuangYaOrganizerResponse') == 5
    assert "apis.extend(self.get_organizer_api())" in INIT


def test_v320_uses_moviepilot_native_rename_preview():
    assert 'from app.modules.filemanager.transhandler import TransHandler' in ORGANIZER
    assert 'transfer_media(' in ORGANIZER and 'preview=True' in ORGANIZER
    assert '_collect_media_candidates' in ORGANIZER
    assert '_preview_mp_target' in ORGANIZER
    assert '_cleanup_empty_source_dirs' in ORGANIZER
    assert 'cleaned_empty_dirs' in ORGANIZER
    assert 'move_planned' in ORGANIZER
    assert '完整重新整理' in ORGANIZER
    assert '重新命名' in PAGE or '智能重命名' in PAGE


def test_v320_plans_final_renamed_paths_and_companions():
    assert 'target_name' in ORGANIZER
    assert 'target_parent' in ORGANIZER
    assert 'companions' in ORGANIZER
    assert 'target_path' in ORGANIZER
    assert '_preview_companion_target' in ORGANIZER
    assert '目标路径完全相同' in ORGANIZER
    assert '多个源文件映射到同一 MoviePilot 目标' in ORGANIZER



def test_v320_language_suffix_sidecars_and_preflight():
    assert 'suffix_tags' in ORGANIZER
    assert 'companion_stem.startswith(video_stem)' in ORGANIZER
    assert 'companion_conflict' in ORGANIZER
    assert 'companion_errors' in ORGANIZER
    assert '伴随文件无法生成 MoviePilot 最终命名' in ORGANIZER
    assert '伴随文件目标已存在' in ORGANIZER

