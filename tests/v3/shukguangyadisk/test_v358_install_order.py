from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
CANDIDATE = (ROOT / "plugins.v3" / "shukguangyadisk" / "organizer_candidate_filter.py").read_text(encoding="utf-8")


def test_v358_is_the_final_organizer_compatibility_layer():
    assert CANDIDATE.index("install_season_context_v358()") > CANDIDATE.index("install_preview_retry_wakeup_v356()")
