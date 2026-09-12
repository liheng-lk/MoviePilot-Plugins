"""Current GuangYa public release contract.

Historical slice tests intentionally run against an r97 projection. This file is
executed before that projection and is the single source of truth for the actual
release metadata shipped by the branch.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
LOCAL = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
PACKAGE = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))[
    "GuangYaTransferAssistant"
]
README = (PLUGIN / "README.md").read_text(encoding="utf-8")


def test_public_release_is_214_r102():
    assert LOCAL["version"] == PACKAGE["version"] == "2.1.4"
    assert "r102" in str(LOCAL.get("description") or "")
    assert "v2.1.4" in (PACKAGE.get("history") or {})
    assert README.startswith("## v2.1.4-r102")

    start = ENTRY.rindex("\nclass GuangYaTransferAssistant(")
    final_class = ENTRY[start:]
    assert 'plugin_version = "2.1.4"' in final_class
    assert 'build_id = "20260913-r102"' in final_class
    assert "光鸭转存助手 v2.1.4 运行入口。" in ENTRY[:1000]


def test_public_release_keeps_single_file_runtime():
    runtime = sorted(
        path.relative_to(PLUGIN).as_posix()
        for path in PLUGIN.rglob("*.py")
    )
    assert runtime == ["__init__.py"]


def test_214_history_documents_channel_parse_and_dispatch_trace():
    history = str((PACKAGE.get("history") or {}).get("v2.1.4") or "")
    for marker in (
        "Forwarded",
        "更新至N集",
        "SxxEyy-Ezz",
        "媒体解析",
        "manual_refresh",
        "final_target",
        "观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K",
    ):
        assert marker in history
