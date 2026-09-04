from __future__ import annotations

import ast
import re
from pathlib import Path
from urllib.parse import urlparse, urlunparse


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = PLUGIN / "__init__.py"
HARDENING = PLUGIN / "gying_hardening_v193.py"

entry_text = ENTRY.read_text(encoding="utf-8")
text = HARDENING.read_text(encoding="utf-8")


def _pure_namespace():
    tree = ast.parse(text, filename=str(HARDENING))
    body = []
    wanted = {"canonical_gying_node", "gying_keyword_variants"}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            node.returns = None
            for arg in node.args.args:
                arg.annotation = None
            body.append(node)
    module = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(module)
    ns = {"re": re, "urlparse": urlparse, "urlunparse": urlunparse, "List": list}
    exec(compile(module, str(HARDENING), "exec"), ns)
    return ns


def test_gying_hardening_parses_and_is_final_node_layer():
    ast.parse(text, filename=str(HARDENING))
    start = entry_text.index("class GuangYaTransferAssistant")
    order = ["GuangYaConfigUiMixin,", "GuangYaGyingHardeningMixin,", "GuangYaGyingFailoverMixin,", "GuangYaGyingRuntimeMixin,", "GuangYaXunleiHardeningMixin,", "GuangYaXunleiFlashMixin,"]
    positions = [entry_text.index(token, start) for token in order]
    assert positions == sorted(positions)
    assert 'build_id = "20260905-r55"' in entry_text


def test_unicode_and_punycode_are_one_node_identity():
    canonical = _pure_namespace()["canonical_gying_node"]
    unicode_node = canonical("https://www.星际穿越.com/a?q=1")
    puny_node = canonical("https://www.xn--kivn76b41nnhi.com/")
    assert unicode_node == puny_node == "https://www.xn--kivn76b41nnhi.com"
    assert canonical("https://user:pass@example.com") == ""
    assert canonical("http://127.0.0.1:8888") == ""


def test_current_content_node_is_seed_not_fixed_single_endpoint():
    assert 'CURRENT_CONTENT_SEEDS = (' in text
    assert '"https://www.星际穿越.com"' in text
    assert "*CURRENT_CONTENT_SEEDS" in text
    assert "*base" in text
    assert "_viewing_registry_urls" not in text or "_discover_gying_nodes" in text


def test_configured_cookie_never_follows_automatic_cross_domain_failover():
    session = text.split("    def _gying_new_session(", 1)[1].split("    def _gying_request", 1)[0]
    assert "configured_cookie and preferred and node == preferred" in session
    assert "_apply_cookie_header(session, saved_cookie)" in session
    assert "_apply_cookie_header(session, configured_cookie)" in session


def test_gying_query_falls_back_from_season_and_year_to_title():
    variants = _pure_namespace()["gying_keyword_variants"]
    assert variants("Demo Show 2024 S01") == ["Demo Show 2024 S01", "Demo Show 2024", "Demo Show"]
    assert variants("Demo Show S02") == ["Demo Show S02", "Demo Show"]
    assert variants("Demo Show") == ["Demo Show"]
    runtime = text.split("    def _gying_raw_results(", 1)[1].split("    @staticmethod\n    def _provider_candidate_matches", 1)[0]
    assert "if int(state.get(\"cards\") or 0) > 0 or rows" in runtime
    assert 'last_state["query_fallback"] = variant' in runtime


def test_candidate_title_match_is_year_aware_when_both_years_exist():
    method = text.split("    def _provider_candidate_matches", 1)[1]
    assert "expected_year and actual_year and expected_year != actual_year" in method
    assert "return False" in method


def test_fake_404_or_angie_page_causes_node_failover():
    assert '"Angie"' in text
    request = text.split("    def _gying_request(", 1)[1].split("    def _gying_raw_results", 1)[0]
    assert "response.status_code in {403, 404}" in request
    assert "观影节点当前出口被阻断" in request
