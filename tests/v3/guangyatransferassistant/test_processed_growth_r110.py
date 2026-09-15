"""r110 processed GuangYa share growth recheck regressions."""
from __future__ import annotations

import ast
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
ENTRY_PATH = ROOT / "plugins.v3" / "guangyatransferassistant" / "__init__.py"
ENTRY = ENTRY_PATH.read_text(encoding="utf-8")


def _probe_class():
    tree = ast.parse(ENTRY, filename=str(ENTRY_PATH))
    final = [
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "GuangYaTransferAssistant"
    ][-1]
    wanted_attrs = {
        "_processed_growth_recheck_seconds_r110",
        "_processed_growth_statuses_r110",
    }
    wanted_methods = {"_entry_processed", "_mark_entry_processed"}
    body = []
    for node in final.body:
        if isinstance(node, ast.Assign):
            names = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if names & wanted_attrs:
                body.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in wanted_methods:
            body.append(node)

    class Base:
        def _entry_processed(self, entry, subscribe=None):
            return bool(self.store.get("k"))

        def _mark_entry_processed(self, entry, status, message="", subscribe=None):
            self.store["k"] = {
                "status": status,
                "message": message,
                "emby_repair_targets_v212": sorted(self.repair),
            }

    cls_node = ast.ClassDef(
        name="Probe",
        bases=[ast.Name(id="Base", ctx=ast.Load())],
        keywords=[],
        body=body,
        decorator_list=[],
    )
    ast.fix_missing_locations(cls_node)
    ns = {"Base": Base, "Any": Any, "time": time, "frozenset": frozenset}
    exec(compile(ast.Module(body=[cls_node], type_ignores=[]), "<r110-probe>", "exec"), ns)
    return ns["Probe"]


def _obj(status="no_new_episode", checked_age=0, stored=(4,), repair=(4,), movie=False):
    Probe = _probe_class()
    obj = Probe()
    now = time.time()
    obj.repair = set(repair)
    obj.movie = movie
    obj.logs = []
    obj.saved = []
    obj.store = {
        "k": {
            "status": status,
            "emby_repair_targets_v212": list(stored),
            "emby_repair_checked_at_v212": now - checked_age,
            "growth_checked_at_r110": now - checked_age,
        }
    }
    obj._is_movie_subscription = lambda subscribe: bool(obj.movie)
    obj._emby_repair_targets_v212 = lambda subscribe: set(obj.repair)
    obj._processed_entry_key = lambda entry, subscribe=None: "k"
    obj.get_data = lambda key: obj.store if key == "processed_entries" else {}
    obj.save_data = lambda key, value: obj.saved.append((key, value.copy()))
    obj._plugin_log = lambda *args: obj.logs.append(args)
    return obj


def test_recent_no_new_episode_stays_processed_before_growth_window():
    obj = _obj(checked_age=60)
    assert obj._entry_processed({"share_id": "S"}, object()) is True


def test_same_missing_target_reopens_after_15_minutes_for_share_growth():
    obj = _obj(checked_age=901)
    assert obj._entry_processed({"share_id": "S"}, object()) is False
    assert any("分享增长复核r110" in str(row) for row in obj.logs)


def test_target_change_still_reopens_immediately_without_waiting():
    obj = _obj(checked_age=10, stored=(3,), repair=(4,))
    assert obj._entry_processed({"share_id": "S"}, object()) is False
    assert any("Emby缺集恢复v2.1.2" in str(row) for row in obj.logs)


def test_transferred_status_does_not_periodically_reopen_on_same_target():
    obj = _obj(status="transferred", checked_age=3600)
    assert obj._entry_processed({"share_id": "S"}, object()) is True


def test_movie_processed_record_is_not_subject_to_tv_growth_recheck():
    obj = _obj(checked_age=3600, movie=True)
    assert obj._entry_processed({"share_id": "S"}, object()) is True


def test_marking_growth_status_refreshes_recheck_timestamp():
    obj = _obj(checked_age=3600)
    before = time.time()
    obj._mark_entry_processed({"share_id": "S"}, "synced", "none", object())
    row = obj.store["k"]
    assert row["status"] == "synced"
    assert row["emby_repair_targets_v212"] == [4]
    assert row["growth_checked_at_r110"] >= before


def test_marking_transferred_does_not_create_growth_timestamp_on_fresh_row():
    Probe = _probe_class()
    obj = Probe()
    obj.repair = {4}
    obj.movie = False
    obj.store = {}
    obj.saved = []
    obj._is_movie_subscription = lambda subscribe: False
    obj._emby_repair_targets_v212 = lambda subscribe: {4}
    obj._processed_entry_key = lambda entry, subscribe=None: "k"
    obj.get_data = lambda key: obj.store if key == "processed_entries" else {}
    obj.save_data = lambda key, value: obj.saved.append((key, value.copy()))
    obj._plugin_log = lambda *args: None
    obj._mark_entry_processed({"share_id": "S"}, "transferred", "ok", object())
    assert "growth_checked_at_r110" not in obj.store["k"]


def test_release_marker_r110():
    final = ENTRY[ENTRY.rindex("\nclass GuangYaTransferAssistant("):]
    assert 'plugin_version = "2.1.12"' in final
    assert 'build_id = "20260915-r110"' in final
