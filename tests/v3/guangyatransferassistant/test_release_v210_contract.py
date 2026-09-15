"""Current GuangYa public release contract."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
LOCAL = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
PACKAGE = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
README = (PLUGIN / "README.md").read_text(encoding="utf-8")


def test_public_release_is_218_r106():
    assert LOCAL["version"] == PACKAGE["version"] == "2.1.8"
    assert LOCAL["description"] == PACKAGE["description"]
    assert "r106" in str(LOCAL.get("description") or "")
    assert "v2.1.8" in (PACKAGE.get("history") or {})
    assert README.startswith("## v2.1.8-r106")
    start = ENTRY.rindex("\nclass GuangYaTransferAssistant(")
    final_class = ENTRY[start:]
    assert 'plugin_version = "2.1.8"' in final_class
    assert 'build_id = "20260915-r106"' in final_class
    assert "光鸭转存助手 v2.1.8 运行入口。" in ENTRY[:1000]


def test_public_release_keeps_single_file_runtime():
    runtime = sorted(path.relative_to(PLUGIN).as_posix() for path in PLUGIN.rglob("*.py"))
    assert runtime == ["__init__.py"]


def test_215_history_documents_channel_fallback_summary_and_sequel_guard():
    history = str((PACKAGE.get("history") or {}).get("v2.1.5") or "")
    for marker in (
        "channel_only", "airing_pull", "手动刷新", "subscribe_id",
        "S01", "S02", "观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K",
    ):
        assert marker in history


def test_218_refresh_is_async_and_v3_enveloped():
    start = ENTRY.rindex("\nclass GuangYaTransferAssistant(")
    final_class = ENTRY[start:]
    for marker in (
        "def _manual_refresh_worker_v217",
        "name=\"GuangYaManualRefresh\"",
        "\"success\": True",
        "\"message\": \"频道刷新已进入后台队列",
        "\"data\": {",
        "\"queued\": True",
        "manual_refresh_last_v217",
    ):
        assert marker in final_class


def test_218_all_post_routes_are_hardened_and_heavy_buttons_are_async():
    start = ENTRY.rindex("\nclass GuangYaTransferAssistant(")
    final_class = ENTRY[start:]
    for marker in (
        "_button_async_paths_v218 = {",
        "\"/transfer\": \"立即转存\"",
        "\"/providers/search/selected\": \"搜索缺失资源\"",
        "\"/providers/test\": \"检测资源来源\"",
        "\"/xunlei/flash/preflight\": \"秒传预检\"",
        "\"/xunlei/flash/test\": \"迅雷分享测试\"",
        "\"/viewing/nodes/refresh\": \"刷新观影节点\"",
        "\"/viewing/session/test\": \"测试观影会话\"",
        "\"/diagnostics/full\": \"一键完整诊断\"",
        "def _button_response_envelope_v218",
        "if \"POST\" in methods",
        "return self._harden_button_routes_v218(routes)",
        "button_action_last_v218",
    ):
        assert marker in final_class
