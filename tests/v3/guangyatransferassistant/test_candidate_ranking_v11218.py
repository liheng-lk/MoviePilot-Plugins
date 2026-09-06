from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
SOURCE = PLUGIN / "candidate_ranking_v11218.py"
MOVIE_IDENTITY = PLUGIN / "movie_identity_v1129.py"
RESOURCE_PLANNER = PLUGIN / "resource_planner_v190.py"


class _Base:
    def __init__(self):
        self.rows = {}
        self.logs = []

    def init_plugin(self, config=None):
        return None

    def _plugin_log(self, *args):
        self.logs.append(args)

    def _source_store(self):
        return {"updated_at": "sig-1", "items": dict(self.rows)}

    @staticmethod
    def _is_movie_subscription(subscribe):
        return str(getattr(subscribe, "type", "")) == "电影"

    @staticmethod
    def _subscription_missing_episodes(subscribe):
        return list(getattr(subscribe, "missing", []) or [])

    @staticmethod
    def _structured_candidate_match_v11217(_subscribe, row):
        score = int((row or {}).get("identity_score") or 0)
        return (score > 0), {"score": score}

    def _cached_matches_for_subscription(self, subscribe):
        return list(getattr(subscribe, "pairs", []) or [])

    @staticmethod
    def _xunlei_candidate_priority_v1125(_subscribe, row, missing):
        episodes = set((row or {}).get("episodes") or [])
        if episodes.intersection(missing):
            return 0, min(episodes.intersection(missing))
        if not episodes:
            return 1, 0
        return 2, min(episodes)

    def _search_viewing_xunlei(self, keyword):
        return [], {"success": True, "keyword": keyword}


def _namespace():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    body = [node for node in tree.body if not (isinstance(node, ast.ImportFrom) and node.level)]
    module = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "GuangYaSearchRecallV11217Mixin": _Base,
        "AUTO_SELECT_CONFIDENCE": 0.95,
        "resolve_episode": lambda *_args, **_kwargs: {},
        "reliable_episode_set": lambda *_args, **_kwargs: set(),
    }
    exec(compile(module, str(SOURCE), "exec"), namespace)
    return namespace


NS = _namespace()
ProbeBase = NS["GuangYaCandidateRankingV11218Mixin"]
quality_bonus = NS["_bayes_quality_bonus_v11218"]


class Probe(ProbeBase):
    def _episode_set_v11218(self, _subscribe, row):
        return set((row or {}).get("episodes") or [])


def tv():
    return SimpleNamespace(id=81, name="测试剧", type="电视剧", season=1, missing=[11])


def test_bayesian_quality_is_smoothed_and_bounded():
    good, good_p = quality_bonus(8, 0)
    bad, bad_p = quality_bonus(0, 8)
    tiny, tiny_p = quality_bonus(1, 0)
    assert 0 < good <= 18
    assert -18 <= bad < 0
    assert abs(tiny) < abs(good)
    assert good_p > tiny_p > 0.5 > bad_p


def test_channel_quality_uses_only_real_terminal_telegram_outcomes():
    probe = Probe()
    probe.rows = {
        "1": {"origin": "telegram", "source_label": "频道A", "state": "completed"},
        "2": {"origin": "telegram", "source_label": "频道A", "state": "failed"},
        "3": {"origin": "telegram", "source_label": "频道A", "state": "waiting"},
        "4": {"origin": "viewing_auto", "source_label": "频道A", "state": "completed"},
        "5": {"origin": "telegram", "source_label": "频道B", "state": "needs_review"},
    }
    snap = probe._channel_quality_snapshot_v11218()
    a = snap[NS["_quality_key_v11218"]("频道A")]
    b = snap[NS["_quality_key_v11218"]("频道B")]
    assert (a["success"], a["failure"], a["samples"]) == (1, 1, 2)
    assert (b["success"], b["failure"], b["samples"]) == (0, 1, 1)


