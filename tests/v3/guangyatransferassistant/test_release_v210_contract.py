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


def test_public_release_is_215_r104():
    assert LOCAL["version"] == PACKAGE["version"] == "2.1.5"
    assert LOCAL["description"] == PACKAGE["description"]
    assert "r104" in str(LOCAL.get("description") or "")
    assert "v2.1.5" in (PACKAGE.get("history") or {})
    assert README.startswith("## v2.1.5-r104")
    start = ENTRY.rindex("\nclass GuangYaTransferAssistant(")
    final_class = ENTRY[start:]
    assert 'plugin_version = "2.1.5"' in final_class
    assert 'build_id = "20260913-r104"' in final_class
    assert "光鸭转存助手 v2.1.5 运行入口。" in ENTRY[:1000]


def test_public_release_keeps_single_file_runtime():
    runtime = sorted(path.relative_to(PLUGIN).as_posix() for path in PLUGIN.rglob("*.py"))
    assert runtime == ["__init__.py"]


def test_215_history_documents_r104_session_identity_and_source_priority():
    history = str((PACKAGE.get("history") or {}).get("v2.1.5") or "")
    for marker in (
        "r104", "活 Session", "S01", "S02", "SEASON_MISMATCH",
        "AUTO_SELECT_CONFIDENCE=0.90",
        "观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K",
    ):
        assert marker in history
