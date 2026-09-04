from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENTRY = (ROOT / "plugins.v3" / "guangyatransferassistant" / "__init__.py").read_text(encoding="utf-8")


def test_v1109_release_marker():
    assert 'plugin_version = "1.12.10"' in ENTRY
    assert 'build_id = "20260905-r56"' in ENTRY
