import ast
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Set


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
MATCH = PLUGIN / "media_match_v11219.py"
FAST = PLUGIN / "fast_recall_v1126.py"
SOURCE = MATCH.read_text(encoding="utf-8")
FAST_SOURCE = FAST.read_text(encoding="utf-8")


def _load_functions(*names):
    tree = ast.parse(SOURCE)
    keep = []
    wanted = set(names)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            keep.append(node)
    module = ast.Module(body=keep, type_ignores=[])
    ast.fix_missing_locations(module)
    ns = {
        "Any": Any,
        "Dict": Dict,
        "Iterable": Iterable,
        "Set": Set,
        "_STRONG_SOURCE_STATES_V11219": {"submitted", "queued", "waiting", "completed"},
    }
    exec(compile(module, str(MATCH), "exec"), ns)
    return ns


def test_unresolved_intent_never_becomes_strong_episode_claim():
    ns = _load_functions("_positive_episode_set_v11219", "source_claim_episodes_v11219")
    claim = ns["source_claim_episodes_v11219"]

    assert claim({"state": "new", "target_episodes": [4, 5]}) == set()
    assert claim({"state": "retry", "target_episodes": [4, 5]}) == set()
    assert claim({"state": "dispatching", "target_episodes": [4, 5]}) == set()
    assert claim({
        "state": "dispatching",
        "target_episodes": [4, 5],
        "resolved_episodes": [4],
        "media_match_verified_v11219": True,
    }) == {4}


def test_submitted_source_claims_only_verified_transfer_episodes():
    ns = _load_functions("_positive_episode_set_v11219", "source_claim_episodes_v11219")
    claim = ns["source_claim_episodes_v11219"]

    assert claim({
        "state": "submitted",
        "task_id": "t1",
        "target_episodes": [4, 5, 6],
        "resolved_episodes": [4, 5],
        "transfer_episodes": [4],
    }) == {4}
    assert claim({
        "state": "waiting",
        "task_id": "t2",
        "target_episodes": [7, 8],
        "resolved_episodes": [7],
    }) == {7}


def test_legacy_existing_task_keeps_target_claim_for_upgrade_safety():
    ns = _load_functions("_positive_episode_set_v11219", "source_claim_episodes_v11219")
    claim = ns["source_claim_episodes_v11219"]

    assert claim({
        "state": "submitted",
        "task_id": "legacy-task",
        "target_episodes": [9, 10],
    }) == {9, 10}
    assert claim({
        "state": "submitted",
        "task_id": "",
        "target_episodes": [9, 10],
    }) == set()


def test_movie_actual_match_rejects_discovery_only_style_success():
    tree = ast.parse(SOURCE)
    keep = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "movie_actual_match_v11219"
    ]
    module = ast.Module(body=keep, type_ignores=[])
    ast.fix_missing_locations(module)

    def fake_assess(**kwargs):
        assert kwargs["is_movie"] is True
        assert kwargs["discovery_evidences"] == ()
        return {
            "ok": True,
            "score": 50,
            "primary_match": False,
            "file_match": False,
            "reason": "would have passed on weak evidence",
        }

    ns = {
        "Any": Any,
        "Dict": Dict,
        "Iterable": Iterable,
        "assess_media_identity_v1111": fake_assess,
    }
    exec(compile(module, str(MATCH), "exec"), ns)
    result = ns["movie_actual_match_v11219"](
        aliases=["Movie Name"],
        expected_year=2026,
        primary_evidences=["movie"],
        file_evidences=["video.mkv"],
    )
    assert result["ok"] is False
    assert result["actual_title_match"] is False
    assert "真实 payload" in result["reason"]


def test_movie_actual_match_accepts_real_primary_or_file_title_match():
    tree = ast.parse(SOURCE)
    keep = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "movie_actual_match_v11219"
    ]
    module = ast.Module(body=keep, type_ignores=[])
    ast.fix_missing_locations(module)

    def fake_assess(**kwargs):
        return {
            "ok": True,
            "score": 70,
            "primary_match": True,
            "file_match": False,
            "reason": "actual primary matched",
        }

    ns = {
        "Any": Any,
        "Dict": Dict,
        "Iterable": Iterable,
        "assess_media_identity_v1111": fake_assess,
    }
    exec(compile(module, str(MATCH), "exec"), ns)
    result = ns["movie_actual_match_v11219"](
        aliases=["Movie Name"],
        expected_year=2026,
        primary_evidences=["Movie Name 2026"],
        file_evidences=["movie.mkv"],
    )
    assert result["ok"] is True
    assert result["actual_title_match"] is True


def test_runtime_wiring_places_match_layers_before_dispatch_and_episode_fence():
    assert "from .media_match_v11219 import GuangYaMediaMatchV11219Mixin" in FAST_SOURCE
    assert "GuangYaMovieXunleiMatchV11219Mixin" not in FAST_SOURCE
    assert not (PLUGIN / "movie_xunlei_match_v11219.py").exists()
    assert "def _xunlei_json_identity_matches_v1123(" in SOURCE


def test_source_schema_separates_intent_candidate_resolved_and_transfer():
    for token in (
        '"requested_episodes"',
        '"candidate_episodes"',
        '"resolved_episodes"',
        '"transfer_episodes"',
        '"media_match_verified_v11219"',
    ):
        assert token in SOURCE
    assert "source_claim_episodes_v11219(row)" in SOURCE
    assert "return source_claim_episodes_v11219(source)" in SOURCE


