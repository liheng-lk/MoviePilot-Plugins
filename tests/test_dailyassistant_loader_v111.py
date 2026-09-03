import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = (ROOT / "plugins.v3/dailyassistant/__init__.py").read_text(encoding="utf-8")
PACKAGE = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))


def test_dailyassistant_exposes_only_final_loader_candidate():
    final_pos = ENTRY.index("class DailyAssistant(DailyAssistantV110Mixin, DailyAssistantV100):")
    delete_pos = ENTRY.index("del DailyAssistantV100")
    export_pos = ENTRY.index("__all__ = [\"DailyAssistant\"]")
    assert final_pos < delete_pos < export_pos
    assert "plugin_version = \"1.1.1\"" in ENTRY[final_pos:export_pos]


def test_dailyassistant_market_version_is_v111():
    assert PACKAGE["DailyAssistant"]["version"] == "1.1.1"
    assert "v1.1.1" in PACKAGE["DailyAssistant"]["history"]
