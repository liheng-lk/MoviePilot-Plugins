from __future__ import annotations

import ast
import html
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Sequence, Set
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
CORE = (PLUGIN / "core_pipeline_v11214.py").read_text(encoding="utf-8")
FINAL = (PLUGIN / "core_pipeline_final_v11214.py").read_text(encoding="utf-8")
CHANNEL = (PLUGIN / "channel_sources_v11214.py").read_text(encoding="utf-8")
CHANNEL_OLD = (PLUGIN / "channel_sources_v190.py").read_text(encoding="utf-8")
MANUAL = (PLUGIN / "manual_check_v11211.py").read_text(encoding="utf-8")
RECONCILE = (PLUGIN / "channel_reconcile_v11215.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
XUNLEI = (PLUGIN / "xunlei_existing_fence_v11213.py").read_text(encoding="utf-8")
VIEWING = (PLUGIN / "viewing_dispatch_v1113.py").read_text(encoding="utf-8")
PLANNER = (PLUGIN / "resource_planner_v190.py").read_text(encoding="utf-8")
MULTI = (PLUGIN / "multisource_v180.py").read_text(encoding="utf-8")
LEGACY = (PLUGIN / "legacy.py").read_text(encoding="utf-8")


def _exec_functions(source: str, names: set[str], namespace: dict) -> dict:
    tree = ast.parse(source)
    nodes = []
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = []
            if isinstance(node, ast.Assign):
                targets = [target.id for target in node.targets if isinstance(target, ast.Name)]
            elif isinstance(node.target, ast.Name):
                targets = [node.target.id]
            if any(name.startswith("_XUNLEI_") for name in targets):
                nodes.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            nodes.append(node)
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, "<v11214-contract>", "exec"), namespace)
    return namespace


class _FinalCoreBase:
    @staticmethod
    def _direct_share_primary_roots_v11214(paths: Sequence[str], expected_year: Any = None) -> List[str]:
        return []


def _exec_final_mixin():
    tree = ast.parse(FINAL, filename=str(PLUGIN / "core_pipeline_final_v11214.py"))
    nodes = []
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = []
            if isinstance(node, ast.Assign):
                targets = [target.id for target in node.targets if isinstance(target, ast.Name)]
            elif isinstance(node.target, ast.Name):
                targets = [node.target.id]
            if any(name.startswith("_ACTUAL_") or name.startswith("_GENERIC_ACTUAL_") for name in targets):
                nodes.append(node)
        elif isinstance(node, ast.ClassDef) and node.name == "GuangYaCorePipelineFinalV11214Mixin":
            nodes.append(node)
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)

    def positive(values):
        result = set()
        for raw in values or []:
            try:
                value = int(raw or 0)
            except (TypeError, ValueError):
                continue
            if value > 0:
                result.add(value)
        return result

    def title_key(value, expected_year=None):
        text = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", str(value or "")).casefold()
        year = str(expected_year or "")
        if year:
            text = text.replace(year.casefold(), "")
        return text

    ns = {
        "re": re,
        "Any": Any,
        "List": List,
        "Sequence": Sequence,
        "Set": Set,
        "GuangYaCorePipelineV11214Mixin": _FinalCoreBase,
        "_positive_episode_set_v11214": positive,
        "title_key_v1111": title_key,
    }
    exec(compile(module, str(PLUGIN / "core_pipeline_final_v11214.py"), "exec"), ns)
    return ns["GuangYaCorePipelineFinalV11214Mixin"]


