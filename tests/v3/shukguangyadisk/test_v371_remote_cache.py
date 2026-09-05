from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REMOTE = (ROOT / "plugins.v3/shukguangyadisk/dist/assets/remoteEntry.js").read_text(encoding="utf-8")


def test_v371_federation_cache_buster_is_current():
    assert "?v=3.7.1" in REMOTE
