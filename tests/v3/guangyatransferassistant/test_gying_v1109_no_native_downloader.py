from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
AUTO = (PLUGIN / "gying_autologin_v1109.py").read_text(encoding="utf-8").lower()


def test_v1109_keeps_fixed_transfer_route():
    assert "观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K" in ENTRY
    for token in ("downloadchain(", "qbittorrent", "transmission", "aria2"):
        assert token not in AUTO
