import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"


def test_v371_history_describes_explicit_core_not_new_media_policy():
    plugin = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    history = plugin["history"]["v3.7.1"]
    for token in ("Phase 2", "monkey patch", "Execution", "v3.7.0"):
        assert token in history
    assert "未识别原地保留" in history
    assert "同大小" in history
    assert "不同大小" in history
