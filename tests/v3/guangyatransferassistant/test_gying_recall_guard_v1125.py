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
    search = _method("_search_viewing_xunlei", "_merge_xunlei_rounds_v1125")
    assert "self._provider_candidate_matches(subscribe, row)" in search
    assert "不在这里重写标题/年份/季号规则" in search


def test_explicit_old_episode_cannot_stop_fallback_but_unknown_pack_can():
    cover = _method("_candidate_can_cover_missing_v1125", "_promote_search_bundle_v1125")
    assert "explicit = self._candidate_episode_hint_v1125" in cover
    assert "return not explicit or bool(explicit.intersection(missing))" in cover
    hint = _method("_candidate_episode_hint_v1125", "_candidate_can_cover_missing_v1125")
    assert "resolve_episode" in hint
    assert "reliable_episode_set" in hint


def test_bundle_contains_only_real_successful_cache_entries_and_preserves_request_time():
    bundle = _method("_promote_search_bundle_v1125", "_search_viewing_xunlei")
    assert 'entry = dict(cache.get(variant) or {})' in bundle
    assert "if not entry:" in bundle
    assert 'state.get("success") is False' in bundle
    assert "valid_variants.append(variant)" in bundle
    assert 'key = (url, passcode)' in bundle
    assert '"bundle_variants": valid_variants' in bundle
    assert '"rows": merged[:800]' in bundle
    assert '"ts": latest_ts or time.time()' in bundle
    assert "max(time.time(), latest_ts)" not in bundle


def test_no_xunlei_match_still_promotes_successful_wide_queries_for_magnet():
    search = _method("_search_viewing_xunlei", "_merge_xunlei_rounds_v1125")
    assert "successful: List[str] = []" in search
    assert "successful.append(variant)" in search
    assert "bundle_variants = [all_variants[0], *successful] if start_index else successful" in search
    assert "self._promote_search_bundle_v1125(all_variants[0], bundle_variants)" in search
    assert 'last_state["searched_variants"] = list(successful)' in search


def test_failed_wide_query_does_not_claim_nonexistent_bundle_variant():
    search = _method("_search_viewing_xunlei", "_merge_xunlei_rounds_v1125")
    failure = search.split('if not last_state.get("success"):', 1)[1].split("successful.append(variant)", 1)[0]
    assert "retry_local.stop_after_failure = True" in failure
    assert "bundle_variants" in failure
    assert "self._promote_search_bundle_v1125(all_variants[0], bundle_variants)" in failure
    assert "successful.append(variant)" not in failure


def test_retry_mode_skips_already_attempted_share_ids_without_persisting_them():
    search = _method("_search_viewing_xunlei", "_merge_xunlei_rounds_v1125")
    assert 'seen_identities = set(getattr(retry_local, "seen_identities", set()) or set())' in search
    assert 'identity = str((row or {}).get("share_id") or (row or {}).get("identity") or "").strip()' in search
    assert "if identity and identity in seen_identities:" in search
    assert "seen_identities.add(identity)" in search
    assert "retry_local.seen_identities = seen_identities" in search
    assert "save_data" not in search


def test_real_xunlei_failure_advances_to_next_keyword_only_after_dispatch_returns():
    dispatch = _method("_dispatch_xunlei_flash", "_dispatch_viewing_external_v1113")
    lower_call = dispatch.index("super()._dispatch_xunlei_flash(subscribe)")
    merge = dispatch.index("_merge_xunlei_rounds_v1125", lower_call)
    handled = dispatch.index('combined.get("handled")', merge)
    failure_stop = dispatch.index('getattr(local, "stop_after_failure", False)', handled)
    next_index = dispatch.index("next_index = last_index + 1", failure_stop)
    advance = dispatch.index("local.start_index = next_index", next_index)
    assert lower_call < merge < handled < failure_stop < next_index < advance
    assert "while True:" in dispatch
    assert "next_index >= len(all_variants)" in dispatch
    assert "local.seen_identities = set()" in dispatch


def test_partial_xunlei_rounds_merge_success_episode_and_errors_without_losing_first_round():
    merge = _method("_merge_xunlei_rounds_v1125", "_dispatch_xunlei_flash")
    assert 'for key in ("shares", "attempted_files", "successful_files")' in merge
    assert 'merged["success"] = bool((base or {}).get("success")) or bool((extra or {}).get("success"))' in merge
    assert 'merged["handled"] = bool((base or {}).get("handled")) or bool((extra or {}).get("handled"))' in merge
    assert 'merged["episodes"] = sorted(episodes)' in merge
    assert 'merged["errors"] = [' in merge


def test_magnet_broadening_waits_for_actual_dispatch_miss_not_candidate_presence():
    method = _method("_dispatch_viewing_external_v1113")
    first_dispatch = method.index("super()._dispatch_viewing_external_v1113(subscribe)")
    first_stop = method.index('if bool(result.get("success")) or list(result.get("actions") or []):')
    strict_cache = method.index("strict_entry =", first_stop)
    broaden = method.index("for variant in variants[1:]:", strict_cache)
    second_dispatch = method.index("super()._dispatch_viewing_external_v1113(subscribe)", first_dispatch + 1)
    action_stop = method.index('if bool(current.get("success")) or list(current.get("actions") or []):', second_dispatch)
    assert first_dispatch < first_stop < strict_cache < broaden < second_dispatch < action_stop
    assert "def _viewing_external_candidates_v1113" not in guard_text


def test_magnet_broadening_requires_successful_strict_search_and_stops_on_wide_search_failure():
    method = _method("_dispatch_viewing_external_v1113")
    assert 'if not strict_entry or strict_state.get("success") is False:' in method
    failure = method.split('if not state.get("success"):', 1)[1].split("attempted.append(variant)", 1)[0]
    assert "return last_result" in failure
    assert "attempted.append(variant)" not in failure
    assert "_promote_search_bundle_v1125(variants[0], attempted)" in method


def test_fallback_stops_only_after_media_and_missing_coverage_filter():
    search = _method("_search_viewing_xunlei", "_merge_xunlei_rounds_v1125")
    media_filter = search.index("self._provider_candidate_matches(subscribe, row)")
    coverage_filter = search.index("self._candidate_can_cover_missing_v1125(subscribe, row, missing)")
    stop = search.index("if matched:")
    assert media_filter < coverage_filter < stop
    assert "for relative_index, variant in enumerate(variants):" in search
    assert "_gying_xunlei_precise_variant_v1125(variant)" in search
    assert "_xunlei_candidate_priority_v1125" in search
    assert "query_fallback" in search


def test_recall_guard_does_not_reimplement_xunlei_share_protocol_or_local_downloader():
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
