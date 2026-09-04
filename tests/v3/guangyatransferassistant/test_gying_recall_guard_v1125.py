from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
GUARD = PLUGIN / "gying_recall_guard_v1125.py"
IDENTITY = PLUGIN / "media_identity_guard_v1111.py"
ENTRY = PLUGIN / "__init__.py"

guard_text = GUARD.read_text(encoding="utf-8")
identity_text = IDENTITY.read_text(encoding="utf-8")
entry_text = ENTRY.read_text(encoding="utf-8")


def _method(name: str, next_name: str | None = None) -> str:
    start = guard_text.index(f"    def {name}(")
    if next_name:
        return guard_text[start:guard_text.index(f"    def {next_name}(", start)]
    return guard_text[start:]


def test_recall_guard_parses_and_is_cooperative_above_existing_hardening():
    ast.parse(guard_text, filename=str(GUARD))
    ast.parse(identity_text, filename=str(IDENTITY))
    ast.parse(entry_text, filename=str(ENTRY))
    assert "class GuangYaGyingRecallGuardV1125Mixin:" in guard_text
    assert "GuangYaGyingHardeningMixin," not in guard_text
    assert 'build_id = "20260904-r51-preview"' in guard_text
    start = entry_text.index("class GuangYaTransferAssistant(")
    identity = entry_text.index("GuangYaMediaIdentityGuardV1111Mixin,", start)
    guard = entry_text.index("GuangYaGyingRecallGuardV1125Mixin,", start)
    hardening = entry_text.index("GuangYaGyingHardeningMixin,", start)
    runtime = entry_text.index("GuangYaGyingRuntimeMixin,", start)
    assert identity < guard < hardening < runtime


def test_recall_guard_reuses_single_media_identity_authority_instead_of_copying_rules():
    assert "def _provider_candidate_matches(" in identity_text
    assert "strong_title_match_v1111" in identity_text
    assert "explicit_years_v1111" in identity_text
    assert "explicit_seasons_v1111" in identity_text
    assert "def _provider_candidate_matches(" not in guard_text
    search = _method("_search_viewing_xunlei")
    assert "self._provider_candidate_matches(subscribe, row)" in search
    assert "不在这里重写标题/年份/季号规则" in search


def test_explicit_old_episode_cannot_stop_fallback_but_unknown_pack_can():
    cover = _method("_candidate_can_cover_missing_v1125", "_search_viewing_xunlei")
    assert "explicit = self._candidate_episode_hint_v1125" in cover
    assert "return not explicit or bool(explicit.intersection(missing))" in cover
    hint = _method("_candidate_episode_hint_v1125", "_candidate_can_cover_missing_v1125")
    assert "resolve_episode" in hint
    assert "reliable_episode_set" in hint


def test_fallback_stops_only_after_media_and_missing_coverage_filter():
    search = _method("_search_viewing_xunlei")
    media_filter = search.index("self._provider_candidate_matches(subscribe, row)")
    coverage_filter = search.index("self._candidate_can_cover_missing_v1125(subscribe, row, missing)")
    stop = search.index("if matched:")
    assert media_filter < coverage_filter < stop
    assert "for variant in variants:" in search
    assert "_gying_xunlei_precise_variant_v1125(variant)" in search
    assert "_xunlei_candidate_priority_v1125" in search
    assert "query_fallback" in search


def test_recall_guard_does_not_reimplement_xunlei_transfer_or_local_downloader():
    lowered = guard_text.lower()
    for forbidden in (
        "downloadchain(",
        "from app.chain.download",
        "qbittorrent",
        "transmission",
        "aria2",
        "_xunlei_share_info(",
        "_xunlei_import_json_batch",
        "cloudcollection",
    ):
        assert forbidden not in lowered