def test_v11214_sources_parse_and_nesting_does_not_move_top_level_mro():
    for path in (
        PLUGIN / "core_pipeline_v11214.py",
        PLUGIN / "core_pipeline_final_v11214.py",
        PLUGIN / "channel_sources_v11214.py",
        PLUGIN / "manual_check_v11211.py",
        PLUGIN / "channel_reconcile_v11215.py",
    ):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    head = ENTRY.split("class GuangYaTransferAssistant(", 1)[1].split("):", 1)[0]
    assert "GuangYaCorePipelineV11214Mixin" not in head
    assert "GuangYaCorePipelineFinalV11214Mixin" not in head
    assert "GuangYaManualCheckV11211Mixin(GuangYaChannelReconcileV11215Mixin)" in MANUAL
    assert "GuangYaChannelReconcileV11215Mixin(GuangYaCorePipelineFinalV11214Mixin)" in RECONCILE
    assert "GuangYaCorePipelineFinalV11214Mixin(GuangYaCorePipelineV11214Mixin)" in FINAL
    assert "GuangYaCorePipelineV11214Mixin(GuangYaXunleiExistingEpisodeFenceV11213Mixin)" in CORE


def test_channel_source_matrix_is_guangya_xunlei_magnet_ed2k():
    assert "_MAGNET_RE" in CHANNEL_OLD and "_ED2K_RE" in CHANNEL_OLD
    assert "xunlei_sources" in CHANNEL
    assert '"xunlei"' in CHANNEL
    assert 'ordered.append("guangya")' in CHANNEL
    assert "external_sources" in CHANNEL
    assert "candidate_types" in CHANNEL
    assert "install_channel_source_matrix_v11214(_legacy_module)" in MANUAL


def test_channel_xunlei_parser_keeps_share_and_same_message_passcode():
    ns = {
        "re": re,
        "html": html,
        "parse_qs": parse_qs,
        "urlsplit": urlsplit,
        "Any": Any,
        "Dict": Dict,
        "List": List,
    }
    _exec_functions(
        CHANNEL,
        {"_clean_xunlei_url_v11214", "_xunlei_channel_rows_v11214"},
        ns,
    )
    rows = ns["_xunlei_channel_rows_v11214"](
        '<div data-post="a/88">迅雷：https://pan.xunlei.com/s/VP-test-one?pwd=3y3x</div>'
    )
    assert len(rows) == 1
    assert rows[0]["share_id"] == "VP-test-one"
    assert rows[0]["passcode"] == "3y3x"
    assert rows[0]["type"] == "xunlei"

    rows = ns["_xunlei_channel_rows_v11214"](
        '<div>https://pan.xunlei.com/s/VP-test-two 提取码：ab12</div>'
    )
    assert rows[0]["share_id"] == "VP-test-two"
    assert rows[0]["passcode"] == "ab12"


def test_channel_xunlei_never_turns_passive_push_into_gying_poll():
    method = CORE.split("    def _search_viewing_xunlei(", 1)[1].split("    # ------------------------------------------------------------------", 1)[0]
    assert 'round_state.get("mode")' in method
    assert '== "channel_event"' in method
    assert "不主动访问 GYING" in method
    assert method.index('== "channel_event"') < method.rindex("return super()._search_viewing_xunlei(keyword)")


def test_gying_guangya_share_enters_direct_share_chain_without_persisting_channel_index():
    hydrate = CORE.split("    def _hydrate_viewing_guangya_shares_v11214(", 1)[1].split("    # ------------------------------------------------------------------", 1)[0]
    getter = CORE.split("    def get_data(", 1)[1].split("    def _route_mode_v11214", 1)[0]
    assert "_gying_raw_results" in hydrate
    assert "_provider_candidate_matches" in hydrate
    assert "_canonical_share_url" in hydrate
    assert '"provider://viewing"' in hydrate
    assert '"观影光鸭分享"' in hydrate
    assert "provider_share_entries" in hydrate
    assert "save_data(\"channel_index\"" not in hydrate
    assert 'str(key or "") != "channel_index"' in getter
    assert "provider_share_entries" in getter
    assert "_gying_alias_scope_v11212" in FINAL


def test_tv_exact_tmdb_aliases_are_season_aware_and_not_fuzzy():
    assert "MediaType.TV" in CORE
    assert "MediaSource.TMDB" in CORE
    assert "_tmdb_id_tv_v11214" in CORE
    assert "_tv_tmdb_aliases_v11214" in CORE
    alias_method = CORE.split("    def _gying_alias_keywords_v11212(", 1)[1].split("    # ------------------------------------------------------------------", 1)[0]
    assert "_tv_tmdb_aliases_v11214" in alias_method
    assert 'parts.append(f"S{season:02d}")' in alias_method
    assert "edit" not in alias_method.lower()
    assert "fuzzy" not in alias_method.lower()


