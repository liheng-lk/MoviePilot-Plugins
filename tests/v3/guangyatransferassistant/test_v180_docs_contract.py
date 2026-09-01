from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
README = (ROOT / "plugins.v3" / "guangyatransferassistant" / "README.md").read_text(encoding="utf-8")
MULTI = (ROOT / "plugins.v3" / "guangyatransferassistant" / "multisource_v180.py").read_text(encoding="utf-8")


def test_readme_states_guangya_native_offline_not_downloader():
    assert "Magnet/ED2K 始终交给光鸭原生 cloudcollection，不经过 MoviePilot 下载器" in README
    assert "/cloudcollection/v1/create_task" in README
    assert "不调用 MoviePilot DownloadChain" in README
    # v1.8 手动 viewing ingest 兼容 API 仍保留；README 重构不要求重复罗列每个历史 API。
    assert '"/viewing/ingest"' in MULTI
