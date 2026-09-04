from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
HARDENING = (PLUGIN / "organizer_hardening_v369.py").read_text(encoding="utf-8")
EXECUTION = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")


def _between(text: str, start_token: str, end_token: str) -> str:
    start = text.index(start_token)
    end = text.index(end_token, start + len(start_token))
    return text[start:end]


def test_v3613_sources_parse():
    ast.parse(HARDENING)
    ast.parse(EXECUTION)


def test_reconcile_noop_does_not_call_mutate():
    block = _between(HARDENING, "def _reconcile_reachable_state", "def _split_children")
    preview = block.index("preview = inspect(store.load())")
    guard = block.index('if int(preview.get("total") or 0) <= 0:')
    early = block.index("return preview", guard)
    mutate = block.index("return dict(store.mutate(apply) or empty)")
    assert preview < guard < early < mutate


def test_missing_child_subtree_is_pruned_only_from_strict_parent_evidence():
    predicate = _between(HARDENING, "def _state_path_is_unreachable", "def _reconcile_reachable_state")
    assert "first_child not in present_dirs" in predicate
    assert "if not normalized.startswith(prefix):" in predicate
    assert "if not directory_exists:" in predicate

    listing = _between(HARDENING, "def list_directory", "def run_monitor_scan")
    strict = listing.index("children = list(strict_list(current) or [])")
    reconcile = listing.index(
        "stats = _reconcile_reachable_state(plugin, path, children, directory_exists=True)"
    )
    split = listing.index("dirs, files = _split_children(plugin, children)")
    assert strict < reconcile < split


def test_nonrecursive_mode_cannot_make_existing_child_look_deleted():
    helper = _between(HARDENING, "def _present_direct_children", "def _state_path_is_unreachable")
    assert "present_dirs.add(path)" in helper
    assert "_organize_monitor_recursive" not in helper


def test_network_failure_cannot_prune_state():
    listing = _between(HARDENING, "def list_directory", "def run_monitor_scan")
    failure = listing.index("except Exception as first_error:")
    refresh = listing.index("refreshed = refresher(Path(path))", failure)
    confirmed_missing = listing.index("if not refreshed:", refresh)
    reconcile_missing = listing.index(
        "_reconcile_reachable_state(plugin, path, [], directory_exists=False)",
        confirmed_missing,
    )
    second_strict = listing.index("children = list(strict_list(refreshed) or [])", confirmed_missing)
    assert failure < refresh < confirmed_missing < reconcile_missing < second_strict
    assert "raise first_error" in listing[failure:confirmed_missing]


def test_v3613_is_infrastructure_only():
    for forbidden in (
        "MediaType.TV",
        "MediaType.MOVIE",
        "target_directory",
        "rename_format",
        "planning_input",
        "do_transfer(",
        "TransferExecutionCommand",
        "move_item",
        "delete_file",
        "overwrite_mode",
    ):
        assert forbidden not in HARDENING, forbidden
    match = re.search(r'"runtime_hardening": "v3\.6\.(\d+)"', EXECUTION)
    assert match and int(match.group(1)) >= 13
