"""Unified transfer routing and MP-priority naming contracts."""

from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ENTRY_PATH = ROOT / "plugins.v3" / "guangyatransferassistant" / "__init__.py"
ENTRY = ENTRY_PATH.read_text(encoding="utf-8")

_REQUIRED_FUNCTIONS = {
    "_normalize_unified_resource_candidate",
    "_unified_transfer_route_name",
    "_extract_transfer_technical_tags",
    "_format_mp_transfer_name",
}
_REQUIRED_CONSTANTS = {
    "_UNIFIED_TRANSFER_ROUTES",
    "_UNIFIED_SOURCE_PRIORITY",
}


def _load_helpers():
    tree = ast.parse(ENTRY, filename=str(ENTRY_PATH))
    body = []
    found_functions = set()
    found_constants = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in _REQUIRED_FUNCTIONS:
            body.append(node)
            found_functions.add(node.name)
            continue
        if isinstance(node, ast.Assign):
            names = {
                target.id for target in node.targets
                if isinstance(target, ast.Name)
            }
            if names.intersection(_REQUIRED_CONSTANTS):
                body.append(node)
                found_constants.update(names.intersection(_REQUIRED_CONSTANTS))
    assert found_functions == _REQUIRED_FUNCTIONS
    assert found_constants == _REQUIRED_CONSTANTS
    module = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"re": re}
    exec(compile(module, str(ENTRY_PATH), "exec"), namespace)
    return namespace


def test_four_resource_types_use_one_execution_contract():
    ns = _load_helpers()
    normalize = ns["_normalize_unified_resource_candidate"]
    route = ns["_unified_transfer_route_name"]

    cases = [
        (
            {"url": "https://pan.xunlei.com/s/VP-demo?pwd=abcd"},
            "xunlei",
            "xunlei_json_flash",
            0,
        ),
        (
            {"share_url": "https://www.guangyapan.com/s/demo?code=1234"},
            "guangya",
            "guangya_share_restore",
            1,
        ),
        (
            {"uri": "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"},
            "magnet",
            "cloudcollection",
            2,
        ),
        (
            {"uri": "ed2k://|file|Demo.S01E01.mkv|123456|0123456789abcdef0123456789abcdef|/"},
            "ed2k",
            "cloudcollection",
            3,
        ),
    ]

    for raw, expected_type, expected_route, expected_priority in cases:
        for origin in ("telegram", "gying"):
            row = normalize(raw, origin=origin)
            assert row["type"] == expected_type
            assert row["route"] == expected_route
            assert row["priority"] == expected_priority
            assert row["origin"] == origin
            assert route(expected_type) == expected_route


def test_unknown_pan_link_is_not_misrouted():
    ns = _load_helpers()
    normalize = ns["_normalize_unified_resource_candidate"]
    row = normalize({"url": "https://115.com/s/not-guangya"}, origin="gying")
    assert row["type"] == ""
    assert row["route"] == ""
    assert row["priority"] == 99


def test_mp_priority_tv_name_preserves_technical_tags():
    ns = _load_helpers()
    format_name = ns["_format_mp_transfer_name"]
    result = format_name(
        "幸运女神",
        2026,
        "幸运女神 S01E07.mkv",
        "Some.Show.2026.S01E07.2160p.WEB-DL.H265.DDP5.1.HDR10-GROUP.mkv",
        False,
    )
    assert result == "幸运女神 - S01E07 - 2160p WEB-DL H265 DDP5.1 HDR10 GROUP.mkv"


def test_mp_priority_movie_name_uses_mp_year_and_preserves_tags():
    ns = _load_helpers()
    format_name = ns["_format_mp_transfer_name"]
    result = format_name(
        "沙丘2",
        2024,
        "沙丘2.mkv",
        "Dune.Part.Two.2024.2160p.BluRay.REMUX.DV.HEVC.TrueHD.7.1-GROUP.mkv",
        True,
    )
    assert result == "沙丘2 (2024) - 2160p BluRay REMUX DV HEVC TrueHD 7.1 GROUP.mkv"


def test_name_without_technical_tags_stays_clean():
    ns = _load_helpers()
    format_name = ns["_format_mp_transfer_name"]
    result = format_name(
        "示例剧",
        2026,
        "示例剧 S01E02.mkv",
        "Example.Show.S01E02.mkv",
        False,
    )
    assert result == "示例剧 - S01E02.mkv"
