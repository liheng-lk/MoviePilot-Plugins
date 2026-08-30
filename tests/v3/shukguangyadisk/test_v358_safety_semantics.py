from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PATCH = (ROOT / "plugins.v3" / "shukguangyadisk" / "organizer_season_context_v358.py").read_text(encoding="utf-8")


def test_conflicting_season_evidence_blocks_real_transfer():
    assert "电视剧季号上下文未确认" in PATCH
    assert "阻止真实整理，源文件保持原位" in PATCH
    assert "member_conflict" in PATCH
    assert "path_member_conflict" in PATCH
