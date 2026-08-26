from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
GUARD = (PLUGIN / "organizer_empty_folder_guard_v3410.py").read_text(encoding="utf-8")
FILTER = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
REMOTE = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")


def test_empty_or_missing_folder_skips_moviepilot_recognition():
    for token in (
        "_live_primary_media_state",
        'state in {"empty", "missing"}',
        "跳过陈旧文件夹任务，不调用 MoviePilot 识别",
        '"folder_empty_skipped"',
        "_clear_stale_transient_state",
    ):
        assert token in GUARD, token


def test_empty_folder_check_uses_moviepilot_media_extensions_only():
    assert 'get_runtime_setting("RMT_MEDIAEXT")' in GUARD
    assert "RMT_SUBEXT" not in GUARD
    assert "RMT_AUDIOEXT" not in GUARD


def test_network_failure_is_not_misclassified_as_empty_folder():
    for token in (
        "_api_network_status",
        "_network_retry_after",
        'return "network"',
        "源目录执行前复核因网络异常延后",
    ):
        assert token in GUARD, token


def test_empty_skip_does_not_reenter_v349_retry_fallback():
    assert "_guangya_empty_folder_skip_v3410" in GUARD
    assert "不能再进入 v3.4.9" in GUARD
    assert "return previous_fallback(self, item, success=success, message=message)" in GUARD


def test_v3410_guard_stays_enabled_in_current_release():
    assert "from .organizer_empty_folder_guard_v3410 import install_empty_folder_guard_v3410" in FILTER
    assert "install_empty_folder_guard_v3410()" in FILTER
    assert FILTER.index("install_loss_guard_v349()") < FILTER.index("install_empty_folder_guard_v3410()")
    assert FILTER.index("install_empty_folder_guard_v3410()") < FILTER.index("install_episode_name_adapter_v3411()")

    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["ShukGuangYaDisk"]
    local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    current = package["version"]
    assert local["version"] == current
    assert f'plugin_version = "{current}"' in ENTRY
    assert f"__federation_expose_AssistantPage-v330.js?v={current}" in REMOTE
    assert package["history"]["v3.4.10"] == "跳过已搬空或无视频的陈旧目录任务，不再触发无意义的 MoviePilot 识别。"
