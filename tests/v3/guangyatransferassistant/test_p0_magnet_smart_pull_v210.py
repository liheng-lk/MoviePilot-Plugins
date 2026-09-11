"""2.0.10-r94 Beta: Magnet selected-file gate + smart pull UNKNOWN + cooldown ABI."""
from __future__ import annotations

import ast
import datetime
import threading
import time
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Set, Tuple
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"


def _load_class(module_file: Path, class_name: str, extra: Optional[Dict[str, Any]] = None):
    tree = ast.parse(module_file.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    mod = ast.Module(body=[cls], type_ignores=[])
    ast.fix_missing_locations(mod)
    ns: Dict[str, Any] = {
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "Optional": Optional,
        "Set": Set,
        "Tuple": Tuple,
        "datetime": datetime,
        "inspect": __import__("inspect"),
        "threading": threading,
        "time": time,
        "Path": Path,
        "CronTrigger": MagicMock(),
        "AUTO_SELECT_CONFIDENCE": 0.8,
        "_AMBIGUOUS_PREFIX": "[AMB]",
    }
    ns["CronTrigger"].from_crontab = MagicMock(return_value="cron")
    if extra:
        ns.update(extra)
    # Provide common legacy helpers used by planner/governance snippets.
    try:
        from plugins.v3.guangyatransferassistant.legacy import _is_subtitle, _is_video
        ns["_is_subtitle"] = _is_subtitle
        ns["_is_video"] = _is_video
    except Exception:
        def _is_video(name: str) -> bool:
            return str(name).lower().endswith((".mkv", ".mp4", ".ts", ".avi"))

        def _is_subtitle(name: str) -> bool:
            return str(name).lower().endswith((".ass", ".srt", ".sup"))

        ns["_is_video"] = _is_video
        ns["_is_subtitle"] = _is_video and _is_subtitle
        ns["_is_subtitle"] = _is_subtitle
    exec(compile(mod, str(module_file), "exec"), ns)
    return ns[class_name], ns


def test_a_magnet_subtitle_only_blocks_create_task():
    Mixin, _ = _load_class(PLUGIN / "resource_planner_v190.py", "GuangYaResourcePlannerMixin")
    resolve_data = {
        "btResInfo": {
            "subfiles": [
                {"fileIndex": 1, "fileName": "movie.mkv", "fileSize": 1000},
                {"fileIndex": 2, "fileName": "movie.ass", "fileSize": 10},
                {"fileIndex": 3, "fileName": "movie.srt", "fileSize": 11},
            ]
        }
    }

    class Obj(Mixin):
        def _plugin_log(self, *a, **k):
            self.logs = getattr(self, "logs", [])
            self.logs.append(a)

    obj = Obj()
    try:
        obj._assert_selected_video_present_v210(
            resolve_data=resolve_data,
            selected_indexes=[2, 3],
            source={"type": "magnet", "name": "坠河的女孩"},
            subscribe=SimpleNamespace(name="坠河的女孩"),
        )
        assert False, "expected SELECTED_VIDEO_MISSING"
    except RuntimeError as err:
        assert "SELECTED_VIDEO_MISSING" in str(err)
    assert any("【云添加文件选择】" in str(row[1]) for row in getattr(obj, "logs", []) if len(row) > 1)


def test_b_file_index_not_array_position():
    Mixin, _ = _load_class(PLUGIN / "resource_planner_v190.py", "GuangYaResourcePlannerMixin")
    resolve_data = {
        "btResInfo": {
            "subfiles": [
                {"fileIndex": 7, "fileName": "movie.mkv", "fileSize": 1000},
                {"fileIndex": 11, "fileName": "movie.ass", "fileSize": 10},
            ]
        }
    }
    by_index = Mixin._subfiles_by_file_index_v210(resolve_data)
    assert 7 in by_index and 11 in by_index
    assert 0 not in by_index
    manifest = Mixin._selected_manifest_v210(resolve_data, [7, 11])
    names = [row["name"] for row in manifest]
    assert names == ["movie.mkv", "movie.ass"]
    assert all(row["file_index"] in {7, 11} for row in manifest)


def test_c_remote_task_completed_subtitle_only():
    source = {
        "id": "s1",
        "selected_manifest": [
            {"file_index": 2, "name": "movie.ass", "size": 1, "type": "subtitle"},
            {"file_index": 3, "name": "movie.srt", "size": 1, "type": "subtitle"},
        ],
    }
    manifest = list(source.get("selected_manifest") or [])
    video_names = [str(row.get("name") or "") for row in manifest if str(row.get("type") or "") == "video"]
    assert manifest and not video_names
    src = (PLUGIN / "multisource_v180.py").read_text(encoding="utf-8")
    assert "REMOTE_VIDEO_MISSING" in src
    assert 'reason_code="REMOTE_VIDEO_MISSING"' in src
    assert "selected_manifest" in src


def test_d_movie_video_plus_subtitle_allowed():
    Mixin, _ = _load_class(PLUGIN / "resource_planner_v190.py", "GuangYaResourcePlannerMixin")
    resolve_data = {
        "btResInfo": {
            "subfiles": [
                {"fileIndex": 1, "fileName": "movie.mkv", "fileSize": 1000},
                {"fileIndex": 2, "fileName": "movie.ass", "fileSize": 10},
            ]
        }
    }

    class Obj(Mixin):
        def _plugin_log(self, *a, **k):
            pass

    manifest = Obj()._assert_selected_video_present_v210(
        resolve_data=resolve_data,
        selected_indexes=[1, 2],
        source={"type": "magnet"},
        subscribe=SimpleNamespace(name="movie"),
    )
    assert sum(1 for row in manifest if row["type"] == "video") == 1
    assert sum(1 for row in manifest if row["type"] == "subtitle") == 1


def _smart_obj(*, gate: Dict[str, Any], cooldown: bool = True, movie: bool = False):
    Mixin, _ = _load_class(PLUGIN / "calendar_driven_v209.py", "GuangYaCalendarDrivenV209Mixin")
    logs = []

    class Base:
        def _active_selected_subscriptions_v1125(self):
            return [SimpleNamespace(id=124, name="冬城猎凶")]

        def _external_search_state_v1114(self):
            return {}

        def _is_movie_subscription(self, subscribe):
            return movie

        def _movie_needs_pull_v1125(self, subscribe):
            return True

        def _positive_ids_v1125(self, values):
            return [int(v) for v in (values or []) if int(v or 0) > 0]

        def _plugin_log(self, *a, **k):
            logs.append(a)

    class Obj(Mixin, Base):
        def _external_cooldown_due_v1125(self, sid, state, now):
            assert isinstance(sid, int)
            assert isinstance(state, dict)
            assert isinstance(now, (int, float))
            return cooldown

        def _refresh_airing_calendar_v1120(self, force=False):
            # Must override Mixin.refresh; otherwise get_data missing → calendar_failed → TV skipped.
            return {"subscriptions": [{"subscribe_id": 124, "episodes": []}]}

        def _airing_gate_v1120(self, subscribe, payload=None):
            return dict(gate)

        def _plugin_log(self, *a, **k):
            logs.append(a)

    return Obj(), logs


def test_e_smart_selector_missing_due():
    obj, logs = _smart_obj(gate={
        "preflight_state": "MISSING",
        "decision": "search_due",
        "due_uncovered": [1],
        "target_episodes": [1],
    })
    assert obj._smart_pull_due_ids_v1125() == [124]
    assert any(
        len(row) > 1 and "【主动检索选择】" in str(row[1]) and True in row
        for row in logs
    )


def test_f_smart_selector_unknown_cooldown_due():
    """OLD: UNKNOWN+empty targets → selected=True (white GYING).
    NEW: UNKNOWN+empty targets → selected=False (no white search).
    WHY: empty final_target must not open GYING/PanSou."""
    obj, logs = _smart_obj(gate={
        "preflight_state": "UNKNOWN",
        "decision": "continue_match",
        "due_uncovered": [],
        "target_episodes": [],
        "final_target": [],
    }, cooldown=True)
    assert obj._smart_pull_due_ids_v1125() == []


def test_f2_smart_selector_unknown_with_due_targets_still_selected():
    obj, _ = _smart_obj(gate={
        "preflight_state": "UNKNOWN",
        "decision": "continue_match",
        "due_uncovered": [5],
        "target_episodes": [5],
        "final_target": [5],
    }, cooldown=True)
    assert obj._smart_pull_due_ids_v1125() == [124]


def test_g_unknown_cooldown_not_due():
    obj, _ = _smart_obj(gate={
        "preflight_state": "UNKNOWN",
        "decision": "continue_match",
    }, cooldown=False)
    assert obj._smart_pull_due_ids_v1125() == []


def test_h_satisfied_future_no_gying():
    obj, _ = _smart_obj(gate={
        "preflight_state": "SATISFIED",
        "decision": "skip_future",
        "due_uncovered": [],
        "future_missing": [5],
    })
    assert obj._smart_pull_due_ids_v1125() == []


def test_j_cooldown_abi_matches_production():
    src = (PLUGIN / "calendar_driven_v209.py").read_text(encoding="utf-8")
    assert "checker(sid, state, now)" in src or "not checker(sid, state, now)" in src
    assert "except Exception:\n                pass" not in src.split("def _smart_pull_due_ids_v1125")[1].split("def _daily_reconcile")[0]
    assert "【检索治理异常】" in src
    # Production FastRecall signature
    fr = (PLUGIN / "fast_recall_v1126.py").read_text(encoding="utf-8")
    assert "def _external_cooldown_due_v1125(\n        self,\n        sid: int,\n        state: Dict[str, Any],\n        now: float,\n    )" in fr.replace("\r\n", "\n")


def test_governance_uses_file_index_map_not_list_position():
    src = (PLUGIN / "governance_v1114.py").read_text(encoding="utf-8")
    # Production quality filter must not index subfiles by list position.
    assert "subfiles[index]" not in src
    assert "by_file_index" in src


def test_no_subfiles_list_index_in_planner_submit_path():
    planner = (PLUGIN / "resource_planner_v190.py").read_text(encoding="utf-8")
    multi = (PLUGIN / "multisource_v180.py").read_text(encoding="utf-8")
    assert "SELECTED_VIDEO_MISSING" in planner
    assert "【云添加文件选择】" in planner
    assert "REMOTE_VIDEO_MISSING" in multi
    assert "selected_manifest" in multi
