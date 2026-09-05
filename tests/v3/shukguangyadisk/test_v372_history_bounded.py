from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RULES = (ROOT / "plugins.v3/shukguangyadisk/ORGANIZER_RULES.md").read_text(encoding="utf-8")


def test_v372_does_not_reintroduce_unbounded_local_history():
    assert "历史" in RULES
