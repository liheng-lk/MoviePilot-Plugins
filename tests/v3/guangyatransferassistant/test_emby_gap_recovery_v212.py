from __future__ import annotations

import ast
import copy
import re
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[3]
ENTRY_PATH = ROOT / "plugins.v3" / "guangyatransferassistant" / "__init__.py"
ENTRY = ENTRY_PATH.read_text(encoding="utf-8")

_METHODS = {
    "_emby_repair_targets_v212",
    "_item_episode_set_v212",
    "_emby_repair_tls_v212",
    "_semantic_fact_exists",
    "_acquired_episode_facts_v1124",
    "_plan_incremental_files",
    "_entry_processed",
    "_mark_entry_processed",
}


def _build_probe_class():
    tree = ast.parse(ENTRY, filename=str(ENTRY_PATH))
    final_class = [
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "GuangYaTransferAssistant"
    ][-1]
    methods = [
        node for node in final_class.body
        if isinstance(node, ast.FunctionDef) and node.name in _METHODS
    ]
    assert {node.name for node in methods} == _METHODS

    class FakeBase:
        def __init__(self):
            self.snapshot = {
                "library_state": "OK",
                "final_target": [1],
            }
            self.data = {"processed_entries": {}}
            self.logs = []
            self.fact_episodes = {1, 2}

        @staticmethod
        def _is_movie_subscription(subscribe):
            return False

        def _episode_target_snapshot_v210(self, subscribe, **kwargs):
            return dict(self.snapshot)

        @staticmethod
        def _episode_from_item(item):
            path = str(
                (item or {}).get("effective_path")
                or (item or {}).get("relative_path")
                or (item or {}).get("path")
                or (item or {}).get("name")
                or ""
            )
            match = re.search(r"(?i)E0*(\d+)", path)
            return int(match.group(1)) if match else 0

        def _media_fact_keys_for_item(self, subscribe, item):
            episode = self._episode_from_item(item)
            return [f"tmdb:test:s01:e{episode:04d}"] if episode else []

        def _semantic_fact_exists(self, subscribe, item):
            return self._episode_from_item(item) in self.fact_episodes

        def _acquired_episode_facts_v1124(self, subscribe):
            return {1, 2}

        def _plan_incremental_files(
            self,
            probe,
            assets,
            subscribe=None,
            target_path="",
            stats=None,
        ):
            note = {int(v) for v in (getattr(subscribe, "note", None) or [])}
            planned = []
            episode_filtered = fact_filtered = inventory_filtered = 0
            for raw in probe.get("files") or []:
                row = dict(raw)
                episode = self._episode_from_item(row)
                if episode in note:
                    episode_filtered += 1
                    continue
                if self._semantic_fact_exists(subscribe, row):
                    fact_filtered += 1
                    continue
                path = str(row.get("relative_path") or row.get("name") or "")
                exists = any(
                    isinstance(asset, dict) and str(asset.get("path") or "") == path
                    for asset in (assets or {}).values()
                )
                if exists:
                    inventory_filtered += 1
                    continue
                row["effective_path"] = path
                planned.append(row)
            if stats is not None:
                stats.update({
                    "eligible": len(planned),
                    "episode": episode_filtered,
                    "fact": fact_filtered,
                    "inventory": inventory_filtered,
                })
            return planned

        @staticmethod
        def _processed_entry_key(entry, subscribe=None):
            return "entry"

        def _entry_processed(self, entry, subscribe=None):
            return True

        def _mark_entry_processed(self, entry, status, message="", subscribe=None):
            self.data.setdefault("processed_entries", {})["entry"] = {
                "status": status,
                "message": message,
            }

        def get_data(self, key):
            return self.data.get(key)

        def save_data(self, key, value):
            self.data[key] = value

        def _plugin_log(self, *args):
            self.logs.append(args)

    class_node = ast.ClassDef(
        name="Probe",
        bases=[ast.Name(id="FakeBase", ctx=ast.Load())],
        keywords=[],
        body=methods,
        decorator_list=[],
    )
    module = ast.Module(body=[class_node], type_ignores=[])
    ast.fix_missing_locations(module)

    def legacy_episode_numbers(path):
        match = re.search(r"(?i)S0*(\d+)E0*(\d+)|(?i:E0*(\d+))", str(path or ""))
        if not match:
            return None, []
        if match.group(1):
            return int(match.group(1)), [int(match.group(2))]
        return None, [int(match.group(3))]

    ns = {
        "FakeBase": FakeBase,
        "Any": Any,
        "Optional": Optional,
        "copy": copy,
        "threading": threading,
        "time": time,
        "_legacy_module": SimpleNamespace(_episode_numbers=legacy_episode_numbers),
    }
    exec(compile(module, "<emby-gap-recovery-v212>", "exec"), ns)
    return ns["Probe"]


