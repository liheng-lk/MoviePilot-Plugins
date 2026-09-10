from __future__ import annotations

import ast
import threading
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[3]
MULTI = ROOT / "plugins.v3" / "guangyatransferassistant" / "multisource_v180.py"
SOURCE = MULTI.read_text(encoding="utf-8")


def _mixin_class():
    tree = ast.parse(SOURCE, filename=str(MULTI))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "GuangYaMultiSourceMixin")
    module = ast.Module(body=[cls], type_ignores=[])
    ast.fix_missing_locations(module)
    ns: Dict[str, Any] = {
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "Path": Path,
        "threading": threading,
        "time": __import__("time"),
        "SOURCE_PENDING_STATES": {"new", "retry"},
        "SOURCE_INFLIGHT_STATES": {"dispatching", "submitted", "queued", "waiting"},
        "normalize_source_uri": lambda uri: {"type": "magnet", "uri": uri, "identity": "x", "name": "", "size": 0},
        "_is_video": lambda _name: False,
        "_is_subtitle": lambda _name: False,
        "_episode_numbers": lambda _name: (0, []),
        "_normalize_media_text": lambda value: str(value or "").strip().lower(),
        "GuangYaSourceStoreMixin": type("Base", (), {}),
    }
    exec(compile(module, str(MULTI), "exec"), ns)
    return ns["GuangYaMultiSourceMixin"]


def test_multisource_has_source_dispatch_slot_helpers():
    assert "def _claim_source_dispatch_slot(" in SOURCE
    assert "def _release_source_dispatch_slot(" in SOURCE
    spawn = SOURCE.split("    def _spawn_source_dispatch(", 1)[1].split("    def _offline_tick(", 1)[0]
    assert "_claim_source_dispatch_slot" in spawn
    assert "_release_source_dispatch_slot" in spawn
    tick = SOURCE.split("    def _offline_tick(", 1)[1].split("    def get_service(", 1)[0]
    assert "_claim_source_dispatch_slot" in tick
    assert "_release_source_dispatch_slot" in tick


def test_offline_tick_skips_sources_already_dispatched_by_other_worker():
    mixin = _mixin_class()

    class Harness(mixin):
        def __init__(self):
            self._enabled = True
            self._external_auto_dispatch = True
            self._offline_batch_limit = 20
            self._offline_lock = threading.RLock()
            self._offline_worker_lock = threading.Lock()
            self._offline_worker_ids = {"src-1"}
            self.submitted = []
            self.polled = []
            self.items = {
                "src-1": {"id": "src-1", "enabled": True, "auto_dispatch": True, "type": "magnet", "state": "new", "next_retry_at": 0},
                "src-2": {"id": "src-2", "enabled": True, "auto_dispatch": True, "type": "magnet", "state": "new", "next_retry_at": 0},
                "src-3": {"id": "src-3", "enabled": True, "auto_dispatch": True, "type": "ed2k", "state": "waiting", "next_retry_at": 0},
            }

        def _source_store(self):
            return {"items": self.items}

        def _submit_offline_source(self, source_id: str):
            self.submitted.append(str(source_id))
            return {"success": True}

        def _poll_offline_source(self, source: Dict[str, Any]):
            self.polled.append(str(source.get("id") or ""))
            return {"success": True}

    harness = Harness()
    harness._offline_tick()
    assert harness.submitted == ["src-2"]
    assert harness.polled == ["src-3"]
    assert "src-1" in harness._offline_worker_ids
    assert "src-2" not in harness._offline_worker_ids
    assert "src-3" not in harness._offline_worker_ids
