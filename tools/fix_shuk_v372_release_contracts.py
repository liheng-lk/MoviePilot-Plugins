from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "tests" / "v3" / "shukguangyadisk" / "test_v371_remote_cache.py"
path.write_text('''import json\nfrom pathlib import Path\n\nROOT = Path(__file__).resolve().parents[3]\nPLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"\nREMOTE = (PLUGIN / "dist/assets/remoteEntry.js").read_text(encoding="utf-8")\n\n\ndef test_v371_federation_cache_buster_tracks_current_release():\n    plugin = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))\n    version = plugin["version"]\n    assert tuple(map(int, version.split("."))) >= (3, 7, 1)\n    assert f"?v={version}" in REMOTE\n''', encoding="utf-8")
print("v3.7.1 federation cache contract converted to release floor")
