import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_v372_does_not_roll_back_guangya_transfer_assistant():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    version = tuple(map(int, package["GuangYaTransferAssistant"]["version"].split(".")))
    assert version >= (1, 12, 14)
