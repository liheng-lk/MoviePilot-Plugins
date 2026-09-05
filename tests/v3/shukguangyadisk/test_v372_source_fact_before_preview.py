from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CONFLICT = (ROOT / "plugins.v3/shukguangyadisk/organizer_conflict_resolution_v353.py").read_text(encoding="utf-8")


def test_v372_source_presence_fact_precedes_moviepilot_preview():
    block = CONFLICT[CONFLICT.index("def _execute_conflict_aware"):]
    assert block.index("_live_primary_media_state(plugin, item.path)") < block.index('preview_kwargs["preview"] = True')
