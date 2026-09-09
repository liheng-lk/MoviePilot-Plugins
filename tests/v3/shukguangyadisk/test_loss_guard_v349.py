from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
GUARD = (PLUGIN / "organizer_loss_guard_v349.py").read_text(encoding="utf-8")
FILTER = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
REMOTE = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")


def test_real_folder_transfer_requires_moviepilot_preview_first():
    for token in (
        'preview_kwargs["preview"] = True',
        "preview = transfer_chain.do_transfer(**preview_kwargs)",
        "safe, guard_message, details = _audit_preview",
        "return _normalize_result(transfer_chain.do_transfer(**kwargs))",
        "整理前预览",
        "开始真实整理",
    ):
        assert token in GUARD, token
    assert GUARD.index('preview_kwargs["preview"] = True') < GUARD.index(
        "return _normalize_result(transfer_chain.do_transfer(**kwargs))"
    )


def test_preview_guard_blocks_missing_failed_empty_or_duplicate_targets():
    for token in (
        "missing = sorted",
        "failed: List[str]",
        "empty_target: List[str]",
        "duplicate_targets",
        "发现 {len(duplicates)} 组重复目标",
        "已阻止真实整理，源文件保持原位",
        '"folder_safety_blocked"',
    ):
        assert token in GUARD, token


def test_guard_does_not_build_a_second_naming_or_classification_policy():
    for forbidden in (
        "RENAME_FORMAT(",
        "get_rename_path(",
        "DirectoryHelper().get_dir(",
        "tmdb_id=",
        "media_id=",
        "self._guangya_api.move",
        "self._guangya_api.copy",
    ):
        assert forbidden not in GUARD, forbidden
    assert "_moviepilot_directory_context" in GUARD
    assert "_moviepilot_episode_format" in GUARD
    assert "_moviepilot_tv_context_from_directory_meta" in GUARD


def test_folder_success_cannot_silently_complete_members_without_file_events():
    for token in (
        "_defer_unconfirmed_members",
        "未收到该成员的 MoviePilot 单文件最终事件",
        "state_store.mark_deferred",
        '"folder_partial" if deferred else "folder_completed"',
        "不标记完成，已退回重试",
    ):
        assert token in GUARD, token
    success_block = GUARD.split("if not success:", 1)[1]
    assert "previous_fallback(self, item, success=True" not in success_block


def test_loss_guard_remains_before_empty_and_episode_adapter_guards():
    assert "from .organizer_loss_guard_v349 import install_loss_guard_v349" in FILTER
    assert "install_loss_guard_v349()" in FILTER
    assert FILTER.index("install_network_resilience_v347()") < FILTER.index("install_loss_guard_v349()")
    assert FILTER.index("install_loss_guard_v349()") < FILTER.index("install_empty_folder_guard_v3410()")
    assert FILTER.index("install_loss_guard_v349()") < FILTER.index("install_episode_name_adapter_v3411()")

    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["ShukGuangYaDisk"]
    local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    current = package["version"]
    assert local["version"] == current
    assert f'plugin_version = "{current}"' in ENTRY
    assert f"__federation_expose_AssistantPage-v352.js?v={current}" in REMOTE
    assert package["history"]["v3.4.9"] == "增加整理前目标唯一性校验，防止集数误映射覆盖并进入回收站。"
