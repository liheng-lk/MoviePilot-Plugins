from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
PATCH = (PLUGIN / "organizer_paged_scan_handoff_v359.py").read_text(encoding="utf-8")
FILTER = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")


def test_v359_historical_module_keeps_50_directory_cursor_contract():
    for token in (
        '_CURSOR_KEY = "organize_v359_paged_scan_cursor"',
        '_PAGE_DIR_LIMIT = 50',
        'while queue and dirs_scanned < _PAGE_DIR_LIMIT:',
        '下一轮从断点继续',
    ):
        assert token in PATCH, token


def test_v359_historical_partial_pages_never_prune_unseen_state():
    assert 'scan_meta["truncated"] = True' in PATCH
    assert 'scan_meta["inventory_paths"] = set(inventory)' in PATCH
    assert 'scan_meta["truncated"] = bool(overflow)' in PATCH


def test_v359_is_no_longer_installed_as_current_discovery_layer():
    assert 'install_paged_scan_handoff_v359(GuangYaCandidateFilterMixin)' not in FILTER
    assert 'from .organizer_paged_scan_handoff_v359 import install_paged_scan_handoff_v359' not in FILTER
    assert 'install_scheduler_convergence_v360(GuangYaCandidateFilterMixin)' in FILTER


def test_v359_history_is_preserved_after_scheduler_convergence():
    plugin_meta = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    assert 'v3.5.9' in plugin_meta["history"]


def test_v359_never_owned_moviepilot_business_rules():
    for forbidden in (
        'target_directory',
        'rename_format',
        'DirectoryHelper',
        'get_rename_path',
    ):
        assert forbidden not in PATCH