def test_identity_score_dominates_learned_channel_quality():
    probe = Probe()
    probe.rows = {
        **{f"g{i}": {"origin": "telegram", "source_label": "好频道", "state": "completed"} for i in range(10)},
        **{f"b{i}": {"origin": "telegram", "source_label": "差频道", "state": "failed"} for i in range(10)},
    }
    sub = tv()
    strong = {"identity_score": 99, "source_label": "差频道", "episodes": [11], "cache_seen_at": 10}
    weak = {"identity_score": 92, "source_label": "好频道", "episodes": [11], "cache_seen_at": 20}
    strong_score = probe._channel_entry_score_v11218(sub, strong)
    weak_score = probe._channel_entry_score_v11218(sub, weak)
    assert strong_score["identity"] == 99
    assert weak_score["quality_bonus"] > strong_score["quality_bonus"]
    assert strong_score["total"] > weak_score["total"]


def test_channel_ranking_prefers_exact_missing_coverage_then_quality_and_recency():
    probe = Probe()
    probe.rows = {
        **{f"g{i}": {"origin": "telegram", "source_label": "稳定频道", "state": "completed"} for i in range(6)},
        **{f"n{i}": {"origin": "telegram", "source_label": "普通频道", "state": "failed"} for i in range(2)},
    }
    sub = tv()
    sub.pairs = [
        ({"identity_score": 95, "source_label": "普通频道", "episodes": [11, 12, 13], "cache_seen_at": 30}, "pack"),
        ({"identity_score": 95, "source_label": "稳定频道", "episodes": [11], "cache_seen_at": 20}, "exact"),
        ({"identity_score": 95, "source_label": "稳定频道", "episodes": [], "cache_seen_at": 40}, "unknown"),
    ]
    ranked = probe._cached_matches_for_subscription(sub)
    assert ranked[0][1] == "exact"
    assert ranked[0][0]["rank_score_v11218"] > ranked[1][0]["rank_score_v11218"]


def test_xunlei_ranking_prefers_exact_missing_and_uses_passcode_only_as_tiebreaker():
    probe = Probe()
    sub = tv()
    exact = {"episodes": [11], "identity_score": 95, "passcode": "1234"}
    pack = {"episodes": [11, 12, 13], "identity_score": 95, "passcode": "1234"}
    unknown = {"episodes": [], "identity_score": 99, "passcode": "1234"}
    assert probe._xunlei_candidate_priority_v1125(sub, exact, {11}) < probe._xunlei_candidate_priority_v1125(sub, pack, {11})
    assert probe._xunlei_candidate_priority_v1125(sub, pack, {11}) < probe._xunlei_candidate_priority_v1125(sub, unknown, {11})

    with_code = {"episodes": [11], "identity_score": 95, "passcode": "1234"}
    without_code = {"episodes": [11], "identity_score": 95, "passcode": ""}
    assert probe._xunlei_candidate_priority_v1125(sub, with_code, {11}) < probe._xunlei_candidate_priority_v1125(sub, without_code, {11})


def test_resource_planner_has_dynamic_v11218_order_hook_without_changing_source_priority():
    text = RESOURCE_PLANNER.read_text(encoding="utf-8")
    planner = text.split("    def _dispatch_channel_external_candidates", 1)[1].split("    def _try_transfer_subscription_inner", 1)[0]
    assert '_channel_entry_priority_v11218' in planner
    assert 'external.sort(key=lambda row: 0 if str(row.get("type") or "") == "magnet" else 1)' in planner
    assert 'rank = 1 if source_type == "magnet" else 2' in planner


def test_v11218_is_nested_under_movie_identity_and_does_not_reimplement_transfer_protocols():
    movie = MOVIE_IDENTITY.read_text(encoding="utf-8")
    assert "GuangYaCandidateRankingV11218Mixin" in movie
    assert "GuangYaMovieIdentityV1129Mixin(GuangYaMovieBilingualIdentityV11216Mixin, GuangYaCandidateRankingV11218Mixin)" in movie
    source = SOURCE.read_text(encoding="utf-8").lower()
    for forbidden in ("cloudcollection/v1/create_task", "userres/rapid", "qbittorrent", "transmission"):
        assert forbidden not in source
    assert "_source_priority" not in source
