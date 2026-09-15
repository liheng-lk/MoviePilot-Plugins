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


def test_public_release_is_219_r107():
    assert LOCAL["version"] == PACKAGE["version"] == "2.1.9"
    assert LOCAL["description"] == PACKAGE["description"]
    assert "r107" in str(LOCAL.get("description") or "")
    assert "v2.1.9" in (PACKAGE.get("history") or {})
    assert README.startswith("## v2.1.9-r107")
    start = ENTRY.rindex("\nclass GuangYaTransferAssistant(")
    final_class = ENTRY[start:]
    assert 'plugin_version = "2.1.9"' in final_class
    assert 'build_id = "20260915-r107"' in final_class
    assert "光鸭转存助手 v2.1.9 运行入口。" in ENTRY[:1000]


def test_public_release_keeps_single_file_runtime():
    runtime = sorted(path.relative_to(PLUGIN).as_posix() for path in PLUGIN.rglob("*.py"))
    assert runtime == ["__init__.py"]


def test_219_history_documents_gying_detail_truth():
    history = str((PACKAGE.get("history") or {}).get("v2.1.9") or "")
    for marker in (
        "www.xn--wcv59z.com", "PanSou", "downurl", "全部失败",
        "success=False", "failover", "合法 0 结果",
    ):
        assert marker in history


def test_218_history_documents_restore_submit_pairing():
    history = str((PACKAGE.get("history") or {}).get("v2.1.8") or "")
    for marker in (
        "restore_share", "accessToken", "shareId", "同源",
        "access_share_id_v216", "share_id_request_v11225", "missing_access_token",
    ):
        assert marker in history


def test_217_history_documents_direct_share_access_contract():
    history = str((PACKAGE.get("history") or {}).get("v2.1.7") or "")
    for marker in (
        "legacy", "空列表", "shareId", "accessToken",
        "基础", "完整", "retryable", "get_share_page_files_list",
    ):
        assert marker in history


def test_216_history_documents_six_channel_entry_contract():
    history = str((PACKAGE.get("history") or {}).get("v2.1.6") or "")
    for marker in (
        "六个 TGM 频道", "guangyapan.com", "curGuildID", "darkmode",
        "message-local", "xunlei > guangya > magnet > ed2k", "115",
    ):
        assert marker in history


def test_215_history_still_documents_channel_fallback_summary_and_sequel_guard():
    history = str((PACKAGE.get("history") or {}).get("v2.1.5") or "")
    for marker in (
        "channel_only", "airing_pull", "手动刷新", "subscribe_id",
        "S01", "S02", "观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K",
    ):
        assert marker in history
