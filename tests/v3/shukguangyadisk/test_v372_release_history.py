import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"


def test_v372_history_describes_architecture_not_new_media_business_rule():
    plugin = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    text = plugin["history"]["v3.7.2"]
    for token in (
        "QueueRecovery",
        "Execution fallback",
        "同大小复核后去重",
        "不同大小版本化",
        "未识别原地保留",
        "fail closed",
    ):
        assert token in text, token
