from __future__ import annotations

import json
from pathlib import Path

from source_helper import single_init_plugin_path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = single_init_plugin_path(ROOT / "plugins.v3" / "shukguangyadisk")
ADAPTER = (PLUGIN / "organizer_episode_name_adapter_v3411.py").read_text(encoding="utf-8")
MPCTX = (PLUGIN / "organizer_mp_folder_context_v346.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")


def test_v3917_standard_sxe_skips_episode_format():
    for token in (
        "native_sxe_no_epformat",
        'kwargs.pop("epformat", None)',
        'token.family == "sxe"',
        "标准 SxxExxx 使用 MoviePilot 原生解析",
    ):
        assert token in ADAPTER or token in MPCTX, token
    assert "_all_members_have_native_sxe" in MPCTX
    assert "recommend_episode_format" in MPCTX


def test_v3917_same_start_and_end_is_not_kept_as_range():
    assert "if episode_end == parsed_start:" in ADAPTER
    assert "episode_end = None" in ADAPTER
    assert "if episode_end == token.start:" in ADAPTER


def test_v3917_user_cases_are_covered_by_native_sxe_contract():
    assert "_STANDARD_SXE_NAME_RE" in MPCTX
    assert "S01E02" in "明明已经杀了丈夫 - S01E02 - 只有我能做到的杀夫方法 - WEB-DL 1080p - H264 - MWeb.mkv"
    assert "S01E181" in "遮天 - S01E181 - 雪园战天凤 - WEB-DL 2160p - H265 - ADWeb.mkv"


def test_v3917_versions_are_synchronized():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["ShukGuangYaDisk"]
    plugin = json.loads((ROOT / "plugins.v3/shukguangyadisk/plugin.json").read_text(encoding="utf-8"))
    remote = (ROOT / "plugins.v3/shukguangyadisk/dist/assets/remoteEntry.js").read_text(encoding="utf-8")
    assert package["version"] == "3.9.17"
    assert plugin["version"] == "3.9.17"
    assert 'plugin_version = "3.9.17"' in ENTRY
    assert "v=3.9.17" in remote
