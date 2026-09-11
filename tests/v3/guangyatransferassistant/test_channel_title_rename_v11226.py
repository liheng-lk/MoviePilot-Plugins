from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
FAST = (PLUGIN / "fast_recall_v1126.py").read_text(encoding="utf-8")
MODULE = PLUGIN / "channel_title_rename_v11226.py"
MODULE_TEXT = MODULE.read_text(encoding="utf-8")
LOCAL = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
PACKAGE = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]


def test_v11226_release_metadata_and_mro():
    assert LOCAL["version"] == PACKAGE["version"] == "2.0.9"
    assert 'plugin_version = "2.0.9"' in ENTRY
    assert "v2.0.8" in PACKAGE["history"]
    assert "v2.0.9" in PACKAGE["history"]
    assert "install_channel_title_rename_v11226" in ENTRY
    class_head = FAST.split("class GuangYaFastRecallV1126Mixin(", 1)[1].split("):", 1)[0]
    assert class_head.index("GuangYaChannelTitleRenameV11226Mixin") < class_head.index(
        "GuangYaAutoRecoveryV11224Mixin"
    )


def _load_helpers():
    # Provide a tiny stub for legacy helpers imported by the module.
    legacy = SimpleNamespace(
        _episode_numbers=None,
        _is_subtitle=lambda path: str(path).lower().endswith((".srt", ".ass", ".ssa")),
        _is_video=lambda path: str(path).lower().endswith((".mkv", ".mp4", ".ts")),
        _safe_relative_path=lambda value: str(value or "").strip("/"),
    )

    def episode_numbers(path):
        text = str(path or "")
        matched = re.search(
            r"(?i)S(\d{1,2})E(\d{1,4})(?:\s*[-~]\s*E?(\d{1,4}))?",
            text,
        )
        if not matched:
            return None, []
        season = int(matched.group(1))
        start = int(matched.group(2))
        end = int(matched.group(3) or start)
        return season, list(range(start, end + 1))

    legacy._episode_numbers = episode_numbers
    sys.modules["plugins.v3.guangyatransferassistant.legacy"] = legacy  # type: ignore
    # Load functions without importing the full package tree.
    tree = ast.parse(MODULE_TEXT, filename=str(MODULE))
    wanted = {
        "_safe_name_v11226",
        "_show_name_v11226",
        "_split_name_ext_v11226",
        "_episode_tag_v11226",
        "_canonical_transfer_name_v11226",
        "_clean_channel_title_v11226",
        "_extract_channel_title_v11226",
    }
    nodes = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.Assign))
        and (
            (isinstance(node, ast.FunctionDef) and node.name in wanted)
            or (
                isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id.startswith("_") for t in node.targets)
            )
        )
    ]
    # Keep regex constants too.
    const_nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id.endswith("_V11226") for t in node.targets)
    ]
    module = ast.Module(body=const_nodes + [n for n in nodes if isinstance(n, ast.FunctionDef)], type_ignores=[])
    namespace = {
        "Any": object,
        "Dict": dict,
        "Iterable": object,
        "List": list,
        "Optional": object,
        "Tuple": tuple,
        "Path": Path,
        "html": __import__("html"),
        "re": re,
        "functools": __import__("functools"),
        "_episode_numbers": episode_numbers,
        "_is_subtitle": legacy._is_subtitle,
        "_is_video": legacy._is_video,
        "_safe_relative_path": legacy._safe_relative_path,
    }
    exec(compile(module, str(MODULE), "exec"), namespace)
    return namespace


def test_v11226_channel_titles_strip_template_noise():
    helpers = _load_helpers()
    clean = helpers["_clean_channel_title_v11226"]
    extract = helpers["_extract_channel_title_v11226"]
    assert clean("囧徒之预演告别(2026） 4K 更新至11集") == "囧徒之预演告别"
    assert clean("幸运女神(2026)【更07集】【4K.HDR10+】") == "幸运女神"
    assert clean("[剧集·光鸭] 侠探杰克 (2022)") == "侠探杰克"
    assert extract("名称：师兄太稳健 (2026)剧情 奇幻 古装 4K 全30集", lambda _: "") == "师兄太稳健"
    assert extract("[剧集·光鸭] 灵境行者 (2026)\nTMDB: 297923", lambda _: "") == "灵境行者"


def test_v11226_transfer_name_is_show_plus_season_episode():
    helpers = _load_helpers()
    name = helpers["_canonical_transfer_name_v11226"]
    tv = SimpleNamespace(name="幸运女神", season=1, year=2026)
    movie = SimpleNamespace(name="沙丘 (2021)", season=None, year=2021)
    assert name(tv, "Show.S01E07.2160p.mkv", is_movie=False) == "幸运女神 S01E07.mkv"
    assert name(tv, "Show.S01E01-E07.mkv", is_movie=False) == "幸运女神 S01E01-E07.mkv"
    assert name(movie, "Dune.2021.2160p.mkv", is_movie=True) == "沙丘.mkv"
