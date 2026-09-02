import importlib.util
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[3]
COMPAT = ROOT / "plugins.v3" / "guangyatransferassistant" / "episode_compat_v171.py"
ENTRY = ROOT / "plugins.v3" / "guangyatransferassistant" / "__init__.py"

spec = importlib.util.spec_from_file_location("guangya_episode_compat_v171", COMPAT)
compat = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(compat)


def test_quality_suffix_episode_examples():
    cases = {
        "01~4K.mp4": 1,
        "02~4K.mp4": 2,
        "08～2160p.mkv": 8,
        "22~[4K][HEVC.AAC].mkv": 22,
        "001 ~ UHD.zh.ass": 1,
    }
    for path, expected in cases.items():
        assert compat.extract_quality_suffix_episode(path) == expected


def test_quality_suffix_episode_does_not_guess_numeric_ranges_or_codecs():
    for path in (
        "01~04.mp4",
        "2160p.mkv",
        "264~4K.mp4",
        "Show.S01E02.mkv",
        "movie.2026.4K.mkv",
    ):
        assert compat.extract_quality_suffix_episode(path) is None


def test_install_patch_only_falls_back_after_legacy_parser_fails():
    calls = []

    def original(path):
        calls.append(path)
        if "S01E03" in path:
            return 1, [3]
        return None, []

    legacy = SimpleNamespace(_episode_numbers=original)
    patched = compat.install_episode_filename_compat(legacy)
    assert patched is legacy._episode_numbers
    assert legacy._episode_numbers("Show.S01E03.mkv") == (1, [3])
    assert legacy._episode_numbers("04~4K.mp4") == (None, [4])
    assert legacy._episode_numbers("05~06.mp4") == (None, [])
    assert compat.install_episode_filename_compat(legacy) is patched
    assert calls == ["Show.S01E03.mkv", "04~4K.mp4", "05~06.mp4"]


def test_duplicate_unparsed_failure_notice_is_collapsed():
    text = (
        "媒体：藏锋 (2026)\n"
        "状态：转存未完成\n"
        "原因：分享内有 14 个媒体/字幕文件无法解析集号，未标记为已处理；"
        "示例：01~4K.mp4、02~4K.mp4、03~4K.mp4；"
        "分享内有 13 个媒体/字幕文件无法解析集号，未标记为已处理；"
        "示例：01~4K.mp4、02~4K.mp4\n"
        "后续：保持转存路线，等待频道刷新或下次重试"
    )
    collapsed = compat.collapse_unparsed_failure_notice(text)
    assert collapsed.count("无法解析集号") == 1
    assert "分享内有 14 个" in collapsed
    assert "01~4K.mp4、02~4K.mp4、03~4K.mp4" in collapsed
    assert "后续：保持转存路线" in collapsed


def test_runtime_entry_installs_compat_patch_and_new_build():
    text = ENTRY.read_text(encoding="utf-8")
    assert "install_episode_filename_compat(_legacy_module)" in text
    assert "collapse_unparsed_failure_notice" in text
    assert 'build_id = "20260902-r20"' in text
