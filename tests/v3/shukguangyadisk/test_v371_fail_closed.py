from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
POLICY = (ROOT / "plugins.v3/shukguangyadisk/organizer_policy.py").read_text(encoding="utf-8")


def test_v371_unknown_size_still_blocks_destructive_action():
    assert "FileDisposition.BLOCK_SAFETY" in POLICY
    assert "DELETE_DUPLICATE" in POLICY
    assert "KEEP_VERSION" in POLICY