def test_physical_file_must_be_complete_subset_not_merely_intersect_target():
    ns = {"Any": Any, "Iterable": Iterable, "Set": Set}
    _exec_functions(CORE, {"_positive_episode_set_v11214", "_physical_episode_subset_v11214"}, ns)
    allowed = {11}
    assert ns["_physical_episode_subset_v11214"]({11}, allowed) is True
    assert ns["_physical_episode_subset_v11214"]({9, 10, 11}, allowed) is False
    assert ns["_physical_episode_subset_v11214"]({9, 10}, allowed) is False
    assert ns["_physical_episode_subset_v11214"](set(), allowed) is False


def test_mixed_sources_only_allow_indivisible_files_fully_inside_e11_gap():
    ns = {"Any": Any, "Iterable": Iterable, "Set": Set}
    _exec_functions(CORE, {"_positive_episode_set_v11214", "_physical_episode_subset_v11214"}, ns)
    subset = ns["_physical_episode_subset_v11214"]
    allowed = {11}
    candidates = [
        ("xunlei", set(range(1, 13))),       # 一个不可分割的 E01-E12 文件/合辑
        ("guangya", {11}),                  # 精确单集
        ("magnet", {9, 10, 11, 12}),        # 一个不可分割的 E09-E12 文件
        ("ed2k", {11}),                     # 精确单集
    ]
    admissible = [source for source, physical in candidates if subset(physical, allowed)]
    assert admissible == ["guangya", "ed2k"]
    priority = {"xunlei": 0, "guangya": 1, "magnet": 2, "ed2k": 3}
    assert min(admissible, key=lambda source: priority[source]) == "guangya"


def test_authoritative_gap_is_library_intersection_logical_minus_reservations_and_other_claims():
    method = FINAL.split("    def _authoritative_missing_v11214(", 1)[1]
    assert "_sync_media_library_progress" in method
    assert "_base_missing_without_due_scope_v11213" in method
    assert "library_missing.intersection" in method
    assert "reservations" in method
    assert "_other_source_claims_v11214" in method
    assert "current_source_id=current_source_id" in method
    assert "fail closed" in method


def test_authoritative_gap_executes_as_library_and_logical_intersection_and_excludes_current_source():
    Mixin = _exec_final_mixin()

    class Probe(Mixin):
        def __init__(self):
            self.claim_calls = []

        @staticmethod
        def _is_movie_subscription(subscribe):
            return False

        @staticmethod
        def _sync_media_library_progress(subscribe):
            return {"success": True, "existing": list(range(1, 11)), "missing": [11, 12]}

        @staticmethod
        def _base_missing_without_due_scope_v11213(subscribe):
            return {10, 11, 12}

        @staticmethod
        def _pending_reservations(subscribe):
            return {"episodes": {12}}

        def _other_source_claims_v11214(self, sid, current_source_id=""):
            self.claim_calls.append((sid, current_source_id))
            return {10}

    subscribe = SimpleNamespace(id=501, type="TV")
    probe = Probe()
    assert probe._authoritative_missing_v11214(subscribe, current_source_id="magnet-current") == {11}
    assert probe.claim_calls == [(501, "magnet-current")]


def test_authoritative_gap_fails_closed_when_moviepilot_library_truth_is_unavailable():
    Mixin = _exec_final_mixin()

    class Probe(Mixin):
        @staticmethod
        def _is_movie_subscription(subscribe):
            return False

        @staticmethod
        def _sync_media_library_progress(subscribe):
            return {"success": False, "missing": [], "message": "library unavailable"}

    probe = Probe()
    try:
        probe._authoritative_missing_v11214(SimpleNamespace(id=502, type="TV"))
    except RuntimeError as err:
        assert "fail closed" in str(err)
        assert "library unavailable" in str(err)
    else:
        raise AssertionError("MoviePilot library truth failure must never fall back to a wider missing set")


