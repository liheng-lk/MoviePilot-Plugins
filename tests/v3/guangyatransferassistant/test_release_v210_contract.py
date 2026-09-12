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


def test_public_release_is_210_r98():
    assert LOCAL["version"] == PACKAGE["version"] == "2.1.0"
    assert "r98" in str(LOCAL.get("description") or "")
    assert "v2.1.0" in (PACKAGE.get("history") or {})
    assert README.startswith("## v2.1.0-r98")

    start = ENTRY.rindex("\nclass GuangYaTransferAssistant(")
    final_class = ENTRY[start:]
    assert 'plugin_version = "2.1.0"' in final_class
    assert 'build_id = "20260912-r98"' in final_class
    assert "光鸭转存助手 v2.1.0 运行入口。" in ENTRY[:1000]


def test_public_release_keeps_single_file_runtime():
    runtime = sorted(
        path.relative_to(PLUGIN).as_posix()
        for path in PLUGIN.rglob("*.py")
    )
    assert runtime == ["__init__.py"]


def test_210_history_documents_real_completion_contract():
    history = str((PACKAGE.get("history") or {}).get("v2.1.0") or "")
    for marker in (
        "单文件",
        "TG/GYING",
        "迅雷",
        "Magnet",
        "ED2K",
        "真实落盘",
        "最终",
        "1076",
    ):
        assert marker in history
