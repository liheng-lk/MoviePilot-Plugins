from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"


def test_v372_adds_no_new_versioned_behavior_installer():
    names = {p.name for p in PLUGIN.glob("organizer_*_v372*.py")}
    assert not names, sorted(names)