def test_rootless_direct_share_uses_only_title_prefix_before_episode_marker():
    Mixin = _exec_final_mixin()
    assert Mixin._direct_share_primary_roots_v11214(["Other.Show.S01E11.mkv"], 2026) == ["Other.Show"]
    assert Mixin._direct_share_primary_roots_v11214(["S01E11.mkv"], 2026) == []
    assert Mixin._direct_share_primary_roots_v11214(["Show.Name.S01E11-GROUP.mkv"], 2026) == ["Show.Name"]


def test_direct_share_actual_content_and_physical_missing_are_final_gates():
    method = CORE.split("    def _plan_incremental_files(", 1)[1].split("    # ------------------------------------------------------------------\n    # Magnet", 1)[0]
    assert "assess_media_identity_v1111" in method
    assert 'assessment.get("hard_conflict")' in method
    assert "_authoritative_missing_v11214" in method
    assert "_physical_episode_subset_v11214" in method
    assert "光鸭分享拒绝不可分割文件" in method
    assert "safe_videos" in method
    assert "_ACTUAL_EP_MARKER_V11214" in FINAL


def test_magnet_and_ed2k_share_same_physical_final_fence():
    method = CORE.split("    def _resolve_offline_source(", 1)[1]
    assert "_authoritative_missing_v11214" in method
    assert "current_source_id=source_id" in method
    assert "_physical_episode_subset_v11214" in method
    assert "ED2K single-file" in method
    assert "safe_video_indexes" in method
    assert "解析成功但没有物理文件能够完整落在当前真实缺集集合内" in method
    assert 'result["selected_indexes"] = sorted(safe_indexes)' in method
    assert "resolved_episodes=sorted(safe_video_eps)" in method


def test_existing_xunlei_hard_fence_remains_below_unified_core():
    assert "GuangYaXunleiExistingEpisodeFenceV11213Mixin" in CORE
    assert "_filter_xunlei_import_indexes_v11213" in XUNLEI
    assert "issubset" in XUNLEI
    assert "E09-E11" in XUNLEI


def test_source_priority_and_short_circuit_contract_remain_unchanged():
    xunlei_flash = (PLUGIN / "xunlei_flash_v193.py").read_text(encoding="utf-8")
    assert "flash = self._dispatch_xunlei_flash(subscribe)" in xunlei_flash
    assert 'if flash.get("handled")' in xunlei_flash
    assert "lower = super()._try_transfer_subscription_inner" in xunlei_flash

    # Direct GuangYa share is always evaluated before channel Magnet/ED2K planner.
    planner_dispatch = PLANNER.split("    def _try_transfer_subscription_inner(", 1)[1].split("    # ------------------------------------------------------------------\n    # API", 1)[0]
    assert planner_dispatch.index("share_result = super()._try_transfer_subscription_inner") < planner_dispatch.index("_dispatch_channel_external_candidates")

    # Both GYING and channel fallback keep Magnet before ED2K, then stop when uncovered reaches zero.
    assert "executable.sort" in VIEWING
    assert '0 if str(row.get("type") or "") == "magnet" else 1' in VIEWING
    assert 'external.sort(key=lambda row: 0 if str(row.get("type") or "") == "magnet" else 1)' in PLANNER
    assert "if is_movie or not uncovered" in PLANNER


def test_every_storage_path_reuses_guangya_target_and_no_moviepilot_downloader():
    assert "target_path = self._target_path(subscribe)" in LEGACY
    assert "_offline_target_parent" in MULTI and "_target_path(subscribe)" in MULTI
    corpus = CORE + FINAL + CHANNEL
    for forbidden in ("DownloaderHelper", "download_transfer", "DownloadChain().download"):
        assert forbidden not in corpus


def test_current_public_release_is_v11214_after_full_gate_passes():
    assert 'plugin_version = "1.12.14"' in ENTRY
    assert 'build_id = "20260905-r60"' in ENTRY
    assert 'plugin_version = "1.12.14"' in CORE
    assert 'build_id = "20260905-r60"' in FINAL
