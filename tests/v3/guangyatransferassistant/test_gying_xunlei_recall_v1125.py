from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
HARDENING = PLUGIN / "gying_hardening_v193.py"
ENTRY = PLUGIN / "__init__.py"

text = HARDENING.read_text(encoding="utf-8")
entry = ENTRY.read_text(encoding="utf-8")


def _rank_namespace():
    tree = ast.parse(text, filename=str(HARDENING))
    wanted = {
        "_gying_rank_text_v1125",
        "_gying_query_identity_v1125",
        "_gying_card_score_v1125",
        "rank_gying_cards_v1125",
    }
    body = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            node.returns = None
            for arg in node.args.args:
                arg.annotation = None
            body.append(node)
    module = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(module)
    ns = {
        "re": re,
        "Any": Any,
        "Dict": Dict,
        "Iterable": Iterable,
        "List": List,
        "Tuple": Tuple,
    }
    exec(compile(module, str(HARDENING), "exec"), ns)
    return ns


def test_v1125_hardening_parses_without_changing_public_release_marker():
    ast.parse(text, filename=str(HARDENING))
    assert 'build_id = "20260904-r51-preview"' in text
    assert 'plugin_version = "1.12.4"' in entry
    assert 'build_id = "20260904-r50"' in entry


def test_search_cards_are_ranked_before_existing_detail_request_limit():
    method = text.split("    def _gying_xunlei_precise_variant_v1125", 1)[1].split(
        "    @staticmethod\n    def _xunlei_candidate_priority_v1125", 1
    )[0]
    assert "ranked_cards = rank_gying_cards_v1125(keyword, cards)" in method
    assert "detail_cards = ranked_cards[:detail_limit]" in method
    assert "detail_limit = max(1, min(int(getattr(self, \"_provider_result_limit\", 20) or 20), 100))" in method
    assert "for item in cards[:" not in method


def test_rank_moves_target_beyond_first_twenty_to_front():
    rank = _rank_namespace()["rank_gying_cards_v1125"]
    cards = [
        {"title": f"无关剧集 {index}", "year": "2026", "type": "tv", "id": str(index)}
        for index in range(25)
    ]
    cards.append({"title": "完美世界", "year": "2021", "info": "S01", "type": "tv", "id": "target"})
    ranked = rank("完美世界 2021 S01", cards)
    assert ranked[0]["id"] == "target"


def test_one_downurl_response_keeps_more_than_generic_twenty_xunlei_candidates():
    assert "def _xunlei_candidates_from_rows_v1125" in text
    precise = text.split("    def _gying_xunlei_precise_variant_v1125", 1)[1].split(
        "    @staticmethod\n    def _xunlei_candidate_priority_v1125", 1
    )[0]
    assert "xunlei_limit = max(40, min(120" in precise
    assert "* 4" in precise
    assert "_xunlei_candidates_from_rows_v1125(deduped, limit=xunlei_limit)" in precise


def test_xunlei_keyword_fallback_is_subscription_aware_not_card_count_aware():
    method = text.split("    def _search_viewing_xunlei(self, keyword: str):", 1)[1].split(
        "    def _dispatch_xunlei_flash", 1
    )[0]
    assert "variants = gying_keyword_variants(keyword)" in method
    assert "for variant in variants:" in method
    assert "self._provider_candidate_matches(subscribe, row)" in method
    assert "if matched:" in method
    assert "query_fallback" in method
    assert "cards" not in method.split("if matched:", 1)[0].split("for variant in variants:", 1)[1]


def test_xunlei_candidates_cover_real_missing_episode_first():
    priority = text.split("    def _xunlei_candidate_priority_v1125", 1)[1].split(
        "    def _search_viewing_xunlei", 1
    )[0]
    search = text.split("    def _search_viewing_xunlei(self, keyword: str):", 1)[1].split(
        "    def _dispatch_xunlei_flash", 1
    )[0]
    assert "resolve_episode" in priority
    assert "reliable_episode_set" in priority
    assert "episodes.intersection(missing)" in priority
    assert "self._subscription_missing_episodes(subscribe)" in search
    assert "matched.sort(key=lambda row: self._xunlei_candidate_priority_v1125" in search


def test_precise_xunlei_results_are_reused_by_later_magnet_search():
    precise = text.split("    def _gying_xunlei_precise_variant_v1125", 1)[1].split(
        "    @staticmethod\n    def _xunlei_candidate_priority_v1125", 1
    )[0]
    assert 'self._gying_search_cache[keyword] = {"ts": time.time(), "rows": deduped, "state": state}' in precise
    assert "recall_ranked_v1125" in precise


def test_subscription_context_is_thread_local_and_transfer_chain_is_not_reimplemented():
    dispatch = text.split("    def _dispatch_xunlei_flash(self, subscribe: Any)", 1)[1].split(
        "    @staticmethod\n    def _provider_candidate_matches", 1
    )[0]
    assert "threading.local()" in dispatch
    assert "context.subscribe = subscribe" in dispatch
    assert "return super()._dispatch_xunlei_flash(subscribe)" in dispatch
    lowered = text.lower()
    for forbidden in (
        "downloadchain(",
        "from app.chain.download",
        "qbittorrent",
        "transmission",
        "aria2",
    ):
        assert forbidden not in lowered