def test_series_final_match_rechecks_authoritative_missing_after_real_resolve():
    assert 'result.get("physical_episodes_v11214")' in SOURCE
    assert 'allowed_fn = getattr(self, "_authoritative_missing_v11214", None)' in SOURCE
    assert "if not physical.issubset(allowed):" in SOURCE
    assert '"transfer_episodes_v11219"' in SOURCE


def test_movie_final_match_requires_real_video_for_share_and_offline_sources():
    assert "if not video_paths:" in SOURCE
    assert "if not video_files:" in SOURCE
    assert "电影真实 payload 未发现可验证的视频文件" in SOURCE
    assert 'origin="guangya_share"' in SOURCE


def test_completed_claim_is_released_after_grace_when_episode_still_missing():
    tree = ast.parse(SOURCE, filename=str(MATCH))
    keep = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in {"_positive_episode_set_v11219", "source_claim_episodes_v11219"}:
            keep.append(node)
        if isinstance(node, ast.ClassDef) and node.name == "GuangYaMediaMatchV11219Mixin":
            keep.append(node)
    module = ast.Module(body=keep, type_ignores=[])
    ast.fix_missing_locations(module)
    ns = {
        "Any": Any,
        "Dict": Dict,
        "Iterable": Iterable,
        "List": list,
        "Set": Set,
        "time": time,
        "_STRONG_SOURCE_STATES_V11219": {"submitted", "queued", "waiting", "completed"},
    }
    exec(compile(module, str(MATCH), "exec"), ns)
    Mixin = ns["GuangYaMediaMatchV11219Mixin"]

    class Probe(Mixin):
        def __init__(self):
            self._completed_claim_grace_seconds_v11219 = 60
            self.logs = []
            self.store = {
                "items": {
                    "s1": {
                        "id": "s1",
                        "subscribe_id": 100,
                        "enabled": True,
                        "state": "completed",
                        "task_id": "task-1",
                        "transfer_episodes": [3],
                        "completed_ts": time.time() - 3600,
                    }
                }
            }

        def _source_store(self):
            return self.store

        @staticmethod
        def _find_subscription(_sid):
            return object()

        @staticmethod
        def _is_movie_subscription(_subscribe):
            return False

        @staticmethod
        def _subscription_missing_episodes(_subscribe):
            return [3]

        def _plugin_log(self, level, message, *args):
            self.logs.append((level, message % args if args else message))

    probe = Probe()
    assert probe._active_source_claims(100) == set()
    assert probe._other_source_claims_v11214(100, current_source_id="new-task") == set()
    assert any("释放过期 completed 占坑" in row[1] for row in probe.logs)

    # The final write gate still protects fresh completions and real inflight work.
    row = probe.store["items"]["s1"]
    row["completed_ts"] = time.time()
    assert probe._other_source_claims_v11214(100, "new-task") == {3}
    assert probe._other_source_claims_v11214(100, "s1") == set()
    row["state"] = "waiting"
    row["completed_ts"] = time.time() - 3600
    assert probe._other_source_claims_v11214(100, "new-task") == {3}
    row["enabled"] = False
    assert probe._other_source_claims_v11214(100, "new-task") == set()


def test_completed_claim_without_completed_ts_is_released_to_avoid_permanent_block():
    tree = ast.parse(SOURCE, filename=str(MATCH))
    keep = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in {"_positive_episode_set_v11219", "source_claim_episodes_v11219"}:
            keep.append(node)
        if isinstance(node, ast.ClassDef) and node.name == "GuangYaMediaMatchV11219Mixin":
            keep.append(node)
    module = ast.Module(body=keep, type_ignores=[])
    ast.fix_missing_locations(module)
    ns = {
        "Any": Any,
        "Dict": Dict,
        "Iterable": Iterable,
        "List": list,
        "Set": Set,
        "time": time,
        "_STRONG_SOURCE_STATES_V11219": {"submitted", "queued", "waiting", "completed"},
    }
    exec(compile(module, str(MATCH), "exec"), ns)
    Mixin = ns["GuangYaMediaMatchV11219Mixin"]

    class Probe(Mixin):
        def __init__(self):
            self._completed_claim_grace_seconds_v11219 = 60
            self.logs = []
            self.store = {
                "items": {
                    "s1": {
                        "id": "s1",
                        "subscribe_id": 100,
                        "enabled": True,
                        "state": "completed",
                        "task_id": "task-1",
                        "transfer_episodes": [7],
                        "completed_ts": 0,
                    }
                }
            }

        def _source_store(self):
            return self.store

        @staticmethod
        def _find_subscription(_sid):
            return object()

        @staticmethod
        def _is_movie_subscription(_subscribe):
            return False

        @staticmethod
        def _subscription_missing_episodes(_subscribe):
            return [7]

        def _plugin_log(self, level, message, *args):
            self.logs.append((level, message % args if args else message))

    probe = Probe()
    assert probe._active_source_claims(100) == set()
    assert probe._other_source_claims_v11214(100, current_source_id="new-task") == set()
    assert any("释放无 completed_ts 的 completed 占坑" in row[1] for row in probe.logs)
