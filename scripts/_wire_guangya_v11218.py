from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
TESTS = ROOT / "tests" / "v3" / "guangyatransferassistant"


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"{label} anchor missing: {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# 1) Preserve MovieIdentityV1129's historical class signature exactly.
# Insert v1.12.18 beneath the v1.12.16 bridge instead:
# MovieIdentity -> MovieBilingual -> CandidateRanking -> SearchRecall.
bilingual = PLUGIN / "movie_bilingual_identity_v11216.py"
replace_once(
    bilingual,
    "from .search_recall_v11217 import GuangYaSearchRecallV11217Mixin\n",
    "from .candidate_ranking_v11218 import GuangYaCandidateRankingV11218Mixin\n",
    "bilingual import",
)
replace_once(
    bilingual,
    "class GuangYaMovieBilingualIdentityV11216Mixin(GuangYaSearchRecallV11217Mixin):",
    "class GuangYaMovieBilingualIdentityV11216Mixin(GuangYaCandidateRankingV11218Mixin):",
    "bilingual base",
)

# 2) Candidate ranking must be hot-reload/isolated-test safe even when init_plugin
# has not yet created the per-subscription log throttle map.
ranking = PLUGIN / "candidate_ranking_v11218.py"
text = ranking.read_text(encoding="utf-8")
old = """        sid = int(getattr(subscribe, \"id\", 0) or 0)\n        now = time.time()\n        last = float(getattr(self, \"_candidate_rank_log_at_v11218\", {}).get(sid, 0) or 0)\n        if last and now - last < self._candidate_rank_log_interval_v11218:\n            return\n        self._candidate_rank_log_at_v11218[sid] = now\n"""
new = """        sid = int(getattr(subscribe, \"id\", 0) or 0)\n        now = time.time()\n        log_state = getattr(self, \"_candidate_rank_log_at_v11218\", None)\n        if not isinstance(log_state, dict):\n            log_state = {}\n            self._candidate_rank_log_at_v11218 = log_state\n        last = float(log_state.get(sid, 0) or 0)\n        if last and now - last < self._candidate_rank_log_interval_v11218:\n            return\n        log_state[sid] = now\n"""
if new not in text:
    if old not in text:
        raise SystemExit("candidate log-state anchor missing")
    ranking.write_text(text.replace(old, new, 1), encoding="utf-8")

# 3) ResourcePlanner only receives a dynamic entry-order hook. Existing fixed
# direct-share > Magnet > ED2K semantics remain verbatim below this block.
planner = PLUGIN / "resource_planner_v190.py"
text = planner.read_text(encoding="utf-8")
anchor = """        actions = []\n        skipped = []\n        magnet_selected = False\n"""
replacement = """        # v1.12.18 只提供同阶段频道候选排序 hook；没有新层时完全保持旧顺序。\n        # 固定来源优先级不在这里改变：本函数仍在光鸭直接转存之后执行，且组内仍 Magnet > ED2K。\n        ranker_v11218 = getattr(self, \"_channel_entry_priority_v11218\", None)\n        if callable(ranker_v11218) and len(matched_entries) > 1:\n            try:\n                matched_entries.sort(key=lambda pair: ranker_v11218(subscribe, pair[0]))\n            except Exception as err:\n                self._plugin_log(\"WARNING\", \"【光鸭转存助手】【候选排序v1.12.18】#%s 频道候选排序失败，保持旧顺序：%s\", sid, str(err)[:180])\n\n        actions = []\n        skipped = []\n        magnet_selected = False\n"""
if "ranker_v11218 = getattr(self, \"_channel_entry_priority_v11218\", None)" not in text:
    if anchor not in text:
        raise SystemExit("resource planner anchor missing")
    planner.write_text(text.replace(anchor, replacement, 1), encoding="utf-8")

# 4) Migrate only structural contracts that described v1.12.17's previous
# nested edge. Historical MovieIdentityV1129 signature assertions stay unchanged.
old_import_assert = 'from .search_recall_v11217 import GuangYaSearchRecallV11217Mixin'
new_import_assert = 'from .candidate_ranking_v11218 import GuangYaCandidateRankingV11218Mixin'
old_class_assert = 'class GuangYaMovieBilingualIdentityV11216Mixin(GuangYaSearchRecallV11217Mixin):'
new_class_assert = 'class GuangYaMovieBilingualIdentityV11216Mixin(GuangYaCandidateRankingV11218Mixin):'
for path in TESTS.glob("test_*.py"):
    text = path.read_text(encoding="utf-8")
    changed = text.replace(old_import_assert, new_import_assert).replace(old_class_assert, new_class_assert)
    if changed != text:
        path.write_text(changed, encoding="utf-8")

# Isolated bilingual bridge harness strips relative imports; inject the new
# direct parent instead of the historical SearchRecall parent.
bilingual_test = TESTS / "test_movie_bilingual_identity_v11216.py"
text = bilingual_test.read_text(encoding="utf-8")
old_ns = '        "GuangYaSearchRecallV11217Mixin": _Base,\n'
new_ns = '        "GuangYaCandidateRankingV11218Mixin": _Base,\n'
if new_ns not in text:
    if old_ns not in text:
        raise SystemExit("bilingual isolated namespace anchor missing")
    bilingual_test.write_text(text.replace(old_ns, new_ns, 1), encoding="utf-8")

# Candidate-specific wiring contract follows the safe nested edge, not a second
# MovieIdentity base.
candidate_test = TESTS / "test_candidate_ranking_v11218.py"
text = candidate_test.read_text(encoding="utf-8")
old = """    movie = MOVIE_IDENTITY.read_text(encoding=\"utf-8\")\n    assert \"GuangYaCandidateRankingV11218Mixin\" in movie\n    assert \"GuangYaMovieIdentityV1129Mixin(GuangYaMovieBilingualIdentityV11216Mixin, GuangYaCandidateRankingV11218Mixin)\" in movie\n"""
new = """    movie = MOVIE_IDENTITY.read_text(encoding=\"utf-8\")\n    bilingual = (PLUGIN / \"movie_bilingual_identity_v11216.py\").read_text(encoding=\"utf-8\")\n    assert \"class GuangYaMovieIdentityV1129Mixin(GuangYaMovieBilingualIdentityV11216Mixin):\" in movie\n    assert \"from .candidate_ranking_v11218 import GuangYaCandidateRankingV11218Mixin\" in bilingual\n    assert \"class GuangYaMovieBilingualIdentityV11216Mixin(GuangYaCandidateRankingV11218Mixin):\" in bilingual\n    assert \"class GuangYaCandidateRankingV11218Mixin(GuangYaSearchRecallV11217Mixin):\" in SOURCE.read_text(encoding=\"utf-8\")\n"""
if new not in text:
    if old not in text:
        raise SystemExit("candidate wiring contract anchor missing")
    candidate_test.write_text(text.replace(old, new, 1), encoding="utf-8")
