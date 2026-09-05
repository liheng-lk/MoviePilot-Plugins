from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
GUARD = (PLUGIN / "organizer_empty_folder_guard_v3410.py").read_text(encoding="utf-8")
CONFLICT = (PLUGIN / "organizer_conflict_resolution_v353.py").read_text(encoding="utf-8")
EXEC = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")
FILTER = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
REMOTE = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")


def test_empty_or_missing_folder_skips_moviepilot_recognition():
    assert "def _live_primary_media_state" in GUARD
    for token in (
        "_live_primary_media_state(plugin, item.path)",
        'live_state in {"empty", "missing"}',
        "_clear_stale_transient_state(plugin, item)",
        "_guangya_empty_folder_skip_v3410",
        "跳过陈旧文件夹任务",
    ):
        assert token in CONFLICT, token
    assert CONFLICT.index("_live_primary_media_state(plugin, item.path)") < CONFLICT.index("_build_moviepilot_kwargs(plugin, item)")


def test_empty_folder_check_uses_moviepilot_media_extensions_only():
    assert 'get_runtime_setting("RMT_MEDIAEXT")' in GUARD
    assert "RMT_SUBEXT" not in GUARD
    assert "RMT_AUDIOEXT" not in GUARD


def test_network_failure_is_not_misclassified_as_empty_folder():
    for token in ("_api_network_status", "_network_retry_after", 'return "network"'):
        assert token in GUARD, token
    assert 'if live_state == "network":' in CONFLICT
    assert "return False, live_detail" in CONFLICT


def test_empty_skip_does_not_reenter_folder_success_deferred_fallback():
    assert "_guangya_empty_folder_skip_v3410" in CONFLICT
    block = EXEC[EXEC.index("if isinstance(item, _FolderBatchEnvelope) and item.directory_mode:"):EXEC.index("return super()._fallback_terminal_state", EXEC.index("if isinstance(item, _FolderBatchEnvelope) and item.directory_mode:"))]
    assert "_guangya_empty_folder_skip_v3410" in block
    assert block.index("_guangya_empty_folder_skip_v3410") < block.index("_defer_unconfirmed_members")


def test_v3410_behavior_stays_enabled_without_runtime_installer():
    assert "install_empty_folder_guard_v3410" not in FILTER
    assert "install_empty_folder_guard_v3410" not in GUARD
    assert "from .organizer_empty_folder_guard_v3410 import" in CONFLICT
    assert "_live_primary_media_state" in CONFLICT

    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["ShukGuangYaDisk"]
    local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    current = package["version"]
    assert local["version"] == current
    assert f'plugin_version = "{current}"' in ENTRY
    assert f"__federation_expose_AssistantPage-v352.js?v={current}" in REMOTE
    assert package["history"]["v3.4.10"] == "跳过已搬空或无视频的陈旧目录任务，不再触发无意义的 MoviePilot 识别。"