def _subscribe():
    return SimpleNamespace(
        id=262,
        name="择日飞升",
        type="电视剧",
        season=1,
        note=[1, 2],
    )


def _probe():
    return {
        "files": [
            {"id": "f1", "relative_path": "择日飞升.S01E01.mkv"},
            {"id": "f2", "relative_path": "择日飞升.S01E02.mkv"},
        ]
    }


def _assets():
    return {
        "a1": {"path": "择日飞升.S01E01.mkv", "target": "/tv"},
        "a2": {"path": "择日飞升.S01E02.mkv", "target": "/tv"},
    }


def test_emby_final_target_reopens_stale_note_fact_and_inventory_for_direct_share():
    Probe = _build_probe_class()
    plugin = Probe()
    stats = {}
    planned = plugin._plan_incremental_files(
        _probe(),
        _assets(),
        subscribe=_subscribe(),
        target_path="/tv",
        stats=stats,
    )

    assert [row["effective_path"] for row in planned] == ["择日飞升.S01E01.mkv"]
    assert stats["emby_repair_targets_v212"] == [1]
    assert stats["emby_repair_note_bypass_v212"] == 1
    assert stats["emby_repair_fact_bypass_v212"] == 1
    assert stats["emby_repair_inventory_bypass_v212"] == 1


def test_emby_final_target_downgrades_old_receipt_but_keeps_other_acquired_episode():
    Probe = _build_probe_class()
    plugin = Probe()
    assert plugin._acquired_episode_facts_v1124(_subscribe()) == {2}


def test_processed_share_reopens_once_for_changed_authoritative_repair_target():
    Probe = _build_probe_class()
    plugin = Probe()
    sub = _subscribe()
    entry = {"share_id": "test"}

    assert plugin._entry_processed(entry, sub) is False
    plugin._mark_entry_processed(entry, "no_new_episode", "old inventory said complete", sub)
    row = plugin.get_data("processed_entries")["entry"]
    assert row["emby_repair_targets_v212"] == [1]
    assert plugin._entry_processed(entry, sub) is True

    plugin.snapshot["final_target"] = [1, 3]
    assert plugin._entry_processed(entry, sub) is False


def test_no_authoritative_emby_snapshot_keeps_legacy_dedupe_fail_closed():
    Probe = _build_probe_class()
    plugin = Probe()
    plugin.snapshot = {"library_state": "UNKNOWN", "final_target": [1]}
    stats = {}
    planned = plugin._plan_incremental_files(
        _probe(),
        _assets(),
        subscribe=_subscribe(),
        target_path="/tv",
        stats=stats,
    )
    assert planned == []
    assert plugin._acquired_episode_facts_v1124(_subscribe()) == {1, 2}


def test_r100_fix_is_single_init_only_and_does_not_touch_future_or_claim_gates():
    final = ENTRY[ENTRY.rindex("\nclass GuangYaTransferAssistant("):]
    assert "Emby缺集恢复v2.1.2" in final
    assert "allow_network=False" in final
    assert "final_target" in final
    assert "pending_library" not in final.split("def _emby_repair_targets_v212", 1)[1].split(
        "def _item_episode_set_v212", 1
    )[0]
