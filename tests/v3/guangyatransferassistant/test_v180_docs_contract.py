from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
README = (ROOT / "plugins.v3" / "guangyatransferassistant" / "README.md").read_text(encoding="utf-8")


def test_readme_states_guangya_native_offline_not_downloader():
    assert "Magnet 与 ED2K **不交给 MoviePilot 下载器**" in README
    assert "cloudcollection/v1/create_task" in README
    assert "不需要 qBittorrent、Transmission、Aria2" in README
    assert "/viewing/ingest" in README
