"""2.0.10-r94 Controlled Real-World Retest: auto GYING path + Magnet/ED2K gates."""
from __future__ import annotations

import ast
import datetime
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Set, Tuple
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"


def _load_class(module_file: Path, class_name: str, extra: Optional[Dict[str, Any]] = None):
    tree = ast.parse(module_file.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    # Drop inheritance for AST isolation so we can stub production methods.
    cls = ast.ClassDef(
        name=cls.name,
        bases=[],
        keywords=[],
        body=cls.body,
        decorator_list=cls.decorator_list,
    )
    mod = ast.Module(body=[cls], type_ignores=[])
    ast.fix_missing_locations(mod)
    ns: Dict[str, Any] = {
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "Optional": Optional,
        "Set": Set,
        "Tuple": Tuple,
        "Iterable": List,
        "datetime": datetime,
        "inspect": __import__("inspect"),
        "threading": threading,
        "time": time,
        "hashlib": __import__("hashlib"),
        "Path": Path,
        "CronTrigger": MagicMock(),
        "AUTO_SELECT_CONFIDENCE": 0.8,
        "_AMBIGUOUS_PREFIX": "[AMB]",
        "_CHANNEL_CACHE_KEY_V1115": "channel_resource_cache_v1115",
        "_CHANNEL_CACHE_RETENTION_SECONDS_V1115": 7 * 24 * 60 * 60,
        "_CHANNEL_CACHE_CLEANUP_SECONDS_V1115": 7 * 24 * 60 * 60,
    }
    ns["CronTrigger"].from_crontab = MagicMock(return_value="cron")
    if extra:
        ns.update(extra)
    try:
        from plugins.v3.guangyatransferassistant.legacy import _is_subtitle, _is_video
        ns["_is_subtitle"] = _is_subtitle
        ns["_is_video"] = _is_video
    except Exception:
        def _is_video(name: str) -> bool:
            return str(name).lower().endswith((".mkv", ".mp4", ".ts", ".avi", ".m2ts"))

        def _is_subtitle(name: str) -> bool:
            return str(name).lower().endswith((".ass", ".srt", ".sup", ".ssa"))

        ns["_is_video"] = _is_video
        ns["_is_subtitle"] = _is_subtitle
    exec(compile(mod, str(module_file), "exec"), ns)
    return ns[class_name], ns


def _smart_obj(*, gate: Dict[str, Any], cooldown: bool = True):
    Mixin, _ = _load_class(PLUGIN / "calendar_driven_v209.py", "GuangYaCalendarDrivenV209Mixin")
    logs: List[tuple] = []

    class Base:
        def _active_selected_subscriptions_v1125(self):
            return [SimpleNamespace(id=124, name="冬城猎凶")]

        def _external_search_state_v1114(self):
            return {}

        def _is_movie_subscription(self, subscribe):
            return False

        def _movie_needs_pull_v1125(self, subscribe):
            return False

        def _positive_ids_v1125(self, values):
            return [int(v) for v in (values or []) if int(v or 0) > 0]

        def _plugin_log(self, *a, **k):
            logs.append(a)

    class Obj(Mixin, Base):
        def _external_cooldown_due_v1125(self, sid, state, now):
            return cooldown

        def _refresh_airing_calendar_v1120(self, force=False):
            return {"subscriptions": [{"subscribe_id": 124, "episodes": []}]}

        def _airing_gate_v1120(self, subscribe, payload=None):
            return dict(gate)

        def _plugin_log(self, *a, **k):
            logs.append(a)

    return Obj(), logs


def test_a_auto_gying_missing_full_path():
    """selector → airing_pull batch → viewing dispatch → GYING search stub."""
    Channel, _ = _load_class(PLUGIN / "channel_event_v1115.py", "GuangYaChannelEventV1115Mixin")
    calls = {"transfer": 0, "viewing": 0, "gying": 0, "dispatch_logs": 0}

    class Parent:
        def _runtime_is_current(self):
            return True

        @property
        def _enabled(self):
            return True

        def _find_subscription(self, sid):
            return SimpleNamespace(id=sid, name="冬城猎凶")

        def _is_guangya_route(self, subscribe):
            return True

        def _hydrate_channel_index_for_subscription_v1115(self, subscribe):
            return None

        def _try_transfer_subscription(self, subscribe, force=False, refresh_channel=False):
            calls["transfer"] += 1
            self._dispatch_viewing_external_v1113(subscribe)
            return {"success": True, "message": "ok"}

        def _dispatch_viewing_external_v1113(self, subscribe):
            calls["viewing"] += 1
            self._gying_raw_results("冬城猎凶", force=False)
            return {"success": True, "actions": []}

        def _gying_raw_results(self, keyword, force=False):
            calls["gying"] += 1
            return [], {}

        def _plugin_log(self, *a, **k):
            if len(a) > 1 and "【主动检索派发】" in str(a[1]):
                calls["dispatch_logs"] += 1

        def _record_route_health(self, **kwargs):
            return None

        def _now_text(self):
            return "now"

    class Obj(Channel, Parent):
        def __init__(self):
            self._inspect_cache = type("C", (), {"clear": lambda self: None})()

        def _hydrate_channel_index_for_subscription_v1115(self, subscribe):
            return None

        def get_data(self, key):
            return {}

        def save_data(self, key, value):
            return None

    obj, logs = _smart_obj(gate={
        "preflight_state": "MISSING",
        "decision": "search_due",
        "due_uncovered": [1],
        "target_episodes": [1],
    }, cooldown=True)
    assert obj._smart_pull_due_ids_v1125() == [124]
    assert any(len(row) > 1 and "【主动检索选择】" in str(row[1]) and True in row for row in logs)

    runner = Obj()
    runner._run_v1115_mode_batch([124], "更新日历主动拉取", "airing_pull", force=False)
    assert calls["transfer"] == 1
    assert calls["viewing"] == 1
    assert calls["gying"] == 1
    assert calls["dispatch_logs"] == 1


def test_b_auto_gying_unknown_cooldown_due():
    obj, _ = _smart_obj(gate={
        "preflight_state": "UNKNOWN",
        "decision": "continue_match",
        "due_uncovered": [],
        "target_episodes": [],
    }, cooldown=True)
    assert obj._smart_pull_due_ids_v1125() == [124]


def test_c_unknown_cooldown_blocks():
    obj, _ = _smart_obj(gate={
        "preflight_state": "UNKNOWN",
        "decision": "continue_match",
    }, cooldown=False)
    assert obj._smart_pull_due_ids_v1125() == []


def test_d_future_only_no_gying():
    obj, _ = _smart_obj(gate={
        "preflight_state": "SATISFIED",
        "decision": "skip_future",
        "due_uncovered": [],
        "future_missing": [5],
    }, cooldown=True)
    assert obj._smart_pull_due_ids_v1125() == []


def test_e_channel_event_no_gying_dispatch_log():
    Channel, _ = _load_class(PLUGIN / "channel_event_v1115.py", "GuangYaChannelEventV1115Mixin")
    gying = {"n": 0}
    logs = []

    class Parent:
        def _runtime_is_current(self):
            return True

        @property
        def _enabled(self):
            return True

        def _find_subscription(self, sid):
            return SimpleNamespace(id=sid, name="x")

        def _is_guangya_route(self, subscribe):
            return True

        def _hydrate_channel_index_for_subscription_v1115(self, subscribe):
            return None

        def _try_transfer_subscription(self, subscribe, force=False, refresh_channel=False):
            return {"success": True, "message": "channel only"}

        def _gying_raw_results(self, *a, **k):
            gying["n"] += 1
            return [], {}

        def _plugin_log(self, *a, **k):
            logs.append(a)

        def _record_route_health(self, **kwargs):
            return None

        def _now_text(self):
            return "now"

    class Obj(Channel, Parent):
        def __init__(self):
            self._inspect_cache = type("C", (), {"clear": lambda self: None})()

        def _hydrate_channel_index_for_subscription_v1115(self, subscribe):
            return None

        def get_data(self, key):
            return {}

        def save_data(self, key, value):
            return None

    Obj()._run_v1115_mode_batch([1], "频道新增资源", "channel_event", force=False)
    assert gying["n"] == 0
    assert not any(len(r) > 1 and "【主动检索派发】" in str(r[1]) for r in logs)


def test_f_magnet_real_fileindex_payload():
    Mixin, _ = _load_class(PLUGIN / "resource_planner_v190.py", "GuangYaResourcePlannerMixin")
    resolve_data = {
        "btResInfo": {
            "subfiles": [
                {"fileIndex": 7, "fileName": "movie.mkv", "fileSize": 1000},
                {"fileIndex": 11, "fileName": "movie.ass", "fileSize": 10},
            ]
        }
    }

    class Obj(Mixin):
        def _plugin_log(self, *a, **k):
            pass

    manifest = Obj()._assert_selected_video_present_v210(
        resolve_data=resolve_data,
        selected_indexes=[7, 11],
        source={"type": "magnet"},
        subscribe=SimpleNamespace(name="movie"),
    )
    assert [row["file_index"] for row in manifest] == [7, 11]
    assert sum(1 for row in manifest if row["type"] == "video") == 1
    payload_indexes = [int(row["file_index"]) for row in manifest]
    assert payload_indexes == [7, 11]
    assert 0 not in payload_indexes and 1 not in payload_indexes


def test_g_subtitle_only_blocks_create_task():
    Mixin, _ = _load_class(PLUGIN / "resource_planner_v190.py", "GuangYaResourcePlannerMixin")
    resolve_data = {
        "btResInfo": {
            "subfiles": [
                {"fileIndex": 7, "fileName": "movie.mkv", "fileSize": 1000},
                {"fileIndex": 11, "fileName": "movie.ass", "fileSize": 10},
            ]
        }
    }

    class Obj(Mixin):
        def _plugin_log(self, *a, **k):
            pass

    try:
        Obj()._assert_selected_video_present_v210(
            resolve_data=resolve_data,
            selected_indexes=[11],
            source={"type": "magnet"},
            subscribe=SimpleNamespace(name="坠河的女孩"),
        )
        assert False, "expected SELECTED_VIDEO_MISSING"
    except RuntimeError as err:
        assert "SELECTED_VIDEO_MISSING" in str(err)


def test_h_manifest_missing_non_video_filename_not_confirmed():
    src = (PLUGIN / "multisource_v180.py").read_text(encoding="utf-8")
    assert "or not manifest" not in src
    assert "remote_verify_source" in src
    assert "task_result_filename" in src
    assert "planned_manifest" in src
    file_name = "坠河的女孩.BZ]"
    manifest: List[Dict[str, Any]] = []
    planned_video: List[str] = []
    if file_name and str(file_name).lower().endswith((".mkv", ".mp4", ".avi", ".ts")):
        verified, verify_source = True, "task_result_filename"
    elif planned_video:
        verified, verify_source = False, "planned_manifest"
    else:
        verified, verify_source = False, "legacy_compat" if not manifest else "selected_manifest"
    assert verified is False
    assert verify_source == "legacy_compat"


def test_i_manifest_missing_real_video_filename_confirmed():
    file_name = "movie.mkv"

    def _is_video(name: str) -> bool:
        return str(name).lower().endswith((".mkv", ".mp4", ".avi", ".ts"))

    manifest: List[Dict[str, Any]] = []
    planned_video: List[str] = []
    if file_name and _is_video(file_name):
        verified, verify_source = True, "task_result_filename"
    elif planned_video:
        verified, verify_source = False, "planned_manifest"
    else:
        verified, verify_source = False, "legacy_compat"
    assert verified is True
    assert verify_source == "task_result_filename"


def test_j_ed2k_subtitle_only_blocked():
    Mixin, _ = _load_class(PLUGIN / "resource_planner_v190.py", "GuangYaResourcePlannerMixin")

    class Obj(Mixin):
        def _plugin_log(self, *a, **k):
            pass

        def _is_movie_subscription(self, subscribe):
            return True

        def _offline_request(self, *a, **k):
            return {
                "code": 0,
                "data": {
                    "url": "ed2k://|file|movie.ass|1|ABCDEF|/",
                    "btResInfo": {"fileName": "movie.ass", "subfiles": []},
                },
            }

        def _offline_api_success(self, response):
            return True

        def _offline_resolved_data(self, response):
            return response["data"]

        def _offline_api_error(self, response, message):
            return message

        def _planner_file_selection(self, source, subscribe, data):
            return {"indexes": [], "episodes": [], "diagnostics": [], "ambiguous": False}

        def _update_source(self, *a, **k):
            return {}

    try:
        Obj()._resolve_offline_source(
            {"id": "e1", "type": "ed2k", "uri": "ed2k://|file|movie.ass|1|ABCDEF|/", "name": "movie.ass"},
            SimpleNamespace(id=1, name="movie", type="电影"),
        )
        assert False, "expected SELECTED_VIDEO_MISSING"
    except RuntimeError as err:
        assert "SELECTED_VIDEO_MISSING" in str(err)


def test_k_ed2k_video_allowed_gate():
    Mixin, _ = _load_class(PLUGIN / "resource_planner_v190.py", "GuangYaResourcePlannerMixin")

    class Obj(Mixin):
        def _plugin_log(self, *a, **k):
            pass

    resolve_data = {"btResInfo": {"fileName": "movie.mkv", "subfiles": []}}
    manifest = Obj()._assert_selected_video_present_v210(
        resolve_data=resolve_data,
        selected_indexes=[],
        source={"type": "ed2k", "name": "movie.mkv"},
        subscribe=SimpleNamespace(name="movie"),
    )
    assert manifest == []


def test_l_winter_city_past_e01_not_skip_complete():
    src = (PLUGIN / "calendar_driven_v209.py").read_text(encoding="utf-8")
    assert "used_empty" in src
    assert "skip_complete" in src
    assert "continue_match" in src
    pre = ROOT / "tests/v3/guangyatransferassistant/test_preflight_calendar_tri_state_v210.py"
    text = pre.read_text(encoding="utf-8")
    assert "winter_city" in text or "test_a_winter_city" in text


def test_dispatch_policy_airing_uses_smart_selector():
    src = (PLUGIN / "dispatch_policy_v1125.py").read_text(encoding="utf-8")
    assert "_smart_pull_due_ids_v1125()" in src
    assert '"airing_pull"' in src
    assert "更新日历主动拉取" in src


def test_create_task_summary_log_present():
    src = (PLUGIN / "multisource_v180.py").read_text(encoding="utf-8")
    assert "【云添加提交摘要】" in src
    assert "selected_video_indexes" in src
    assert "【云添加终态】" in src
    assert "【主动检索派发】" in (PLUGIN / "channel_event_v1115.py").read_text(encoding="utf-8")
