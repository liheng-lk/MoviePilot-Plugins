from __future__ import annotations

import ast
import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
PATCH_PATH = PLUGIN / "organizer_terminal_index_gc_v3619.py"
EXEC_PATH = PLUGIN / "organizer_execution_v360.py"
PATCH = PATCH_PATH.read_text(encoding="utf-8")
EXEC = EXEC_PATH.read_text(encoding="utf-8")


def _load_module():
    app = sys.modules.setdefault("app", types.ModuleType("app"))
    sdk = sys.modules.setdefault("app.sdk", types.ModuleType("app.sdk"))
    logging_mod = types.ModuleType("app.sdk.logging")

    class _Logger:
        def info(self, *args, **kwargs):
            pass

    logging_mod.logger = _Logger()
    sys.modules["app.sdk.logging"] = logging_mod
    setattr(app, "sdk", sdk)
    setattr(sdk, "logging", logging_mod)

    spec = importlib.util.spec_from_file_location("shuk_v3619_terminal_index_gc_test", PATCH_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Plugin:
    def __init__(self):
        self.known = {}
        self.pending = {}
        self.known_saves = 0
        self.pending_saves = 0
        self.status = {}

    @staticmethod
    def _v360_norm(path):
        text = str(path or "").replace("\\", "/")
        return text.rstrip("/") or "/"

    def _v366_load_known(self):
        return dict(self.known)

    def _v366_save_known(self, rows):
        self.known = dict(rows)
        self.known_saves += 1

    def _v361_load_pending(self):
        return dict(self.pending)

    def _v361_save_pending(self, rows):
        self.pending = dict(rows)
        self.pending_saves += 1

    def _save_monitor_status(self, **kwargs):
        self.status.update(kwargs)


def test_v3619_sources_parse_and_runtime_reports_current_hardening():
    ast.parse(PATCH, filename=str(PATCH_PATH))
    ast.parse(EXEC, filename=str(EXEC_PATH))
    assert '"runtime_hardening": "v3.6.19"' in EXEC


def test_missing_direct_child_prunes_known_and_pending_descendants_only():
    module = _load_module()
    plugin = _Plugin()
    plugin.known = {
        "/root/gone/show/Season 1": {"signature": "a"},
        "/root/gone/other": {"signature": "b"},
        "/root/live/show": {"signature": "c"},
        "/outside/show": {"signature": "d"},
    }
    plugin.pending = {
        "/root/gone/show/Season 1": {"due_at": 1},
        "/root/live/show": {"due_at": 2},
    }

    result = module.prune_unreachable_resource_indexes_v3619(
        plugin,
        group="/root",
        directory_exists=True,
        present_dirs={"/root/live"},
    )

    assert result == {"known": 2, "pending": 1}
    assert set(plugin.known) == {"/root/live/show", "/outside/show"}
    assert set(plugin.pending) == {"/root/live/show"}
    assert plugin.known_saves == 1
    assert plugin.pending_saves == 1
    assert plugin.status["terminal_index_pruned"] == 3
    assert plugin.status["terminal_index_pruned_path"] == "/root"


def test_missing_directory_prunes_exact_group_and_whole_index_subtree():
    module = _load_module()
    plugin = _Plugin()
    plugin.known = {
        "/root/gone": {},
        "/root/gone/show": {},
        "/root/gone/show/Season 3": {},
        "/root/keep": {},
    }
    plugin.pending = {
        "/root/gone/show": {},
        "/root/keep": {},
    }

    result = module.prune_unreachable_resource_indexes_v3619(
        plugin,
        group="/root/gone",
        directory_exists=False,
        present_dirs=set(),
    )

    assert result == {"known": 3, "pending": 1}
    assert set(plugin.known) == {"/root/keep"}
    assert set(plugin.pending) == {"/root/keep"}


def test_existing_direct_child_preserves_its_whole_deeper_subtree():
    module = _load_module()
    plugin = _Plugin()
    plugin.known = {
        "/root/live/show/Season 1": {},
        "/root/live/show/Season 2": {},
    }
    plugin.pending = {"/root/live/show/Season 2": {}}

    result = module.prune_unreachable_resource_indexes_v3619(
        plugin,
        group="/root",
        directory_exists=True,
        present_dirs={"/root/live"},
    )

    assert result == {"known": 0, "pending": 0}
    assert plugin.known_saves == 0
    assert plugin.pending_saves == 0


def test_exact_existing_group_is_not_removed_when_parent_directory_exists():
    module = _load_module()
    plugin = _Plugin()
    plugin.known = {"/root": {}, "/root/live": {}}
    plugin.pending = {"/root": {}}

    result = module.prune_unreachable_resource_indexes_v3619(
        plugin,
        group="/root",
        directory_exists=True,
        present_dirs={"/root/live"},
    )

    assert result == {"known": 0, "pending": 0}
    assert set(plugin.known) == {"/root", "/root/live"}
    assert set(plugin.pending) == {"/root"}


def test_v3619_installs_immediately_after_strict_reachability_patch():
    init = EXEC[EXEC.index("def init_organizer_monitor"):EXEC.index("def _execute_isolated_transfer")]
    hardening = "install_organizer_hardening_v369()"
    index_gc = "install_terminal_index_gc_v3619()"
    durable = "install_durable_retry_v3611()"
    assert "from .organizer_terminal_index_gc_v3619 import install_terminal_index_gc_v3619" in init
    assert init.index(hardening) < init.index(index_gc) < init.index(durable)


def test_v3619_is_index_lifecycle_only_not_media_or_file_delete_policy():
    lower = PATCH.lower()
    assert "recognize_media" not in lower
    assert "category" not in lower
    assert "tmdb" not in lower
    assert "delete_file" not in lower
    assert "move_item" not in lower
    assert "list_strict" in PATCH  # doc-boundary: facts come from v3.6.13 strict listing
    assert "_reconcile_reachable_state" in PATCH
