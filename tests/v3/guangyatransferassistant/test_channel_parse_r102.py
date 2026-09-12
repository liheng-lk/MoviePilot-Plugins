"""r102 real-log regression: forwarded channel titles + episode metadata."""
from __future__ import annotations

import ast
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
ENTRY_PATH = ROOT / "plugins.v3" / "guangyatransferassistant" / "__init__.py"
ENTRY = ENTRY_PATH.read_text(encoding="utf-8")


def _helpers():
    tree = ast.parse(ENTRY, filename=str(ENTRY_PATH))
    wanted_functions = {
        "_strip_forwarded_guangya_prefix_v214",
        "_normalize_channel_title_v214",
        "_install_channel_parse_compat_v214",
    }
    wanted_constants = {
        "_FORWARDED_GUANGYA_PREFIX_V214",
        "_FORWARD_EP_RANGE_V214",
        "_FORWARD_SEASON_EP_V214",
        "_FORWARD_UPDATED_TO_V214",
    }
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if names & wanted_constants:
                nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in wanted_functions:
            nodes.append(node)

    legacy = SimpleNamespace(
        _clean_channel_display_title=lambda value: str(value or ""),
        _extract_channel_display_title=lambda value: str(value or ""),
    )
    resource = SimpleNamespace(
        parse_message_title_metadata_v209=lambda value: {
            "raw_title": "",
            "match_title": "",
            "title_candidates": [],
            "season_hint": None,
            "episode_hint": "",
        }
    )
    channel = SimpleNamespace(
        _log_resource_discovery=lambda *args, **kwargs: None,
        _channel_slug_from_url=lambda value: "test",
    )
    ns = {
        "re": re,
        "Any": Any,
        "functools": __import__("functools"),
        "_legacy_module": legacy,
        "_resource_inbox_module": resource,
        "_channel_sources_module": channel,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ENTRY_PATH), "exec"), ns)
    ns["_install_channel_parse_compat_v214"]()
    return ns, legacy, resource


def test_forwarded_guangya_title_is_canonical():
    ns, legacy, resource = _helpers()
    raw = "光鸭云盘资源频道 Forwarded from 光鸭云盘资源频道 早春晴朗 NF"
    assert ns["_normalize_channel_title_v214"](raw) == "早春晴朗"
    assert legacy._clean_channel_display_title(raw) == "早春晴朗"
    meta = resource.parse_message_title_metadata_v209(raw + "\n更新至17集")
    assert meta["match_title"] == "早春晴朗"
    assert meta["title_candidates"][0] == "早春晴朗"
    assert meta["episode_hint"] == "E17"


def test_episode_range_recovers_season_and_full_range():
    _, _, resource = _helpers()
    meta = resource.parse_message_title_metadata_v209("[剧集·光鸭] 谜探路德维希 S02E01-E06")
    assert meta["season_hint"] == 2
    assert meta["episode_hint"] == "S02E01-E06"


def test_r102_parser_survives_r103_dispatch_release():
    assert "【光鸭转存助手】【媒体解析】title=%s season=%s episodes=%s" in ENTRY
    assert "【光鸭转存助手】【调度入口v2.1.5】source=manual_refresh" in ENTRY
    assert "【光鸭转存助手】【调度入口v2.1.5】source=tick" in ENTRY
    assert "【光鸭转存助手】【订阅调度v2.1.5】trigger=%s" in ENTRY
