from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
FAST = (PLUGIN / "fast_recall_v1126.py").read_text(encoding="utf-8")
MATCH = (PLUGIN / "media_match_v11219.py").read_text(encoding="utf-8")


def test_media_match_slice_does_not_bump_public_release_metadata():
    assert 'plugin_version = "1.12.18"' in ENTRY
    assert 'build_id = "20260906-r65"' in ENTRY
    assert "GuangYaMediaMatchV11219Mixin" in FAST
    assert "requested_episodes" in MATCH
    assert "transfer_episodes" in MATCH
