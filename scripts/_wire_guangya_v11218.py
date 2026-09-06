from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"

movie = PLUGIN / "movie_identity_v1129.py"
text = movie.read_text(encoding="utf-8")
old_import = "from .movie_bilingual_identity_v11216 import GuangYaMovieBilingualIdentityV11216Mixin\n"
new_import = old_import + "from .candidate_ranking_v11218 import GuangYaCandidateRankingV11218Mixin\n"
if "from .candidate_ranking_v11218 import GuangYaCandidateRankingV11218Mixin" not in text:
    if old_import not in text:
        raise SystemExit("movie identity import anchor missing")
    text = text.replace(old_import, new_import, 1)
old_class = "class GuangYaMovieIdentityV1129Mixin(GuangYaMovieBilingualIdentityV11216Mixin):"
new_class = "class GuangYaMovieIdentityV1129Mixin(GuangYaMovieBilingualIdentityV11216Mixin, GuangYaCandidateRankingV11218Mixin):"
if new_class not in text:
    if old_class not in text:
        raise SystemExit("movie identity class anchor missing")
    text = text.replace(old_class, new_class, 1)
movie.write_text(text, encoding="utf-8")

planner = PLUGIN / "resource_planner_v190.py"
text = planner.read_text(encoding="utf-8")
anchor = """        actions = []\n        skipped = []\n        magnet_selected = False\n"""
replacement = """        # v1.12.18 只提供同阶段频道候选排序 hook；没有新层时完全保持旧顺序。\n        # 固定来源优先级不在这里改变：本函数仍在光鸭直接转存之后执行，且组内仍 Magnet > ED2K。\n        ranker_v11218 = getattr(self, \"_channel_entry_priority_v11218\", None)\n        if callable(ranker_v11218) and len(matched_entries) > 1:\n            try:\n                matched_entries.sort(key=lambda pair: ranker_v11218(subscribe, pair[0]))\n            except Exception as err:\n                self._plugin_log(\"WARNING\", \"【光鸭转存助手】【候选排序v1.12.18】#%s 频道候选排序失败，保持旧顺序：%s\", sid, str(err)[:180])\n\n        actions = []\n        skipped = []\n        magnet_selected = False\n"""
if "ranker_v11218 = getattr(self, \"_channel_entry_priority_v11218\", None)" not in text:
    if anchor not in text:
        raise SystemExit("resource planner anchor missing")
    text = text.replace(anchor, replacement, 1)
planner.write_text(text, encoding="utf-8")
