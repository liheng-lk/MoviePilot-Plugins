"""v2.1.6/r104 channel entry normalization regressions."""
from __future__ import annotations

import ast
import hashlib
import html
import re
import sys
import types
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urlparse, urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parents[3]
ENTRY_PATH = ROOT / "plugins.v3" / "guangyatransferassistant" / "__init__.py"
ENTRY = ENTRY_PATH.read_text(encoding="utf-8")


def _bundled(name: str) -> str:
    tree = ast.parse(ENTRY, filename=str(ENTRY_PATH))
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(target, ast.Name) and target.id == "_BUNDLED_SOURCES" for target in targets):
            return str(ast.literal_eval(node.value)[name])
    raise AssertionError("_BUNDLED_SOURCES missing")


def _legacy_helpers():
    source = _bundled("legacy")
    tree = ast.parse(source, filename="<legacy>")
    wanted_functions = {"_decode_url_layers", "_canonical_share_url", "_share_identity"}
    wanted_constants = {"CODE_PATTERN", "SHARE_PATTERN"}
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if names & wanted_constants:
                nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in wanted_functions:
            nodes.append(node)
    ns = {
        "Any": Any,
        "html": html,
        "re": re,
        "parse_qs": parse_qs,
        "unquote": unquote,
        "urlencode": urlencode,
        "urlsplit": urlsplit,
        "urlunsplit": urlunsplit,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<legacy-helpers>", "exec"), ns)
    return ns


def _resource_module():
    pkg = "_guangya_v216_contract"
    package = types.ModuleType(pkg)
    package.__path__ = []
    sys.modules[pkg] = package

    source_types = types.ModuleType(f"{pkg}.source_types_v180")

    def normalize_source_uri(uri: str):
        value = str(uri or "")
        if value.lower().startswith("magnet:"):
            matched = re.search(r"(?i)urn:btih:([0-9a-z]+)", value)
            return {"uri": value, "identity": matched.group(1).lower() if matched else value}
        if value.lower().startswith("ed2k:"):
            parts = value.split("|")
            return {"uri": value, "identity": parts[4].lower() if len(parts) >= 5 else value}
        return {"uri": value, "identity": value}

    source_types.normalize_source_uri = normalize_source_uri
    sys.modules[source_types.__name__] = source_types

    diag = types.ModuleType(f"{pkg}.transfer_diag_v209")
    diag.stable_trace_id = lambda *values: hashlib.sha1(
        "|".join(str(v or "") for v in values).encode("utf-8")
    ).hexdigest()[:20]
    sys.modules[diag.__name__] = diag

    legacy_ns = _legacy_helpers()
    legacy = types.ModuleType(f"{pkg}.legacy")
    legacy._canonical_share_url = legacy_ns["_canonical_share_url"]
    sys.modules[legacy.__name__] = legacy

    module = types.ModuleType(f"{pkg}.resource_inbox_v209")
    module.__package__ = pkg
    sys.modules[module.__name__] = module
    exec(compile(_bundled("resource_inbox_v209"), "<resource_inbox_v209>", "exec"), module.__dict__)
    return module


def test_guangya_subdomain_and_ui_params_canonicalize():
    inbox = _resource_module()
    rows = inbox.extract_message_resource_candidates_v209(
        "",
        "https://pan.guangyapan.com/s/SUBDOMAIN01?curGuildID=84560461773980088&darkmode=0#/share",
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["type"] == "guangya"
    assert row["identity"] == "SUBDOMAIN01"
    assert row["share_id"] == "SUBDOMAIN01"
    assert row["uri"] == "https://www.guangyapan.com/s/SUBDOMAIN01"
    assert "curGuildID" not in row["uri"]
    assert "darkmode" not in row["uri"]
    assert "#/share" not in row["uri"]


def test_guangya_bare_host_and_access_code_are_preserved():
    inbox = _resource_module()
    rows = inbox.extract_message_resource_candidates_v209(
        "",
        "www.guangyapan.com/s/BARE01?code=zz99&darkmode=1",
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["type"] == "guangya"
    assert row["identity"] == "BARE01"
    assert row["passcode"] == "zz99"
    assert row["uri"] == "https://www.guangyapan.com/s/BARE01?code=zz99"
    assert row["canonical_url"] == row["uri"]


def test_hidden_guangya_message_local_code_survives_legacy_bridge():
    inbox = _resource_module()
    html_value = (
        '<div data-clipboard-text="https://www.guangyapan.com/s/HIDDEN01">'
        "复制链接</div>"
    )
    text = "名称：隐藏资源(2026)\n提取码：ab12"
    row = inbox.build_inbox_row_from_message_block({
        "channel": "vip115hot",
        "source_url": "https://tgm.li668.asia/vip115hot",
        "message_id": "6000",
        "raw_html": html_value,
        "visible_text": text,
    })
    assert len(row["candidates"]) == 1
    candidate = row["candidates"][0]
    assert candidate["type"] == "guangya"
    assert candidate["extractor"] == "clipboard"
    assert candidate["passcode"] == "ab12"
    assert candidate["uri"].endswith("?code=ab12")
    entry = inbox.convert_inbox_row_to_entry(row)
    assert entry["share_id"] == "HIDDEN01"
    assert entry["share_code"] == "ab12"
    assert entry["passcode"] == "ab12"
    assert entry["share_url"].endswith("?code=ab12")


def test_mixed_channel_resources_have_fixed_execution_priority_and_115_is_diagnostic():
    inbox = _resource_module()
    e1 = "ed2k://|file|Demo.S01E01.1080p.mkv|111|AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA|/"
    e2 = "ed2k://|file|Demo.S01E01.2160p.mkv|222|BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB|/"
    text = (
        "名称：混合资源(2026)\n"
        "https://pan.xunlei.com/s/XL01?pwd=xy12\n"
        "https://www.guangyapan.com/s/GY01\n"
        "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567\n"
        f"{e1}\n{e2}\n"
        "https://115cdn.com/s/ONLY-DIAGNOSTIC"
    )
    bundle = inbox.extract_message_resources_bundle_v209("", text)
    kinds = [row["type"] for row in bundle["candidates"]]
    assert kinds == ["xunlei", "guangya", "magnet", "ed2k", "ed2k"]
    assert any(row.get("kind") == "115" for row in bundle["other_urls"])


def test_candidate_types_are_unique_even_with_multiple_ed2k():
    inbox = _resource_module()
    row = {
        "inbox_id": "g1",
        "resource_group_id": "g1",
        "channel": "regeng115",
        "source_url": "https://tgm.li668.asia/regeng115",
        "message_id": "10",
        "match_title": "Demo",
        "candidates": [
            {"type": "xunlei", "uri": "https://pan.xunlei.com/s/XL", "identity": "XL", "passcode": ""},
            {"type": "ed2k", "uri": "ed2k://|file|A.mkv|1|AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA|/", "identity": "a" * 32},
            {"type": "ed2k", "uri": "ed2k://|file|B.mkv|2|BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB|/", "identity": "b" * 32},
        ],
    }
    entry = inbox.convert_inbox_row_to_entry(row)
    assert entry["candidate_types"] == ["xunlei", "ed2k"]
    assert len(entry["external_sources"]) == 2


def test_passcode_never_crosses_message_boundary():
    inbox = _resource_module()
    first = inbox.build_inbox_row_from_message_block({
        "channel": "vip115hot",
        "source_url": "https://tgm.li668.asia/vip115hot",
        "message_id": "1",
        "raw_html": "<div>迅雷：https://pan.xunlei.com/s/NO-CODE</div>",
        "visible_text": "迅雷：https://pan.xunlei.com/s/NO-CODE",
    })
    second = inbox.build_inbox_row_from_message_block({
        "channel": "vip115hot",
        "source_url": "https://tgm.li668.asia/vip115hot",
        "message_id": "2",
        "raw_html": "<div>密码：abcd</div>",
        "visible_text": "密码：abcd",
    })
    assert first["candidates"][0]["passcode"] == ""
    assert second["candidates"] == []


def test_legacy_canonicalizer_keeps_only_access_parameters():
    legacy = _legacy_helpers()
    canonical = legacy["_canonical_share_url"](
        "https://foo.guangyapan.com/s/LEGACY01?curGuildID=123&darkmode=0&code=qwer#/share"
    )
    assert canonical == "https://www.guangyapan.com/s/LEGACY01?code=qwer"
    assert legacy["_share_identity"](canonical) == "LEGACY01|qwer"


def test_release_marker_v216_r104():
    assert 'plugin_version = "2.1.6"' in ENTRY[ENTRY.rindex("\nclass GuangYaTransferAssistant("):]
    assert 'build_id = "20260915-r104"' in ENTRY[ENTRY.rindex("\nclass GuangYaTransferAssistant("):]
