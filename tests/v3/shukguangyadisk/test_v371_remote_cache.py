import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
REMOTE = (PLUGIN / "dist/assets/remoteEntry.js").read_text(encoding="utf-8")


def test_v371_federation_cache_buster_tracks_current_release():
    plugin = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    version = plugin["version"]
    assert tuple(map(int, version.split("."))) >= (3, 7, 1)
    assert f"?v={version}" in REMOTE
