from __future__ import annotations

import copy
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Any, Dict, List, Sequence, Set, Tuple


ROOT = Path(__file__).resolve().parents[3]
PATCH = (ROOT / "plugins.v3" / "shukguangyadisk" / "organizer_hardening_v369.py").read_text(
    encoding="utf-8"
)
_STATE_NAMES = ("completed", "ignored", "blocked", "stabilizing", "inflight", "retry")


def _helper_namespace() -> Dict[str, Any]:
    start = PATCH.index("def _direct_parent")
    end = PATCH.index("def _split_children", start)
    namespace: Dict[str, Any] = {
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "Sequence": Sequence,
        "Set": Set,
        "Tuple": Tuple,
        "PurePosixPath": PurePosixPath,
        "_STATE_NAMES": _STATE_NAMES,
    }
    exec(PATCH[start:end], namespace)
    return namespace


class _StateStore:
    def __init__(self, data: Dict[str, Any]):
        self.data = copy.deepcopy(data)
        self.writes = 0

    def load(self) -> Dict[str, Any]:
        return copy.deepcopy(self.data)

    def mutate(self, callback):
        state = copy.deepcopy(self.data)
        result = callback(state)
        self.data = state
        self.writes += 1
        return result


class _Plugin:
    def __init__(self, state: Dict[str, Any]):
        self.store = _StateStore(state)
        self._organize_monitor_recursive = False

    @staticmethod
    def _v360_norm(raw: Any) -> str:
        text = str(raw or "").replace("\\", "/")
        if not text:
            return ""
        if not text.startswith("/"):
            text = "/" + text
        while "//" in text:
            text = text.replace("//", "/")
        if len(text) > 1:
            text = text.rstrip("/")
        return text

    def _state(self) -> _StateStore:
        return self.store


def _child(path: str, kind: str):
    return SimpleNamespace(path=path, name=PurePosixPath(path).name, type=kind)


def _base_state() -> Dict[str, Any]:
    return {
        "completed": {
            "/root/old/E01.mkv": "fp-old-1",
            "/root/live/E02.mkv": "fp-live-2",
            "/root/missing-direct.mkv": "fp-direct",
            "/other/keep.mkv": "fp-other",
        },
        "ignored": {},
        "blocked": {},
        "stabilizing": {},
        "inflight": {},
        "retry": {
            "/root/old/E03.mkv": {"fingerprint": "fp-old-3", "retry_at": 1},
            "/root/live/E04.mkv": {"fingerprint": "fp-live-4", "retry_at": 1},
        },
    }


def test_missing_direct_child_prunes_whole_subtree_but_keeps_existing_child_subtree():
    ns = _helper_namespace()
    reconcile = ns["_reconcile_reachable_state"]
    plugin = _Plugin(_base_state())

    children = [
        _child("/root/live", "dir"),
        _child("/root/keep-direct.mkv", "file"),
    ]
    result = reconcile(plugin, "/root", children, directory_exists=True)

    assert result["total"] == 3
    assert result["direct"] == 1
    assert result["subtree"] == 2
    assert result["by_state"] == {"completed": 2, "retry": 1}
    assert plugin.store.writes == 1

    completed = plugin.store.data["completed"]
    retry = plugin.store.data["retry"]
    assert "/root/old/E01.mkv" not in completed
    assert "/root/missing-direct.mkv" not in completed
    assert "/root/old/E03.mkv" not in retry
    assert "/root/live/E02.mkv" in completed
    assert "/root/live/E04.mkv" in retry
    assert "/other/keep.mkv" in completed


def test_second_unchanged_scan_is_zero_write():
    ns = _helper_namespace()
    reconcile = ns["_reconcile_reachable_state"]
    plugin = _Plugin(_base_state())
    children = [_child("/root/live", "dir")]

    first = reconcile(plugin, "/root", children, directory_exists=True)
    assert first["total"] > 0
    writes_after_first = plugin.store.writes

    second = reconcile(plugin, "/root", children, directory_exists=True)
    assert second["total"] == 0
    assert plugin.store.writes == writes_after_first


def test_confirmed_missing_directory_prunes_all_descendant_states_only():
    ns = _helper_namespace()
    reconcile = ns["_reconcile_reachable_state"]
    plugin = _Plugin(_base_state())

    result = reconcile(plugin, "/root/live", [], directory_exists=False)

    assert result["total"] == 2
    assert result["direct"] == 0
    assert result["subtree"] == 2
    assert "/root/live/E02.mkv" not in plugin.store.data["completed"]
    assert "/root/live/E04.mkv" not in plugin.store.data["retry"]
    assert "/root/old/E01.mkv" in plugin.store.data["completed"]
    assert "/other/keep.mkv" in plugin.store.data["completed"]


def test_existing_hidden_or_nonrecursive_child_still_proves_subtree_reachable():
    ns = _helper_namespace()
    reconcile = ns["_reconcile_reachable_state"]
    state = _base_state()
    state["completed"]["/root/.hidden/E05.mkv"] = "fp-hidden"
    plugin = _Plugin(state)

    children = [
        _child("/root/live", "dir"),
        _child("/root/.hidden", "dir"),
    ]
    reconcile(plugin, "/root", children, directory_exists=True)

    assert "/root/live/E02.mkv" in plugin.store.data["completed"]
    assert "/root/.hidden/E05.mkv" in plugin.store.data["completed"]
